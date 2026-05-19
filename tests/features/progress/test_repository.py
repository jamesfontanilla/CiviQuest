"""Repository tests for the progress slice (Task 8.1).

Exercises :class:`ProgressRepository` against in-memory SQLite — no
mocks, per ``testing-standards.md``. Each test seeds a real
``User -> Module -> Topic -> Subtopic -> Lesson`` chain so foreign-key
constraints are honoured during the test.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.features.content.models import (
    LessonStatus,
    Lesson,
    Module,
    Subtopic,
    Topic,
)
from app.features.progress.models import (
    LessonCompletion,
    UserModuleProgress,
    UserTopicProgress,
)
from app.features.progress.repository import ProgressRepository
from app.features.users.models import Category
from app.features.users.repository import UserRepository
from app.features.users.schemas import UserCreate


# --- factories --------------------------------------------------------------


def _make_user(
    db: Session, *, email: str = "alice@example.com"
) -> object:
    repo = UserRepository(db=db)
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


def _seed_user_subtopic_lesson(
    db: Session, *, email: str = "alice@example.com"
) -> tuple[object, Subtopic, Lesson]:
    """Create User + Module + Topic + Subtopic + Lesson chain."""
    user = _make_user(db, email=email)

    module = Module(
        category=Category.PROFESSIONAL.value,
        slug=f"m-{email}",
        title="M",
        order_index=0,
    )
    db.add(module)
    db.commit()
    db.refresh(module)

    topic = Topic(
        module_id=module.id, slug=f"t-{email}", title="T", order_index=0
    )
    db.add(topic)
    db.commit()
    db.refresh(topic)

    subtopic = Subtopic(
        topic_id=topic.id, slug=f"s-{email}", title="S", order_index=0
    )
    db.add(subtopic)
    db.commit()
    db.refresh(subtopic)

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
    db.add(lesson)
    db.commit()
    db.refresh(lesson)

    return user, subtopic, lesson


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


# --- LessonCompletion: insert + UNIQUE -------------------------------------


def test_mark_lesson_complete_persists_all_fields(db_session: Session) -> None:
    user, _, lesson = _seed_user_subtopic_lesson(db_session)
    repo = ProgressRepository(db=db_session)
    when = _now()

    row = repo.mark_lesson_complete(
        user_id=user.id,
        lesson_id=lesson.id,
        completed_at=when,
        client_event_id="evt-1",
    )

    assert row.id is not None
    assert row.user_id == user.id
    assert row.lesson_id == lesson.id
    assert row.client_event_id == "evt-1"
    # SQLite drops tz on round-trip; assert via raw second precision.
    assert row.completed_at.replace(tzinfo=None) == when.replace(tzinfo=None)


def test_mark_lesson_complete_unique_user_lesson_violation(
    db_session: Session,
) -> None:
    user, _, lesson = _seed_user_subtopic_lesson(db_session)
    repo = ProgressRepository(db=db_session)
    when = _now()
    repo.mark_lesson_complete(
        user_id=user.id, lesson_id=lesson.id, completed_at=when
    )

    with pytest.raises(IntegrityError):
        repo.mark_lesson_complete(
            user_id=user.id, lesson_id=lesson.id, completed_at=when
        )
    db_session.rollback()


def test_mark_lesson_complete_unique_client_event_id_violation(
    db_session: Session,
) -> None:
    user, _, lesson = _seed_user_subtopic_lesson(db_session)
    user2, _, lesson2 = _seed_user_subtopic_lesson(
        db_session, email="bob@example.com"
    )
    repo = ProgressRepository(db=db_session)
    when = _now()

    repo.mark_lesson_complete(
        user_id=user.id,
        lesson_id=lesson.id,
        completed_at=when,
        client_event_id="shared-evt",
    )
    with pytest.raises(IntegrityError):
        repo.mark_lesson_complete(
            user_id=user2.id,
            lesson_id=lesson2.id,
            completed_at=when,
            client_event_id="shared-evt",
        )
    db_session.rollback()


# --- LessonCompletion: lookups ---------------------------------------------


def test_get_by_client_event_id_returns_row_or_none(
    db_session: Session,
) -> None:
    user, _, lesson = _seed_user_subtopic_lesson(db_session)
    repo = ProgressRepository(db=db_session)

    assert repo.get_by_client_event_id("nope") is None

    repo.mark_lesson_complete(
        user_id=user.id,
        lesson_id=lesson.id,
        completed_at=_now(),
        client_event_id="evt-find-me",
    )
    found = repo.get_by_client_event_id("evt-find-me")

    assert found is not None
    assert found.lesson_id == lesson.id
    assert found.user_id == user.id


def test_get_lesson_completion_returns_row_or_none(
    db_session: Session,
) -> None:
    user, _, lesson = _seed_user_subtopic_lesson(db_session)
    repo = ProgressRepository(db=db_session)

    assert repo.get_lesson_completion(user.id, lesson.id) is None

    repo.mark_lesson_complete(
        user_id=user.id, lesson_id=lesson.id, completed_at=_now()
    )
    found = repo.get_lesson_completion(user.id, lesson.id)

    assert found is not None
    assert found.user_id == user.id
    assert found.lesson_id == lesson.id


# --- is_lesson_complete_for_subtopic ---------------------------------------


def test_is_lesson_complete_for_subtopic_true_when_lesson_done(
    db_session: Session,
) -> None:
    user, subtopic, lesson = _seed_user_subtopic_lesson(db_session)
    repo = ProgressRepository(db=db_session)

    repo.mark_lesson_complete(
        user_id=user.id, lesson_id=lesson.id, completed_at=_now()
    )

    assert repo.is_lesson_complete_for_subtopic(user.id, subtopic.id) is True


def test_is_lesson_complete_for_subtopic_false_without_completion(
    db_session: Session,
) -> None:
    user, subtopic, _ = _seed_user_subtopic_lesson(db_session)
    repo = ProgressRepository(db=db_session)

    assert repo.is_lesson_complete_for_subtopic(user.id, subtopic.id) is False


def test_is_lesson_complete_for_subtopic_false_when_lesson_missing(
    db_session: Session,
) -> None:
    user = _make_user(db_session)
    # No lesson row for this subtopic id.
    repo = ProgressRepository(db=db_session)

    assert repo.is_lesson_complete_for_subtopic(user.id, 99999) is False


def test_is_lesson_complete_for_subtopic_isolated_per_user(
    db_session: Session,
) -> None:
    """Bob completing the lesson does not satisfy Alice's gate."""
    alice, subtopic, lesson = _seed_user_subtopic_lesson(db_session)
    bob = _make_user(db_session, email="bob@example.com")
    repo = ProgressRepository(db=db_session)

    repo.mark_lesson_complete(
        user_id=bob.id, lesson_id=lesson.id, completed_at=_now()
    )

    assert repo.is_lesson_complete_for_subtopic(alice.id, subtopic.id) is False
    assert repo.is_lesson_complete_for_subtopic(bob.id, subtopic.id) is True


# --- mark_topic_complete / mark_module_complete: idempotent upsert --------


def test_mark_topic_complete_inserts_and_is_idempotent(
    db_session: Session,
) -> None:
    user, subtopic, _ = _seed_user_subtopic_lesson(db_session)
    topic_id = subtopic.topic_id
    repo = ProgressRepository(db=db_session)
    when = _now()

    first = repo.mark_topic_complete(user.id, topic_id, when)
    second = repo.mark_topic_complete(user.id, topic_id, when)

    assert first.id == second.id
    # Only one row in the table.
    assert (
        db_session.query(UserTopicProgress).filter_by(user_id=user.id).count()
        == 1
    )


def test_mark_module_complete_inserts_and_is_idempotent(
    db_session: Session,
) -> None:
    user, subtopic, _ = _seed_user_subtopic_lesson(db_session)
    # Walk back up to the module.
    topic = (
        db_session.query(Topic).filter_by(id=subtopic.topic_id).one()
    )
    module_id = topic.module_id
    repo = ProgressRepository(db=db_session)
    when = _now()

    first = repo.mark_module_complete(user.id, module_id, when)
    second = repo.mark_module_complete(user.id, module_id, when)

    assert first.id == second.id
    assert (
        db_session.query(UserModuleProgress).filter_by(user_id=user.id).count()
        == 1
    )


def test_get_topic_progress_returns_none_if_absent(db_session: Session) -> None:
    user = _make_user(db_session)
    repo = ProgressRepository(db=db_session)
    assert repo.get_topic_progress(user.id, 999) is None


def test_get_module_progress_returns_none_if_absent(
    db_session: Session,
) -> None:
    user = _make_user(db_session)
    repo = ProgressRepository(db=db_session)
    assert repo.get_module_progress(user.id, 999) is None


# --- list_completions_for_user --------------------------------------------


def test_list_completions_for_user_returns_only_user_rows(
    db_session: Session,
) -> None:
    alice, _, lesson_a = _seed_user_subtopic_lesson(db_session)
    bob, _, lesson_b = _seed_user_subtopic_lesson(
        db_session, email="bob@example.com"
    )
    repo = ProgressRepository(db=db_session)
    when = _now()

    repo.mark_lesson_complete(
        user_id=alice.id, lesson_id=lesson_a.id, completed_at=when
    )
    repo.mark_lesson_complete(
        user_id=bob.id, lesson_id=lesson_b.id, completed_at=when
    )

    rows = repo.list_completions_for_user(alice.id)

    assert len(rows) == 1
    assert rows[0].user_id == alice.id
    assert rows[0].lesson_id == lesson_a.id


def test_list_completions_for_user_empty_when_user_has_none(
    db_session: Session,
) -> None:
    user = _make_user(db_session)
    repo = ProgressRepository(db=db_session)

    assert repo.list_completions_for_user(user.id) == []


def test_list_completions_for_user_orders_by_completed_at(
    db_session: Session,
) -> None:
    """Snapshot output must be deterministic — ordered by completion time."""
    user = _make_user(db_session)
    # Build two lessons under the same module so we have two distinct
    # ``lesson_id`` values for the same user.
    module = Module(
        category=Category.PROFESSIONAL.value,
        slug="m-order",
        title="M",
        order_index=0,
    )
    db_session.add(module)
    db_session.commit()
    db_session.refresh(module)
    topic = Topic(module_id=module.id, slug="t", title="T", order_index=0)
    db_session.add(topic)
    db_session.commit()
    db_session.refresh(topic)
    subs = []
    lessons = []
    for i in range(2):
        sub = Subtopic(
            topic_id=topic.id, slug=f"s{i}", title="S", order_index=i
        )
        db_session.add(sub)
        db_session.commit()
        db_session.refresh(sub)
        subs.append(sub)
        ls = Lesson(
            subtopic_id=sub.id,
            content_json={"x": "y"},
            status=LessonStatus.PUBLISHED.value,
        )
        db_session.add(ls)
        db_session.commit()
        db_session.refresh(ls)
        lessons.append(ls)

    repo = ProgressRepository(db=db_session)
    later = datetime(2025, 1, 2, tzinfo=timezone.utc)
    earlier = datetime(2025, 1, 1, tzinfo=timezone.utc)

    # Insert later first to prove ordering is by ``completed_at`` not
    # insertion order.
    repo.mark_lesson_complete(
        user_id=user.id, lesson_id=lessons[0].id, completed_at=later
    )
    repo.mark_lesson_complete(
        user_id=user.id, lesson_id=lessons[1].id, completed_at=earlier
    )

    rows = repo.list_completions_for_user(user.id)

    assert [r.lesson_id for r in rows] == [lessons[1].id, lessons[0].id]


# --- LessonCompletion exists in DB (smoke for model + conftest registration)


def test_lesson_completion_table_is_created(db_session: Session) -> None:
    """Sanity check: confirm the table is registered on Base.metadata so
    ``conftest.py`` ``create_all`` picks it up."""
    db_session.query(LessonCompletion).all()  # would raise OperationalError
