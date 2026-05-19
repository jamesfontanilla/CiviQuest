"""Router tests for the mock-exam slice (Task 12.8).

Per ``testing-standards.md`` router tests use ``TestClient`` with
mocked services injected via ``app.dependency_overrides``. The DB is
never hit here.

Coverage shape (per Task 12.8 acceptance bullets):

* POST start: 201 happy + 401 (no token) + 403 (banned via override) +
  409 (mock_exam_in_progress) + 404 (no config).
* GET attempt: 200 in-progress + 200 submitted polymorphic + 401 +
  403 (wrong user) + 422 (non-int id).
* PATCH answer: 200 + 422 (bad body) + 401 + 403 + 409 (already
  submitted) + 409 (question_finalized).
* POST :report-focus-loss: 204 + 422 + 401.
* POST :submit: 200 + 401 + 403 + 409 (already submitted).
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
from app.features.mock_exams.router import (
    get_mock_exam_service,
    router as mock_router,
)
from app.features.mock_exams.schemas import (
    MockExamAttemptResponse,
    MockExamStartResponse,
    MockExamSubmittedResponse,
    ModuleScoreBreakdown,
)
from app.features.mock_exams.service import MockExamService
from app.features.quizzes.schemas import (
    QuizAttemptInProgressQuestion,
    QuizGradedQuestion,
)
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


def _make_start_response() -> MockExamStartResponse:
    return MockExamStartResponse(
        attempt_id=99,
        category=Category.PROFESSIONAL,
        started_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        time_limit_minutes=180,
        remaining_seconds=180 * 60,
        nav_policy="LINEAR_NO_REVISIT",
        questions=[
            QuizAttemptInProgressQuestion(
                id=1,
                ordinal=1,
                stem="Q1?",
                qtype="MULTIPLE_CHOICE",
                options=["A", "B", "C", "D"],
                selected_answer=None,
            )
        ],
        total_questions=1,
    )


def _make_in_progress_response() -> MockExamAttemptResponse:
    return MockExamAttemptResponse(
        attempt_id=99,
        category=Category.PROFESSIONAL,
        started_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        time_limit_minutes=180,
        remaining_seconds=170 * 60,
        nav_policy="LINEAR_NO_REVISIT",
        status="IN_PROGRESS",
        questions=[
            QuizAttemptInProgressQuestion(
                id=1,
                ordinal=1,
                stem="Q1?",
                qtype="MULTIPLE_CHOICE",
                options=["A", "B", "C", "D"],
                selected_answer=None,
            )
        ],
        total_questions=1,
    )


def _make_submitted_response() -> MockExamSubmittedResponse:
    return MockExamSubmittedResponse(
        attempt_id=99,
        category=Category.PROFESSIONAL,
        status="SUBMITTED",
        submission_mode="MANUAL",
        started_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        submitted_at=datetime(2025, 1, 1, 1, 0, tzinfo=timezone.utc),
        score=40,
        max_score=50,
        percentage=0.8,
        passed=True,
        awarded_xp=500,
        per_module_breakdown=[
            ModuleScoreBreakdown(
                module_id=1,
                title="Module 1",
                score=40,
                max=50,
                pct=0.8,
            ),
        ],
        weakness_summary=[
            ModuleScoreBreakdown(
                module_id=1,
                title="Module 1",
                score=40,
                max=50,
                pct=0.8,
            ),
        ],
        questions=[
            QuizGradedQuestion(
                id=1,
                ordinal=1,
                stem="Q1?",
                selected_answer="A",
                correct_answer="A",
                is_correct=True,
                explanation="exp",
            )
        ],
    )


# --- fixtures ---------------------------------------------------------------


@pytest.fixture
def mock_service() -> MagicMock:
    return MagicMock(spec=MockExamService)


@pytest.fixture
def authed_user() -> User:
    return _make_user()


@pytest.fixture
def app(mock_service: MagicMock, authed_user: User) -> Iterator[FastAPI]:
    fastapi_app = FastAPI()
    fastapi_app.add_middleware(AuthMiddleware)
    fastapi_app.add_middleware(RequestLoggingMiddleware)
    register_exception_handlers(fastapi_app)
    fastapi_app.include_router(mock_router)

    fastapi_app.dependency_overrides[get_mock_exam_service] = (
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
    app.dependency_overrides[get_current_user] = _raise_401
    return TestClient(app)


def _raise_401() -> None:
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_credentials"
    )


def _raise_403_banned() -> None:
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN, detail="account_banned"
    )


# ===========================================================================
# POST /v1/mock-exams/attempts
# ===========================================================================


def test_start_mock_exam_201(
    client: TestClient, mock_service: MagicMock
) -> None:
    mock_service.start_attempt.return_value = _make_start_response()

    response = client.post("/v1/mock-exams/attempts")

    assert response.status_code == 201
    body = response.json()
    assert body["attempt_id"] == 99
    assert body["nav_policy"] == "LINEAR_NO_REVISIT"
    assert body["total_questions"] == 1
    # Property 17 — no correctness fields on the wire.
    for q in body["questions"]:
        assert "correct_answer" not in q
        assert "is_correct" not in q
        assert "explanation" not in q


def test_start_mock_exam_401_without_token(
    unauthenticated_client: TestClient,
) -> None:
    response = unauthenticated_client.post("/v1/mock-exams/attempts")
    assert response.status_code == 401


def test_start_mock_exam_403_for_banned_user(
    app: FastAPI, mock_service: MagicMock
) -> None:
    app.dependency_overrides[get_current_user] = _raise_403_banned
    client = TestClient(app)

    response = client.post("/v1/mock-exams/attempts")

    assert response.status_code == 403
    mock_service.start_attempt.assert_not_called()


def test_start_mock_exam_409_when_in_progress(
    client: TestClient, mock_service: MagicMock
) -> None:
    mock_service.start_attempt.side_effect = HTTPException(
        status_code=status.HTTP_409_CONFLICT, detail="mock_exam_in_progress"
    )

    response = client.post("/v1/mock-exams/attempts")

    assert response.status_code == 409
    assert response.json()["error"]["message"] == "mock_exam_in_progress"


def test_start_mock_exam_404_when_no_config(
    client: TestClient, mock_service: MagicMock
) -> None:
    mock_service.start_attempt.side_effect = HTTPException(
        status_code=status.HTTP_404_NOT_FOUND, detail="mock_config_not_found"
    )

    response = client.post("/v1/mock-exams/attempts")

    assert response.status_code == 404


# ===========================================================================
# GET /v1/mock-exams/attempts/{id}
# ===========================================================================


def test_get_mock_attempt_in_progress_200(
    client: TestClient, mock_service: MagicMock
) -> None:
    mock_service.get_attempt.return_value = _make_in_progress_response()

    response = client.get("/v1/mock-exams/attempts/99")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "IN_PROGRESS"
    assert body["remaining_seconds"] == 170 * 60
    # Property 17.
    for q in body["questions"]:
        assert "correct_answer" not in q
        assert "is_correct" not in q
        assert "explanation" not in q


def test_get_mock_attempt_submitted_200_polymorphic(
    client: TestClient, mock_service: MagicMock
) -> None:
    mock_service.get_attempt.return_value = _make_submitted_response()

    response = client.get("/v1/mock-exams/attempts/99")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "SUBMITTED"
    assert body["score"] == 40
    assert body["passed"] is True
    # Submitted branch — correctness fields ARE present.
    assert body["questions"][0]["correct_answer"] == "A"
    assert body["questions"][0]["is_correct"] is True


def test_get_mock_attempt_401_without_token(
    unauthenticated_client: TestClient,
) -> None:
    response = unauthenticated_client.get("/v1/mock-exams/attempts/99")
    assert response.status_code == 401


def test_get_mock_attempt_403_wrong_user(
    client: TestClient, mock_service: MagicMock
) -> None:
    mock_service.get_attempt.side_effect = HTTPException(
        status_code=status.HTTP_403_FORBIDDEN, detail="forbidden"
    )

    response = client.get("/v1/mock-exams/attempts/99")

    assert response.status_code == 403


def test_get_mock_attempt_422_non_int_id(client: TestClient) -> None:
    response = client.get("/v1/mock-exams/attempts/abc")
    assert response.status_code == 422


# ===========================================================================
# PATCH /v1/mock-exams/attempts/{id}/answers/{qid}
# ===========================================================================


def test_patch_answer_200(
    client: TestClient, mock_service: MagicMock
) -> None:
    mock_service.set_answer.return_value = None

    response = client.patch(
        "/v1/mock-exams/attempts/99/answers/1",
        json={"selected_answer": "A"},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_patch_answer_422_missing_field(client: TestClient) -> None:
    response = client.patch(
        "/v1/mock-exams/attempts/99/answers/1", json={}
    )
    assert response.status_code == 422


def test_patch_answer_422_extra_field(client: TestClient) -> None:
    response = client.patch(
        "/v1/mock-exams/attempts/99/answers/1",
        json={"selected_answer": "A", "is_correct": True},
    )
    assert response.status_code == 422


def test_patch_answer_401_without_token(
    unauthenticated_client: TestClient,
) -> None:
    response = unauthenticated_client.patch(
        "/v1/mock-exams/attempts/99/answers/1",
        json={"selected_answer": "A"},
    )
    assert response.status_code == 401


def test_patch_answer_403_other_user(
    client: TestClient, mock_service: MagicMock
) -> None:
    mock_service.set_answer.side_effect = HTTPException(
        status_code=status.HTTP_403_FORBIDDEN, detail="forbidden"
    )

    response = client.patch(
        "/v1/mock-exams/attempts/99/answers/1",
        json={"selected_answer": "A"},
    )

    assert response.status_code == 403


def test_patch_answer_409_already_submitted(
    client: TestClient, mock_service: MagicMock
) -> None:
    mock_service.set_answer.side_effect = HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="attempt_already_submitted",
    )

    response = client.patch(
        "/v1/mock-exams/attempts/99/answers/1",
        json={"selected_answer": "A"},
    )

    assert response.status_code == 409
    assert response.json()["error"]["message"] == "attempt_already_submitted"


def test_patch_answer_409_question_finalized(
    client: TestClient, mock_service: MagicMock
) -> None:
    mock_service.set_answer.side_effect = HTTPException(
        status_code=status.HTTP_409_CONFLICT, detail="question_finalized"
    )

    response = client.patch(
        "/v1/mock-exams/attempts/99/answers/1",
        json={"selected_answer": "B"},
    )

    assert response.status_code == 409
    assert response.json()["error"]["message"] == "question_finalized"


# ===========================================================================
# POST /v1/mock-exams/attempts/{id}:report-focus-loss
# ===========================================================================


def test_report_focus_loss_204(
    client: TestClient, mock_service: MagicMock
) -> None:
    mock_service.report_focus_loss.return_value = None

    response = client.post(
        "/v1/mock-exams/attempts/99:report-focus-loss",
        json={
            "kind": "blur",
            "at": "2025-01-01T12:00:00+00:00",
        },
    )

    assert response.status_code == 204


def test_report_focus_loss_422_missing_kind(client: TestClient) -> None:
    response = client.post(
        "/v1/mock-exams/attempts/99:report-focus-loss",
        json={"at": "2025-01-01T12:00:00+00:00"},
    )
    assert response.status_code == 422


def test_report_focus_loss_422_extra_field(client: TestClient) -> None:
    response = client.post(
        "/v1/mock-exams/attempts/99:report-focus-loss",
        json={
            "kind": "blur",
            "at": "2025-01-01T12:00:00+00:00",
            "duration": 1.5,
        },
    )
    assert response.status_code == 422


def test_report_focus_loss_401_without_token(
    unauthenticated_client: TestClient,
) -> None:
    response = unauthenticated_client.post(
        "/v1/mock-exams/attempts/99:report-focus-loss",
        json={"kind": "blur", "at": "2025-01-01T12:00:00+00:00"},
    )
    assert response.status_code == 401


# ===========================================================================
# POST /v1/mock-exams/attempts/{id}:submit
# ===========================================================================


def test_submit_attempt_200(
    client: TestClient, mock_service: MagicMock
) -> None:
    mock_service.submit_attempt.return_value = _make_submitted_response()

    response = client.post("/v1/mock-exams/attempts/99:submit")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "SUBMITTED"
    assert body["passed"] is True
    assert body["awarded_xp"] == 500
    assert "per_module_breakdown" in body
    assert "weakness_summary" in body


def test_submit_attempt_401_without_token(
    unauthenticated_client: TestClient,
) -> None:
    response = unauthenticated_client.post("/v1/mock-exams/attempts/99:submit")
    assert response.status_code == 401


def test_submit_attempt_403_other_user(
    client: TestClient, mock_service: MagicMock
) -> None:
    mock_service.submit_attempt.side_effect = HTTPException(
        status_code=status.HTTP_403_FORBIDDEN, detail="forbidden"
    )

    response = client.post("/v1/mock-exams/attempts/99:submit")

    assert response.status_code == 403


def test_submit_attempt_409_already_submitted(
    client: TestClient, mock_service: MagicMock
) -> None:
    mock_service.submit_attempt.side_effect = HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="attempt_already_submitted",
    )

    response = client.post("/v1/mock-exams/attempts/99:submit")

    assert response.status_code == 409
