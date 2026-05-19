"""Repositories for content (modules, topics, subtopics, lessons, questions).

One module covers the slice's five related tables plus the rejection log
because the slice convention prefers a single ``repository.py`` per feature.
Each repository inherits ``BaseRepository`` for generic CRUD and adds the
feature-specific queries the service layer needs.

Quality-gate enforcement lives on ``QuestionRepository`` so every assembly
caller (``quizzes.algorithms.assembly``,
``mock_exams.algorithms.category_weighted_assembly``) goes through the same
filtered read. The SQL predicate handles type-agnostic rules; the Python
post-filter completes the JSON-aware rules — see
``algorithms/quality_gate.py`` for the rationale.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.features.content.algorithms.quality_gate import (
    is_question_quality_passing,
    valid_question_filter,
)
from app.features.content.models import (
    LevelScope,
    Lesson,
    Module,
    Question,
    QuestionRejectionLog,
    Subtopic,
    Topic,
)
from app.features.users.models import Category
from app.infrastructure.repositories.base import BaseRepository


class ModuleRepository(BaseRepository[Module]):
    """Reads and writes for ``Module`` rows."""

    model = Module

    def __init__(self, db: Session) -> None:
        super().__init__(db=db)

    def list_by_category(
        self, category: Category, *, skip: int = 0, limit: int = 20
    ) -> tuple[list[Module], int]:
        """Return ``(rows, total)`` for modules in ``category`` (Req 5.1, 5.2).

        ``total`` reflects the same filter as ``rows`` so the router can
        render pagination controls (Req 15.2). ``skip``/``limit`` bounds
        are enforced upstream by ``PaginationParams``.
        """
        rows_stmt = (
            select(Module)
            .where(Module.category == category.value)
            .order_by(Module.order_index, Module.id)
            .offset(skip)
            .limit(limit)
        )
        count_stmt = (
            select(func.count())
            .select_from(Module)
            .where(Module.category == category.value)
        )
        rows = list(self.db.execute(rows_stmt).scalars().all())
        total = int(self.db.execute(count_stmt).scalar_one())
        return rows, total


class TopicRepository(BaseRepository[Topic]):
    """Reads and writes for ``Topic`` rows."""

    model = Topic

    def __init__(self, db: Session) -> None:
        super().__init__(db=db)

    def list_by_module(self, module_id: int) -> list[Topic]:
        """Return all topics under ``module_id``, ordered by ``order_index``."""
        stmt = (
            select(Topic)
            .where(Topic.module_id == module_id)
            .order_by(Topic.order_index, Topic.id)
        )
        return list(self.db.execute(stmt).scalars().all())


class SubtopicRepository(BaseRepository[Subtopic]):
    """Reads and writes for ``Subtopic`` rows."""

    model = Subtopic

    def __init__(self, db: Session) -> None:
        super().__init__(db=db)

    def list_by_topic(self, topic_id: int) -> list[Subtopic]:
        """Return all subtopics under ``topic_id``, ordered by ``order_index``."""
        stmt = (
            select(Subtopic)
            .where(Subtopic.topic_id == topic_id)
            .order_by(Subtopic.order_index, Subtopic.id)
        )
        return list(self.db.execute(stmt).scalars().all())


class LessonRepository(BaseRepository[Lesson]):
    """Reads and writes for ``Lesson`` rows."""

    model = Lesson

    def __init__(self, db: Session) -> None:
        super().__init__(db=db)

    def get_by_subtopic_id(self, subtopic_id: int) -> Lesson | None:
        """Return the single lesson attached to ``subtopic_id``, if any.

        ``lessons.subtopic_id`` is UNIQUE so this is a single-row lookup;
        the design pins one lesson per subtopic.
        """
        stmt = select(Lesson).where(Lesson.subtopic_id == subtopic_id)
        return self.db.execute(stmt).scalar_one_or_none()


class QuestionRepository(BaseRepository[Question]):
    """Reads, writes, and quality-gated assembly reads for ``Question`` rows."""

    model = Question

    def __init__(self, db: Session) -> None:
        super().__init__(db=db)

    def list_active_passing_quality_gate(
        self,
        *,
        subtopic_id: int | None = None,
        topic_id: int | None = None,
        module_id: int | None = None,
        category: Category | None = None,
        level_scope: LevelScope | None = None,
    ) -> list[Question]:
        """Return active, quality-gated questions matching the scope filters.

        Two-stage filter:

        - SQL: ``valid_question_filter()`` handles is_active, non-empty
          stem/explanation/correct_answer, and closed-set ``difficulty``
          and ``qtype`` (Req 18.1 minus the JSON parts).
        - Python: ``is_question_quality_passing`` adds Req 18.2 (MC option
          count) and Req 18.3 (correct_answer in options).

        Read-side rejection is **not** logged. Req 18.4 logging is for
        admin write attempts; the read path simply hides bad questions.
        """
        stmt = select(Question).where(valid_question_filter())

        if subtopic_id is not None:
            stmt = stmt.where(Question.subtopic_id == subtopic_id)
        if topic_id is not None:
            stmt = stmt.where(Question.topic_id == topic_id)
        if module_id is not None:
            stmt = stmt.where(Question.module_id == module_id)
        if category is not None:
            stmt = stmt.where(Question.category == category.value)
        if level_scope is not None:
            stmt = stmt.where(Question.level_scope == level_scope.value)

        # Stable ordering keeps the Python post-filter deterministic for the
        # service tests; assemblers will shuffle later via their own seed.
        stmt = stmt.order_by(Question.id)

        candidates = list(self.db.execute(stmt).scalars().all())
        return [q for q in candidates if is_question_quality_passing(q)[0]]

    def log_rejection(self, question_id: int, rule: str) -> QuestionRejectionLog:
        """Append a rejection log row (Req 18.4).

        The rule string should come from the ``RULE_*`` constants in
        ``algorithms.quality_gate`` so the audit set stays closed.
        """
        log = QuestionRejectionLog(question_id=question_id, rule=rule)
        self.db.add(log)
        self.db.commit()
        self.db.refresh(log)
        return log
