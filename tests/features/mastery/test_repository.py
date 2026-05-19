"""Repository tests for the mastery feature — real DB, no mocks."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.features.content.models import Module, Subtopic, Topic
from app.features.mastery.models import (
    MasteryLevel,
    ReviewSchedule,
    UserSubtopicMastery,
)
from app.features.mastery.repository import (
    MasteryRepository,
    ReviewScheduleRepository,
)
from app.features.users.models import AccountState, Category, Role, User


def _make_user(db: Session, **overrides) -> User:
    defaults = {
        "email": "test@example.com",
        "display_name": "Test User",
        "age": 25,
        "category": Category.PROFESSIONAL.value,
        "role": Role.LEARNER.value,
        "account_state": AccountState.VERIFIED.value,
        "is_banned": False,
        "tz_name": "UTC",
        "password_hash": "hashed",
        "cross_category_preview": False,
    }
    user = User(**{**defaults, **overrides})
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _make_subtopic(db: Session, **overrides) -> Subtopic:
    """Create a module -> topic -> subtopic chain with unique slugs."""
    import uuid
    uid = uuid.uuid4().hex[:8]

    module = Module(
        category=Category.PROFESSIONAL.value,
        slug=f"mod-{uid}",
        title="Test Module",
        order_index=0,
    )
    db.add(module)
    db.commit()
    db.refresh(module)

    topic = Topic(
        module_id=module.id,
        slug=f"topic-{uid}",
        title="Test Topic",
        order_index=0,
    )
    db.add(topic)
    db.commit()
    db.refresh(topic)

    defaults = {
        "topic_id": topic.id,
        "slug": f"subtopic-{uid}",
        "title": "Test Subtopic",
        "order_index": 0,
    }
    subtopic = Subtopic(**{**defaults, **overrides, "topic_id": topic.id})
    db.add(subtopic)
    db.commit()
    db.refresh(subtopic)
    return subtopic


# ---------------------------------------------------------------------------
# MasteryRepository
# ---------------------------------------------------------------------------


class TestMasteryRepository:
    def test_get_by_user_and_subtopic_returns_none_when_empty(self, db_session: Session):
        repo = MasteryRepository(db=db_session)
        result = repo.get_by_user_and_subtopic(999, 999)
        assert result is None

    def test_upsert_creates_new_row(self, db_session: Session):
        user = _make_user(db_session)
        subtopic = _make_subtopic(db_session)
        repo = MasteryRepository(db=db_session)

        mastery = UserSubtopicMastery(
            user_id=user.id,
            subtopic_id=subtopic.id,
            mastery_score=0.5,
            mastery_level=MasteryLevel.PROFICIENT.value,
        )
        result = repo.upsert(mastery)
        assert result.id is not None
        assert result.mastery_score == 0.5

    def test_get_by_user_and_subtopic_returns_row(self, db_session: Session):
        user = _make_user(db_session)
        subtopic = _make_subtopic(db_session)
        repo = MasteryRepository(db=db_session)

        mastery = UserSubtopicMastery(
            user_id=user.id,
            subtopic_id=subtopic.id,
            mastery_score=0.3,
            mastery_level=MasteryLevel.FAMILIAR.value,
        )
        repo.upsert(mastery)

        found = repo.get_by_user_and_subtopic(user.id, subtopic.id)
        assert found is not None
        assert found.mastery_score == 0.3

    def test_list_by_user(self, db_session: Session):
        user = _make_user(db_session)
        s1 = _make_subtopic(db_session)
        s2 = _make_subtopic(db_session)
        repo = MasteryRepository(db=db_session)

        repo.upsert(UserSubtopicMastery(
            user_id=user.id, subtopic_id=s1.id,
            mastery_score=0.3, mastery_level=MasteryLevel.FAMILIAR.value,
        ))
        repo.upsert(UserSubtopicMastery(
            user_id=user.id, subtopic_id=s2.id,
            mastery_score=0.8, mastery_level=MasteryLevel.ADVANCED.value,
        ))

        results = repo.list_by_user(user.id)
        assert len(results) == 2

    def test_list_weakest_returns_ordered(self, db_session: Session):
        user = _make_user(db_session)
        s1 = _make_subtopic(db_session)
        s2 = _make_subtopic(db_session)
        s3 = _make_subtopic(db_session)
        repo = MasteryRepository(db=db_session)

        repo.upsert(UserSubtopicMastery(
            user_id=user.id, subtopic_id=s1.id,
            mastery_score=0.9, mastery_level=MasteryLevel.MASTERED.value,
        ))
        repo.upsert(UserSubtopicMastery(
            user_id=user.id, subtopic_id=s2.id,
            mastery_score=0.1, mastery_level=MasteryLevel.BEGINNER.value,
        ))
        repo.upsert(UserSubtopicMastery(
            user_id=user.id, subtopic_id=s3.id,
            mastery_score=0.5, mastery_level=MasteryLevel.PROFICIENT.value,
        ))

        results = repo.list_weakest(user.id, limit=2)
        assert len(results) == 2
        assert results[0].mastery_score == 0.1
        assert results[1].mastery_score == 0.5


# ---------------------------------------------------------------------------
# ReviewScheduleRepository
# ---------------------------------------------------------------------------


class TestReviewScheduleRepository:
    def test_get_by_user_and_subtopic_returns_none(self, db_session: Session):
        repo = ReviewScheduleRepository(db=db_session)
        result = repo.get_by_user_and_subtopic(999, 999)
        assert result is None

    def test_upsert_creates_schedule(self, db_session: Session):
        user = _make_user(db_session)
        subtopic = _make_subtopic(db_session)
        repo = ReviewScheduleRepository(db=db_session)

        now = datetime.now(tz=timezone.utc)
        schedule = ReviewSchedule(
            user_id=user.id,
            subtopic_id=subtopic.id,
            next_review_at=now + timedelta(days=1),
            interval_days=1.0,
            ease_factor=2.5,
            repetitions=0,
        )
        result = repo.upsert(schedule)
        assert result.id is not None
        assert result.interval_days == 1.0

    def test_list_due_returns_overdue_items(self, db_session: Session):
        user = _make_user(db_session)
        s1 = _make_subtopic(db_session)
        s2 = _make_subtopic(db_session)
        repo = ReviewScheduleRepository(db=db_session)

        now = datetime.now(tz=timezone.utc)
        # s1 is overdue
        repo.upsert(ReviewSchedule(
            user_id=user.id, subtopic_id=s1.id,
            next_review_at=now - timedelta(days=2),
        ))
        # s2 is not yet due
        repo.upsert(ReviewSchedule(
            user_id=user.id, subtopic_id=s2.id,
            next_review_at=now + timedelta(days=5),
        ))

        due = repo.list_due(user.id, now=now)
        assert len(due) == 1
        assert due[0].subtopic_id == s1.id

    def test_list_by_user(self, db_session: Session):
        user = _make_user(db_session)
        s1 = _make_subtopic(db_session)
        s2 = _make_subtopic(db_session)
        repo = ReviewScheduleRepository(db=db_session)

        now = datetime.now(tz=timezone.utc)
        repo.upsert(ReviewSchedule(
            user_id=user.id, subtopic_id=s1.id,
            next_review_at=now + timedelta(days=1),
        ))
        repo.upsert(ReviewSchedule(
            user_id=user.id, subtopic_id=s2.id,
            next_review_at=now + timedelta(days=3),
        ))

        results = repo.list_by_user(user.id)
        assert len(results) == 2
