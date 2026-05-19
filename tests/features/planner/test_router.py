"""Router tests for the planner feature — mocked service, HTTP client."""

from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.features.planner.schemas import (
    PlanDayResponse,
    ReadinessResponse,
    StudyPlanResponse,
)
from app.features.planner.service import ReadinessService, StudyPlannerService
from app.features.users.models import User
from app.main import app


@pytest.fixture
def mock_user() -> User:
    user = MagicMock(spec=User)
    user.id = 1
    user.role = "LEARNER"
    user.is_banned = False
    return user


@pytest.fixture
def mock_planner_service() -> MagicMock:
    return MagicMock(spec=StudyPlannerService)


@pytest.fixture
def mock_readiness_service() -> MagicMock:
    return MagicMock(spec=ReadinessService)


@pytest.fixture
def client(mock_user, mock_planner_service, mock_readiness_service) -> TestClient:
    from app.common.deps import get_current_user
    from app.features.planner.router import _get_planner_service, _get_readiness_service

    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[_get_planner_service] = lambda: mock_planner_service
    app.dependency_overrides[_get_readiness_service] = lambda: mock_readiness_service

    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()


def test_create_plan_returns_201(client, mock_planner_service):
    future = date.today() + timedelta(days=30)
    mock_planner_service.create_plan.return_value = StudyPlanResponse(
        id=1,
        target_exam_date=future,
        available_hours_per_day=2.0,
        target_score=0.85,
        status="ACTIVE",
        total_days=30,
        days_remaining=30,
        completion_percentage=0.0,
    )
    response = client.post("/v1/planner/plans", json={
        "target_exam_date": future.isoformat(),
        "available_hours_per_day": 2.0,
        "target_score": 0.85,
    })
    assert response.status_code == 201
    assert response.json()["status"] == "ACTIVE"


def test_create_plan_returns_422_invalid_hours(client):
    future = date.today() + timedelta(days=30)
    response = client.post("/v1/planner/plans", json={
        "target_exam_date": future.isoformat(),
        "available_hours_per_day": 0.1,  # below minimum
        "target_score": 0.85,
    })
    assert response.status_code == 422


def test_get_active_plan_returns_200(client, mock_planner_service):
    future = date.today() + timedelta(days=30)
    mock_planner_service.get_active_plan.return_value = StudyPlanResponse(
        id=1,
        target_exam_date=future,
        available_hours_per_day=2.0,
        target_score=0.85,
        status="ACTIVE",
        total_days=30,
        days_remaining=30,
        completion_percentage=50.0,
    )
    response = client.get("/v1/planner/plans/me")
    assert response.status_code == 200


def test_get_today_tasks_returns_200(client, mock_planner_service):
    mock_planner_service.get_today_tasks.return_value = [
        PlanDayResponse(
            id=1,
            plan_date=date.today(),
            subtopic_title="Vocabulary",
            activity_type="lesson",
            estimated_minutes=30,
            completed=False,
        )
    ]
    response = client.get("/v1/planner/plans/me/today")
    assert response.status_code == 200
    assert len(response.json()) == 1


def test_mark_task_complete_returns_200(client, mock_planner_service):
    mock_planner_service.mark_task_complete.return_value = None
    response = client.post("/v1/planner/plans/me/tasks/1:complete")
    assert response.status_code == 200


def test_abandon_plan_returns_204(client, mock_planner_service):
    mock_planner_service.abandon_plan.return_value = None
    response = client.delete("/v1/planner/plans/me")
    assert response.status_code == 204


def test_readiness_returns_200(client, mock_readiness_service):
    mock_readiness_service.get_readiness.return_value = ReadinessResponse(
        passing_probability=0.72,
        predicted_score=0.68,
        readiness_percentage=68.0,
        recommended_hours_remaining=12.8,
        strengths=["Vocabulary", "Grammar"],
        weaknesses=["Math"],
        confidence_level="high",
    )
    response = client.get("/v1/planner/readiness/me")
    assert response.status_code == 200
    data = response.json()
    assert data["confidence_level"] == "high"
    assert data["passing_probability"] == 0.72


def test_unauthenticated_returns_401():
    app.dependency_overrides.clear()
    client = TestClient(app)
    response = client.post("/v1/planner/plans", json={
        "target_exam_date": "2025-12-01",
        "available_hours_per_day": 2.0,
        "target_score": 0.85,
    })
    assert response.status_code == 401
