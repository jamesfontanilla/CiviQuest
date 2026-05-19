"""FastAPI router for the AI tutor feature.

Mounts under ``/v1/tutor`` and exposes rule-based explanation endpoints.
All routes require authentication.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.common.deps import get_current_user
from app.features.content.repository import QuestionRepository, SubtopicRepository
from app.features.tutor.repository import TutorRepository
from app.features.tutor.schemas import (
    RateRequest,
    SimilarQuestionResponse,
    StepByStepResponse,
    TutorRequest,
    TutorResponse,
)
from app.features.tutor.service import TutorService
from app.features.users.models import User
from app.infrastructure.database.session import get_db

router = APIRouter(prefix="/v1/tutor", tags=["tutor"])


def _get_tutor_service(db: Session = Depends(get_db)) -> TutorService:
    """Construct TutorService for the request."""
    return TutorService(
        tutor_repo=TutorRepository(db=db),
        question_repo=QuestionRepository(db=db),
        subtopic_repo=SubtopicRepository(db=db),
    )


@router.post("/explain", response_model=TutorResponse)
def tutor_explain(
    payload: TutorRequest,
    user: User = Depends(get_current_user),
    service: TutorService = Depends(_get_tutor_service),
) -> TutorResponse:
    """Get an explanation for a question's answer."""
    return service.explain(
        user_id=user.id,
        question_id=payload.question_id,
        selected_answer=payload.selected_answer,
    )


@router.post("/simplify", response_model=TutorResponse)
def tutor_simplify(
    payload: TutorRequest,
    user: User = Depends(get_current_user),
    service: TutorService = Depends(_get_tutor_service),
) -> TutorResponse:
    """Get a simplified explanation for a question."""
    return service.simplify(
        user_id=user.id,
        question_id=payload.question_id,
    )


@router.post("/similar", response_model=SimilarQuestionResponse)
def tutor_similar(
    payload: TutorRequest,
    user: User = Depends(get_current_user),
    service: TutorService = Depends(_get_tutor_service),
) -> SimilarQuestionResponse:
    """Generate a similar practice question."""
    return service.similar_question(
        user_id=user.id,
        question_id=payload.question_id,
    )


@router.post("/hint", response_model=TutorResponse)
def tutor_hint(
    payload: TutorRequest,
    user: User = Depends(get_current_user),
    service: TutorService = Depends(_get_tutor_service),
) -> TutorResponse:
    """Get a hint for a question without revealing the answer."""
    return service.hint(
        user_id=user.id,
        question_id=payload.question_id,
    )


@router.post("/step-by-step", response_model=StepByStepResponse)
def tutor_step_by_step(
    payload: TutorRequest,
    user: User = Depends(get_current_user),
    service: TutorService = Depends(_get_tutor_service),
) -> StepByStepResponse:
    """Get a step-by-step breakdown of the solution."""
    return service.step_by_step_explain(
        user_id=user.id,
        question_id=payload.question_id,
    )


@router.post("/interactions/{interaction_id}:rate")
def rate_interaction(
    interaction_id: int,
    payload: RateRequest,
    user: User = Depends(get_current_user),
    service: TutorService = Depends(_get_tutor_service),
) -> dict[str, str]:
    """Rate a tutor interaction as helpful or not."""
    service.rate_interaction(interaction_id, payload.helpful)
    return {"status": "ok"}
