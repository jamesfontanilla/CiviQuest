"""Pydantic schemas for the gamification slice."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


# --- Daily Goals -----------------------------------------------------------


class DailyGoalResponse(BaseModel):
    """Today's daily goal state."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    target_xp: int
    current_xp: int
    goal_date: date
    completed: bool
    completed_at: datetime | None = None


class SetTargetRequest(BaseModel):
    """Request to set the daily XP target."""

    target_xp: int = Field(ge=25, le=150)


class DaySummary(BaseModel):
    """One day in the weekly summary."""

    goal_date: date
    target_xp: int
    current_xp: int
    completed: bool


class WeeklySummary(BaseModel):
    """Last 7 days of goal completion."""

    days: list[DaySummary]
    completed_count: int
    total_days: int


# --- Streak Freeze ---------------------------------------------------------


class StreakFreezeCountResponse(BaseModel):
    """Available streak freezes count."""

    available: int


class StreakFreezeUseResponse(BaseModel):
    """Result of using a streak freeze."""

    success: bool
    remaining: int


# --- XP Multiplier ---------------------------------------------------------


class XPMultiplierResponse(BaseModel):
    """An active XP multiplier."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    multiplier: float
    reason: str
    expires_at: datetime


# --- Tournament ------------------------------------------------------------


class TournamentResponse(BaseModel):
    """Tournament listing entry."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    description: str | None = None
    category: str | None = None
    starts_at: datetime
    ends_at: datetime
    status: str
    max_participants: int | None = None
    prize_description: str | None = None


class TournamentLeaderboardEntry(BaseModel):
    """One entry in a tournament leaderboard."""

    user_id: int
    xp_earned: int
    rank: int


class TournamentJoinResponse(BaseModel):
    """Result of joining a tournament."""

    tournament_id: int
    user_id: int
    joined_at: datetime
