"""Admin service: analytics aggregation, export/import orchestration.

Orchestrates admin operations across multiple feature repositories.
All admin actions log via Python logging with TODO for audit log (Task 18).
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.features.admin.algorithms.export import build_export
from app.features.admin.algorithms.import_validator import apply_import, validate_import
from app.features.admin.repository import AdminRepository
from app.features.admin.schemas import AnalyticsResponse, WeakSubtopic
from app.features.content.models import (
    Lesson,
    Module,
    Question,
    Subtopic,
    Topic,
)
from app.features.content.repository import (
    LessonRepository,
    ModuleRepository,
    QuestionRepository,
    SubtopicRepository,
    TopicRepository,
)
from app.features.content.schemas import QuestionCreate
from app.features.content.service import QuestionService
from app.features.progress.models import LessonCompletion, UserModuleProgress, UserTopicProgress
from app.features.quizzes.models import QuizAttempt
from app.features.users.models import Role, User
from app.features.users.repository import UserRepository

logger = logging.getLogger(__name__)


class AdminService:
    """Orchestrates admin operations (Req 15-17, 24)."""

    def __init__(
        self,
        *,
        db: Session,
        user_repo: UserRepository,
        admin_repo: AdminRepository,
        module_repo: ModuleRepository,
        topic_repo: TopicRepository,
        subtopic_repo: SubtopicRepository,
        lesson_repo: LessonRepository,
        question_repo: QuestionRepository,
    ) -> None:
        self._db = db
        self._user_repo = user_repo
        self._admin_repo = admin_repo
        self._module_repo = module_repo
        self._topic_repo = topic_repo
        self._subtopic_repo = subtopic_repo
        self._lesson_repo = lesson_repo
        self._question_repo = question_repo

    # --- User management (Task 17.1) ----------------------------------------

    def list_users(
        self,
        *,
        skip: int = 0,
        limit: int = 20,
        category: str | None = None,
        is_banned: bool | None = None,
        role: str | None = None,
    ) -> tuple[list[User], int]:
        """Paginated admin user list (Req 15.2)."""
        from app.features.users.models import Category, Role as RoleEnum

        cat = Category(category) if category else None
        r = RoleEnum(role) if role else None
        return self._user_repo.paginated_admin_list(
            skip=skip, limit=limit, category=cat, is_banned=is_banned, role=r
        )

    def patch_user(self, user_id: int, *, is_banned: bool | None = None, role: Role | None = None) -> User:
        """Ban toggle or role change (Req 15.3)."""
        user = self._user_repo.get(user_id)
        if user is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user_not_found")

        if is_banned is not None:
            user.is_banned = is_banned
        if role is not None:
            user.role = role.value

        self._db.commit()
        self._db.refresh(user)

        # TODO(Task 18): Write to audit_log table
        logging.info(
            "admin_user_patch: user_id=%d, is_banned=%s, role=%s",
            user_id, is_banned, role,
        )
        return user

    def delete_user(self, user_id: int) -> None:
        """Cascade-delete user (Req 15.4)."""
        user = self._user_repo.get(user_id)
        if user is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user_not_found")

        self._user_repo.delete_with_progress_cascade(user)

        # TODO(Task 18): Write to audit_log table
        logging.info("admin_user_delete: user_id=%d", user_id)

    # --- Content management (Task 17.2) -------------------------------------

    def create_module(self, payload: dict[str, Any]) -> Module:
        """Create a module (Req 16.1)."""
        module = Module(**payload)
        self._module_repo.create(module)
        logging.info("admin_module_create: id=%d", module.id)
        return module

    def update_module(self, module_id: int, payload: dict[str, Any]) -> Module:
        """Update a module."""
        module = self._module_repo.get(module_id)
        if module is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="module_not_found")
        for key, value in payload.items():
            setattr(module, key, value)
        self._db.commit()
        self._db.refresh(module)
        logging.info("admin_module_update: id=%d", module_id)
        return module

    def delete_module(self, module_id: int, *, force: bool = False) -> None:
        """Delete a module with force-flag check (Req 16.3)."""
        module = self._module_repo.get(module_id)
        if module is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="module_not_found")

        if not force and self._has_progress_for_module(module_id):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="progress_exists",
            )

        self._db.delete(module)
        self._db.commit()
        logging.info("admin_module_delete: id=%d, force=%s", module_id, force)

    def create_topic(self, payload: dict[str, Any]) -> Topic:
        """Create a topic (Req 16.1)."""
        # Validate parent module exists
        module = self._module_repo.get(payload.get("module_id"))
        if module is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid_module_id")
        topic = Topic(**payload)
        self._topic_repo.create(topic)
        logging.info("admin_topic_create: id=%d", topic.id)
        return topic

    def update_topic(self, topic_id: int, payload: dict[str, Any]) -> Topic:
        """Update a topic."""
        topic = self._topic_repo.get(topic_id)
        if topic is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="topic_not_found")
        for key, value in payload.items():
            setattr(topic, key, value)
        self._db.commit()
        self._db.refresh(topic)
        logging.info("admin_topic_update: id=%d", topic_id)
        return topic

    def delete_topic(self, topic_id: int, *, force: bool = False) -> None:
        """Delete a topic with force-flag check (Req 16.3)."""
        topic = self._topic_repo.get(topic_id)
        if topic is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="topic_not_found")

        if not force and self._has_progress_for_topic(topic_id):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="progress_exists",
            )

        self._db.delete(topic)
        self._db.commit()
        logging.info("admin_topic_delete: id=%d, force=%s", topic_id, force)

    def create_subtopic(self, payload: dict[str, Any]) -> Subtopic:
        """Create a subtopic (Req 16.1)."""
        topic = self._topic_repo.get(payload.get("topic_id"))
        if topic is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid_topic_id")
        subtopic = Subtopic(**payload)
        self._subtopic_repo.create(subtopic)
        logging.info("admin_subtopic_create: id=%d", subtopic.id)
        return subtopic

    def update_subtopic(self, subtopic_id: int, payload: dict[str, Any]) -> Subtopic:
        """Update a subtopic."""
        subtopic = self._subtopic_repo.get(subtopic_id)
        if subtopic is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="subtopic_not_found")
        for key, value in payload.items():
            setattr(subtopic, key, value)
        self._db.commit()
        self._db.refresh(subtopic)
        logging.info("admin_subtopic_update: id=%d", subtopic_id)
        return subtopic

    def delete_subtopic(self, subtopic_id: int, *, force: bool = False) -> None:
        """Delete a subtopic with force-flag check (Req 16.3)."""
        subtopic = self._subtopic_repo.get(subtopic_id)
        if subtopic is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="subtopic_not_found")

        if not force and self._has_progress_for_subtopic(subtopic_id):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="progress_exists",
            )

        self._db.delete(subtopic)
        self._db.commit()
        logging.info("admin_subtopic_delete: id=%d, force=%s", subtopic_id, force)

    def create_lesson(self, payload: dict[str, Any]) -> Lesson:
        """Create a lesson."""
        subtopic = self._subtopic_repo.get(payload.get("subtopic_id"))
        if subtopic is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid_subtopic_id")
        lesson = Lesson(**payload)
        self._lesson_repo.create(lesson)
        logging.info("admin_lesson_create: id=%d", lesson.id)
        return lesson

    def update_lesson(self, lesson_id: int, payload: dict[str, Any]) -> Lesson:
        """Update a lesson."""
        lesson = self._lesson_repo.get(lesson_id)
        if lesson is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="lesson_not_found")
        for key, value in payload.items():
            setattr(lesson, key, value)
        self._db.commit()
        self._db.refresh(lesson)
        logging.info("admin_lesson_update: id=%d", lesson_id)
        return lesson

    def delete_lesson(self, lesson_id: int, *, force: bool = False) -> None:
        """Delete a lesson with force-flag check."""
        lesson = self._lesson_repo.get(lesson_id)
        if lesson is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="lesson_not_found")

        if not force and self._has_progress_for_lesson(lesson_id):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="progress_exists",
            )

        self._db.delete(lesson)
        self._db.commit()
        logging.info("admin_lesson_delete: id=%d, force=%s", lesson_id, force)

    def create_question(self, payload: QuestionCreate) -> Question:
        """Create a question via QuestionService (Req 16.2)."""
        question_service = QuestionService(
            question_repo=self._question_repo,
            subtopic_repo=self._subtopic_repo,
            topic_repo=self._topic_repo,
            module_repo=self._module_repo,
        )
        question = question_service.create(payload)
        logging.info("admin_question_create: id=%d", question.id)
        return question

    def update_question(self, question_id: int, payload: dict[str, Any]) -> Question:
        """Update a question."""
        question = self._question_repo.get(question_id)
        if question is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="question_not_found")
        for key, value in payload.items():
            setattr(question, key, value)
        self._db.commit()
        self._db.refresh(question)
        logging.info("admin_question_update: id=%d", question_id)
        return question

    def delete_question(self, question_id: int, *, force: bool = False) -> None:
        """Delete a question."""
        question = self._question_repo.get(question_id)
        if question is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="question_not_found")
        self._db.delete(question)
        self._db.commit()
        logging.info("admin_question_delete: id=%d", question_id)

    def bulk_import_questions(self, questions_data: list[dict[str, Any]]) -> dict[str, Any]:
        """Bulk import questions (Req 16.4).

        Validates no duplicate question ids, then creates each via QuestionService.
        Returns {accepted: int, rejected: list}.
        """
        # Check for duplicate ids within the import batch
        seen_ids: set[int | None] = set()
        duplicates: list[dict[str, Any]] = []
        for i, q in enumerate(questions_data):
            qid = q.get("id")
            if qid is not None and qid in seen_ids:
                duplicates.append({"index": i, "reason": f"duplicate_id:{qid}"})
            if qid is not None:
                seen_ids.add(qid)

        if duplicates:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"message": "duplicate_question_ids", "duplicates": duplicates},
            )

        accepted = 0
        rejected: list[dict[str, Any]] = []

        question_service = QuestionService(
            question_repo=self._question_repo,
            subtopic_repo=self._subtopic_repo,
            topic_repo=self._topic_repo,
            module_repo=self._module_repo,
        )

        for i, q_data in enumerate(questions_data):
            try:
                payload = QuestionCreate(**q_data)
                question_service.create(payload)
                accepted += 1
            except HTTPException as e:
                rejected.append({"index": i, "reason": str(e.detail)})
            except Exception as e:
                rejected.append({"index": i, "reason": str(e)})

        logging.info("admin_bulk_import: accepted=%d, rejected=%d", accepted, len(rejected))
        return {"accepted": accepted, "rejected": rejected}

    # --- Mock-attempt reset and analytics (Task 17.3) -----------------------

    def delete_mock_attempts(self, user_id: int) -> int:
        """Delete all mock exam attempts for a user (Req 17.1)."""
        user = self._user_repo.get(user_id)
        if user is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user_not_found")

        count = self._admin_repo.delete_mock_attempts_for_user(user_id)
        logging.info("admin_mock_reset: user_id=%d, deleted=%d", user_id, count)
        return count

    def get_analytics(self) -> AnalyticsResponse:
        """Return platform analytics (Req 17.2)."""
        data = self._admin_repo.get_analytics()
        return AnalyticsResponse(
            total_users=data["total_users"],
            verified_users=data["verified_users"],
            banned_users=data["banned_users"],
            total_lessons_completed=data["total_lessons_completed"],
            total_quiz_attempts=data["total_quiz_attempts"],
            total_mock_attempts=data["total_mock_attempts"],
            mock_pass_rate=data["mock_pass_rate"],
            weakest_subtopics=[
                WeakSubtopic(**ws) for ws in data["weakest_subtopics"]
            ],
        )

    # --- Export and import (Task 17.4) --------------------------------------

    def export_data(self) -> dict[str, Any]:
        """Build export artifact (Req 17.3, 24.1)."""
        data = build_export(self._db)
        logging.info("admin_export: tables=%d", len(data))
        return data

    def import_data(self, data: dict[str, Any]) -> dict[str, Any]:
        """Validate and import data (Req 24.2, 24.3).

        Atomic: rollback on any error, commit on success.
        """
        errors = validate_import(data)
        if errors:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"message": "import_referential_integrity", "errors": errors},
            )

        try:
            apply_import(self._db, data)
            self._db.commit()
            logging.info("admin_import: success")
            return {"success": True, "errors": []}
        except Exception as e:
            self._db.rollback()
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"message": "import_failed", "errors": [{"type": "EXCEPTION", "detail": str(e)}]},
            )

    # --- Progress check helpers ---------------------------------------------

    def _has_progress_for_module(self, module_id: int) -> bool:
        """Check if any learner progress exists for a module."""
        from sqlalchemy import select

        stmt = select(UserModuleProgress).where(
            UserModuleProgress.module_id == module_id
        ).limit(1)
        return self._db.execute(stmt).scalar_one_or_none() is not None

    def _has_progress_for_topic(self, topic_id: int) -> bool:
        """Check if any learner progress exists for a topic."""
        from sqlalchemy import select

        stmt = select(UserTopicProgress).where(
            UserTopicProgress.topic_id == topic_id
        ).limit(1)
        return self._db.execute(stmt).scalar_one_or_none() is not None

    def _has_progress_for_subtopic(self, subtopic_id: int) -> bool:
        """Check if any learner progress exists for a subtopic."""
        from sqlalchemy import select

        # Check lesson completions for lessons under this subtopic
        lesson = self._lesson_repo.get_by_subtopic_id(subtopic_id)
        if lesson is None:
            return False
        stmt = select(LessonCompletion).where(
            LessonCompletion.lesson_id == lesson.id
        ).limit(1)
        return self._db.execute(stmt).scalar_one_or_none() is not None

    def _has_progress_for_lesson(self, lesson_id: int) -> bool:
        """Check if any learner progress exists for a lesson."""
        from sqlalchemy import select

        stmt = select(LessonCompletion).where(
            LessonCompletion.lesson_id == lesson_id
        ).limit(1)
        return self._db.execute(stmt).scalar_one_or_none() is not None
