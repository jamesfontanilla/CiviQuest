"""Router tests for the gamification slice.

Per testing-standards.md: mocked services, HTTP client.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI, HTTPException, status
from fastapi.testclient import TestClient

from app.common.deps import get_current_user
from app.common.middlewares.auth import AuthMiddleware
from app.common.middlewares.error_handler import register_exception_handlers
from app.common.middlewares.logging import RequestLoggingMiddleware
from app.features.gamification.multiplier_service import XPMultiplierService
from app.features.gamification.router import (
    get_daily_goal_service,
    get_multiplier_service,
    get_streak_freeze_service,
    get_tournament_service,
    router as gamification_router,
)
from app.features.gamification.schemas import (
    DailyGoalResponse,
    TournamentJoinResponse,
    TournamentLeaderboardEntry,
    TournamentResponse,
    WeeklySummary,
    DaySummary,
    XPMultiplierResponse,
)
from app.features.gamification.service import DailyGoalService, StreakFreezeService
from app.features.gamification.tournament_service import TournamentService
from app.features.users.models import AccountState, Category, Role, User


# --- factories --------------------------------------------------------------


def _make_user(**overrides: object) -> User:
    defaults: dict[str, object] = {
        "id": 1,
        "email": "alice@example.com",
        "display_name": "Alice",
        "age": 25,
        "category": Category.PROFESSIONAL.value,
        "role": Role.LEARNER.value,
        "account_state": AccountState.VERIFIED.value,
        "is_banned": False,
        "tz_name": "UTC",
        "password_hash": "x",
        "cross_category_preview": False,
    }
    return User(**{**defaults, **overrides})


# --- fixtures ---------------------------------------------------------------


@pytest.fixture
def mock_goal_service() -> MagicMock:
    return MagicMock(spec=DailyGoalService)


@pytest.fixture
def mock_freeze_service() -> MagicMock:
    return MagicMock(spec=StreakFreezeService)


@pytest.fixture
def mock_multiplier_service() -> MagicMock:
    return MagicMock(spec=XPMultiplierService)


@pytest.fixture
def mock_tournament_service() -> MagicMock:
    return MagicMock(spec=TournamentService)


@pytest.fixture
def authed_user() -> User:
    return _make_user()


@pytest.fixture
def app(
    mock_goal_service: MagicMock,
    mock_freeze_service: MagicMock,
    mock_multiplier_service: MagicMock,
    mock_tournament_service: MagicMock,
    authed_user: User,
) -> Iterator[FastAPI]:
    fastapi_app = FastAPI()
    fastapi_app.add_middleware(AuthMiddleware)
    fastapi_app.add_middleware(RequestLoggingMiddleware)
    register_exception_handlers(fastapi_app)
    fastapi_app.include_router(gamification_router)

    fastapi_app.dependency_overrides[get_daily_goal_service] = lambda: mock_goal_service
    fastapi_app.dependency_overrides[get_streak_freeze_service] = lambda: mock_freeze_service
    fastapi_app.dependency_overrides[get_multiplier_service] = lambda: mock_multiplier_service
    fastapi_app.dependency_overrides[get_tournament_service] = lambda: mock_tournament_service
    fastapi_app.dependency_overrides[get_current_user] = lambda: authed_user

    try:
        yield fastapi_app
    finally:
        fastapi_app.dependency_overrides.clear()


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


@pytest.fixture
def unauthenticated_client(app: FastAPI) -> TestClient:
    def _raise_401() -> None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid_credentials",
        )

    app.dependency_overrides[get_current_user] = _raise_401
    return TestClient(app)


# ===========================================================================
# GET /v1/goals/me/today
# ===========================================================================


def test_get_today_goal_200(client: TestClient, mock_goal_service: MagicMock) -> None:
    from app.features.gamification.models import UserDailyGoal

    goal = MagicMock()
    goal.id = 1
    goal.target_xp = 50
    goal.current_xp = 20
    goal.goal_date = date(2025, 6, 15)
    goal.completed = False
    goal.completed_at = None
    mock_goal_service.get_or_create_today.return_value = goal

    response = client.get("/v1/goals/me/today")
    assert response.status_code == 200
    body = response.json()
    assert body["target_xp"] == 50
    assert body["current_xp"] == 20
    assert body["completed"] is False


def test_get_today_goal_401(unauthenticated_client: TestClient) -> None:
    response = unauthenticated_client.get("/v1/goals/me/today")
    assert response.status_code == 401


# ===========================================================================
# PUT /v1/goals/me/target
# ===========================================================================


def test_set_target_200(client: TestClient, mock_goal_service: MagicMock) -> None:
    mock_goal_service.set_target.return_value = None

    response = client.put("/v1/goals/me/target", json={"target_xp": 100})
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_set_target_422_invalid_value(client: TestClient) -> None:
    response = client.put("/v1/goals/me/target", json={"target_xp": 5})
    assert response.status_code == 422


# ===========================================================================
# GET /v1/goals/me/weekly
# ===========================================================================


def test_get_weekly_summary_200(client: TestClient, mock_goal_service: MagicMock) -> None:
    mock_goal_service.get_weekly_summary.return_value = WeeklySummary(
        days=[
            DaySummary(goal_date=date(2025, 6, 15), target_xp=50, current_xp=50, completed=True)
        ],
        completed_count=1,
        total_days=7,
    )

    response = client.get("/v1/goals/me/weekly")
    assert response.status_code == 200
    body = response.json()
    assert body["completed_count"] == 1


# ===========================================================================
# GET /v1/streak/me/freezes
# ===========================================================================


def test_get_freezes_200(client: TestClient, mock_freeze_service: MagicMock) -> None:
    mock_freeze_service.get_available.return_value = 2

    response = client.get("/v1/streak/me/freezes")
    assert response.status_code == 200
    assert response.json() == {"available": 2}


# ===========================================================================
# POST /v1/streak/me/freezes:use
# ===========================================================================


def test_use_freeze_200(client: TestClient, mock_freeze_service: MagicMock) -> None:
    mock_freeze_service.use_freeze.return_value = True
    mock_freeze_service.get_available.return_value = 1

    response = client.post("/v1/streak/me/freezes:use")
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["remaining"] == 1


# ===========================================================================
# GET /v1/multipliers/me
# ===========================================================================


def test_get_multipliers_200(client: TestClient, mock_multiplier_service: MagicMock) -> None:
    from app.features.gamification.models import XPMultiplier

    m = MagicMock()
    m.id = 1
    m.multiplier = 1.5
    m.reason = "streak_7"
    m.expires_at = datetime(2025, 6, 16, 12, 0, 0, tzinfo=timezone.utc)
    mock_multiplier_service.get_active.return_value = [m]

    response = client.get("/v1/multipliers/me")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["multiplier"] == 1.5


# ===========================================================================
# GET /v1/tournaments
# ===========================================================================


def test_list_tournaments_200(client: TestClient, mock_tournament_service: MagicMock) -> None:
    now = datetime(2025, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
    mock_tournament_service.list_active.return_value = [
        TournamentResponse(
            id=1,
            title="Sprint",
            starts_at=now,
            ends_at=now + timedelta(days=7),
            status="ACTIVE",
        )
    ]

    response = client.get("/v1/tournaments")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["title"] == "Sprint"


# ===========================================================================
# POST /v1/tournaments/{id}:join
# ===========================================================================


def test_join_tournament_201(client: TestClient, mock_tournament_service: MagicMock) -> None:
    now = datetime(2025, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
    mock_tournament_service.join.return_value = TournamentJoinResponse(
        tournament_id=1, user_id=1, joined_at=now
    )

    response = client.post("/v1/tournaments/1:join")
    assert response.status_code == 201
    body = response.json()
    assert body["tournament_id"] == 1


def test_join_tournament_409_already_joined(
    client: TestClient, mock_tournament_service: MagicMock
) -> None:
    mock_tournament_service.join.side_effect = HTTPException(
        status_code=409, detail="already_joined"
    )

    response = client.post("/v1/tournaments/1:join")
    assert response.status_code == 409


# ===========================================================================
# GET /v1/tournaments/{id}/leaderboard
# ===========================================================================


def test_get_tournament_leaderboard_200(
    client: TestClient, mock_tournament_service: MagicMock
) -> None:
    mock_tournament_service.get_leaderboard.return_value = [
        TournamentLeaderboardEntry(user_id=1, xp_earned=200, rank=1),
        TournamentLeaderboardEntry(user_id=2, xp_earned=100, rank=2),
    ]

    response = client.get("/v1/tournaments/1/leaderboard")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 2
    assert body[0]["rank"] == 1
