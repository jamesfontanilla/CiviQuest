"""FastAPI router for learner-facing content reads.

Mounts under ``/v1`` and exposes the read surface for modules / topics /
subtopics / lessons. Admin write routes live under ``/v1/admin/...`` and
land in Task 17.2 — keeping admin and learner concerns on different
prefixes lets each set of routes pick the dependency stack it needs
(``require_admin`` versus ``require_no_active_mock``) without the other
side carrying dead deps.

Per ``code-conventions.md`` the route handlers are thin: each one takes a
service via ``Depends(...)``, performs no business logic, and returns the
result. The factory functions resolve the dependency graph exactly once
per request — composing :class:`ModuleService` into the topic / subtopic /
lesson services so the category-isolation policy lives in one place.

Mock-exam guard contract (Req 19.1):
    Every read route here depends on ``require_no_active_mock``. Until
    Task 12.1 lands the dependency is a no-op pass-through; once the
    mock-exam slice exists, an in-progress attempt will surface as 409
    ``exam_in_progress`` from these same routes with no router change.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.common.deps import require_no_active_mock
from app.common.schemas.request import PaginationParams
from app.common.schemas.response import PaginatedResponse
from app.features.content.repository import (
    LessonRepository,
    ModuleRepository,
    QuestionRepository,
    SubtopicRepository,
    TopicRepository,
)
from app.features.content.schemas import (
    LessonResponse,
    ModuleResponse,
    SubtopicResponse,
    TopicResponse,
)
from app.features.content.service import (
    LessonService,
    ModuleService,
    QuestionService,
    SubtopicService,
    TopicService,
)
from app.features.users.models import User
from app.infrastructure.database.session import get_db


router = APIRouter(prefix="/v1", tags=["content"])


# --- Service factories ------------------------------------------------------
#
# Each factory hangs off ``Depends(get_db)`` so a single ``Session`` is shared
# across the request. The topic / subtopic / lesson services receive a
# pre-built :class:`ModuleService` so the category-isolation policy is
# uniform — modifying ``ModuleService.get_for_user`` flows automatically
# through every dependent service.


def get_module_service(db: Session = Depends(get_db)) -> ModuleService:
    """Construct :class:`ModuleService` for the request."""
    return ModuleService(module_repo=ModuleRepository(db=db))


def get_topic_service(
    db: Session = Depends(get_db),
    module_service: ModuleService = Depends(get_module_service),
) -> TopicService:
    """Construct :class:`TopicService`, reusing the shared module service."""
    return TopicService(
        topic_repo=TopicRepository(db=db),
        module_service=module_service,
    )


def get_subtopic_service(
    db: Session = Depends(get_db),
    module_service: ModuleService = Depends(get_module_service),
) -> SubtopicService:
    """Construct :class:`SubtopicService`, reusing the shared module service."""
    return SubtopicService(
        subtopic_repo=SubtopicRepository(db=db),
        topic_repo=TopicRepository(db=db),
        module_service=module_service,
    )


def get_lesson_service(
    db: Session = Depends(get_db),
    module_service: ModuleService = Depends(get_module_service),
) -> LessonService:
    """Construct :class:`LessonService`, reusing the shared module service."""
    return LessonService(
        lesson_repo=LessonRepository(db=db),
        subtopic_repo=SubtopicRepository(db=db),
        topic_repo=TopicRepository(db=db),
        module_service=module_service,
    )


def get_question_service(db: Session = Depends(get_db)) -> QuestionService:
    """Construct :class:`QuestionService` for admin write paths.

    Not wired to a learner-facing route in this slice; admin routes in
    Task 17.2 will mount this factory under ``/v1/admin``.
    """
    return QuestionService(
        question_repo=QuestionRepository(db=db),
        subtopic_repo=SubtopicRepository(db=db),
        topic_repo=TopicRepository(db=db),
        module_repo=ModuleRepository(db=db),
    )


# --- Routes -----------------------------------------------------------------


@router.get(
    "/modules",
    response_model=PaginatedResponse[ModuleResponse],
)
def list_modules(
    pagination: PaginationParams = Depends(),
    user: User = Depends(require_no_active_mock),
    service: ModuleService = Depends(get_module_service),
) -> PaginatedResponse[ModuleResponse]:
    """Paginated module list filtered by the caller's category (Req 5.1, 5.2)."""
    rows, total = service.list_for_user(
        user, skip=pagination.skip, limit=pagination.limit
    )
    # Pydantic 2 with ``from_attributes=True`` validates ORM rows directly
    # when wrapped in a generic envelope. Building each ``ModuleResponse``
    # eagerly here avoids relying on FastAPI's ``response_model`` to perform
    # the ORM -> Pydantic conversion through the generic wrapper, which is
    # finicky in some pydantic versions.
    items = [ModuleResponse.model_validate(row) for row in rows]
    return PaginatedResponse[ModuleResponse](
        items=items, total=total, skip=pagination.skip, limit=pagination.limit
    )


@router.get("/modules/{module_id}", response_model=ModuleResponse)
def get_module(
    module_id: int,
    user: User = Depends(require_no_active_mock),
    service: ModuleService = Depends(get_module_service),
):
    """Single module by id; 403 on category mismatch or unknown id (Req 5.3)."""
    return service.get_for_user(user, module_id)


@router.get(
    "/modules/{module_id}/topics",
    response_model=list[TopicResponse],
)
def list_topics(
    module_id: int,
    user: User = Depends(require_no_active_mock),
    service: TopicService = Depends(get_topic_service),
):
    """Topics under a module; gated by the module's category isolation."""
    return service.list_for_user(user, module_id)


@router.get(
    "/topics/{topic_id}/subtopics",
    response_model=list[SubtopicResponse],
)
def list_subtopics(
    topic_id: int,
    user: User = Depends(require_no_active_mock),
    service: SubtopicService = Depends(get_subtopic_service),
):
    """Subtopics under a topic; walks topic -> module for the category check."""
    return service.list_for_user(user, topic_id)


@router.get(
    "/subtopics/{subtopic_id}/lesson",
    response_model=LessonResponse,
)
def get_lesson(
    subtopic_id: int,
    user: User = Depends(require_no_active_mock),
    service: LessonService = Depends(get_lesson_service),
):
    """Published lesson for a subtopic; INCOMPLETE/DRAFT/missing -> 403 (Req 6.4)."""
    return service.get_for_user(user, subtopic_id)
