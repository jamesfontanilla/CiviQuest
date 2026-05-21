"""Router tests for the quizzes slice (Task 11.7).

Per ``testing-standards.md`` router tests use ``TestClient`` with
mocked services injected via ``app.dependency_overrides``. The DB is
never hit here.

Coverage shape (per Task 11.7 acceptance bullets):

* Each route: 200/201 happy + 422 (bad body / non-int id) + 401
  (missing token) + 403 (banned via override) + 409
  (lesson-not-completed for subtopic; prereq-not-met for topic /
  module; mock-in-progress via override) + 409
  (insufficient_question_pool).
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
from app.features.content.models import LevelScope
from app.features.quizzes.router import (
    get_quiz_service,
    router as quiz_router,
)
from app.features.quizzes.schemas import (
    QuizAttemptInProgressQuestion,
    QuizAttemptInProgressResponse,
    QuizGradedQuestion,
    QuizSubmittedResponse,
    QuizSummary,
)
from app.features.quizzes.service import QuizService
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


def _make_in_progress_response(scope: LevelScope, scope_id: int = 10):
    return QuizAttemptInProgressResponse(
        attempt_id=99,
        scope_level=scope,
        scope_id=scope_id,
        status="IN_PROGRESS",
        started_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        time_limit_seconds=None,
        questions=[
            QuizAttemptInProgressQuestion(
                id=1,
                ordinal=1,
                stem="Q?",
                qtype="MULTIPLE_CHOICE",
                difficulty="EASY",
                options=["A", "B", "C", "D"],
                selected_answer=None,
            )
        ],
        total_questions=1,
    )


def _make_submitted_response():
    return QuizSubmittedResponse(
        attempt_id=99,
        scope_level=LevelScope.SUBTOPIC,
        scope_id=10,
        status="SUBMITTED",
        started_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        submitted_at=datetime(2025, 1, 1, 0, 30, tzinfo=timezone.utc),
        time_limit_seconds=None,
        score=18,
        max_score=20,
        percentage=0.9,
        is_perfect=False,
        is_passing=True,
        awarded_xp=20,
        summary=QuizSummary(
            total_questions=20,
            correct=18,
            incorrect=2,
            unanswered=0,
            score=18,
            max_score=20,
            percentage=0.9,
            is_passing=True,
            is_perfect=False,
            result_label="Passed",
        ),
        questions=[
            QuizGradedQuestion(
                id=1,
                ordinal=1,
                stem="Q?",
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
    return MagicMock(spec=QuizService)


@pytest.fixture
def authed_user() -> User:
    return _make_user()


@pytest.fixture
def app(
    mock_service: MagicMock, authed_user: User
) -> Iterator[FastAPI]:
    fastapi_app = FastAPI()
    fastapi_app.add_middleware(AuthMiddleware)
    fastapi_app.add_middleware(RequestLoggingMiddleware)
    register_exception_handlers(fastapi_app)
    fastapi_app.include_router(quiz_router)

    fastapi_app.dependency_overrides[get_quiz_service] = lambda: mock_service
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
    app.dependency_overrides[get_current_user] = _raise_401
    app.dependency_overrides[require_no_active_mock] = _raise_401
    return TestClient(app)


def _raise_401() -> None:
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_credentials"
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
# POST /v1/subtopics/{id}/quiz-attempts
# ===========================================================================


def test_start_subtopic_quiz_201(
    client: TestClient, mock_service: MagicMock
) -> None:
    mock_service.start_subtopic_quiz.return_value = (
        _make_in_progress_response(LevelScope.SUBTOPIC)
    )

    response = client.post("/v1/subtopics/10/quiz-attempts")

    assert response.status_code == 201
    body = response.json()
    assert body["scope_level"] == "SUBTOPIC"
    assert body["status"] == "IN_PROGRESS"
    # Property 17 — no correctness fields on the wire.
    for q in body["questions"]:
        assert "correct_answer" not in q
        assert "is_correct" not in q
        assert "explanation" not in q


def test_start_subtopic_quiz_422_for_non_int_id(client: TestClient) -> None:
    response = client.post("/v1/subtopics/not-a-number/quiz-attempts")
    assert response.status_code == 422


def test_start_subtopic_quiz_401_without_token(
    unauthenticated_client: TestClient,
) -> None:
    response = unauthenticated_client.post("/v1/subtopics/10/quiz-attempts")
    assert response.status_code == 401


def test_start_subtopic_quiz_403_for_banned_user(
    app: FastAPI, mock_service: MagicMock
) -> None:
    app.dependency_overrides[require_no_active_mock] = _raise_403_banned
    client = TestClient(app)

    response = client.post("/v1/subtopics/10/quiz-attempts")

    assert response.status_code == 403
    mock_service.start_subtopic_quiz.assert_not_called()


def test_start_subtopic_quiz_403_for_wrong_category(
    client: TestClient, mock_service: MagicMock
) -> None:
    """Service raises 403 when subtopic belongs to a different category."""
    mock_service.start_subtopic_quiz.side_effect = HTTPException(
        status_code=status.HTTP_403_FORBIDDEN, detail="forbidden"
    )

    response = client.post("/v1/subtopics/10/quiz-attempts")

    assert response.status_code == 403


def test_start_subtopic_quiz_409_lesson_not_completed(
    client: TestClient, mock_service: MagicMock
) -> None:
    mock_service.start_subtopic_quiz.side_effect = HTTPException(
        status_code=status.HTTP_409_CONFLICT, detail="lesson_not_completed"
    )

    response = client.post("/v1/subtopics/10/quiz-attempts")

    assert response.status_code == 409
    assert response.json()["error"]["message"] == "lesson_not_completed"


def test_start_subtopic_quiz_409_when_mock_in_progress(
    app: FastAPI, mock_service: MagicMock
) -> None:
    app.dependency_overrides[require_no_active_mock] = (
        _raise_409_mock_in_progress
    )
    client = TestClient(app)

    response = client.post("/v1/subtopics/10/quiz-attempts")

    assert response.status_code == 409
    assert response.json()["error"]["message"] == "exam_in_progress"
    mock_service.start_subtopic_quiz.assert_not_called()


def test_start_subtopic_quiz_409_insufficient_pool(
    client: TestClient, mock_service: MagicMock
) -> None:
    mock_service.start_subtopic_quiz.side_effect = HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="insufficient_question_pool",
    )

    response = client.post("/v1/subtopics/10/quiz-attempts")

    assert response.status_code == 409
    assert (
        response.json()["error"]["message"] == "insufficient_question_pool"
    )


# ===========================================================================
# POST /v1/topics/{id}/quiz-attempts
# ===========================================================================


def test_start_topic_quiz_201(
    client: TestClient, mock_service: MagicMock
) -> None:
    mock_service.start_topic_quiz.return_value = _make_in_progress_response(
        LevelScope.TOPIC, scope_id=20
    )

    response = client.post("/v1/topics/20/quiz-attempts")

    assert response.status_code == 201
    assert response.json()["scope_level"] == "TOPIC"


def test_start_topic_quiz_422_for_non_int_id(client: TestClient) -> None:
    response = client.post("/v1/topics/abc/quiz-attempts")
    assert response.status_code == 422


def test_start_topic_quiz_401_without_token(
    unauthenticated_client: TestClient,
) -> None:
    response = unauthenticated_client.post("/v1/topics/20/quiz-attempts")
    assert response.status_code == 401


def test_start_topic_quiz_403_for_wrong_category(
    client: TestClient, mock_service: MagicMock
) -> None:
    mock_service.start_topic_quiz.side_effect = HTTPException(
        status_code=status.HTTP_403_FORBIDDEN, detail="forbidden"
    )
    response = client.post("/v1/topics/20/quiz-attempts")
    assert response.status_code == 403


def test_start_topic_quiz_409_prereq_not_met(
    client: TestClient, mock_service: MagicMock
) -> None:
    mock_service.start_topic_quiz.side_effect = HTTPException(
        status_code=status.HTTP_409_CONFLICT, detail="prerequisites_not_met"
    )

    response = client.post("/v1/topics/20/quiz-attempts")

    assert response.status_code == 409
    assert response.json()["error"]["message"] == "prerequisites_not_met"


def test_start_topic_quiz_409_when_mock_in_progress(
    app: FastAPI, mock_service: MagicMock
) -> None:
    app.dependency_overrides[require_no_active_mock] = (
        _raise_409_mock_in_progress
    )
    client = TestClient(app)
    response = client.post("/v1/topics/20/quiz-attempts")
    assert response.status_code == 409
    mock_service.start_topic_quiz.assert_not_called()


# ===========================================================================
# POST /v1/modules/{id}/quiz-attempts
# ===========================================================================


def test_start_module_quiz_201(
    client: TestClient, mock_service: MagicMock
) -> None:
    mock_service.start_module_quiz.return_value = _make_in_progress_response(
        LevelScope.MODULE, scope_id=30
    )

    response = client.post("/v1/modules/30/quiz-attempts")

    assert response.status_code == 201
    assert response.json()["scope_level"] == "MODULE"


def test_start_module_quiz_422_for_non_int_id(client: TestClient) -> None:
    response = client.post("/v1/modules/abc/quiz-attempts")
    assert response.status_code == 422


def test_start_module_quiz_401_without_token(
    unauthenticated_client: TestClient,
) -> None:
    response = unauthenticated_client.post("/v1/modules/30/quiz-attempts")
    assert response.status_code == 401


def test_start_module_quiz_403_for_wrong_category(
    client: TestClient, mock_service: MagicMock
) -> None:
    mock_service.start_module_quiz.side_effect = HTTPException(
        status_code=status.HTTP_403_FORBIDDEN, detail="forbidden"
    )
    response = client.post("/v1/modules/30/quiz-attempts")
    assert response.status_code == 403


def test_start_module_quiz_409_prereq_not_met(
    client: TestClient, mock_service: MagicMock
) -> None:
    mock_service.start_module_quiz.side_effect = HTTPException(
        status_code=status.HTTP_409_CONFLICT, detail="prerequisites_not_met"
    )

    response = client.post("/v1/modules/30/quiz-attempts")

    assert response.status_code == 409


def test_start_module_quiz_409_when_mock_in_progress(
    app: FastAPI, mock_service: MagicMock
) -> None:
    app.dependency_overrides[require_no_active_mock] = (
        _raise_409_mock_in_progress
    )
    client = TestClient(app)
    response = client.post("/v1/modules/30/quiz-attempts")
    assert response.status_code == 409
    mock_service.start_module_quiz.assert_not_called()


# ===========================================================================
# GET /v1/quiz-attempts/{id}
# ===========================================================================


def test_get_attempt_in_progress_200(
    client: TestClient, mock_service: MagicMock
) -> None:
    mock_service.get_attempt.return_value = _make_in_progress_response(
        LevelScope.SUBTOPIC
    )

    response = client.get("/v1/quiz-attempts/99")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "IN_PROGRESS"
    # Property 17 — even on a polymorphic GET, in-progress payloads
    # MUST NOT include correctness fields.
    for q in body["questions"]:
        assert "correct_answer" not in q
        assert "is_correct" not in q
        assert "explanation" not in q


def test_get_attempt_submitted_200(
    client: TestClient, mock_service: MagicMock
) -> None:
    mock_service.get_attempt.return_value = _make_submitted_response()

    response = client.get("/v1/quiz-attempts/99")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "SUBMITTED"
    # On the submitted branch, correctness fields are present.
    assert body["questions"][0]["correct_answer"] == "A"
    assert body["questions"][0]["is_correct"] is True


def test_get_attempt_403_for_other_user(
    client: TestClient, mock_service: MagicMock
) -> None:
    mock_service.get_attempt.side_effect = HTTPException(
        status_code=status.HTTP_403_FORBIDDEN, detail="forbidden"
    )

    response = client.get("/v1/quiz-attempts/99")

    assert response.status_code == 403


def test_get_attempt_401_without_token(
    unauthenticated_client: TestClient,
) -> None:
    response = unauthenticated_client.get("/v1/quiz-attempts/99")
    assert response.status_code == 401


def test_get_attempt_422_for_non_int_id(client: TestClient) -> None:
    response = client.get("/v1/quiz-attempts/abc")
    assert response.status_code == 422


def test_get_attempt_409_when_mock_in_progress(
    app: FastAPI, mock_service: MagicMock
) -> None:
    app.dependency_overrides[require_no_active_mock] = (
        _raise_409_mock_in_progress
    )
    client = TestClient(app)
    response = client.get("/v1/quiz-attempts/99")
    assert response.status_code == 409


# ===========================================================================
# PATCH /v1/quiz-attempts/{id}/answers/{qid}
# ===========================================================================


def test_set_answer_200(
    client: TestClient, mock_service: MagicMock
) -> None:
    mock_service.set_answer.return_value = None

    response = client.patch(
        "/v1/quiz-attempts/99/answers/1",
        json={"selected_answer": "A"},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_set_answer_422_missing_field(client: TestClient) -> None:
    response = client.patch("/v1/quiz-attempts/99/answers/1", json={})
    assert response.status_code == 422


def test_set_answer_422_extra_field_forbidden(client: TestClient) -> None:
    response = client.patch(
        "/v1/quiz-attempts/99/answers/1",
        json={"selected_answer": "A", "is_correct": True},
    )
    assert response.status_code == 422


def test_set_answer_422_empty_string(client: TestClient) -> None:
    response = client.patch(
        "/v1/quiz-attempts/99/answers/1",
        json={"selected_answer": ""},
    )
    assert response.status_code == 422


def test_set_answer_401_without_token(
    unauthenticated_client: TestClient,
) -> None:
    response = unauthenticated_client.patch(
        "/v1/quiz-attempts/99/answers/1",
        json={"selected_answer": "A"},
    )
    assert response.status_code == 401


def test_set_answer_403_for_other_user(
    client: TestClient, mock_service: MagicMock
) -> None:
    mock_service.set_answer.side_effect = HTTPException(
        status_code=status.HTTP_403_FORBIDDEN, detail="forbidden"
    )

    response = client.patch(
        "/v1/quiz-attempts/99/answers/1",
        json={"selected_answer": "A"},
    )

    assert response.status_code == 403


def test_set_answer_409_already_submitted(
    client: TestClient, mock_service: MagicMock
) -> None:
    mock_service.set_answer.side_effect = HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="attempt_already_submitted",
    )

    response = client.patch(
        "/v1/quiz-attempts/99/answers/1",
        json={"selected_answer": "A"},
    )

    assert response.status_code == 409


def test_set_answer_409_when_mock_in_progress(
    app: FastAPI, mock_service: MagicMock
) -> None:
    app.dependency_overrides[require_no_active_mock] = (
        _raise_409_mock_in_progress
    )
    client = TestClient(app)
    response = client.patch(
        "/v1/quiz-attempts/99/answers/1",
        json={"selected_answer": "A"},
    )
    assert response.status_code == 409
    mock_service.set_answer.assert_not_called()


# ===========================================================================
# POST /v1/quiz-attempts/{id}:submit
# ===========================================================================


def test_submit_attempt_200(
    client: TestClient, mock_service: MagicMock
) -> None:
    mock_service.submit_attempt.return_value = _make_submitted_response()

    response = client.post("/v1/quiz-attempts/99:submit")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "SUBMITTED"
    assert body["score"] == 18
    assert body["is_passing"] is True
    assert body["awarded_xp"] == 20


def test_submit_attempt_401_without_token(
    unauthenticated_client: TestClient,
) -> None:
    response = unauthenticated_client.post("/v1/quiz-attempts/99:submit")
    assert response.status_code == 401


def test_submit_attempt_403_for_other_user(
    client: TestClient, mock_service: MagicMock
) -> None:
    mock_service.submit_attempt.side_effect = HTTPException(
        status_code=status.HTTP_403_FORBIDDEN, detail="forbidden"
    )

    response = client.post("/v1/quiz-attempts/99:submit")

    assert response.status_code == 403


def test_submit_attempt_409_already_submitted(
    client: TestClient, mock_service: MagicMock
) -> None:
    mock_service.submit_attempt.side_effect = HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="attempt_already_submitted",
    )

    response = client.post("/v1/quiz-attempts/99:submit")

    assert response.status_code == 409


def test_submit_attempt_409_when_mock_in_progress(
    app: FastAPI, mock_service: MagicMock
) -> None:
    app.dependency_overrides[require_no_active_mock] = (
        _raise_409_mock_in_progress
    )
    client = TestClient(app)
    response = client.post("/v1/quiz-attempts/99:submit")
    assert response.status_code == 409
    mock_service.submit_attempt.assert_not_called()


def test_submit_attempt_422_for_non_int_id(client: TestClient) -> None:
    response = client.post("/v1/quiz-attempts/abc:submit")
    assert response.status_code == 422
