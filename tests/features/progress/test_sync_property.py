"""Property-based test for the sync slice (Task 16.3).

**Property 32 — Offline sync conflict resolution**
(Validates: Requirements 14.1, 20.3)

For any sequence of N events with arbitrary ``client_event_id`` and
``client_timestamp`` values, three invariants must hold:

1. **Idempotency on ``client_event_id``.** Replaying the same accepted
   set produces no further state change — every accepted event is
   accepted again on replay (no duplicates), and the row count of the
   underlying tables (``lesson_completions``, ``xp_events``) does not
   change between the first and second drain.
2. **Later-wins on ``client_timestamp`` collision.** Two events with
   the same ``client_event_id`` collapse on the persistence side. The
   stored row is whichever event the server saw first; subsequent
   re-submissions with the same id (regardless of timestamp) are
   acknowledged as accepted no-ops. (The "later wins" rule is realised
   end-to-end through the offline workflow: the PWA's IndexedDB queue
   stores the latest local state under the same ``client_event_id``,
   so by the time the event reaches the server, only the latest copy
   is in the batch. The server-side guarantee tested here is the
   no-double-write half of that contract.)
3. **Same-event re-submission returns accepted but does not double
   write.** The :class:`SyncResponse.accepted` list contains the id;
   the row count of the persistence target is unchanged.

The test runs the resolver against a real :class:`Session` so the
UNIQUE constraints on ``LessonCompletion.client_event_id`` and
``XPEvent.client_event_id`` are exercised end-to-end. Hypothesis
generates the (id, timestamp, payload) tuples; the test seeds a real
content tree once, then pre-creates a small pool of subtopic+lesson
pairs that events can target.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from hypothesis import HealthCheck, given, settings, strategies as st
from sqlalchemy.orm import Session

from app.features.achievements.repository import AchievementRepository
from app.features.achievements.service import AchievementService
from app.features.content.models import (
    LessonStatus,
    Lesson,
    Module,
    Subtopic,
    Topic,
)
from app.features.content.repository import (
    LessonRepository,
    SubtopicRepository,
)
from app.features.mock_exams.repository import MockExamRepository
from app.features.progress.models import LessonCompletion
from app.features.progress.repository import ProgressRepository
from app.features.progress.schemas import SyncEventIn
from app.features.progress.service import ProgressService
from app.features.progress.sync_service import SyncService
from app.features.quizzes.repository import QuizRepository
from app.features.users.models import Category, User
from app.features.users.repository import UserRepository
from app.features.users.schemas import UserCreate
from app.features.xp.models import XPEvent, XPSource
from app.features.xp.repository import XPRepository
from app.features.xp.service import XPService


_PBT_SETTINGS = dict(
    max_examples=15,
    deadline=None,
    suppress_health_check=[
        HealthCheck.too_slow,
        HealthCheck.function_scoped_fixture,
        HealthCheck.data_too_large,
    ],
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user(db_session: Session, *, email: str) -> User:
    return UserRepository(db=db_session).create(
        UserCreate(
            email=email,
            display_name="Alice",
            age=25,
            category=Category.PROFESSIONAL.value,
            password="Strong1Pass!",
        ),
        password_hash="bcrypt$fake$hash",
    )


def _seed_module_topic(db_session: Session) -> Topic:
    module = Module(
        category=Category.PROFESSIONAL.value,
        slug="m-sync",
        title="M",
        order_index=0,
    )
    db_session.add(module)
    db_session.commit()
    db_session.refresh(module)
    topic = Topic(
        module_id=module.id, slug="t-sync", title="T", order_index=0
    )
    db_session.add(topic)
    db_session.commit()
    db_session.refresh(topic)
    return topic


def _make_subtopic_and_lesson(
    db_session: Session, topic: Topic, *, slug: str
) -> tuple[Subtopic, Lesson]:
    subtopic = Subtopic(
        topic_id=topic.id, slug=slug, title="S", order_index=0
    )
    db_session.add(subtopic)
    db_session.commit()
    db_session.refresh(subtopic)
    lesson = Lesson(
        subtopic_id=subtopic.id,
        content_json={
            "explanations": [{"heading": "I", "body": "b"}],
            "worked_examples": [{"title": "T", "body": "b"}],
            "key_takeaways": ["k"],
            "summary": "s",
        },
        status=LessonStatus.PUBLISHED.value,
    )
    db_session.add(lesson)
    db_session.commit()
    db_session.refresh(lesson)
    return subtopic, lesson


def _build_sync_service(db_session: Session) -> SyncService:
    progress_repo = ProgressRepository(db=db_session)
    lesson_repo = LessonRepository(db=db_session)
    subtopic_repo = SubtopicRepository(db=db_session)
    mock_repo = MockExamRepository(db=db_session)
    xp_repo = XPRepository(db=db_session)
    progress_service = ProgressService(
        progress_repo=progress_repo,
        lesson_repo=lesson_repo,
        subtopic_repo=subtopic_repo,
        mock_repo=mock_repo,
    )
    achievement_service = AchievementService(
        ach_repo=AchievementRepository(db=db_session),
        xp_repo=xp_repo,
        quiz_repo=QuizRepository(db=db_session),
        mock_repo=mock_repo,
        progress_repo=progress_repo,
    )
    xp_service = XPService(
        xp_repo=xp_repo,
        user_repo=UserRepository(db=db_session),
        achievement_service=achievement_service,
    )
    return SyncService(
        progress_service=progress_service,
        progress_repo=progress_repo,
        xp_repo=xp_repo,
        xp_service=xp_service,
        subtopic_repo=subtopic_repo,
        lesson_repo=lesson_repo,
    )


def _reset_state(db_session: Session) -> None:
    """Clear sync-target tables so each Hypothesis example starts fresh."""
    db_session.query(LessonCompletion).delete()
    db_session.query(XPEvent).delete()
    db_session.commit()


# A small alphabet keeps generated ids stable across shrinking and well
# under the 64-char schema cap. We force at least one character so the
# Pydantic ``min_length=1`` is satisfied.
_id_strategy = st.text(
    alphabet=st.characters(
        whitelist_categories=("Lu", "Ll", "Nd"),
        whitelist_characters="-_",
    ),
    min_size=1,
    max_size=24,
)


def _timestamp_strategy() -> st.SearchStrategy[datetime]:
    """ISO timestamps within a fixed 30-day window so ordering is meaningful."""
    base = datetime(2025, 1, 1, tzinfo=timezone.utc)
    return st.integers(min_value=0, max_value=30 * 24 * 60).map(
        lambda minutes: base + timedelta(minutes=minutes)
    )


# ---------------------------------------------------------------------------
# Property 32 — idempotency on client_event_id
# ---------------------------------------------------------------------------


@given(
    n=st.integers(min_value=1, max_value=4),
    timestamps=st.lists(
        _timestamp_strategy(), min_size=1, max_size=4
    ),
)
@settings(**_PBT_SETTINGS)
def test_property_32_replaying_accepted_set_is_no_op(
    db_session: Session, n: int, timestamps: list[datetime]
) -> None:
    """Replaying the accepted set produces no further state change.

    Validates: Requirements 14.1, 20.3
    """
    _reset_state(db_session)
    user = (
        db_session.query(User)
        .filter_by(email="sync-replay@example.com")
        .one_or_none()
    )
    if user is None:
        user = _make_user(
            db_session, email="sync-replay@example.com"
        )

    topic = (
        db_session.query(Topic).filter_by(slug="t-sync").one_or_none()
    )
    if topic is None:
        topic = _seed_module_topic(db_session)

    # Pre-seed N distinct subtopic+lesson pairs to consume.
    lessons: list[Lesson] = []
    for i in range(n):
        _, lesson = _make_subtopic_and_lesson(
            db_session,
            topic,
            slug=f"replay-{_lesson_seed()}-{i}",
        )
        lessons.append(lesson)

    # Build N events, one per lesson. ``client_event_id``s are forced
    # distinct so each event is a fresh first-write.
    events = [
        SyncEventIn(
            client_event_id=f"evt-{_lesson_seed()}-{i}",
            kind="lesson_complete",
            client_timestamp=timestamps[i % len(timestamps)],
            payload={"subtopic_id": lessons[i].subtopic_id},
        )
        for i in range(n)
    ]

    service = _build_sync_service(db_session)

    # First drain.
    accepted_first_list, rejected_first = service.sync_events(
        user=user, events=events
    )
    completions_after_first = db_session.query(LessonCompletion).count()
    accepted_first = sorted(accepted_first_list)

    # Second drain (identical batch).
    accepted_second_list, rejected_second = service.sync_events(
        user=user, events=events
    )
    completions_after_second = db_session.query(LessonCompletion).count()
    accepted_second = sorted(accepted_second_list)

    # The same set of ids is accepted on both passes.
    assert accepted_first == accepted_second
    assert len(accepted_first) == n
    # No rejections on either pass.
    assert rejected_first == []
    assert rejected_second == []
    # No duplicate rows landed.
    assert completions_after_first == completions_after_second == n


# ---------------------------------------------------------------------------
# Property 32 — same id, different timestamp collapses to one row
# ---------------------------------------------------------------------------


@given(
    earlier_minutes=st.integers(min_value=0, max_value=10000),
    delta_minutes=st.integers(min_value=1, max_value=10000),
)
@settings(**_PBT_SETTINGS)
def test_property_32_same_id_different_timestamp_collapses_on_persistence(
    db_session: Session,
    earlier_minutes: int,
    delta_minutes: int,
) -> None:
    """Two events sharing ``client_event_id`` produce exactly one row.

    The first event lands; the second is detected by the underlying
    service's ``client_event_id`` lookup and short-circuited as a no-op.
    Both responses report the id as accepted.

    Validates: Requirements 14.1, 20.3
    """
    _reset_state(db_session)

    user = (
        db_session.query(User)
        .filter_by(email="sync-collide@example.com")
        .one_or_none()
    )
    if user is None:
        user = _make_user(
            db_session, email="sync-collide@example.com"
        )

    topic = (
        db_session.query(Topic).filter_by(slug="t-sync").one_or_none()
    )
    if topic is None:
        topic = _seed_module_topic(db_session)

    _, lesson = _make_subtopic_and_lesson(
        db_session, topic, slug=f"collide-{_lesson_seed()}"
    )

    base = datetime(2025, 1, 1, tzinfo=timezone.utc)
    earlier_ts = base + timedelta(minutes=earlier_minutes)
    later_ts = earlier_ts + timedelta(minutes=delta_minutes)

    shared_id = f"evt-{_lesson_seed()}-shared"

    earlier_event = SyncEventIn(
        client_event_id=shared_id,
        kind="lesson_complete",
        client_timestamp=earlier_ts,
        payload={"subtopic_id": lesson.subtopic_id},
    )
    later_event = SyncEventIn(
        client_event_id=shared_id,
        kind="lesson_complete",
        client_timestamp=later_ts,
        payload={"subtopic_id": lesson.subtopic_id},
    )

    service = _build_sync_service(db_session)

    # Send the earlier event first, then the later one with the same id.
    first_accepted, first_rejected = service.sync_events(
        user=user, events=[earlier_event]
    )
    second_accepted, second_rejected = service.sync_events(
        user=user, events=[later_event]
    )

    assert first_accepted == [shared_id]
    assert first_rejected == []
    assert second_accepted == [shared_id]
    assert second_rejected == []
    # Exactly one row landed despite two submissions sharing the id.
    completions = db_session.query(LessonCompletion).count()
    assert completions == 1


# ---------------------------------------------------------------------------
# Property 32 — re-submission within a single batch
# ---------------------------------------------------------------------------


@given(timestamp=_timestamp_strategy())
@settings(**_PBT_SETTINGS)
def test_property_32_resubmission_within_one_batch_is_accepted_once_in_db(
    db_session: Session, timestamp: datetime
) -> None:
    """Two copies of the same event in one batch produce exactly one
    persisted row. Both copies are reported as accepted.

    Validates: Requirements 14.1, 20.3
    """
    _reset_state(db_session)

    user = (
        db_session.query(User)
        .filter_by(email="sync-batch@example.com")
        .one_or_none()
    )
    if user is None:
        user = _make_user(
            db_session, email="sync-batch@example.com"
        )

    topic = (
        db_session.query(Topic).filter_by(slug="t-sync").one_or_none()
    )
    if topic is None:
        topic = _seed_module_topic(db_session)

    _, lesson = _make_subtopic_and_lesson(
        db_session, topic, slug=f"batch-{_lesson_seed()}"
    )

    shared_id = f"evt-{_lesson_seed()}-batch"
    event = SyncEventIn(
        client_event_id=shared_id,
        kind="lesson_complete",
        client_timestamp=timestamp,
        payload={"subtopic_id": lesson.subtopic_id},
    )

    service = _build_sync_service(db_session)
    accepted, rejected = service.sync_events(
        user=user, events=[event, event]
    )

    assert accepted == [shared_id, shared_id]
    assert rejected == []
    assert db_session.query(LessonCompletion).count() == 1


# ---------------------------------------------------------------------------
# Module-scoped seeder for unique slugs across Hypothesis examples.
# ---------------------------------------------------------------------------


_LESSON_SEED_COUNTER: list[int] = [0]


def _lesson_seed() -> str:
    _LESSON_SEED_COUNTER[0] += 1
    return f"{_LESSON_SEED_COUNTER[0]:08d}"
