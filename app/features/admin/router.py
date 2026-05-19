"""FastAPI router for admin endpoints.

Mounts under ``/v1/admin`` and exposes:
- User management: GET /users, PATCH /users/{id}, DELETE /users/{id}
- Content CRUD: modules, topics, subtopics, lessons, questions
- Bulk import: POST /questions:bulk-import
- Mock-attempt reset: DELETE /users/{id}/mock-exam-attempts
- Analytics: GET /analytics
- Export/Import: POST /exports, POST /imports
- Announcements: POST /announcements

All routes depend on ``require_admin`` (Req 15.1).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.common.deps import require_admin
from app.common.schemas.request import PaginationParams
from app.common.schemas.response import PaginatedResponse
from app.features.admin.repository import AdminRepository
from app.features.admin.schemas import (
    AdminLessonCreate,
    AdminLessonUpdate,
    AdminModuleCreate,
    AdminModuleUpdate,
    AdminQuestionCreate,
    AdminQuestionUpdate,
    AdminSubtopicCreate,
    AdminSubtopicUpdate,
    AdminTopicCreate,
    AdminTopicUpdate,
    AdminUserPatch,
    AdminUserResponse,
    AnalyticsResponse,
    AnnouncementCreate,
    AnnouncementResponse,
    BulkImportPayload,
    BulkImportResult,
    ExportResponse,
    ImportPayload,
    ImportResult,
)
from app.features.admin.service import AdminService
from app.features.announcements.models import Announcement
from app.features.announcements.repository import AnnouncementRepository
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
    QuestionCreate,
    QuestionResponse,
    SubtopicResponse,
    TopicResponse,
)
from app.features.users.models import User
from app.features.users.repository import UserRepository
from app.infrastructure.database.session import get_db

router = APIRouter(prefix="/v1/admin", tags=["admin"])


# --- Service factory --------------------------------------------------------


def get_admin_service(db: Session = Depends(get_db)) -> AdminService:
    """Construct AdminService for the request."""
    return AdminService(
        db=db,
        user_repo=UserRepository(db=db),
        admin_repo=AdminRepository(db=db),
        module_repo=ModuleRepository(db=db),
        topic_repo=TopicRepository(db=db),
        subtopic_repo=SubtopicRepository(db=db),
        lesson_repo=LessonRepository(db=db),
        question_repo=QuestionRepository(db=db),
    )


# --- User management (Task 17.1) -------------------------------------------


@router.get("/users", response_model=PaginatedResponse[AdminUserResponse])
def list_users(
    pagination: PaginationParams = Depends(),
    category: str | None = Query(default=None),
    is_banned: bool | None = Query(default=None),
    role: str | None = Query(default=None),
    admin: User = Depends(require_admin),
    service: AdminService = Depends(get_admin_service),
) -> PaginatedResponse[AdminUserResponse]:
    """Paginated admin user list (Req 15.2)."""
    rows, total = service.list_users(
        skip=pagination.skip,
        limit=pagination.limit,
        category=category,
        is_banned=is_banned,
        role=role,
    )
    items = [AdminUserResponse.model_validate(row) for row in rows]
    return PaginatedResponse[AdminUserResponse](
        items=items, total=total, skip=pagination.skip, limit=pagination.limit
    )


@router.patch("/users/{user_id}", response_model=AdminUserResponse)
def patch_user(
    user_id: int,
    payload: AdminUserPatch,
    admin: User = Depends(require_admin),
    service: AdminService = Depends(get_admin_service),
) -> AdminUserResponse:
    """Ban toggle or role change (Req 15.3)."""
    user = service.patch_user(user_id, is_banned=payload.is_banned, role=payload.role)
    return AdminUserResponse.model_validate(user)


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(
    user_id: int,
    admin: User = Depends(require_admin),
    service: AdminService = Depends(get_admin_service),
) -> None:
    """Cascade-delete user (Req 15.4)."""
    service.delete_user(user_id)


# --- Content management (Task 17.2) ----------------------------------------

# Modules


@router.post("/modules", status_code=status.HTTP_201_CREATED, response_model=ModuleResponse)
def create_module(
    payload: AdminModuleCreate,
    admin: User = Depends(require_admin),
    service: AdminService = Depends(get_admin_service),
) -> ModuleResponse:
    """Create a module (Req 16.1)."""
    data = payload.model_dump()
    data["category"] = data["category"].value
    module = service.create_module(data)
    return ModuleResponse.model_validate(module)


@router.patch("/modules/{module_id}", response_model=ModuleResponse)
def update_module(
    module_id: int,
    payload: AdminModuleUpdate,
    admin: User = Depends(require_admin),
    service: AdminService = Depends(get_admin_service),
) -> ModuleResponse:
    """Update a module."""
    data = payload.model_dump(exclude_unset=True)
    if "category" in data and data["category"] is not None:
        data["category"] = data["category"].value
    module = service.update_module(module_id, data)
    return ModuleResponse.model_validate(module)


@router.delete("/modules/{module_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_module(
    module_id: int,
    force: bool = Query(default=False),
    admin: User = Depends(require_admin),
    service: AdminService = Depends(get_admin_service),
) -> None:
    """Delete a module (Req 16.3)."""
    service.delete_module(module_id, force=force)


# Topics


@router.post("/topics", status_code=status.HTTP_201_CREATED, response_model=TopicResponse)
def create_topic(
    payload: AdminTopicCreate,
    admin: User = Depends(require_admin),
    service: AdminService = Depends(get_admin_service),
) -> TopicResponse:
    """Create a topic (Req 16.1)."""
    topic = service.create_topic(payload.model_dump())
    return TopicResponse.model_validate(topic)


@router.patch("/topics/{topic_id}", response_model=TopicResponse)
def update_topic(
    topic_id: int,
    payload: AdminTopicUpdate,
    admin: User = Depends(require_admin),
    service: AdminService = Depends(get_admin_service),
) -> TopicResponse:
    """Update a topic."""
    data = payload.model_dump(exclude_unset=True)
    topic = service.update_topic(topic_id, data)
    return TopicResponse.model_validate(topic)


@router.delete("/topics/{topic_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_topic(
    topic_id: int,
    force: bool = Query(default=False),
    admin: User = Depends(require_admin),
    service: AdminService = Depends(get_admin_service),
) -> None:
    """Delete a topic (Req 16.3)."""
    service.delete_topic(topic_id, force=force)


# Subtopics


@router.post("/subtopics", status_code=status.HTTP_201_CREATED, response_model=SubtopicResponse)
def create_subtopic(
    payload: AdminSubtopicCreate,
    admin: User = Depends(require_admin),
    service: AdminService = Depends(get_admin_service),
) -> SubtopicResponse:
    """Create a subtopic (Req 16.1)."""
    subtopic = service.create_subtopic(payload.model_dump())
    return SubtopicResponse.model_validate(subtopic)


@router.patch("/subtopics/{subtopic_id}", response_model=SubtopicResponse)
def update_subtopic(
    subtopic_id: int,
    payload: AdminSubtopicUpdate,
    admin: User = Depends(require_admin),
    service: AdminService = Depends(get_admin_service),
) -> SubtopicResponse:
    """Update a subtopic."""
    data = payload.model_dump(exclude_unset=True)
    subtopic = service.update_subtopic(subtopic_id, data)
    return SubtopicResponse.model_validate(subtopic)


@router.delete("/subtopics/{subtopic_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_subtopic(
    subtopic_id: int,
    force: bool = Query(default=False),
    admin: User = Depends(require_admin),
    service: AdminService = Depends(get_admin_service),
) -> None:
    """Delete a subtopic (Req 16.3)."""
    service.delete_subtopic(subtopic_id, force=force)


# Lessons


@router.post("/lessons", status_code=status.HTTP_201_CREATED, response_model=LessonResponse)
def create_lesson(
    payload: AdminLessonCreate,
    admin: User = Depends(require_admin),
    service: AdminService = Depends(get_admin_service),
) -> LessonResponse:
    """Create a lesson."""
    lesson = service.create_lesson(payload.model_dump())
    return LessonResponse.model_validate(lesson)


@router.patch("/lessons/{lesson_id}", response_model=LessonResponse)
def update_lesson(
    lesson_id: int,
    payload: AdminLessonUpdate,
    admin: User = Depends(require_admin),
    service: AdminService = Depends(get_admin_service),
) -> LessonResponse:
    """Update a lesson."""
    data = payload.model_dump(exclude_unset=True)
    lesson = service.update_lesson(lesson_id, data)
    return LessonResponse.model_validate(lesson)


@router.delete("/lessons/{lesson_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_lesson(
    lesson_id: int,
    force: bool = Query(default=False),
    admin: User = Depends(require_admin),
    service: AdminService = Depends(get_admin_service),
) -> None:
    """Delete a lesson."""
    service.delete_lesson(lesson_id, force=force)


# Questions


@router.post("/questions", status_code=status.HTTP_201_CREATED, response_model=QuestionResponse)
def create_question(
    payload: AdminQuestionCreate,
    admin: User = Depends(require_admin),
    service: AdminService = Depends(get_admin_service),
) -> QuestionResponse:
    """Create a question (Req 16.2)."""
    question_create = QuestionCreate(**payload.model_dump())
    question = service.create_question(question_create)
    return QuestionResponse.model_validate(question)


@router.patch("/questions/{question_id}", response_model=QuestionResponse)
def update_question(
    question_id: int,
    payload: AdminQuestionUpdate,
    admin: User = Depends(require_admin),
    service: AdminService = Depends(get_admin_service),
) -> QuestionResponse:
    """Update a question."""
    data = payload.model_dump(exclude_unset=True)
    question = service.update_question(question_id, data)
    return QuestionResponse.model_validate(question)


@router.delete("/questions/{question_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_question(
    question_id: int,
    force: bool = Query(default=False),
    admin: User = Depends(require_admin),
    service: AdminService = Depends(get_admin_service),
) -> None:
    """Delete a question."""
    service.delete_question(question_id, force=force)


# Bulk import


@router.post("/questions:bulk-import", response_model=BulkImportResult)
def bulk_import_questions(
    payload: BulkImportPayload,
    admin: User = Depends(require_admin),
    service: AdminService = Depends(get_admin_service),
) -> BulkImportResult:
    """Bulk import questions (Req 16.4)."""
    questions_data = [q.model_dump() for q in payload.questions]
    result = service.bulk_import_questions(questions_data)
    return BulkImportResult(**result)


# --- Mock-attempt reset and analytics (Task 17.3) ---------------------------


@router.delete(
    "/users/{user_id}/mock-exam-attempts",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_mock_attempts(
    user_id: int,
    admin: User = Depends(require_admin),
    service: AdminService = Depends(get_admin_service),
) -> None:
    """Delete all mock exam attempts for a user (Req 17.1)."""
    service.delete_mock_attempts(user_id)


@router.get("/analytics", response_model=AnalyticsResponse)
def get_analytics(
    admin: User = Depends(require_admin),
    service: AdminService = Depends(get_admin_service),
) -> AnalyticsResponse:
    """Platform analytics (Req 17.2)."""
    return service.get_analytics()


# --- Export and import (Task 17.4) ------------------------------------------


@router.post("/exports", status_code=status.HTTP_201_CREATED)
def export_data(
    admin: User = Depends(require_admin),
    service: AdminService = Depends(get_admin_service),
) -> dict[str, Any]:
    """Build export artifact (Req 17.3, 24.1)."""
    return service.export_data()


@router.post("/imports")
def import_data(
    payload: ImportPayload,
    admin: User = Depends(require_admin),
    service: AdminService = Depends(get_admin_service),
) -> ImportResult:
    """Validate and import data (Req 24.2, 24.3)."""
    result = service.import_data(payload.data)
    return ImportResult(**result)


# --- Announcements (Task 17.6) ---------------------------------------------


@router.post("/announcements", status_code=status.HTTP_201_CREATED, response_model=AnnouncementResponse)
def create_announcement(
    payload: AnnouncementCreate,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> AnnouncementResponse:
    """Create an announcement (Req 17.4)."""
    repo = AnnouncementRepository(db=db)
    announcement = repo.create_announcement(
        title=payload.title,
        body=payload.body,
        audience_filter=payload.audience_filter,
        expires_at=payload.expires_at,
        created_by=admin.id,
    )
    return AnnouncementResponse.model_validate(announcement)
