"""FastAPI router for the study planner and readiness predictor.

Mounts under ``/v1/planner`` and exposes plan CRUD + readiness endpoint.
All routes require authentication.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.common.deps import get_current_user
from app.features.content.repository import SubtopicRepository
from app.features.mastery.repository import MasteryRepository
from app.features.planner.repository import (
    StudyPlanDayRepository,
    StudyPlanRepository,
)
from app.features.planner.schemas import (
    CreatePlanRequest,
    PlanDayResponse,
    ReadinessResponse,
    StudyPlanResponse,
)
from app.features.planner.service import ReadinessService, StudyPlannerService
from app.features.users.models import User
from app.infrastructure.database.session import get_db

router = APIRouter(prefix="/v1/planner", tags=["planner"])


def _get_planner_service(db: Session = Depends(get_db)) -> StudyPlannerService:
    """Construct StudyPlannerService for the request."""
    return StudyPlannerService(
        plan_repo=StudyPlanRepository(db=db),
        day_repo=StudyPlanDayRepository(db=db),
        mastery_repo=MasteryRepository(db=db),
        subtopic_repo=SubtopicRepository(db=db),
    )


def _get_readiness_service(db: Session = Depends(get_db)) -> ReadinessService:
    """Construct ReadinessService for the request."""
    return ReadinessService(
        mastery_repo=MasteryRepository(db=db),
        subtopic_repo=SubtopicRepository(db=db),
        db=db,
    )


@router.post("/plans", status_code=201, response_model=StudyPlanResponse)
def create_plan(
    payload: CreatePlanRequest,
    user: User = Depends(get_current_user),
    service: StudyPlannerService = Depends(_get_planner_service),
) -> StudyPlanResponse:
    """Create a new study plan."""
    return service.create_plan(
        user_id=user.id,
        target_exam_date=payload.target_exam_date,
        available_hours_per_day=payload.available_hours_per_day,
        target_score=payload.target_score,
    )


@router.get("/plans/me", response_model=StudyPlanResponse | None)
def get_active_plan(
    user: User = Depends(get_current_user),
    service: StudyPlannerService = Depends(_get_planner_service),
) -> StudyPlanResponse | None:
    """Get the user's active study plan."""
    return service.get_active_plan(user.id)


@router.get("/plans/me/today", response_model=list[PlanDayResponse])
def get_today_tasks(
    user: User = Depends(get_current_user),
    service: StudyPlannerService = Depends(_get_planner_service),
) -> list[PlanDayResponse]:
    """Get today's tasks from the active plan."""
    return service.get_today_tasks(user.id)


@router.post("/plans/me/tasks/{task_id}:complete")
def mark_task_complete(
    task_id: int,
    user: User = Depends(get_current_user),
    service: StudyPlannerService = Depends(_get_planner_service),
) -> dict[str, str]:
    """Mark a plan task as complete."""
    service.mark_task_complete(user.id, task_id)
    return {"status": "ok"}


@router.delete("/plans/me", status_code=204)
def abandon_plan(
    user: User = Depends(get_current_user),
    service: StudyPlannerService = Depends(_get_planner_service),
) -> None:
    """Abandon the current active plan."""
    service.abandon_plan(user.id)


@router.get("/readiness/me", response_model=ReadinessResponse)
def get_readiness(
    user: User = Depends(get_current_user),
    service: ReadinessService = Depends(_get_readiness_service),
) -> ReadinessResponse:
    """Get exam readiness prediction."""
    return service.get_readiness(user.id)
