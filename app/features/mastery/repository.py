"""Repository layer for the mastery feature.

Provides DB access for UserSubtopicMastery and ReviewSchedule models.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.features.mastery.models import ReviewSchedule, UserSubtopicMastery
from app.infrastructure.database.base import Base
from app.infrastructure.repositories.base import BaseRepository


class MasteryRepository(BaseRepository[UserSubtopicMastery]):
    """DB access for UserSubtopicMastery rows."""

    model = UserSubtopicMastery

    def get_by_user_and_subtopic(
        self, user_id: int, subtopic_id: int
    ) -> UserSubtopicMastery | None:
        """Return the mastery row for a specific user+subtopic pair."""
        stmt = select(UserSubtopicMastery).where(
            UserSubtopicMastery.user_id == user_id,
            UserSubtopicMastery.subtopic_id == subtopic_id,
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def list_by_user(self, user_id: int) -> Sequence[UserSubtopicMastery]:
        """Return all mastery rows for a user."""
        stmt = select(UserSubtopicMastery).where(
            UserSubtopicMastery.user_id == user_id
        )
        return self.db.execute(stmt).scalars().all()

    def list_weakest(
        self, user_id: int, *, limit: int = 5
    ) -> Sequence[UserSubtopicMastery]:
        """Return the N subtopics with lowest mastery_score for a user."""
        stmt = (
            select(UserSubtopicMastery)
            .where(UserSubtopicMastery.user_id == user_id)
            .order_by(UserSubtopicMastery.mastery_score.asc())
            .limit(limit)
        )
        return self.db.execute(stmt).scalars().all()

    def upsert(self, mastery: UserSubtopicMastery) -> UserSubtopicMastery:
        """Create or update a mastery row (merge by PK)."""
        self.db.add(mastery)
        self.db.commit()
        self.db.refresh(mastery)
        return mastery


class ReviewScheduleRepository(BaseRepository[ReviewSchedule]):
    """DB access for ReviewSchedule rows."""

    model = ReviewSchedule

    def get_by_user_and_subtopic(
        self, user_id: int, subtopic_id: int
    ) -> ReviewSchedule | None:
        """Return the schedule for a specific user+subtopic pair."""
        stmt = select(ReviewSchedule).where(
            ReviewSchedule.user_id == user_id,
            ReviewSchedule.subtopic_id == subtopic_id,
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def list_due(
        self, user_id: int, *, now: datetime, limit: int = 10
    ) -> Sequence[ReviewSchedule]:
        """Return schedules where next_review_at <= now, ordered by most overdue."""
        stmt = (
            select(ReviewSchedule)
            .where(
                ReviewSchedule.user_id == user_id,
                ReviewSchedule.next_review_at <= now,
            )
            .order_by(ReviewSchedule.next_review_at.asc())
            .limit(limit)
        )
        return self.db.execute(stmt).scalars().all()

    def list_by_user(self, user_id: int) -> Sequence[ReviewSchedule]:
        """Return all review schedules for a user."""
        stmt = select(ReviewSchedule).where(
            ReviewSchedule.user_id == user_id
        )
        return self.db.execute(stmt).scalars().all()

    def upsert(self, schedule: ReviewSchedule) -> ReviewSchedule:
        """Create or update a review schedule row."""
        self.db.add(schedule)
        self.db.commit()
        self.db.refresh(schedule)
        return schedule
