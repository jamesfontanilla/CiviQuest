"""FastAPI router for the quizzes slice (Task 11.6).

Mounts under ``/v1`` and exposes the start / get / answer / submit
surface for subtopic, topic, and module quizzes.

Per ``code-conventions.md`` the route handlers are thin: each takes a
service via ``Depends(...)`` and returns the result. The factory
function constructs the service per-request, sharing one ``Session``
across the dependency graph.

Mock-exam guard contract (Req 19.1): every route here depends on
:func:`require_no_active_mock`. While a mock attempt is IN_PROGRESS
the endpoints return 409 ``exam_in_progress``.

Polymorphic GET on ``/v1/quiz-attempts/{attempt_id}``: the response is
either :class:`QuizAttemptInProgressResponse` or
:class:`QuizSubmittedResponse` depending on attempt state. The route
omits ``response_model`` so FastAPI lets the service's already-built
Pydantic instance pass through unchanged — declaring a union as
``response_model`` is finicky across pydantic versions and not worth
the brittleness here.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.common.deps import require_no_active_mock
from app.features.content.repository import (
    QuestionRepository,
    SubtopicRepository,
    TopicRepository,
)
from app.features.progress.repository import ProgressRepository
from app.features.quizzes.repository import QuizRepository
from app.features.quizzes.schemas import (
    QuizAnswerPatchRequest,
    QuizAttemptInProgressResponse,
    QuizStartRequest,
    QuizSubmittedResponse,
)
from app.features.quizzes.service import QuizService
from app.features.users.models import User
from app.features.users.repository import UserRepository
from app.features.xp.repository import XPRepository
from app.features.xp.service import XPService
from app.infrastructure.database.session import get_db


router = APIRouter(prefix="/v1", tags=["quizzes"])


def get_quiz_service(db: Session = Depends(get_db)) -> QuizService:
    """Construct :class:`QuizService` for the request."""
    return QuizService(
        quiz_repo=QuizRepository(db=db),
        question_repo=QuestionRepository(db=db),
        progress_repo=ProgressRepository(db=db),
        topic_repo=TopicRepository(db=db),
        subtopic_repo=SubtopicRepository(db=db),
        xp_service=XPService(
            xp_repo=XPRepository(db=db),
            user_repo=UserRepository(db=db),
        ),
    )


# ---------------------------------------------------------------------------
# Start endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/subtopics/{subtopic_id}/quiz-attempts",
    status_code=status.HTTP_201_CREATED,
    response_model=QuizAttemptInProgressResponse,
)
def start_subtopic_quiz(
    subtopic_id: int,
    payload: QuizStartRequest = QuizStartRequest(),
    user: User = Depends(require_no_active_mock),
    service: QuizService = Depends(get_quiz_service),
) -> QuizAttemptInProgressResponse:
    """Start a 20-question subtopic quiz (Req 7.1, 6.1).

    Accepts an optional ``QuizStartRequest`` body to set a countdown
    timer (practice=1200s, exam=900s, power=600s). Omitting the body
    or sending ``{"time_limit_seconds": null}`` starts with no timer.
    """
    return service.start_subtopic_quiz(
        user=user,
        subtopic_id=subtopic_id,
        time_limit_seconds=payload.time_limit_seconds,
    )


@router.post(
    "/topics/{topic_id}/quiz-attempts",
    status_code=status.HTTP_201_CREATED,
    response_model=QuizAttemptInProgressResponse,
)
def start_topic_quiz(
    topic_id: int,
    payload: QuizStartRequest = QuizStartRequest(),
    user: User = Depends(require_no_active_mock),
    service: QuizService = Depends(get_quiz_service),
) -> QuizAttemptInProgressResponse:
    """Start a 50-question topic quiz (Req 8.1, 8.2)."""
    return service.start_topic_quiz(
        user=user,
        topic_id=topic_id,
        time_limit_seconds=payload.time_limit_seconds,
    )


@router.post(
    "/modules/{module_id}/quiz-attempts",
    status_code=status.HTTP_201_CREATED,
    response_model=QuizAttemptInProgressResponse,
)
def start_module_quiz(
    module_id: int,
    user: User = Depends(require_no_active_mock),
    service: QuizService = Depends(get_quiz_service),
) -> QuizAttemptInProgressResponse:
    """Start a 100-question module quiz (Req 9.1, 9.2)."""
    return service.start_module_quiz(user=user, module_id=module_id)


# ---------------------------------------------------------------------------
# Attempt operations
# ---------------------------------------------------------------------------


@router.get("/quiz-attempts/{attempt_id}")
def get_attempt(
    attempt_id: int,
    user: User = Depends(require_no_active_mock),
    service: QuizService = Depends(get_quiz_service),
):
    """Polymorphic read: in-progress shape vs submitted shape.

    Pydantic instances flow through unchanged because we don't pin a
    ``response_model``. FastAPI serializes via the service's return
    type. Property 17 keeps the in-progress branch from leaking
    correctness fields.
    """
    return service.get_attempt(attempt_id=attempt_id, user=user)


@router.patch(
    "/quiz-attempts/{attempt_id}/answers/{question_id}",
    status_code=status.HTTP_200_OK,
)
def set_answer(
    attempt_id: int,
    question_id: int,
    payload: QuizAnswerPatchRequest,
    user: User = Depends(require_no_active_mock),
    service: QuizService = Depends(get_quiz_service),
) -> dict[str, str]:
    """Persist the learner's selection (Req 7.4, 14.1).

    Returns a minimal ``{"status": "ok"}`` body. The mid-attempt
    response shape MUST NOT carry correctness fields (Property 17).
    """
    service.set_answer(
        attempt_id=attempt_id,
        question_id=question_id,
        payload=payload,
        user=user,
    )
    return {"status": "ok"}


@router.post(
    "/quiz-attempts/{attempt_id}:submit",
    response_model=QuizSubmittedResponse,
)
def submit_attempt(
    attempt_id: int,
    user: User = Depends(require_no_active_mock),
    service: QuizService = Depends(get_quiz_service),
) -> QuizSubmittedResponse:
    """Grade + persist + fan out XP / completion (Req 7.5–7.7, 8.4–8.5,
    9.4)."""
    return service.submit_attempt(attempt_id=attempt_id, user=user)
