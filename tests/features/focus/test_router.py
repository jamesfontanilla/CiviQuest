"""Router tests for the focus feature — mocked service, HTTP client."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.common.deps import get_current_user
from app.features.focus.router import _get_focus_service
from app.features.focus.schemas import FocusSessionResponse, FocusStatsResponse, WellnessResponse
from app.features.focus.service import FocusService
from app.features.users.models import User
from app.main import app


@pytest.fixture()
def mock_service() -> MagicMock:
    return MagicMock(spec=FocusService)


@pytest.fixture()
def mock_user() -> User:
    user = User(
        id=1,
        email="test@test.com",
        display_name="Tester",
        age=25,
        category="PROFESSIONAL",
        role="LEARNER",
        account_state="VERIFIED",
        password_hash="$2b$10$fakehash",
    )
    return user


@pytest.fixture()
def client(mock_service: MagicMock, mock_user: User) -> TestClient:
    app.dependency_overrides[_get_focus_service] = lambda: mock_service
    app.dependency_overrides[get_current_user] = lambda: mock_user
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_start_session_returns_201(client: TestClient, mock_service: MagicMock) -> None:
    mock_service.start_session.return_value = FocusSessionResponse(
        id=1,
        mode="25_5",
        work_minutes=25,
        break_minutes=5,
        started_at=datetime.now(tz=timezone.utc),
        ended_at=None,
        completed=False,
        total_focus_minutes=0,
        distractions=0,
    )
    response = client.post(
        "/v1/focus/sessions",
        json={"mode": "25_5", "work_minutes": 25, "break_minutes": 5},
    )
    assert response.status_code == 201
    assert response.json()["mode"] == "25_5"


def test_start_session_invalid_mode_returns_422(client: TestClient) -> None:
    response = client.post(
        "/v1/focus/sessions",
        json={"mode": "invalid", "work_minutes": 25, "break_minutes": 5},
    )
    assert response.status_code == 422


def test_complete_session_returns_200(client: TestClient, mock_service: MagicMock) -> None:
    mock_service.complete_session.return_value = FocusSessionResponse(
        id=1,
        mode="25_5",
        work_minutes=25,
        break_minutes=5,
        started_at=datetime.now(tz=timezone.utc),
        ended_at=datetime.now(tz=timezone.utc),
        completed=True,
        total_focus_minutes=22,
        distractions=1,
    )
    response = client.post(
        "/v1/focus/sessions/1:complete",
        json={"total_focus_minutes": 22, "distractions": 1},
    )
    assert response.status_code == 200
    assert response.json()["completed"] is True


def test_abandon_session_returns_204(client: TestClient, mock_service: MagicMock) -> None:
    mock_service.abandon_session.return_value = None
    response = client.post("/v1/focus/sessions/1:abandon")
    assert response.status_code == 204


def test_get_stats_returns_200(client: TestClient, mock_service: MagicMock) -> None:
    mock_service.get_stats.return_value = FocusStatsResponse(
        total_sessions=10,
        total_focus_hours=5.0,
        avg_session_minutes=30.0,
        sessions_today=2,
        focus_minutes_today=50,
    )
    response = client.get("/v1/focus/sessions/me/stats")
    assert response.status_code == 200
    assert response.json()["total_sessions"] == 10


def test_get_wellness_returns_200(client: TestClient, mock_service: MagicMock) -> None:
    mock_service.get_wellness.return_value = WellnessResponse(
        is_fatigued=False,
        fatigue_level="none",
        message="Keep going!",
        suggestion="keep_going",
    )
    response = client.get("/v1/focus/wellness/me")
    assert response.status_code == 200
    assert response.json()["is_fatigued"] is False
