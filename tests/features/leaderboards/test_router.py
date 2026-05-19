"""Router tests for the leaderboard slice (Task 14.5).

Per ``testing-standards.md`` router tests use ``TestClient`` with a
mocked service injected via ``app.dependency_overrides``. The DB is
never hit here.

Coverage shape (per Task 14.5 acceptance bullets):

* GET /v1/leaderboards/{global,weekly,monthly}: 200 happy path with
  ordering verified on a small fixture, plus 401 (no token) for each
  route.
"""

from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI, HTTPException, status
from fastapi.testclient import TestClient

from app.common.deps import get_current_user
from app.common.middlewares.auth import AuthMiddleware
from app.common.middlewares.error_handler import register_exception_handlers
from app.common.middlewares.logging import RequestLoggingMiddleware
from app.features.leaderboards.router import (
    get_leaderboard_service,
    router as leaderboard_router,
)
from app.features.leaderboards.schemas import LeaderboardEntry
from app.features.leaderboards.service import LeaderboardService
from app.features.users.models import AccountState, Category, Role, User


# --- factories -------------------------------------------------------------


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


def _make_entries() -> list[LeaderboardEntry]:
    """Three-row fixture in the canonical leaderboard order."""
    return [
        LeaderboardEntry(
            user_id=1,
            display_name="Alice",
            level=5,
            xp_window=1000,
            category=Category.PROFESSIONAL,
        ),
        LeaderboardEntry(
            user_id=2,
            display_name="Bob",
            level=3,
            xp_window=500,
            category=Category.SUB_PROFESSIONAL,
        ),
        LeaderboardEntry(
            user_id=3,
            display_name="Carol",
            level=2,
            xp_window=250,
            category=Category.PROFESSIONAL,
        ),
    ]


# --- fixtures --------------------------------------------------------------


@pytest.fixture
def mock_service() -> MagicMock:
    return MagicMock(spec=LeaderboardService)


@pytest.fixture
def authed_user() -> User:
    return _make_user()


@pytest.fixture
def app(mock_service: MagicMock, authed_user: User) -> Iterator[FastAPI]:
    fastapi_app = FastAPI()
    fastapi_app.add_middleware(AuthMiddleware)
    fastapi_app.add_middleware(RequestLoggingMiddleware)
    register_exception_handlers(fastapi_app)
    fastapi_app.include_router(leaderboard_router)

    fastapi_app.dependency_overrides[get_leaderboard_service] = (
        lambda: mock_service
    )
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
    """Client whose auth dependency raises 401."""

    def _raise_401() -> None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid_credentials",
        )

    app.dependency_overrides[get_current_user] = _raise_401
    return TestClient(app)


# ===========================================================================
# GET /v1/leaderboards/global
# ===========================================================================


def test_get_global_leaderboard_200_returns_ordered_entries(
    client: TestClient, mock_service: MagicMock
) -> None:
    mock_service.global_top.return_value = _make_entries()

    response = client.get("/v1/leaderboards/global")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 3
    assert [row["display_name"] for row in body] == ["Alice", "Bob", "Carol"]
    assert [row["xp_window"] for row in body] == [1000, 500, 250]
    # Spec shape (Req 12.5): user_id, display_name, level, xp_window, category.
    assert set(body[0].keys()) == {
        "user_id",
        "display_name",
        "level",
        "xp_window",
        "category",
    }


def test_get_global_leaderboard_passes_limit_100(
    client: TestClient, mock_service: MagicMock
) -> None:
    mock_service.global_top.return_value = []

    client.get("/v1/leaderboards/global")

    mock_service.global_top.assert_called_once_with(limit=100)


def test_get_global_leaderboard_returns_empty_list_when_no_users(
    client: TestClient, mock_service: MagicMock
) -> None:
    mock_service.global_top.return_value = []

    response = client.get("/v1/leaderboards/global")

    assert response.status_code == 200
    assert response.json() == []


def test_get_global_leaderboard_401_without_token(
    unauthenticated_client: TestClient,
) -> None:
    response = unauthenticated_client.get("/v1/leaderboards/global")

    assert response.status_code == 401
    assert response.json() == {
        "error": {"message": "invalid_credentials", "code": "HTTP_401"}
    }


# ===========================================================================
# GET /v1/leaderboards/weekly
# ===========================================================================


def test_get_weekly_leaderboard_200_returns_ordered_entries(
    client: TestClient, mock_service: MagicMock
) -> None:
    mock_service.weekly_top.return_value = _make_entries()

    response = client.get("/v1/leaderboards/weekly")

    assert response.status_code == 200
    body = response.json()
    assert [row["xp_window"] for row in body] == [1000, 500, 250]


def test_get_weekly_leaderboard_passes_limit_100(
    client: TestClient, mock_service: MagicMock
) -> None:
    mock_service.weekly_top.return_value = []

    client.get("/v1/leaderboards/weekly")

    mock_service.weekly_top.assert_called_once_with(limit=100)


def test_get_weekly_leaderboard_401_without_token(
    unauthenticated_client: TestClient,
) -> None:
    response = unauthenticated_client.get("/v1/leaderboards/weekly")

    assert response.status_code == 401


# ===========================================================================
# GET /v1/leaderboards/monthly
# ===========================================================================


def test_get_monthly_leaderboard_200_returns_ordered_entries(
    client: TestClient, mock_service: MagicMock
) -> None:
    mock_service.monthly_top.return_value = _make_entries()

    response = client.get("/v1/leaderboards/monthly")

    assert response.status_code == 200
    body = response.json()
    assert [row["xp_window"] for row in body] == [1000, 500, 250]


def test_get_monthly_leaderboard_passes_limit_100(
    client: TestClient, mock_service: MagicMock
) -> None:
    mock_service.monthly_top.return_value = []

    client.get("/v1/leaderboards/monthly")

    mock_service.monthly_top.assert_called_once_with(limit=100)


def test_get_monthly_leaderboard_401_without_token(
    unauthenticated_client: TestClient,
) -> None:
    response = unauthenticated_client.get("/v1/leaderboards/monthly")

    assert response.status_code == 401


# ===========================================================================
# Cross-route checks
# ===========================================================================


def test_global_route_does_not_call_window_methods(
    client: TestClient, mock_service: MagicMock
) -> None:
    mock_service.global_top.return_value = []

    client.get("/v1/leaderboards/global")

    mock_service.weekly_top.assert_not_called()
    mock_service.monthly_top.assert_not_called()


def test_weekly_route_does_not_call_other_methods(
    client: TestClient, mock_service: MagicMock
) -> None:
    mock_service.weekly_top.return_value = []

    client.get("/v1/leaderboards/weekly")

    mock_service.global_top.assert_not_called()
    mock_service.monthly_top.assert_not_called()


def test_monthly_route_does_not_call_other_methods(
    client: TestClient, mock_service: MagicMock
) -> None:
    mock_service.monthly_top.return_value = []

    client.get("/v1/leaderboards/monthly")

    mock_service.global_top.assert_not_called()
    mock_service.weekly_top.assert_not_called()


def test_global_route_echoes_request_id(
    client: TestClient, mock_service: MagicMock
) -> None:
    """Req 21.4 — every response must carry an X-Request-ID."""
    mock_service.global_top.return_value = []

    response = client.get(
        "/v1/leaderboards/global", headers={"X-Request-ID": "trace-1"}
    )

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "trace-1"
