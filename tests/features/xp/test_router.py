"""Router tests for the XP slice (Task 9.6).

Per ``testing-standards.md`` router tests use ``TestClient`` with a
mocked service injected via ``app.dependency_overrides``. The DB is
never hit here.

Coverage shape (per Task 9.6 acceptance bullets):

* ``GET /v1/xp/me``: 200 happy path verifying the response shape +
  401 without a token.
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
from app.features.users.models import AccountState, Category, Role, User
from app.features.xp.router import get_xp_service, router as xp_router
from app.features.xp.schemas import UserXPResponse
from app.features.xp.service import XPService


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
def mock_service() -> MagicMock:
    return MagicMock(spec=XPService)


@pytest.fixture
def authed_user() -> User:
    return _make_user()


@pytest.fixture
def app(mock_service: MagicMock, authed_user: User) -> Iterator[FastAPI]:
    fastapi_app = FastAPI()
    fastapi_app.add_middleware(AuthMiddleware)
    fastapi_app.add_middleware(RequestLoggingMiddleware)
    register_exception_handlers(fastapi_app)
    fastapi_app.include_router(xp_router)

    fastapi_app.dependency_overrides[get_xp_service] = lambda: mock_service
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
    """Client whose auth dependency raises 401 (no/invalid token)."""

    def _raise_401() -> None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid_credentials",
        )

    app.dependency_overrides[get_current_user] = _raise_401
    return TestClient(app)


# ===========================================================================
# GET /v1/xp/me
# ===========================================================================


def test_get_my_xp_200_returns_full_shape(
    client: TestClient, mock_service: MagicMock
) -> None:
    mock_service.get_user_xp_view.return_value = UserXPResponse(
        cumulative_xp=420, level=2, streak=5
    )

    response = client.get("/v1/xp/me")

    assert response.status_code == 200
    assert response.json() == {
        "cumulative_xp": 420,
        "level": 2,
        "streak": 5,
    }


def test_get_my_xp_200_for_fresh_user(
    client: TestClient, mock_service: MagicMock
) -> None:
    """Fresh learner with no XP yet — every field is zero."""
    mock_service.get_user_xp_view.return_value = UserXPResponse(
        cumulative_xp=0, level=0, streak=0
    )

    response = client.get("/v1/xp/me")

    assert response.status_code == 200
    body = response.json()
    assert body["cumulative_xp"] == 0
    assert body["level"] == 0
    assert body["streak"] == 0


def test_get_my_xp_decay_applied_on_read(
    client: TestClient, mock_service: MagicMock
) -> None:
    """Req 11.6 — service returns the decayed streak; router echoes it."""
    mock_service.get_user_xp_view.return_value = UserXPResponse(
        cumulative_xp=1000, level=4, streak=0  # decayed from a stale streak
    )

    response = client.get("/v1/xp/me")

    assert response.status_code == 200
    assert response.json()["streak"] == 0


def test_get_my_xp_calls_service_with_authed_user(
    client: TestClient, mock_service: MagicMock, authed_user: User
) -> None:
    mock_service.get_user_xp_view.return_value = UserXPResponse(
        cumulative_xp=10, level=0, streak=1
    )

    client.get("/v1/xp/me")

    mock_service.get_user_xp_view.assert_called_once_with(authed_user)


def test_get_my_xp_401_without_token(
    unauthenticated_client: TestClient,
) -> None:
    response = unauthenticated_client.get("/v1/xp/me")

    assert response.status_code == 401
    assert response.json() == {
        "error": {"message": "invalid_credentials", "code": "HTTP_401"}
    }


def test_get_my_xp_echoes_request_id(
    client: TestClient, mock_service: MagicMock
) -> None:
    """Req 21.4 — every response must carry an X-Request-ID."""
    mock_service.get_user_xp_view.return_value = UserXPResponse(
        cumulative_xp=0, level=0, streak=0
    )

    response = client.get("/v1/xp/me", headers={"X-Request-ID": "trace-1"})

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "trace-1"
