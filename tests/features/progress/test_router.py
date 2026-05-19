"""Router tests for the progress slice (Task 8.5).

Per ``testing-standards.md`` router tests use ``TestClient`` with mocked
services injected via ``app.dependency_overrides``. The DB is never hit
here.

Coverage shape (per Task 8.5 acceptance bullets):

* ``POST /v1/subtopics/{id}/lesson:complete``: 201 happy + 422 (bad
  body) + 401 + 403 (banned via override) + 409 (mock-in-progress via
  override).
* ``GET /v1/progress/snapshot``: 200 happy + 401.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI, HTTPException, status
from fastapi.testclient import TestClient

from app.common.deps import get_current_user, require_no_active_mock
from app.common.middlewares.auth import AuthMiddleware
from app.common.middlewares.error_handler import register_exception_handlers
from app.common.middlewares.logging import RequestLoggingMiddleware
from app.features.progress.router import (
    get_progress_service,
    router as progress_router,
)
from app.features.progress.schemas import (
    LessonCompleteResponse,
    ProgressSnapshotResponse,
)
from app.features.progress.service import ProgressService
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
def mock_service() -> MagicMock:
    return MagicMock(spec=ProgressService)


@pytest.fixture
def authed_user() -> User:
    return _make_user()


@pytest.fixture
def app(
    mock_service: MagicMock, authed_user: User
) -> Iterator[FastAPI]:
    """Mount the progress router with the production middleware stack."""
    fastapi_app = FastAPI()
    fastapi_app.add_middleware(AuthMiddleware)
    fastapi_app.add_middleware(RequestLoggingMiddleware)
    register_exception_handlers(fastapi_app)
    fastapi_app.include_router(progress_router)

    fastapi_app.dependency_overrides[get_progress_service] = (
        lambda: mock_service
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
    app.dependency_overrides[get_current_user] = _raise_401
    app.dependency_overrides[require_no_active_mock] = _raise_401
    return TestClient(app)


def _raise_401() -> None:
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="invalid_credentials",
    )


def _raise_403_banned() -> None:
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN, detail="account_banned"
    )


def _raise_409_mock_in_progress() -> None:
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT, detail="exam_in_progress"
    )


# ===========================================================================
# POST /v1/subtopics/{id}/lesson:complete
# ===========================================================================


def test_complete_lesson_201(
    client: TestClient, mock_service: MagicMock
) -> None:
    when = datetime(2025, 1, 1, tzinfo=timezone.utc)
    mock_service.complete_lesson.return_value = LessonCompleteResponse(
        lesson_id=40, user_id=1, completed_at=when, awarded_xp=20
    )

    response = client.post(
        "/v1/subtopics/30/lesson:complete",
        json={"client_event_id": "evt-1"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["lesson_id"] == 40
    assert body["awarded_xp"] == 20


def test_complete_lesson_201_idempotent_returns_zero_xp(
    client: TestClient, mock_service: MagicMock
) -> None:
    when = datetime(2025, 1, 1, tzinfo=timezone.utc)
    mock_service.complete_lesson.return_value = LessonCompleteResponse(
        lesson_id=40, user_id=1, completed_at=when, awarded_xp=0
    )

    response = client.post(
        "/v1/subtopics/30/lesson:complete",
        json={"client_event_id": "evt-replay"},
    )

    assert response.status_code == 201
    assert response.json()["awarded_xp"] == 0


def test_complete_lesson_201_with_empty_body(
    client: TestClient, mock_service: MagicMock
) -> None:
    """Empty body is valid: ``client_event_id`` and ``completed_at`` are
    both optional (server stamps now)."""
    when = datetime(2025, 1, 1, tzinfo=timezone.utc)
    mock_service.complete_lesson.return_value = LessonCompleteResponse(
        lesson_id=40, user_id=1, completed_at=when, awarded_xp=20
    )

    response = client.post("/v1/subtopics/30/lesson:complete", json={})

    assert response.status_code == 201


def test_complete_lesson_422_for_unexpected_field(
    client: TestClient,
) -> None:
    """``extra='forbid'`` on the schema rejects unknown keys."""
    response = client.post(
        "/v1/subtopics/30/lesson:complete",
        json={"unexpected_field": "boom"},
    )
    assert response.status_code == 422


def test_complete_lesson_422_for_non_int_subtopic_id(
    client: TestClient,
) -> None:
    response = client.post(
        "/v1/subtopics/not-a-number/lesson:complete", json={}
    )
    assert response.status_code == 422


def test_complete_lesson_403_for_unpublished_lesson(
    client: TestClient, mock_service: MagicMock
) -> None:
    """Service raises 403 for missing/unpublished lessons (Req 6.4)."""
    mock_service.complete_lesson.side_effect = HTTPException(
        status_code=status.HTTP_403_FORBIDDEN, detail="forbidden"
    )

    response = client.post("/v1/subtopics/30/lesson:complete", json={})

    assert response.status_code == 403
    assert response.json() == {
        "error": {"message": "forbidden", "code": "HTTP_403"}
    }


def test_complete_lesson_401_without_token(
    unauthenticated_client: TestClient,
) -> None:
    response = unauthenticated_client.post(
        "/v1/subtopics/30/lesson:complete", json={}
    )
    assert response.status_code == 401
    assert response.json() == {
        "error": {"message": "invalid_credentials", "code": "HTTP_401"}
    }


def test_complete_lesson_403_for_banned_user(
    app: FastAPI, mock_service: MagicMock
) -> None:
    """``require_no_active_mock`` -> ``get_current_user`` raises 403 for
    banned users (Req 15.3). We override the dep to simulate that
    branch without minting a real banned user row."""
    app.dependency_overrides[require_no_active_mock] = _raise_403_banned
    client = TestClient(app)

    response = client.post("/v1/subtopics/30/lesson:complete", json={})

    assert response.status_code == 403
    assert response.json() == {
        "error": {"message": "account_banned", "code": "HTTP_403"}
    }
    mock_service.complete_lesson.assert_not_called()


def test_complete_lesson_409_when_mock_exam_in_progress(
    app: FastAPI, mock_service: MagicMock
) -> None:
    """Req 19.1 — endpoint refused while a mock attempt is IN_PROGRESS."""
    app.dependency_overrides[require_no_active_mock] = _raise_409_mock_in_progress
    client = TestClient(app)

    response = client.post("/v1/subtopics/30/lesson:complete", json={})

    assert response.status_code == 409
    assert response.json() == {
        "error": {"message": "exam_in_progress", "code": "HTTP_409"}
    }
    mock_service.complete_lesson.assert_not_called()


# ===========================================================================
# GET /v1/progress/snapshot
# ===========================================================================


def test_progress_snapshot_200(
    client: TestClient, mock_service: MagicMock
) -> None:
    mock_service.get_snapshot.return_value = ProgressSnapshotResponse(
        completed_lesson_ids=[10, 20, 30],
        in_progress_quizzes=[],
        in_progress_mock_attempts=[],
        cumulative_xp=0,
        level=0,
        streak=0,
    )

    response = client.get("/v1/progress/snapshot")

    assert response.status_code == 200
    body = response.json()
    assert body["completed_lesson_ids"] == [10, 20, 30]
    assert body["in_progress_quizzes"] == []
    assert body["in_progress_mock_attempts"] == []
    assert body["cumulative_xp"] == 0
    assert body["level"] == 0
    assert body["streak"] == 0


def test_progress_snapshot_200_empty(
    client: TestClient, mock_service: MagicMock
) -> None:
    """First-time learner with no progress: empty payload."""
    mock_service.get_snapshot.return_value = ProgressSnapshotResponse(
        completed_lesson_ids=[]
    )

    response = client.get("/v1/progress/snapshot")

    assert response.status_code == 200
    assert response.json()["completed_lesson_ids"] == []


def test_progress_snapshot_401_without_token(
    unauthenticated_client: TestClient,
) -> None:
    response = unauthenticated_client.get("/v1/progress/snapshot")
    assert response.status_code == 401
    assert response.json() == {
        "error": {"message": "invalid_credentials", "code": "HTTP_401"}
    }


def test_progress_snapshot_works_during_mock_attempt(
    app: FastAPI, mock_service: MagicMock
) -> None:
    """Per design, snapshot is the only endpoint that must succeed
    during an active mock attempt — clients use it to resume."""
    # Override require_no_active_mock to raise 409 (proving it isn't
    # exercised by this route).
    app.dependency_overrides[require_no_active_mock] = (
        _raise_409_mock_in_progress
    )
    mock_service.get_snapshot.return_value = ProgressSnapshotResponse(
        completed_lesson_ids=[]
    )
    client = TestClient(app)

    response = client.get("/v1/progress/snapshot")

    assert response.status_code == 200
    mock_service.get_snapshot.assert_called_once()
