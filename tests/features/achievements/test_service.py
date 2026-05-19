"""Service tests for the achievements slice (Task 15.2).

Tests run against a real ``db_session`` because the evaluator threads
through ``user_xp`` cache reads and ``xp_events`` writes — mocking the
ledger would mean re-implementing it in the test, and the resulting
test would not catch the bugs that actually matter (criterion-kind
typos, amount discriminant drift, idempotency race windows).

The :class:`AchievementService` constructor accepts repositories for
quiz / mock / progress that the current criterion set doesn't read.
We pass real instances anyway — they're cheap to construct, and a
forward-compat criterion that starts reading them gets test coverage
for free.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.features.achievements.repository import AchievementRepository
from app.features.achievements.seed import (
    seed_all_achievements,
    seed_mvp_achievements,
)
from app.features.achievements.service import AchievementService
from app.features.mock_exams.repository import MockExamRepository
from app.features.progress.repository import ProgressRepository
from app.features.quizzes.repository import QuizRepository
from app.features.users.models import Category, User
from app.features.users.repository import UserRepository
from app.features.users.schemas import UserCreate
from app.features.xp.models import UserXP, XPEvent, XPSource
from app.features.xp.repository import XPRepository
from app.features.xp.service import XPService


# --- factories --------------------------------------------------------------


def _make_user(db: Session, *, email: str = "alice@example.com") -> User:
    return UserRepository(db=db).create(
        UserCreate(
            email=email,
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


def _make_xp_service(
    db: Session, ach_service: AchievementService
) -> XPService:
    return XPService(
        xp_repo=XPRepository(db=db),
        user_repo=UserRepository(db=db),
        achievement_service=ach_service,
    )


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


# ============================================================================
# evaluate_after_xp_event — direct calls
# ============================================================================


def test_evaluate_grants_first_lesson_on_first_lesson_event(
    db_session: Session,
) -> None:
    """FIRST_LESSON fires on the first LESSON_FIRST_COMPLETE."""
    user = _make_user(db_session)
    seed_mvp_achievements(AchievementRepository(db=db_session))
    ach_service = _make_achievement_service(db_session)

    # Insert an XP event directly (bypassing XPService so we can drive
    # the evaluator without invoking it via award).
    xp_repo = XPRepository(db=db_session)
    event, _ = xp_repo.insert_event_and_recompute(
        user_id=user.id,
        source=XPSource.LESSON_FIRST_COMPLETE,
        amount=20,
        occurred_at=_now(),
    )

    granted = ach_service.evaluate_after_xp_event(user=user, xp_event=event)

    assert {g.achievement_id for g in granted} == {"FIRST_LESSON"}


def test_evaluate_returns_empty_when_no_criterion_satisfied(
    db_session: Session,
) -> None:
    """An ADMIN_CORRECTION fires no MVP achievement."""
    user = _make_user(db_session)
    seed_mvp_achievements(AchievementRepository(db=db_session))
    ach_service = _make_achievement_service(db_session)

    xp_repo = XPRepository(db=db_session)
    event, _ = xp_repo.insert_event_and_recompute(
        user_id=user.id,
        source=XPSource.ADMIN_CORRECTION,
        amount=10,
        occurred_at=_now(),
    )

    granted = ach_service.evaluate_after_xp_event(user=user, xp_event=event)

    assert granted == []


def test_evaluate_is_idempotent_does_not_double_grant(
    db_session: Session,
) -> None:
    """Property 23 — second evaluation of the same trigger doesn't re-grant."""
    user = _make_user(db_session)
    seed_mvp_achievements(AchievementRepository(db=db_session))
    ach_service = _make_achievement_service(db_session)
    xp_repo = XPRepository(db=db_session)

    event, _ = xp_repo.insert_event_and_recompute(
        user_id=user.id,
        source=XPSource.LESSON_FIRST_COMPLETE,
        amount=20,
        occurred_at=_now(),
    )

    first = ach_service.evaluate_after_xp_event(user=user, xp_event=event)
    second = ach_service.evaluate_after_xp_event(user=user, xp_event=event)

    assert {g.achievement_id for g in first} == {"FIRST_LESSON"}
    assert second == []
    # Storage layer also has only one row.
    assert (
        AchievementRepository(db=db_session)
        .list_user_achievement_ids(user.id)
    ) == {"FIRST_LESSON"}


def test_evaluate_grants_streak_when_count_reaches_threshold(
    db_session: Session,
) -> None:
    """STREAK_7_DAYS fires once streak_count >= 7."""
    user = _make_user(db_session)
    seed_mvp_achievements(AchievementRepository(db=db_session))
    ach_service = _make_achievement_service(db_session)
    xp_repo = XPRepository(db=db_session)

    # Manually push the cache row to streak_count == 7. This is a
    # white-box construction that mirrors what the streak rollover
    # would produce after seven consecutive days of activity.
    user_xp = xp_repo.get_or_create_user_xp(user.id)
    user_xp.streak_count = 7
    db_session.commit()

    event, _ = xp_repo.insert_event_and_recompute(
        user_id=user.id,
        source=XPSource.LESSON_FIRST_COMPLETE,
        amount=20,
        occurred_at=_now(),
    )

    granted = ach_service.evaluate_after_xp_event(user=user, xp_event=event)
    granted_ids = {g.achievement_id for g in granted}

    assert "STREAK_7_DAYS" in granted_ids


def test_evaluate_does_not_grant_streak_below_threshold(
    db_session: Session,
) -> None:
    user = _make_user(db_session)
    seed_mvp_achievements(AchievementRepository(db=db_session))
    ach_service = _make_achievement_service(db_session)
    xp_repo = XPRepository(db=db_session)

    user_xp = xp_repo.get_or_create_user_xp(user.id)
    user_xp.streak_count = 6  # one short
    db_session.commit()

    event, _ = xp_repo.insert_event_and_recompute(
        user_id=user.id,
        source=XPSource.LESSON_FIRST_COMPLETE,
        amount=20,
        occurred_at=_now(),
    )

    granted = ach_service.evaluate_after_xp_event(user=user, xp_event=event)
    granted_ids = {g.achievement_id for g in granted}

    assert "STREAK_7_DAYS" not in granted_ids


def test_evaluate_grants_level_10_when_level_reaches_threshold(
    db_session: Session,
) -> None:
    """LEVEL_10 fires once user_xp.level >= 10."""
    user = _make_user(db_session)
    seed_mvp_achievements(AchievementRepository(db=db_session))
    ach_service = _make_achievement_service(db_session)
    xp_repo = XPRepository(db=db_session)

    # 50 * 10 * 11 = 5500 XP threshold for level 10.
    event, _ = xp_repo.insert_event_and_recompute(
        user_id=user.id,
        source=XPSource.MOCK_PASS,
        amount=5500,
        occurred_at=_now(),
    )

    granted = ach_service.evaluate_after_xp_event(user=user, xp_event=event)
    granted_ids = {g.achievement_id for g in granted}

    assert "LEVEL_10" in granted_ids


def test_evaluate_does_not_grant_level_10_below_threshold(
    db_session: Session,
) -> None:
    user = _make_user(db_session)
    seed_mvp_achievements(AchievementRepository(db=db_session))
    ach_service = _make_achievement_service(db_session)
    xp_repo = XPRepository(db=db_session)

    # 5499 XP — one below the level-10 threshold.
    event, _ = xp_repo.insert_event_and_recompute(
        user_id=user.id,
        source=XPSource.MOCK_PASS,
        amount=5499,
        occurred_at=_now(),
    )

    granted = ach_service.evaluate_after_xp_event(user=user, xp_event=event)

    assert {g.achievement_id for g in granted} == set()


# ============================================================================
# Phase 2 criteria
# ============================================================================


def test_evaluate_grants_first_perfect_subtopic_quiz(
    db_session: Session,
) -> None:
    user = _make_user(db_session)
    seed_all_achievements(AchievementRepository(db=db_session))
    ach_service = _make_achievement_service(db_session)
    xp_repo = XPRepository(db=db_session)

    event, _ = xp_repo.insert_event_and_recompute(
        user_id=user.id,
        source=XPSource.QUIZ_PERFECT,
        amount=50,
        occurred_at=_now(),
    )

    granted = ach_service.evaluate_after_xp_event(user=user, xp_event=event)
    granted_ids = {g.achievement_id for g in granted}

    assert "FIRST_PERFECT_SUBTOPIC_QUIZ" in granted_ids


def test_evaluate_grants_first_topic_passed_for_amount_100(
    db_session: Session,
) -> None:
    """Topic-quiz pass fires QUIZ_PASS with amount=100 (Req 8.4)."""
    user = _make_user(db_session)
    seed_all_achievements(AchievementRepository(db=db_session))
    ach_service = _make_achievement_service(db_session)
    xp_repo = XPRepository(db=db_session)

    event, _ = xp_repo.insert_event_and_recompute(
        user_id=user.id,
        source=XPSource.QUIZ_PASS,
        amount=100,
        occurred_at=_now(),
    )

    granted = ach_service.evaluate_after_xp_event(user=user, xp_event=event)
    granted_ids = {g.achievement_id for g in granted}

    assert "FIRST_TOPIC_PASSED" in granted_ids
    assert "FIRST_MODULE_PASSED" not in granted_ids


def test_evaluate_grants_first_module_passed_for_amount_250(
    db_session: Session,
) -> None:
    """Module-quiz pass fires QUIZ_PASS with amount=250 (Req 9.4)."""
    user = _make_user(db_session)
    seed_all_achievements(AchievementRepository(db=db_session))
    ach_service = _make_achievement_service(db_session)
    xp_repo = XPRepository(db=db_session)

    event, _ = xp_repo.insert_event_and_recompute(
        user_id=user.id,
        source=XPSource.QUIZ_PASS,
        amount=250,
        occurred_at=_now(),
    )

    granted = ach_service.evaluate_after_xp_event(user=user, xp_event=event)
    granted_ids = {g.achievement_id for g in granted}

    assert "FIRST_MODULE_PASSED" in granted_ids
    assert "FIRST_TOPIC_PASSED" not in granted_ids


def test_evaluate_subtopic_quiz_pass_amount_does_not_grant_topic(
    db_session: Session,
) -> None:
    """A subtopic QUIZ_PASS (amount=20) fires neither TOPIC nor MODULE."""
    user = _make_user(db_session)
    seed_all_achievements(AchievementRepository(db=db_session))
    ach_service = _make_achievement_service(db_session)
    xp_repo = XPRepository(db=db_session)

    event, _ = xp_repo.insert_event_and_recompute(
        user_id=user.id,
        source=XPSource.QUIZ_PASS,
        amount=20,
        occurred_at=_now(),
    )

    granted = ach_service.evaluate_after_xp_event(user=user, xp_event=event)
    granted_ids = {g.achievement_id for g in granted}

    assert "FIRST_TOPIC_PASSED" not in granted_ids
    assert "FIRST_MODULE_PASSED" not in granted_ids


def test_evaluate_grants_first_mock_passed(db_session: Session) -> None:
    user = _make_user(db_session)
    seed_all_achievements(AchievementRepository(db=db_session))
    ach_service = _make_achievement_service(db_session)
    xp_repo = XPRepository(db=db_session)

    event, _ = xp_repo.insert_event_and_recompute(
        user_id=user.id,
        source=XPSource.MOCK_PASS,
        amount=500,
        occurred_at=_now(),
    )

    granted = ach_service.evaluate_after_xp_event(user=user, xp_event=event)
    granted_ids = {g.achievement_id for g in granted}

    assert "FIRST_MOCK_PASSED" in granted_ids


def test_evaluate_grants_streak_30_at_threshold(db_session: Session) -> None:
    user = _make_user(db_session)
    seed_all_achievements(AchievementRepository(db=db_session))
    ach_service = _make_achievement_service(db_session)
    xp_repo = XPRepository(db=db_session)

    user_xp = xp_repo.get_or_create_user_xp(user.id)
    user_xp.streak_count = 30
    db_session.commit()

    event, _ = xp_repo.insert_event_and_recompute(
        user_id=user.id,
        source=XPSource.LESSON_FIRST_COMPLETE,
        amount=20,
        occurred_at=_now(),
    )

    granted = ach_service.evaluate_after_xp_event(user=user, xp_event=event)
    granted_ids = {g.achievement_id for g in granted}

    # Reaching 30 also satisfies the 7-day threshold.
    assert "STREAK_30_DAYS" in granted_ids
    assert "STREAK_7_DAYS" in granted_ids


def test_evaluate_grants_level_25_at_threshold(db_session: Session) -> None:
    user = _make_user(db_session)
    seed_all_achievements(AchievementRepository(db=db_session))
    ach_service = _make_achievement_service(db_session)
    xp_repo = XPRepository(db=db_session)

    # 50 * 25 * 26 = 32500 XP threshold for level 25.
    event, _ = xp_repo.insert_event_and_recompute(
        user_id=user.id,
        source=XPSource.MOCK_PASS,
        amount=32_500,
        occurred_at=_now(),
    )

    granted = ach_service.evaluate_after_xp_event(user=user, xp_event=event)
    granted_ids = {g.achievement_id for g in granted}

    # Crossing 25 also crosses 10.
    assert "LEVEL_25" in granted_ids
    assert "LEVEL_10" in granted_ids


# ============================================================================
# XPService integration
# ============================================================================


def test_xp_service_award_triggers_achievement_evaluator(
    db_session: Session,
) -> None:
    """XPService.award invokes the evaluator and persists the grant."""
    user = _make_user(db_session)
    seed_mvp_achievements(AchievementRepository(db=db_session))
    ach_service = _make_achievement_service(db_session)
    xp_service = _make_xp_service(db_session, ach_service)

    xp_service.award(user=user, source=XPSource.LESSON_FIRST_COMPLETE)

    granted = ach_service.list_for_user(user.id)
    assert {g.achievement_id for g in granted} == {"FIRST_LESSON"}


def test_xp_service_award_without_achievement_service_does_not_grant(
    db_session: Session,
) -> None:
    """When achievement_service is None, the award still works."""
    user = _make_user(db_session)
    seed_mvp_achievements(AchievementRepository(db=db_session))
    xp_service = XPService(
        xp_repo=XPRepository(db=db_session),
        user_repo=UserRepository(db=db_session),
        # achievement_service intentionally omitted (default None)
    )

    event, user_xp = xp_service.award(
        user=user, source=XPSource.LESSON_FIRST_COMPLETE
    )

    assert event.id is not None
    # 20 (lesson) + 25 (streak) = 45.
    assert user_xp.cumulative_xp == 45
    # No grants because the evaluator wasn't wired.
    granted = AchievementRepository(db=db_session).list_for_user(user.id)
    assert granted == []


def test_xp_service_award_idempotent_with_evaluator(
    db_session: Session,
) -> None:
    """Repeated awards don't double-grant FIRST_LESSON."""
    user = _make_user(db_session)
    seed_mvp_achievements(AchievementRepository(db=db_session))
    ach_service = _make_achievement_service(db_session)
    xp_service = _make_xp_service(db_session, ach_service)

    xp_service.award(user=user, source=XPSource.LESSON_FIRST_COMPLETE)
    xp_service.award(user=user, source=XPSource.LESSON_FIRST_COMPLETE)

    granted = ach_service.list_for_user(user.id)
    assert len([g for g in granted if g.achievement_id == "FIRST_LESSON"]) == 1


# ============================================================================
# list_for_user
# ============================================================================


def test_list_for_user_returns_metadata_joined_with_grants(
    db_session: Session,
) -> None:
    user = _make_user(db_session)
    ach_repo = AchievementRepository(db=db_session)
    seed_mvp_achievements(ach_repo)
    ach_service = _make_achievement_service(db_session)

    when = datetime(2025, 6, 1, 12, 0, tzinfo=timezone.utc)
    ach_repo.grant(
        user_id=user.id, achievement_id="FIRST_LESSON", granted_at=when
    )

    out = ach_service.list_for_user(user.id)

    assert len(out) == 1
    entry = out[0]
    assert entry.achievement_id == "FIRST_LESSON"
    assert entry.title == "First Lesson"
    assert entry.description == "Complete your first lesson."


def test_list_for_user_returns_empty_for_user_with_no_grants(
    db_session: Session,
) -> None:
    user = _make_user(db_session)
    seed_mvp_achievements(AchievementRepository(db=db_session))
    ach_service = _make_achievement_service(db_session)

    assert ach_service.list_for_user(user.id) == []


def test_list_for_user_orders_by_granted_at(db_session: Session) -> None:
    user = _make_user(db_session)
    ach_repo = AchievementRepository(db=db_session)
    seed_all_achievements(ach_repo)
    ach_service = _make_achievement_service(db_session)

    base = datetime(2025, 6, 1, tzinfo=timezone.utc)
    ach_repo.grant(
        user_id=user.id,
        achievement_id="LEVEL_25",
        granted_at=base + timedelta(days=10),
    )
    ach_repo.grant(
        user_id=user.id, achievement_id="FIRST_LESSON", granted_at=base
    )

    out = ach_service.list_for_user(user.id)

    assert [o.achievement_id for o in out] == ["FIRST_LESSON", "LEVEL_25"]
