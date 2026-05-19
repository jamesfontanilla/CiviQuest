"""Business logic for focus sessions and wellness checks."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException, status

from app.features.focus.algorithms.wellness import WellnessCheck, check_wellness
from app.features.focus.models import FocusSession
from app.features.focus.repository import FocusSessionRepository
from app.features.focus.schemas import FocusSessionResponse, FocusStatsResponse, WellnessResponse


class FocusService:
    """Orchestrates focus session lifecycle and wellness checks."""

    def __init__(self, *, repository: FocusSessionRepository) -> None:
        self._repo = repository

    def start_session(
        self,
        user_id: int,
        *,
        mode: str,
        work_minutes: int,
        break_minutes: int,
    ) -> FocusSessionResponse:
        """Create and persist a new focus session."""
        session = FocusSession(
            user_id=user_id,
            mode=mode,
            work_minutes=work_minutes,
            break_minutes=break_minutes,
            started_at=datetime.now(tz=timezone.utc),
        )
        session = self._repo.create(session)
        return self._to_response(session)

    def complete_session(
        self,
        user_id: int,
        session_id: int,
        *,
        total_focus_minutes: int,
        distractions: int,
    ) -> FocusSessionResponse:
        """Mark a session as completed with actual focus data."""
        session = self._repo.get_user_session(user_id, session_id)
        if session is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Focus session not found",
            )
        if session.completed:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Session already completed",
            )

        session = self._repo.update(
            session,
            completed=True,
            ended_at=datetime.now(tz=timezone.utc),
            total_focus_minutes=total_focus_minutes,
            distractions=distractions,
        )
        return self._to_response(session)

    def abandon_session(self, user_id: int, session_id: int) -> None:
        """Abandon a session (mark ended but not completed)."""
        session = self._repo.get_user_session(user_id, session_id)
        if session is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Focus session not found",
            )
        if session.completed:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Session already completed",
            )

        self._repo.update(
            session,
            ended_at=datetime.now(tz=timezone.utc),
        )

    def get_stats(self, user_id: int) -> FocusStatsResponse:
        """Return aggregated focus statistics for the user."""
        total_sessions = self._repo.count_user_sessions(user_id)
        total_minutes = self._repo.total_focus_minutes(user_id)
        avg_minutes = self._repo.avg_session_minutes(user_id)
        sessions_today = self._repo.sessions_today(user_id)
        minutes_today = self._repo.focus_minutes_today(user_id)

        return FocusStatsResponse(
            total_sessions=total_sessions,
            total_focus_hours=round(total_minutes / 60.0, 2),
            avg_session_minutes=round(avg_minutes, 1),
            sessions_today=sessions_today,
            focus_minutes_today=minutes_today,
        )

    def get_wellness(
        self,
        user_id: int,
        *,
        accuracy_last_10: float = 1.0,
        accuracy_trend: str = "stable",
        consecutive_wrong: int = 0,
        current_streak_days: int = 0,
    ) -> WellnessResponse:
        """Run the wellness check algorithm with current session data."""
        minutes_today = self._repo.focus_minutes_today(user_id)

        result: WellnessCheck = check_wellness(
            session_minutes_today=minutes_today,
            accuracy_last_10=accuracy_last_10,
            accuracy_trend=accuracy_trend,
            consecutive_wrong=consecutive_wrong,
            current_streak_days=current_streak_days,
        )

        return WellnessResponse(
            is_fatigued=result.is_fatigued,
            fatigue_level=result.fatigue_level,
            message=result.message,
            suggestion=result.suggestion,
        )

    def _to_response(self, session: FocusSession) -> FocusSessionResponse:
        """Convert ORM model to response schema."""
        return FocusSessionResponse(
            id=session.id,
            mode=session.mode,
            work_minutes=session.work_minutes,
            break_minutes=session.break_minutes,
            started_at=session.started_at,
            ended_at=session.ended_at,
            completed=session.completed,
            total_focus_minutes=session.total_focus_minutes,
            distractions=session.distractions,
        )
