"""Router tests for the offline-sync endpoint (Task 16.4).

Per ``testing-standards.md`` router tests use ``TestClient`` with a
mocked service injected via ``app.dependency_overrides``. The DB is
never hit here.

Coverage shape (per Task 16.4 acceptance bullets):

* ``POST /v1/progress:sync``: 200 happy with mixed accepted/rejected +
  401 (no token) + 422 (malformed event missing required field).
* Sanity: the endpoint does NOT depend on
  :func:`require_no_active_mock` — a learner with an active mock
  attempt can still flush queued events.
"""

from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI, HTTPException, status
from fastapi.testclient import TestClient

from app.common.deps import get_current_user, require_no_active_mock
from app.common.middlewares.auth import AuthMiddleware
from app.common.middlewares.error_handler import register_exception_handlers
from app.common.middlewares.logging import RequestLoggingMiddleware
from app.features.progress.algorithms.sync_resolver import SyncEventResult
from app.features.progress.router import (
    get_progress_service,
    get_sync_service,
    router as progress_router,
)
from app.features.progress.schemas import SyncResponse, SyncResultOut
from app.features.progress.service import ProgressService
from app.features.progress.sync_service import SyncService
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
def mock_sync_service() -> MagicMock:
    return MagicMock(spec=SyncService)


@pytest.fixture
def mock_progress_service() -> MagicMock:
    return MagicMock(spec=ProgressService)


@pytest.fixture
def authed_user() -> User:
    return _make_user()


@pytest.fixture
def app(
    mock_sync_service: MagicMock,
    mock_progress_service: MagicMock,
    authed_user: User,
) -> Iterator[FastAPI]:
    fastapi_app = FastAPI()
    fastapi_app.add_middleware(AuthMiddleware)
    fastapi_app.add_middleware(RequestLoggingMiddleware)
    register_exception_handlers(fastapi_app)
    fastapi_app.include_router(progress_router)

    fastapi_app.dependency_overrides[get_sync_service] = (
        lambda: mock_sync_service
    )
    fastapi_app.dependency_overrides[get_progress_service] = (
        lambda: mock_progress_service
    )
    fastapi_app.dependency_overrides[get_current_user] = lambda: authed_user
    fastapi_app.dependency_overrides[require_no_active_mock] = (
        lambda: authed_user
    )

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


# ---------------------------------------------------------------------------
# Happy path with mixed accepted/rejected
# ---------------------------------------------------------------------------


def test_sync_progress_200_with_mixed_results(
    client: TestClient, mock_sync_service: MagicMock
) -> None:
    """Mixed batch: one accepted, one rejected. 200 in both cases —
    rejection is a row in the body, not an HTTP status."""
    mock_sync_service.sync_events.return_value = (
        ["evt-1"],
        [
            SyncEventResult(
                client_event_id="evt-2",
                accepted=False,
                reason="forbidden",
            )
        ],
    )

    response = client.post(
        "/v1/progress:sync",
        json={
            "events": [
                {
                    "client_event_id": "evt-1",
                    "kind": "lesson_complete",
                    "client_timestamp": "2025-01-01T00:00:00Z",
                    "payload": {"subtopic_id": 30},
                },
                {
                    "client_event_id": "evt-2",
                    "kind": "lesson_complete",
                    "client_timestamp": "2025-01-01T01:00:00Z",
                    "payload": {"subtopic_id": 99},
                },
            ]
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["accepted"] == ["evt-1"]
    assert body["rejected"] == [
        {
            "client_event_id": "evt-2",
            "accepted": False,
            "reason": "forbidden",
        }
    ]


def test_sync_progress_200_empty_batch(
    client: TestClient, mock_sync_service: MagicMock
) -> None:
    """Empty events list is valid — server returns empty partition."""
    mock_sync_service.sync_events.return_value = ([], [])

    response = client.post("/v1/progress:sync", json={"events": []})

    assert response.status_code == 200
    assert response.json() == {"accepted": [], "rejected": []}


def test_sync_progress_200_all_accepted(
    client: TestClient, mock_sync_service: MagicMock
) -> None:
    mock_sync_service.sync_events.return_value = (
        ["evt-1", "evt-2"],
        [],
    )

    response = client.post(
        "/v1/progress:sync",
        json={
            "events": [
                {
                    "client_event_id": "evt-1",
                    "kind": "lesson_complete",
                    "client_timestamp": "2025-01-01T00:00:00Z",
                    "payload": {"subtopic_id": 30},
                },
                {
                    "client_event_id": "evt-2",
                    "kind": "xp_event",
                    "client_timestamp": "2025-01-01T01:00:00Z",
                    "payload": {"source": "LESSON_FIRST_COMPLETE"},
                },
            ]
        },
    )

    assert response.status_code == 200
    assert response.json()["accepted"] == ["evt-1", "evt-2"]


def test_sync_progress_calls_service_with_authed_user(
    client: TestClient, mock_sync_service: MagicMock, authed_user: User
) -> None:
    mock_sync_service.sync_events.return_value = ([], [])

    client.post("/v1/progress:sync", json={"events": []})

    mock_sync_service.sync_events.assert_called_once()
    call_kwargs = mock_sync_service.sync_events.call_args.kwargs
    assert call_kwargs["user"] is authed_user
    assert call_kwargs["events"] == []


# ---------------------------------------------------------------------------
# 401 without a token
# ---------------------------------------------------------------------------


def test_sync_progress_401_without_token(
    unauthenticated_client: TestClient,
) -> None:
    response = unauthenticated_client.post(
        "/v1/progress:sync", json={"events": []}
    )
    assert response.status_code == 401
    assert response.json() == {
        "error": {"message": "invalid_credentials", "code": "HTTP_401"}
    }


# ---------------------------------------------------------------------------
# 422 on malformed events
# ---------------------------------------------------------------------------


def test_sync_progress_422_when_event_missing_client_event_id(
    client: TestClient,
) -> None:
    response = client.post(
        "/v1/progress:sync",
        json={
            "events": [
                {
                    "kind": "lesson_complete",
                    "client_timestamp": "2025-01-01T00:00:00Z",
                    "payload": {"subtopic_id": 30},
                }
            ]
        },
    )
    assert response.status_code == 422


def test_sync_progress_422_when_event_missing_kind(
    client: TestClient,
) -> None:
    response = client.post(
        "/v1/progress:sync",
        json={
            "events": [
                {
                    "client_event_id": "evt-1",
                    "client_timestamp": "2025-01-01T00:00:00Z",
                    "payload": {"subtopic_id": 30},
                }
            ]
        },
    )
    assert response.status_code == 422


def test_sync_progress_422_when_event_missing_timestamp(
    client: TestClient,
) -> None:
    response = client.post(
        "/v1/progress:sync",
        json={
            "events": [
                {
                    "client_event_id": "evt-1",
                    "kind": "lesson_complete",
                    "payload": {"subtopic_id": 30},
                }
            ]
        },
    )
    assert response.status_code == 422


def test_sync_progress_422_when_event_missing_payload(
    client: TestClient,
) -> None:
    response = client.post(
        "/v1/progress:sync",
        json={
            "events": [
                {
                    "client_event_id": "evt-1",
                    "kind": "lesson_complete",
                    "client_timestamp": "2025-01-01T00:00:00Z",
                }
            ]
        },
    )
    assert response.status_code == 422


def test_sync_progress_422_when_envelope_missing_events(
    client: TestClient,
) -> None:
    response = client.post("/v1/progress:sync", json={})
    assert response.status_code == 422


def test_sync_progress_422_when_events_not_a_list(
    client: TestClient,
) -> None:
    """Completely malformed body: ``events`` is a string, not a list."""
    response = client.post(
        "/v1/progress:sync", json={"events": "not a list"}
    )
    assert response.status_code == 422


def test_sync_progress_422_for_extra_fields(
    client: TestClient,
) -> None:
    """``extra='forbid'`` on the schema rejects unknown keys."""
    response = client.post(
        "/v1/progress:sync",
        json={"events": [], "unexpected_field": "boom"},
    )
    assert response.status_code == 422


def test_sync_progress_422_for_extra_field_in_event(
    client: TestClient,
) -> None:
    """``extra='forbid'`` on :class:`SyncEventIn` rejects unknown keys."""
    response = client.post(
        "/v1/progress:sync",
        json={
            "events": [
                {
                    "client_event_id": "evt-1",
                    "kind": "lesson_complete",
                    "client_timestamp": "2025-01-01T00:00:00Z",
                    "payload": {"subtopic_id": 30},
                    "rogue_field": "boom",
                }
            ]
        },
    )
    assert response.status_code == 422


def test_sync_progress_422_for_too_long_client_event_id(
    client: TestClient,
) -> None:
    """``Field(max_length=64)`` enforces the 64-char cap."""
    response = client.post(
        "/v1/progress:sync",
        json={
            "events": [
                {
                    "client_event_id": "x" * 65,
                    "kind": "lesson_complete",
                    "client_timestamp": "2025-01-01T00:00:00Z",
                    "payload": {"subtopic_id": 30},
                }
            ]
        },
    )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Sanity — sync ignores require_no_active_mock
# ---------------------------------------------------------------------------


def test_sync_progress_works_during_mock_attempt(
    app: FastAPI, mock_sync_service: MagicMock
) -> None:
    """Sync MUST succeed even while a mock is IN_PROGRESS so a learner
    who started a mock can still flush their pre-mock pending events."""

    def _raise_409() -> None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="exam_in_progress",
        )

    # Override the mock-exam guard to raise 409 (proving it isn't
    # exercised by this route).
    app.dependency_overrides[require_no_active_mock] = _raise_409
    mock_sync_service.sync_events.return_value = ([], [])
    client = TestClient(app)

    response = client.post("/v1/progress:sync", json={"events": []})

    assert response.status_code == 200
    mock_sync_service.sync_events.assert_called_once()
