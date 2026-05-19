"""Pydantic schemas for admin endpoints (analytics, export, import, user patch).

Covers:
- AdminUserPatch: ban toggle and role change (Req 15.3, Task 17.1)
- BulkImportResult: accepted/rejected counts for question import (Req 16.4)
- AnalyticsResponse: aggregated platform metrics (Req 17.2)
- AdminUserResponse: admin-facing user projection (Req 15.2)
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.features.content.models import (
    Difficulty,
    LessonStatus,
    LevelScope,
    QuestionType,
)
from app.features.users.models import AccountState, Category, Role


# --- User management --------------------------------------------------------


class AdminUserPatch(BaseModel):
    """PATCH payload for admin user updates (ban toggle, role change)."""

    is_banned: bool | None = None
    role: Role | None = None


class AdminUserResponse(BaseModel):
    """Admin-facing user projection (Req 15.2)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    display_name: str
    category: str
    role: str
    account_state: str
    is_banned: bool
    created_at: datetime


# --- Content management -----------------------------------------------------


class AdminModuleCreate(BaseModel):
    """Admin payload for creating a module."""

    category: Category
    slug: str = Field(min_length=1, max_length=255)
    title: str = Field(min_length=1, max_length=255)
    order_index: int = Field(default=0, ge=0)
    is_published: bool = True


class AdminModuleUpdate(BaseModel):
    """Partial update for a module."""

    category: Category | None = None
    slug: str | None = Field(default=None, min_length=1, max_length=255)
    title: str | None = Field(default=None, min_length=1, max_length=255)
    order_index: int | None = Field(default=None, ge=0)
    is_published: bool | None = None


class AdminTopicCreate(BaseModel):
    """Admin payload for creating a topic."""

    module_id: int
    slug: str = Field(min_length=1, max_length=255)
    title: str = Field(min_length=1, max_length=255)
    order_index: int = Field(default=0, ge=0)


class AdminTopicUpdate(BaseModel):
    """Partial update for a topic."""

    slug: str | None = Field(default=None, min_length=1, max_length=255)
    title: str | None = Field(default=None, min_length=1, max_length=255)
    order_index: int | None = Field(default=None, ge=0)


class AdminSubtopicCreate(BaseModel):
    """Admin payload for creating a subtopic."""

    topic_id: int
    slug: str = Field(min_length=1, max_length=255)
    title: str = Field(min_length=1, max_length=255)
    order_index: int = Field(default=0, ge=0)


class AdminSubtopicUpdate(BaseModel):
    """Partial update for a subtopic."""

    slug: str | None = Field(default=None, min_length=1, max_length=255)
    title: str | None = Field(default=None, min_length=1, max_length=255)
    order_index: int | None = Field(default=None, ge=0)


class AdminLessonCreate(BaseModel):
    """Admin payload for creating a lesson."""

    subtopic_id: int
    content_json: dict[str, Any]
    status: LessonStatus = LessonStatus.DRAFT


class AdminLessonUpdate(BaseModel):
    """Partial update for a lesson."""

    content_json: dict[str, Any] | None = None
    status: LessonStatus | None = None


class AdminQuestionCreate(BaseModel):
    """Admin payload for creating a question (delegates to QuestionCreate)."""

    subtopic_id: int
    level_scope: LevelScope
    stem: str = Field(min_length=1)
    options: list[str] | None = None
    correct_answer: str = Field(min_length=1)
    explanation: str = Field(min_length=1)
    difficulty: Difficulty
    qtype: QuestionType


class AdminQuestionUpdate(BaseModel):
    """Partial update for a question."""

    level_scope: LevelScope | None = None
    stem: str | None = Field(default=None, min_length=1)
    options: list[str] | None = None
    correct_answer: str | None = Field(default=None, min_length=1)
    explanation: str | None = Field(default=None, min_length=1)
    difficulty: Difficulty | None = None
    qtype: QuestionType | None = None
    is_active: bool | None = None


class BulkImportQuestion(BaseModel):
    """Single question in a bulk import payload."""

    id: int | None = None
    subtopic_id: int
    level_scope: LevelScope
    stem: str = Field(min_length=1)
    options: list[str] | None = None
    correct_answer: str = Field(min_length=1)
    explanation: str = Field(min_length=1)
    difficulty: Difficulty
    qtype: QuestionType


class BulkImportPayload(BaseModel):
    """Payload for POST /v1/admin/questions:bulk-import."""

    questions: list[BulkImportQuestion]


class BulkImportResult(BaseModel):
    """Response for bulk import (Req 16.4)."""

    accepted: int
    rejected: list[dict[str, Any]]


# --- Analytics --------------------------------------------------------------


class WeakSubtopic(BaseModel):
    """A subtopic with its average quiz score."""

    subtopic_id: int
    title: str
    avg_score: float


class AnalyticsResponse(BaseModel):
    """Platform analytics (Req 17.2)."""

    total_users: int
    verified_users: int
    banned_users: int
    total_lessons_completed: int
    total_quiz_attempts: int
    total_mock_attempts: int
    mock_pass_rate: float
    weakest_subtopics: list[WeakSubtopic]


# --- Export / Import --------------------------------------------------------


class ExportResponse(BaseModel):
    """Wrapper for the export artifact."""

    data: dict[str, Any]


class ImportPayload(BaseModel):
    """Payload for POST /v1/admin/imports."""

    data: dict[str, Any]


class ImportResult(BaseModel):
    """Response for import."""

    success: bool
    errors: list[dict[str, Any]] = Field(default_factory=list)


# --- Announcements ----------------------------------------------------------


class AnnouncementCreate(BaseModel):
    """Admin payload for creating an announcement (Req 17.4)."""

    title: str = Field(min_length=1, max_length=255)
    body: str = Field(min_length=1)
    audience_filter: dict[str, Any] | None = None
    expires_at: datetime | None = None


class AnnouncementResponse(BaseModel):
    """Read-side projection of an announcement."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    body: str
    audience_filter: dict[str, Any] | None
    expires_at: datetime | None
    created_by: int
    created_at: datetime
