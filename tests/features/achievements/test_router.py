"""Router tests for the achievements slice (Task 15.4).

Per ``testing-standards.md`` router tests use ``TestClient`` with a
mocked service injected via ``app.dependency_overrides``. The DB is
never hit here.

Coverage shape (per Task 15.4 acceptance bullets):

* ``GET /v1/achievements/me``: 200 happy path + 401 (no token) +
  empty-list case.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI, HTTPException, status
from fastapi.testclient import TestClient

from app.common.deps import get_current_user
from app.common.middlewares.auth import AuthMiddleware
from app.common.middlewares.error_handler import register_exception_handlers
from app.common.middlewares.logging import RequestLoggingMiddleware
from app.features.achievements.router import (
    get_achievement_service,
    router as achievements_router,
)
from app.features.achievements.schemas import UserAchievementResponse
from app.features.achievements.service import AchievementService
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


def _make_entry(
    *,
    achievement_id: str = "FIRST_LESSON",
    title: str = "First Lesson",
    description: str = "Complete your first lesson.",
    granted_at: datetime | None = None,
) -> UserAchievementResponse:
    return UserAchievementResponse(
        achievement_id=achievement_id,
        title=title,
        description=description,
        granted_at=granted_at or datetime(2025, 6, 1, 12, 0, tzinfo=timezone.utc),
    )


# --- fixtures --------------------------------------------------------------


@pytest.fixture
def mock_service() -> MagicMock:
    return MagicMock(spec=AchievementService)


@pytest.fixture
def authed_user() -> User:
    return _make_user()


@pytest.fixture
def app(mock_service: MagicMock, authed_user: User) -> Iterator[FastAPI]:
    fastapi_app = FastAPI()
    fastapi_app.add_middleware(AuthMiddleware)
    fastapi_app.add_middleware(RequestLoggingMiddleware)
    register_exception_handlers(fastapi_app)
    fastapi_app.include_router(achievements_router)

    fastapi_app.dependency_overrides[get_achievement_service] = (
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
# GET /v1/achievements/me
# ===========================================================================


def test_get_my_achievements_200_returns_list(
    client: TestClient, mock_service: MagicMock
) -> None:
    """Happy path — service returns entries; router echoes them."""
    mock_service.list_for_user.return_value = [
        _make_entry(),
        _make_entry(
            achievement_id="STREAK_7_DAYS",
            title="7-Day Streak",
            description="Maintain a 7-day learning streak.",
        ),
    ]

    response = client.get("/v1/achievements/me")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 2
    assert body[0]["achievement_id"] == "FIRST_LESSON"
    assert body[0]["title"] == "First Lesson"
    assert body[0]["description"] == "Complete your first lesson."
    assert "granted_at" in body[0]


def test_get_my_achievements_200_returns_empty_list(
    client: TestClient, mock_service: MagicMock
) -> None:
    """A learner with no grants gets ``[]``, not 404."""
    mock_service.list_for_user.return_value = []

    response = client.get("/v1/achievements/me")

    assert response.status_code == 200
    assert response.json() == []


def test_get_my_achievements_calls_service_with_user_id(
    client: TestClient, mock_service: MagicMock, authed_user: User
) -> None:
    mock_service.list_for_user.return_value = []

    client.get("/v1/achievements/me")

    mock_service.list_for_user.assert_called_once_with(authed_user.id)


def test_get_my_achievements_response_shape_is_spec_only(
    client: TestClient, mock_service: MagicMock
) -> None:
    """Wire surface includes the achievement fields from the schema."""
    mock_service.list_for_user.return_value = [_make_entry()]

    response = client.get("/v1/achievements/me")

    assert response.status_code == 200
    body = response.json()
    assert set(body[0].keys()) == {
        "achievement_id",
        "title",
        "description",
        "rarity",
        "icon",
        "xp_reward",
        "granted_at",
    }


def test_get_my_achievements_401_without_token(
    unauthenticated_client: TestClient,
) -> None:
    response = unauthenticated_client.get("/v1/achievements/me")

    assert response.status_code == 401
    assert response.json() == {
        "error": {"message": "invalid_credentials", "code": "HTTP_401"}
    }


def test_get_my_achievements_echoes_request_id(
    client: TestClient, mock_service: MagicMock
) -> None:
    """Req 21.4 — every response must carry an X-Request-ID."""
    mock_service.list_for_user.return_value = []

    response = client.get(
        "/v1/achievements/me", headers={"X-Request-ID": "trace-1"}
    )

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "trace-1"
