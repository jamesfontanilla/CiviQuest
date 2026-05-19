"""Property-based tests for the progress slice (Task 8.3).

Two correctness properties from the design's catalog land here:

- **Property 24 — Progress durability before response** (Req 14.1):
  for any ``complete_lesson`` call, the persisted row is observable in
  the database BEFORE :meth:`ProgressService.complete_lesson` returns.
- **Property 25 — Resume snapshot fidelity** (Req 14.2): for any
  sequence of N lesson-complete events on a single user, the snapshot
  returned by :meth:`ProgressService.get_snapshot` exactly enumerates
  the completed lesson ids — no missing entries, no spurious ones.

Both tests run against a real :class:`Session` (via the ``db_session``
fixture) so they exercise the ORM + UNIQUE constraints at the same
time. The ``HealthCheck.function_scoped_fixture`` suppression is
needed because Hypothesis re-uses the per-test session across the
generated examples; this is fine for our purposes (each example
operates on disjoint data) but Hypothesis warns about it by default.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from hypothesis import HealthCheck, given, settings, strategies as st

from app.features.content.models import LessonStatus, Lesson, Module, Subtopic, Topic
from app.features.content.repository import (
    LessonRepository,
    SubtopicRepository,
)
from app.features.progress.repository import ProgressRepository
from app.features.progress.schemas import LessonCompleteRequest
from app.features.progress.service import ProgressService
from app.features.users.models import Category, User
from app.features.users.repository import UserRepository
from app.features.users.schemas import UserCreate


_PBT_SETTINGS = dict(
    max_examples=20,
    deadline=None,
    suppress_health_check=[
        HealthCheck.too_slow,
        HealthCheck.function_scoped_fixture,
    ],
)


# ----- helpers --------------------------------------------------------------


def _make_user(
    db_session, *, email: str = "alice@example.com"
) -> User:
    repo = UserRepository(db=db_session)
    return repo.create(
        UserCreate(
            email=email,
            display_name="Alice",
            age=25,
            category=Category.PROFESSIONAL.value,
            password="Strong1Pass!",
        ),
        password_hash="bcrypt$fake$hash",
    )


def _seed_module_topic(db_session) -> Topic:
    module = Module(
        category=Category.PROFESSIONAL.value,
        slug="m-pbt",
        title="M",
        order_index=0,
    )
    db_session.add(module)
    db_session.commit()
    db_session.refresh(module)
    topic = Topic(
        module_id=module.id, slug="t-pbt", title="T", order_index=0
    )
    db_session.add(topic)
    db_session.commit()
    db_session.refresh(topic)
    return topic


def _make_subtopic_and_lesson(
    db_session, topic: Topic, slug: str
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


def _build_service(db_session) -> ProgressService:
    return ProgressService(
        progress_repo=ProgressRepository(db=db_session),
        lesson_repo=LessonRepository(db=db_session),
        subtopic_repo=SubtopicRepository(db=db_session),
    )


# ----- Property 24: progress durability ------------------------------------
#
# Validates: Requirements 14.1
#
# For any ``complete_lesson`` call, the row must exist in the DB BEFORE
# the response is returned. The test calls the service and then,
# immediately after, queries the repository to confirm the row is
# observable.


@given(
    client_event_id=st.one_of(
        st.none(),
        st.text(
            alphabet=st.characters(
                whitelist_categories=("Lu", "Ll", "Nd"),
                whitelist_characters="-_",
            ),
            min_size=1,
            max_size=32,
        ),
    ),
)
@settings(**_PBT_SETTINGS)
def test_property_24_progress_durability_before_response(
    db_session, client_event_id: str | None
) -> None:
    """The persisted row is observable in the DB the instant
    ``complete_lesson`` returns (Req 14.1)."""
    # Each generated example runs against the same db_session — clean
    # the previous example's rows so we can exercise the persist-before-
    # respond invariant on a fresh (user, lesson) pair every time.
    from app.features.progress.models import LessonCompletion

    db_session.query(LessonCompletion).delete()
    db_session.commit()

    user = (
        db_session.query(User).filter_by(email="durability@example.com").one_or_none()
    )
    if user is None:
        user = _make_user(db_session, email="durability@example.com")

    topic = (
        db_session.query(Topic).filter_by(slug="t-pbt").one_or_none()
    )
    if topic is None:
        topic = _seed_module_topic(db_session)

    # Always re-seed a fresh lesson so the (user, lesson) UNIQUE
    # doesn't collide across hypothesis examples.
    _, lesson = _make_subtopic_and_lesson(
        db_session, topic, slug=f"sub-{lesson_seed()}"
    )

    service = _build_service(db_session)
    progress_repo = ProgressRepository(db=db_session)

    response = service.complete_lesson(
        user=user,
        subtopic_id=lesson.subtopic_id,
        payload=LessonCompleteRequest(client_event_id=client_event_id),
    )

    # The row must already be observable in the DB.
    persisted = progress_repo.get_lesson_completion(user.id, lesson.id)
    assert persisted is not None, (
        "row must be persisted before complete_lesson returns (Req 14.1)"
    )
    assert persisted.lesson_id == response.lesson_id
    assert persisted.user_id == response.user_id


# Module-scoped counter so each example produces a unique slug. Resets
# every test invocation — Hypothesis re-runs the function fresh.
_LESSON_SEED_COUNTER: list[int] = [0]


def lesson_seed() -> str:
    _LESSON_SEED_COUNTER[0] += 1
    return f"{_LESSON_SEED_COUNTER[0]:08d}"


# ----- Property 25: resume snapshot fidelity ------------------------------
#
# Validates: Requirements 14.2
#
# For any 1..5 lesson-complete events on a single user, the snapshot's
# ``completed_lesson_ids`` exactly equals the set of completed lesson
# ids — no duplicates, no missing entries.


@given(n=st.integers(min_value=1, max_value=5))
@settings(**_PBT_SETTINGS)
def test_property_25_resume_snapshot_fidelity(db_session, n: int) -> None:
    """The snapshot enumerates exactly the lesson ids the user has
    completed (Req 14.2)."""
    # Reset progress rows for a clean per-example state.
    from app.features.progress.models import LessonCompletion

    db_session.query(LessonCompletion).delete()
    db_session.commit()

    user = (
        db_session.query(User).filter_by(email="snapshot@example.com").one_or_none()
    )
    if user is None:
        user = _make_user(db_session, email="snapshot@example.com")

    topic = (
        db_session.query(Topic).filter_by(slug="t-pbt").one_or_none()
    )
    if topic is None:
        topic = _seed_module_topic(db_session)

    # Build N distinct subtopic+lesson pairs so the (user, lesson)
    # UNIQUE constraint is honoured.
    lessons: list[Lesson] = []
    for _ in range(n):
        _, lesson = _make_subtopic_and_lesson(
            db_session, topic, slug=f"snap-{lesson_seed()}"
        )
        lessons.append(lesson)

    service = _build_service(db_session)

    # Complete the N lessons with monotonically increasing timestamps so
    # the snapshot ordering is deterministic.
    base_time = datetime(2025, 1, 1, tzinfo=timezone.utc)
    for i, lesson in enumerate(lessons):
        service.complete_lesson(
            user=user,
            subtopic_id=lesson.subtopic_id,
            payload=LessonCompleteRequest(
                completed_at=base_time + timedelta(minutes=i)
            ),
        )

    snapshot = service.get_snapshot(user)

    # The snapshot must enumerate every completed lesson exactly once.
    assert sorted(snapshot.completed_lesson_ids) == sorted(
        lesson.id for lesson in lessons
    )
    assert len(snapshot.completed_lesson_ids) == n
