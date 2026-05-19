"""Repository for focus sessions."""

from __future__ import annotations

from datetime import date, datetime, time, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.features.focus.models import FocusSession
from app.infrastructure.repositories.base import BaseRepository


class FocusSessionRepository(BaseRepository[FocusSession]):
    """Data access for focus sessions."""

    model = FocusSession

    def __init__(self, db: Session) -> None:
        super().__init__(db)

    def get_user_session(self, user_id: int, session_id: int) -> FocusSession | None:
        """Get a specific session belonging to a user."""
        stmt = select(FocusSession).where(
            FocusSession.id == session_id,
            FocusSession.user_id == user_id,
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def count_user_sessions(self, user_id: int) -> int:
        """Count total completed sessions for a user."""
        stmt = select(func.count(FocusSession.id)).where(
            FocusSession.user_id == user_id,
            FocusSession.completed == True,  # noqa: E712
        )
        result = self.db.execute(stmt).scalar()
        return result or 0

    def total_focus_minutes(self, user_id: int) -> int:
        """Sum of all focus minutes for a user."""
        stmt = select(func.coalesce(func.sum(FocusSession.total_focus_minutes), 0)).where(
            FocusSession.user_id == user_id,
            FocusSession.completed == True,  # noqa: E712
        )
        result = self.db.execute(stmt).scalar()
        return result or 0

    def avg_session_minutes(self, user_id: int) -> float:
        """Average focus minutes per completed session."""
        stmt = select(func.avg(FocusSession.total_focus_minutes)).where(
            FocusSession.user_id == user_id,
            FocusSession.completed == True,  # noqa: E712
        )
        result = self.db.execute(stmt).scalar()
        return float(result) if result else 0.0

    def sessions_today(self, user_id: int) -> int:
        """Count sessions started today."""
        today_start = datetime.combine(date.today(), time.min, tzinfo=timezone.utc)
        stmt = select(func.count(FocusSession.id)).where(
            FocusSession.user_id == user_id,
            FocusSession.started_at >= today_start,
        )
        result = self.db.execute(stmt).scalar()
        return result or 0

    def focus_minutes_today(self, user_id: int) -> int:
        """Sum of focus minutes for sessions started today."""
        today_start = datetime.combine(date.today(), time.min, tzinfo=timezone.utc)
        stmt = select(
            func.coalesce(func.sum(FocusSession.total_focus_minutes), 0)
        ).where(
            FocusSession.user_id == user_id,
            FocusSession.completed == True,  # noqa: E712
            FocusSession.started_at >= today_start,
        )
        result = self.db.execute(stmt).scalar()
        return result or 0
