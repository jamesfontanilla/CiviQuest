"""FastAPI router for the gamification slice.

Endpoints for daily goals, streak freezes, XP multipliers, and tournaments.
All routes depend on get_current_user.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.common.deps import get_current_user
from app.features.gamification.multiplier_service import XPMultiplierService
from app.features.gamification.repository import (
    DailyGoalRepository,
    StreakFreezeRepository,
    TournamentRepository,
    XPMultiplierRepository,
)
from app.features.gamification.schemas import (
    DailyGoalResponse,
    SetTargetRequest,
    StreakFreezeCountResponse,
    StreakFreezeUseResponse,
    TournamentJoinResponse,
    TournamentLeaderboardEntry,
    TournamentResponse,
    WeeklySummary,
    XPMultiplierResponse,
)
from app.features.gamification.service import DailyGoalService, StreakFreezeService
from app.features.gamification.tournament_service import TournamentService
from app.features.users.models import User
from app.infrastructure.database.session import get_db

router = APIRouter(prefix="/v1", tags=["gamification"])


# --- Dependency factories ---------------------------------------------------


def get_daily_goal_service(db: Session = Depends(get_db)) -> DailyGoalService:
    return DailyGoalService(goal_repo=DailyGoalRepository(db=db))


def get_streak_freeze_service(db: Session = Depends(get_db)) -> StreakFreezeService:
    return StreakFreezeService(freeze_repo=StreakFreezeRepository(db=db))


def get_multiplier_service(db: Session = Depends(get_db)) -> XPMultiplierService:
    return XPMultiplierService(multiplier_repo=XPMultiplierRepository(db=db))


def get_tournament_service(db: Session = Depends(get_db)) -> TournamentService:
    return TournamentService(tournament_repo=TournamentRepository(db=db))


# --- Daily Goals ------------------------------------------------------------


@router.get("/goals/me/today", response_model=DailyGoalResponse)
def get_today_goal(
    user: User = Depends(get_current_user),
    service: DailyGoalService = Depends(get_daily_goal_service),
) -> DailyGoalResponse:
    """Get today's daily goal."""
    goal = service.get_or_create_today(user.id)
    return DailyGoalResponse.model_validate(goal)


@router.put("/goals/me/target", status_code=200)
def set_daily_target(
    payload: SetTargetRequest,
    user: User = Depends(get_current_user),
    service: DailyGoalService = Depends(get_daily_goal_service),
) -> dict[str, str]:
    """Set the daily XP target."""
    service.set_target(user.id, payload.target_xp)
    return {"status": "ok"}


@router.get("/goals/me/weekly", response_model=WeeklySummary)
def get_weekly_summary(
    user: User = Depends(get_current_user),
    service: DailyGoalService = Depends(get_daily_goal_service),
) -> WeeklySummary:
    """Return last 7 days of goal completion."""
    return service.get_weekly_summary(user.id)


# --- Streak Freeze ----------------------------------------------------------


@router.get("/streak/me/freezes", response_model=StreakFreezeCountResponse)
def get_freezes(
    user: User = Depends(get_current_user),
    service: StreakFreezeService = Depends(get_streak_freeze_service),
) -> StreakFreezeCountResponse:
    """Get available streak freezes count."""
    count = service.get_available(user.id)
    return StreakFreezeCountResponse(available=count)


@router.post("/streak/me/freezes:use", response_model=StreakFreezeUseResponse)
def use_freeze(
    user: User = Depends(get_current_user),
    service: StreakFreezeService = Depends(get_streak_freeze_service),
) -> StreakFreezeUseResponse:
    """Use a streak freeze."""
    success = service.use_freeze(user.id)
    remaining = service.get_available(user.id)
    return StreakFreezeUseResponse(success=success, remaining=remaining)


# --- XP Multipliers ---------------------------------------------------------


@router.get("/multipliers/me", response_model=list[XPMultiplierResponse])
def get_multipliers(
    user: User = Depends(get_current_user),
    service: XPMultiplierService = Depends(get_multiplier_service),
) -> list[XPMultiplierResponse]:
    """Get active XP multipliers."""
    multipliers = service.get_active(user.id)
    return [XPMultiplierResponse.model_validate(m) for m in multipliers]


# --- Tournaments ------------------------------------------------------------


@router.get("/tournaments", response_model=list[TournamentResponse])
def list_tournaments(
    user: User = Depends(get_current_user),
    service: TournamentService = Depends(get_tournament_service),
) -> list[TournamentResponse]:
    """List active and upcoming tournaments."""
    return service.list_active()


@router.post(
    "/tournaments/{tournament_id}:join",
    status_code=201,
    response_model=TournamentJoinResponse,
)
def join_tournament(
    tournament_id: int,
    user: User = Depends(get_current_user),
    service: TournamentService = Depends(get_tournament_service),
) -> TournamentJoinResponse:
    """Join a tournament."""
    return service.join(user.id, tournament_id)


@router.get(
    "/tournaments/{tournament_id}/leaderboard",
    response_model=list[TournamentLeaderboardEntry],
)
def get_tournament_leaderboard(
    tournament_id: int,
    user: User = Depends(get_current_user),
    service: TournamentService = Depends(get_tournament_service),
) -> list[TournamentLeaderboardEntry]:
    """Get tournament leaderboard."""
    return service.get_leaderboard(tournament_id)
