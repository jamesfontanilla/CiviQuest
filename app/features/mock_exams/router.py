"""FastAPI router for the mock-exam slice (Task 12.7).

Mounts under ``/v1`` and exposes the start / get / answer /
focus-loss / submit surface for mock exams.

Per ``code-conventions.md`` the route handlers are thin: each takes a
service via ``Depends(...)`` and returns the result. The factory
function constructs the service per-request, sharing one ``Session``
across the dependency graph.

Auth contract for these routes:
    Routes here use :func:`get_current_user` directly, **not**
    :func:`require_no_active_mock`. The user is allowed (and
    expected) to interact with their own in-progress mock attempt:
    blocking that with the global mock-in-progress guard would make
    it impossible to answer questions or submit. The "no other
    routes during a mock" rule is enforced on every other slice
    (Req 19.1 / Property 29) — this slice is the carve-out.

Polymorphic GET on ``/v1/mock-exams/attempts/{attempt_id}``: the
response is either :class:`MockExamAttemptResponse` (in-progress) or
:class:`MockExamSubmittedResponse` (already submitted, or
auto-submitted by the timer-authority check). The route omits
``response_model`` so FastAPI lets the service's already-built
Pydantic instance pass through unchanged — declaring a union as
``response_model`` is finicky across pydantic versions.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from app.common.deps import get_current_user
from app.features.content.repository import (
    ModuleRepository,
    QuestionRepository,
)
from app.features.mock_exams.repository import MockExamRepository
from app.features.mock_exams.schemas import (
    FocusLossReportRequest,
    MockAnswerPatchRequest,
    MockExamStartResponse,
    MockExamSubmittedResponse,
)
from app.features.mock_exams.service import MockExamService
from app.features.users.models import User
from app.features.users.repository import UserRepository
from app.features.xp.repository import XPRepository
from app.features.xp.service import XPService
from app.infrastructure.database.session import get_db


router = APIRouter(prefix="/v1", tags=["mock-exams"])


def get_mock_exam_service(
    db: Session = Depends(get_db),
) -> MockExamService:
    """Construct :class:`MockExamService` for the request."""
    return MockExamService(
        mock_repo=MockExamRepository(db=db),
        question_repo=QuestionRepository(db=db),
        module_repo=ModuleRepository(db=db),
        xp_service=XPService(
            xp_repo=XPRepository(db=db),
            user_repo=UserRepository(db=db),
        ),
    )


# ---------------------------------------------------------------------------
# Start endpoint
# ---------------------------------------------------------------------------


@router.post(
    "/mock-exams/attempts",
    status_code=status.HTTP_201_CREATED,
    response_model=MockExamStartResponse,
)
def start_mock_exam(
    user: User = Depends(get_current_user),
    service: MockExamService = Depends(get_mock_exam_service),
) -> MockExamStartResponse:
    """Start a mock-exam attempt (Req 10.1, 10.2).

    The service handles the at-most-one-IN_PROGRESS check (Req 10.8 /
    Property 36); a duplicate start surfaces as 409
    ``mock_exam_in_progress``.
    """
    return service.start_attempt(user=user)


# ---------------------------------------------------------------------------
# Attempt operations
# ---------------------------------------------------------------------------


@router.get("/mock-exams/attempts/{attempt_id}")
def get_mock_attempt(
    attempt_id: int,
    user: User = Depends(get_current_user),
    service: MockExamService = Depends(get_mock_exam_service),
):
    """Polymorphic read: in-progress shape vs submitted shape.

    Property 30 — if the timer has expired and the attempt is still
    IN_PROGRESS at read time, the service auto-submits and returns
    the submitted response.
    """
    return service.get_attempt(attempt_id=attempt_id, user=user)


@router.patch(
    "/mock-exams/attempts/{attempt_id}/answers/{question_id}",
    status_code=status.HTTP_200_OK,
)
def set_mock_answer(
    attempt_id: int,
    question_id: int,
    payload: MockAnswerPatchRequest,
    user: User = Depends(get_current_user),
    service: MockExamService = Depends(get_mock_exam_service),
) -> dict[str, str]:
    """Persist the learner's selection (Req 14.1, 19.4).

    Returns a minimal ``{"status": "ok"}`` body. The mid-attempt
    response shape MUST NOT carry correctness fields (Property 17 /
    Req 10.4).
    """
    service.set_answer(
        attempt_id=attempt_id,
        question_id=question_id,
        payload=payload,
        user=user,
    )
    return {"status": "ok"}


@router.post(
    "/mock-exams/attempts/{attempt_id}:report-focus-loss",
    status_code=status.HTTP_204_NO_CONTENT,
)
def report_focus_loss(
    attempt_id: int,
    payload: FocusLossReportRequest,
    user: User = Depends(get_current_user),
    service: MockExamService = Depends(get_mock_exam_service),
) -> Response:
    """Append a focus-loss event to the attempt (Req 19.2).

    The service does not modify ``started_at`` or
    ``time_limit_minutes`` — Property 30 / Req 19.2 require that
    spamming this route does not extend the timer.
    """
    service.report_focus_loss(
        attempt_id=attempt_id, payload=payload, user=user
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/mock-exams/attempts/{attempt_id}:submit",
    response_model=MockExamSubmittedResponse,
)
def submit_mock_attempt(
    attempt_id: int,
    user: User = Depends(get_current_user),
    service: MockExamService = Depends(get_mock_exam_service),
) -> MockExamSubmittedResponse:
    """Grade + persist + fan out 500 XP on pass (Req 10.5, 10.6)."""
    return service.submit_attempt(attempt_id=attempt_id, user=user)
