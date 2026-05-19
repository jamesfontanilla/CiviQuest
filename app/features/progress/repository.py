"""Repository for the progress slice.

A single :class:`ProgressRepository` owns reads and writes for all three
progress tables. The class extends ``BaseRepository[LessonCompletion]``
because :class:`LessonCompletion` is the busy table — most operations
target it. ``UserTopicProgress`` and ``UserModuleProgress`` get their
own helper methods on the same class rather than separate
repository classes; the slice convention is "one ``repository.py`` per
feature" and these two tables share the user-scoped query shape with
LessonCompletion.

Key design choices:

- **Idempotent inserts.** ``mark_lesson_complete`` does not perform the
  existence check itself — the service layer is responsible for that.
  The repository only persists. This keeps the repository ORM-only per
  ``code-conventions.md`` and lets the service layer choose between
  "first completion" semantics (insert and award XP) vs "duplicate
  retry" semantics (return existing row).
- **``mark_topic_complete`` and ``mark_module_complete`` are upserts.**
  These are simpler one-shots — there is no XP-award decision riding
  on the existence check, so the repository owns the "lookup or
  insert" round trip. The service layer just calls them.
- **``is_lesson_complete_for_subtopic`` lives here despite being
  consumed by the quizzes slice (Req 6.1).** The natural home for the
  query is the slice that owns the underlying tables. The quiz slice
  injects this repository when it needs to gate quiz starts.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.features.content.models import Lesson
from app.features.progress.models import (
    LessonCompletion,
    UserModuleProgress,
    UserTopicProgress,
)
from app.infrastructure.repositories.base import BaseRepository


class ProgressRepository(BaseRepository[LessonCompletion]):
    """Persistence for lesson, topic, and module completion rows."""

    model = LessonCompletion

    def __init__(self, db: Session) -> None:
        super().__init__(db=db)

    # ------------------------------------------------------------------
    # LessonCompletion
    # ------------------------------------------------------------------

    def get_by_client_event_id(
        self, client_event_id: str
    ) -> LessonCompletion | None:
        """Idempotency lookup for offline sync (Req 20.3).

        Returns the existing row when a previous request with this
        ``client_event_id`` already landed; ``None`` otherwise. The
        column is UNIQUE so this is a single-row lookup.
        """
        stmt = select(LessonCompletion).where(
            LessonCompletion.client_event_id == client_event_id
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def get_lesson_completion(
        self, user_id: int, lesson_id: int
    ) -> LessonCompletion | None:
        """Lookup by ``(user_id, lesson_id)`` for first-completion checks.

        Used by the service layer to detect "first completion" for the
        XP award; the natural-key UNIQUE constraint guarantees at most
        one row.
        """
        stmt = select(LessonCompletion).where(
            LessonCompletion.user_id == user_id,
            LessonCompletion.lesson_id == lesson_id,
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def mark_lesson_complete(
        self,
        *,
        user_id: int,
        lesson_id: int,
        completed_at: datetime,
        client_event_id: str | None = None,
    ) -> LessonCompletion:
        """Insert a :class:`LessonCompletion` row.

        Caller is responsible for checking existence first
        (:meth:`get_lesson_completion` / :meth:`get_by_client_event_id`)
        — calling this on an already-completed (user, lesson) pair will
        raise :class:`sqlalchemy.exc.IntegrityError` from the UNIQUE
        constraint.
        """
        row = LessonCompletion(
            user_id=user_id,
            lesson_id=lesson_id,
            completed_at=completed_at,
            client_event_id=client_event_id,
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def is_lesson_complete_for_subtopic(
        self, user_id: int, subtopic_id: int
    ) -> bool:
        """Return True iff the user has completed the lesson for ``subtopic_id``.

        Used by the quiz-start gate (Req 6.1). Two-stage lookup:

        1. Resolve the lesson row keyed by ``subtopic_id`` (the
           ``lessons.subtopic_id`` column is UNIQUE).
        2. Check for a :class:`LessonCompletion` row keyed by
           ``(user_id, lesson.id)``.

        Both legs are single-row indexed lookups. Returns ``False`` when
        either leg misses; a missing lesson is treated as "not
        complete" so the quiz-start gate fails closed.
        """
        lesson_stmt = select(Lesson.id).where(Lesson.subtopic_id == subtopic_id)
        lesson_id = self.db.execute(lesson_stmt).scalar_one_or_none()
        if lesson_id is None:
            return False
        completion_stmt = select(LessonCompletion.id).where(
            LessonCompletion.user_id == user_id,
            LessonCompletion.lesson_id == lesson_id,
        )
        return self.db.execute(completion_stmt).scalar_one_or_none() is not None

    def list_completions_for_user(
        self, user_id: int
    ) -> list[LessonCompletion]:
        """Return every completion row for ``user_id``.

        Used by :meth:`ProgressService.get_snapshot` (Req 14.2). Ordered
        by ``completed_at`` ascending for deterministic snapshot output.
        """
        stmt = (
            select(LessonCompletion)
            .where(LessonCompletion.user_id == user_id)
            .order_by(LessonCompletion.completed_at, LessonCompletion.id)
        )
        return list(self.db.execute(stmt).scalars().all())

    # ------------------------------------------------------------------
    # UserTopicProgress / UserModuleProgress
    # ------------------------------------------------------------------

    def get_topic_progress(
        self, user_id: int, topic_id: int
    ) -> UserTopicProgress | None:
        stmt = select(UserTopicProgress).where(
            UserTopicProgress.user_id == user_id,
            UserTopicProgress.topic_id == topic_id,
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def get_module_progress(
        self, user_id: int, module_id: int
    ) -> UserModuleProgress | None:
        stmt = select(UserModuleProgress).where(
            UserModuleProgress.user_id == user_id,
            UserModuleProgress.module_id == module_id,
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def mark_topic_complete(
        self, user_id: int, topic_id: int, completed_at: datetime
    ) -> UserTopicProgress:
        """Idempotent upsert of a :class:`UserTopicProgress` row (Req 8.5)."""
        existing = self.get_topic_progress(user_id, topic_id)
        if existing is not None:
            return existing
        row = UserTopicProgress(
            user_id=user_id, topic_id=topic_id, completed_at=completed_at
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def mark_module_complete(
        self, user_id: int, module_id: int, completed_at: datetime
    ) -> UserModuleProgress:
        """Idempotent upsert of a :class:`UserModuleProgress` row (Req 9.4)."""
        existing = self.get_module_progress(user_id, module_id)
        if existing is not None:
            return existing
        row = UserModuleProgress(
            user_id=user_id, module_id=module_id, completed_at=completed_at
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row
