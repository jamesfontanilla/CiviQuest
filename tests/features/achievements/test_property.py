"""Property-based tests for the achievements slice (Task 15.3).

One named property from the design's catalog lands here:

- **Property 23 — Achievement uniqueness.**
  *For any* user ``u`` and *for any* achievement ``a``, *for any*
  sequence of XP-awarding events that satisfies ``a``'s criterion at
  one or more events, ``u`` has exactly one ``user_achievements`` row
  for ``a``, with ``granted_at`` equal to the timestamp of the first
  satisfying event, and the evaluator emits the achievement at most
  once.

**Validates: Requirements 13.2, 13.3**

Strategy: generate random sequences of XP events (mixed sources +
amounts), feed each through the achievement evaluator one at a time,
and assert after each step that no ``(user_id, achievement_id)`` pair
has more than one row in the DB. We additionally track which
achievements were "newly granted" by the evaluator on each call and
assert that no achievement appears in that returned list more than
once across the entire sequence — this directly validates the
"emitted at most once" half of the property.

Hypothesis settings: ``max_examples=20`` per the task spec; deadline
disabled because each example performs O(events) DB writes;
``function_scoped_fixture`` suppressed so the ``db_session`` fixture
can be reused across generated examples.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from hypothesis import HealthCheck, given, settings, strategies as st
from sqlalchemy.orm import Session

from app.features.achievements.models import UserAchievement
from app.features.achievements.repository import AchievementRepository
from app.features.achievements.seed import seed_all_achievements
from app.features.achievements.service import AchievementService
from app.features.mock_exams.repository import MockExamRepository
from app.features.progress.repository import ProgressRepository
from app.features.quizzes.repository import QuizRepository
from app.features.users.models import Category, User
from app.features.users.repository import UserRepository
from app.features.users.schemas import UserCreate
from app.features.xp.models import UserXP, XPEvent, XPSource
from app.features.xp.repository import XPRepository


_PBT_SETTINGS = dict(
    max_examples=20,
    deadline=None,
    suppress_health_check=[
        HealthCheck.too_slow,
        HealthCheck.function_scoped_fixture,
    ],
)


# --- helpers --------------------------------------------------------------


def _reset(db: Session) -> None:
    """Clear every table this property touches so generated examples are isolated."""
    db.query(UserAchievement).delete()
    db.query(XPEvent).delete()
    db.query(UserXP).delete()
    db.query(User).delete()
    db.commit()


def _make_user(db: Session) -> User:
    return UserRepository(db=db).create(
        UserCreate(
            email="alice@example.com",
            display_name="Alice",
            age=25,
            category=Category.PROFESSIONAL.value,
            password="Strong1Pass!",
        ),
        password_hash="bcrypt$fake$hash",
    )


def _make_achievement_service(db: Session) -> AchievementService:
    return AchievementService(
        ach_repo=AchievementRepository(db=db),
        xp_repo=XPRepository(db=db),
        quiz_repo=QuizRepository(db=db),
        mock_repo=MockExamRepository(db=db),
        progress_repo=ProgressRepository(db=db),
    )


# --- strategies ----------------------------------------------------------


# Sources the evaluator switches on. ADMIN_CORRECTION and STREAK_DAY are
# excluded from the generator because they don't satisfy any MVP /
# Phase 2 criterion directly; including them would only pad the
# sequence with no-op events.
_award_source = st.sampled_from(
    [
        XPSource.LESSON_FIRST_COMPLETE,
        XPSource.QUIZ_PASS,
        XPSource.QUIZ_PERFECT,
        XPSource.MOCK_PASS,
    ]
)


# Amounts spanning the discriminants the evaluator cares about
# (subtopic 20 / topic 100 / module 250 for QUIZ_PASS) plus a few
# off-discriminant values to ensure the FIRST_TOPIC / FIRST_MODULE
# checks reject mismatched amounts. For non-QUIZ_PASS sources the
# amount is irrelevant to the criterion logic; we still generate
# realistic values so the level-threshold check sees movement.
_amount = st.sampled_from([20, 50, 100, 250, 500, 1_000, 5_500])


@st.composite
def _event_sequence(draw: st.DrawFn) -> list[tuple[XPSource, int]]:
    """Generate a 1..15-event sequence of (source, amount) tuples."""
    n = draw(st.integers(min_value=1, max_value=15))
    return [(draw(_award_source), draw(_amount)) for _ in range(n)]


# --- properties ----------------------------------------------------------


@given(events=_event_sequence())
@settings(**_PBT_SETTINGS)
def test_property_23_at_most_one_grant_per_user_achievement_pair(
    db_session: Session,
    events: list[tuple[XPSource, int]],
) -> None:
    """Property 23 — every (user, achievement) pair has at most one row.

    For any sequence of XP-awarding events, after evaluating each one,
    no ``(user_id, achievement_id)`` pair appears in
    ``user_achievements`` more than once. We additionally assert the
    evaluator never returns the same achievement twice across the run.

    **Validates: Requirements 13.2, 13.3**
    """
    _reset(db_session)
    user = _make_user(db_session)
    seed_all_achievements(AchievementRepository(db=db_session))
    ach_service = _make_achievement_service(db_session)
    xp_repo = XPRepository(db=db_session)
    ach_repo = AchievementRepository(db=db_session)

    base = datetime(2025, 6, 1, 12, 0, tzinfo=timezone.utc)

    # Bookkeeping for the "emitted at most once" half of the property.
    seen_in_returns: set[str] = set()

    for i, (source, amount) in enumerate(events):
        # Insert the XP event directly so we control the inputs.
        event, _ = xp_repo.insert_event_and_recompute(
            user_id=user.id,
            source=source,
            amount=amount,
            occurred_at=base + timedelta(minutes=i),
        )
        granted = ach_service.evaluate_after_xp_event(
            user=user, xp_event=event
        )

        # Half 1 of the property: the evaluator's return value never
        # contains the same achievement twice across the entire run.
        for g in granted:
            assert g.achievement_id not in seen_in_returns, (
                f"achievement {g.achievement_id} emitted twice "
                f"(events so far: {events[: i + 1]})"
            )
            seen_in_returns.add(g.achievement_id)

        # Half 2 of the property: storage layer also has at most one
        # row per (user, achievement). We check after every step so a
        # bug producing two rows is caught at the point of the bad
        # write, not at the end.
        all_grants = ach_repo.list_for_user(user.id)
        seen_pairs: set[tuple[int, str]] = set()
        for grant in all_grants:
            key = (grant.user_id, grant.achievement_id)
            assert key not in seen_pairs, (
                f"duplicate user_achievements row for {key} "
                f"(events so far: {events[: i + 1]})"
            )
            seen_pairs.add(key)


@given(n_repeats=st.integers(min_value=2, max_value=5))
@settings(**_PBT_SETTINGS)
def test_property_23_repeated_evaluation_of_same_event_grants_at_most_once(
    db_session: Session,
    n_repeats: int,
) -> None:
    """Re-running the evaluator on the same XP event grants nothing new.

    A direct test of the "emitted at most once" guarantee: after the
    first evaluation grants FIRST_LESSON, every subsequent call with
    the same XP event must return an empty list and the row count must
    stay at one.

    **Validates: Requirements 13.2, 13.3**
    """
    _reset(db_session)
    user = _make_user(db_session)
    seed_all_achievements(AchievementRepository(db=db_session))
    ach_service = _make_achievement_service(db_session)
    xp_repo = XPRepository(db=db_session)

    when = datetime(2025, 6, 1, 12, 0, tzinfo=timezone.utc)
    event, _ = xp_repo.insert_event_and_recompute(
        user_id=user.id,
        source=XPSource.LESSON_FIRST_COMPLETE,
        amount=20,
        occurred_at=when,
    )

    first = ach_service.evaluate_after_xp_event(user=user, xp_event=event)
    assert {g.achievement_id for g in first} == {"FIRST_LESSON"}

    for _ in range(n_repeats):
        again = ach_service.evaluate_after_xp_event(
            user=user, xp_event=event
        )
        assert again == []

    # Still exactly one row.
    grants = AchievementRepository(db=db_session).list_for_user(user.id)
    first_lesson_grants = [
        g for g in grants if g.achievement_id == "FIRST_LESSON"
    ]
    assert len(first_lesson_grants) == 1


@given(events=_event_sequence())
@settings(**_PBT_SETTINGS)
def test_property_23_granted_at_matches_first_satisfying_event(
    db_session: Session,
    events: list[tuple[XPSource, int]],
) -> None:
    """``granted_at`` equals the timestamp of the first satisfying event.

    For any sequence of XP-awarding events, the ``granted_at`` of each
    grant equals the ``occurred_at`` of the event that first satisfied
    its criterion. We capture the timestamp of the first event that
    produced a grant for each achievement and assert the row's
    ``granted_at`` matches.

    **Validates: Requirements 13.2, 13.3**
    """
    _reset(db_session)
    user = _make_user(db_session)
    seed_all_achievements(AchievementRepository(db=db_session))
    ach_service = _make_achievement_service(db_session)
    xp_repo = XPRepository(db=db_session)

    base = datetime(2025, 6, 1, 12, 0, tzinfo=timezone.utc)

    # Map achievement_id -> the timestamp of the event that produced it.
    first_satisfying: dict[str, datetime] = {}

    for i, (source, amount) in enumerate(events):
        when = base + timedelta(minutes=i)
        event, _ = xp_repo.insert_event_and_recompute(
            user_id=user.id,
            source=source,
            amount=amount,
            occurred_at=when,
        )
        granted = ach_service.evaluate_after_xp_event(
            user=user, xp_event=event, now=when
        )
        for g in granted:
            # First time we see this achievement — record the event time.
            if g.achievement_id not in first_satisfying:
                first_satisfying[g.achievement_id] = when

    # Verify each grant's ``granted_at`` matches the first-satisfying event.
    grants = AchievementRepository(db=db_session).list_for_user(user.id)
    for grant in grants:
        expected = first_satisfying.get(grant.achievement_id)
        assert expected is not None, (
            f"grant for {grant.achievement_id} has no recorded "
            f"first-satisfying event in this run"
        )
        # SQLite drops tz on round-trip; compare naive components.
        assert grant.granted_at.replace(tzinfo=None) == expected.replace(
            tzinfo=None
        ), (
            f"granted_at mismatch for {grant.achievement_id}: "
            f"row={grant.granted_at}, expected={expected}"
        )
