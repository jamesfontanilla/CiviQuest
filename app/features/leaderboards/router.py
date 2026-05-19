"""FastAPI router for the leaderboard slice (Task 14.4).

Three GET endpoints mounted under ``/v1``:

- ``GET /v1/leaderboards/global`` — top 100 by cumulative XP (Req 12.1).
- ``GET /v1/leaderboards/weekly`` — top 100 by current ISO-week XP
  (Req 12.2).
- ``GET /v1/leaderboards/monthly`` — top 100 by current calendar-month
  XP (Req 12.3).

All three depend on :func:`get_current_user` only. The
:func:`require_no_active_mock` dependency that gates most other
slices during a mock-exam attempt is **deliberately not used here**:
the PWA's mock-exam UI shows the learner's standing in the
leaderboard chrome while the timer runs, and blocking those reads
mid-attempt would force the chrome to hide for a multi-hour window.
The mock-exam carve-out is the same one applied to ``GET /v1/xp/me``
and ``GET /v1/progress/snapshot``.

Service factory composes the repository in-place; no caching, no
warm-up. Every request runs the live query — for the MVP load
profile (small user base, indexed reads) this is fast enough; if it
becomes a hot path later, the obvious knob is a per-window
in-memory cache or a Redis-backed materialised view, both of which
land at the service layer without router churn.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.common.deps import get_current_user
from app.features.leaderboards.repository import LeaderboardRepository
from app.features.leaderboards.schemas import LeaderboardEntry
from app.features.leaderboards.service import LeaderboardService
from app.features.users.models import User
from app.infrastructure.database.session import get_db


router = APIRouter(prefix="/v1", tags=["leaderboards"])


def get_leaderboard_service(
    db: Session = Depends(get_db),
) -> LeaderboardService:
    """Construct :class:`LeaderboardService` for the request."""
    return LeaderboardService(
        leaderboard_repo=LeaderboardRepository(db=db),
    )


@router.get(
    "/leaderboards/global",
    response_model=list[LeaderboardEntry],
)
def get_global_leaderboard(
    user: User = Depends(get_current_user),
    service: LeaderboardService = Depends(get_leaderboard_service),
) -> list[LeaderboardEntry]:
    """Return the global top 100 by cumulative XP (Req 12.1)."""
    return service.global_top(limit=100)


@router.get(
    "/leaderboards/weekly",
    response_model=list[LeaderboardEntry],
)
def get_weekly_leaderboard(
    user: User = Depends(get_current_user),
    service: LeaderboardService = Depends(get_leaderboard_service),
) -> list[LeaderboardEntry]:
    """Return the weekly top 100 by current ISO-week XP (Req 12.2)."""
    return service.weekly_top(limit=100)


@router.get(
    "/leaderboards/monthly",
    response_model=list[LeaderboardEntry],
)
def get_monthly_leaderboard(
    user: User = Depends(get_current_user),
    service: LeaderboardService = Depends(get_leaderboard_service),
) -> list[LeaderboardEntry]:
    """Return the monthly top 100 by current-calendar-month XP (Req 12.3)."""
    return service.monthly_top(limit=100)
