"""FastAPI router for focus sessions and wellness.

Mounts under ``/v1/focus`` and exposes session CRUD + wellness endpoint.
All routes require authentication.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.common.deps import get_current_user
from app.features.focus.repository import FocusSessionRepository
from app.features.focus.schemas import (
    CompleteSessionRequest,
    FocusSessionResponse,
    FocusStatsResponse,
    StartSessionRequest,
    WellnessResponse,
)
from app.features.focus.service import FocusService
from app.features.users.models import User
from app.infrastructure.database.session import get_db

router = APIRouter(prefix="/v1/focus", tags=["focus"])


def _get_focus_service(db: Session = Depends(get_db)) -> FocusService:
    """Construct FocusService for the request."""
    return FocusService(repository=FocusSessionRepository(db=db))


@router.post("/sessions", status_code=201, response_model=FocusSessionResponse)
def start_session(
    payload: StartSessionRequest,
    user: User = Depends(get_current_user),
    service: FocusService = Depends(_get_focus_service),
) -> FocusSessionResponse:
    """Start a new focus session."""
    return service.start_session(
        user.id,
        mode=payload.mode,
        work_minutes=payload.work_minutes,
        break_minutes=payload.break_minutes,
    )


@router.post("/sessions/{session_id}:complete", response_model=FocusSessionResponse)
def complete_session(
    session_id: int,
    payload: CompleteSessionRequest,
    user: User = Depends(get_current_user),
    service: FocusService = Depends(_get_focus_service),
) -> FocusSessionResponse:
    """Mark a focus session as completed."""
    return service.complete_session(
        user.id,
        session_id,
        total_focus_minutes=payload.total_focus_minutes,
        distractions=payload.distractions,
    )


@router.post("/sessions/{session_id}:abandon", status_code=204)
def abandon_session(
    session_id: int,
    user: User = Depends(get_current_user),
    service: FocusService = Depends(_get_focus_service),
) -> None:
    """Abandon a focus session."""
    service.abandon_session(user.id, session_id)


@router.get("/sessions/me/stats", response_model=FocusStatsResponse)
def get_focus_stats(
    user: User = Depends(get_current_user),
    service: FocusService = Depends(_get_focus_service),
) -> FocusStatsResponse:
    """Get focus session statistics for the current user."""
    return service.get_stats(user.id)


@router.get("/wellness/me", response_model=WellnessResponse)
def get_wellness(
    user: User = Depends(get_current_user),
    service: FocusService = Depends(_get_focus_service),
    accuracy_last_10: float = Query(default=1.0, ge=0.0, le=1.0),
    accuracy_trend: str = Query(default="stable", pattern=r"^(improving|stable|declining)$"),
    consecutive_wrong: int = Query(default=0, ge=0),
    current_streak_days: int = Query(default=0, ge=0),
) -> WellnessResponse:
    """Get wellness/burnout check for the current user."""
    return service.get_wellness(
        user.id,
        accuracy_last_10=accuracy_last_10,
        accuracy_trend=accuracy_trend,
        consecutive_wrong=consecutive_wrong,
        current_streak_days=current_streak_days,
    )
