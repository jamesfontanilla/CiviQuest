"""Router tests for the tutor feature — mocked service, HTTP client."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.features.tutor.schemas import (
    SimilarQuestionResponse,
    StepByStepResponse,
    TutorResponse,
)
from app.features.tutor.service import TutorService
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
def mock_service() -> MagicMock:
    return MagicMock(spec=TutorService)


@pytest.fixture
def client(mock_user, mock_service) -> TestClient:
    from app.common.deps import get_current_user
    from app.features.tutor.router import _get_tutor_service

    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[_get_tutor_service] = lambda: mock_service

    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()


def test_explain_returns_200(client, mock_service):
    mock_service.explain.return_value = TutorResponse(
        interaction_id=1, response_text="Explanation here", interaction_type="explain_answer"
    )
    response = client.post("/v1/tutor/explain", json={"question_id": 1, "selected_answer": "A"})
    assert response.status_code == 200
    data = response.json()
    assert data["interaction_type"] == "explain_answer"
    assert data["response_text"] == "Explanation here"


def test_explain_returns_422_missing_question_id(client):
    response = client.post("/v1/tutor/explain", json={})
    assert response.status_code == 422


def test_simplify_returns_200(client, mock_service):
    mock_service.simplify.return_value = TutorResponse(
        interaction_id=2, response_text="Simplified", interaction_type="simplify"
    )
    response = client.post("/v1/tutor/simplify", json={"question_id": 1})
    assert response.status_code == 200
    assert response.json()["interaction_type"] == "simplify"


def test_hint_returns_200(client, mock_service):
    mock_service.hint.return_value = TutorResponse(
        interaction_id=3, response_text="Hint text", interaction_type="hint"
    )
    response = client.post("/v1/tutor/hint", json={"question_id": 1})
    assert response.status_code == 200
    assert response.json()["interaction_type"] == "hint"


def test_step_by_step_returns_200(client, mock_service):
    mock_service.step_by_step_explain.return_value = StepByStepResponse(
        interaction_id=4, steps=["Step 1", "Step 2", "Step 3"]
    )
    response = client.post("/v1/tutor/step-by-step", json={"question_id": 1})
    assert response.status_code == 200
    data = response.json()
    assert len(data["steps"]) == 3


def test_similar_returns_200(client, mock_service):
    mock_service.similar_question.return_value = SimilarQuestionResponse(
        interaction_id=5, stem="Similar Q", options=["A", "B"], correct_answer="A", explanation="Because A"
    )
    response = client.post("/v1/tutor/similar", json={"question_id": 1})
    assert response.status_code == 200
    data = response.json()
    assert data["stem"] == "Similar Q"


def test_rate_returns_200(client, mock_service):
    mock_service.rate_interaction.return_value = None
    response = client.post("/v1/tutor/interactions/1:rate", json={"helpful": True})
    assert response.status_code == 200


def test_rate_returns_422_missing_helpful(client):
    response = client.post("/v1/tutor/interactions/1:rate", json={})
    assert response.status_code == 422


def test_unauthenticated_returns_401():
    """Without auth override, should get 401."""
    app.dependency_overrides.clear()
    client = TestClient(app)
    response = client.post("/v1/tutor/explain", json={"question_id": 1})
    assert response.status_code == 401
