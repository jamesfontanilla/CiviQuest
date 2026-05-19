"""Pydantic request/response schemas for the focus feature."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class StartSessionRequest(BaseModel):
    """Request body for starting a focus session."""

    mode: str = Field(pattern=r"^(25_5|50_10|custom)$")
    work_minutes: int = Field(ge=5, le=120)
    break_minutes: int = Field(ge=1, le=30)


class CompleteSessionRequest(BaseModel):
    """Request body for completing a focus session."""

    total_focus_minutes: int = Field(ge=0)
    distractions: int = Field(ge=0)


class FocusSessionResponse(BaseModel):
    """Response for a focus session."""

    id: int
    mode: str
    work_minutes: int
    break_minutes: int
    started_at: datetime
    ended_at: datetime | None
    completed: bool
    total_focus_minutes: int
    distractions: int

    model_config = {"from_attributes": True}


class FocusStatsResponse(BaseModel):
    """Aggregated focus statistics for a user."""

    total_sessions: int
    total_focus_hours: float
    avg_session_minutes: float
    sessions_today: int
    focus_minutes_today: int


class WellnessResponse(BaseModel):
    """Wellness/burnout check response."""

    is_fatigued: bool
    fatigue_level: str
    message: str
    suggestion: str
