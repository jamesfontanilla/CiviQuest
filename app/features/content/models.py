"""SQLAlchemy ORM models for the content feature.

Owns the canonical content hierarchy (``Module`` -> ``Topic`` -> ``Subtopic``
-> ``Lesson`` and the question pool keyed off ``Subtopic``) plus the closed
enums consumed by the schemas, repositories, and services in this slice.

The shape mirrors the design's ``Table specifications`` -> ``Content`` block.
A few choices worth flagging up-front because they shape the rest of the
slice:

- ``Question`` carries denormalized ``topic_id``, ``module_id``, and
  ``category`` columns so quiz/mock-exam assembly stays a single indexed
  query (design Req 22.2). The cost is keeping those columns in sync at
  admin write; the service layer is the source of truth for that fan-out.
- ``options`` and ``content_json`` use SQLAlchemy's portable ``JSON`` type.
  On SQLite that stores text and the json1 extension parses it on read; on
  Postgres later it becomes ``JSONB`` with no model change.
- No ``relationship()`` declarations — bare FKs are enough for this slice.
  Adding ``relationship()`` invites N+1 surprises and isn't needed by the
  current repositories. We add them later, behind a clear use case.
- Closed-set columns (``category``, ``status``, ``difficulty``, ``qtype``,
  ``level_scope``) are constrained both at the Python layer (the enum
  classes below feed Pydantic schemas) and at the SQL layer
  (``CheckConstraint``) so a hand-rolled ``INSERT`` outside the service
  surface still can't introduce junk values.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base


class LessonStatus(str, Enum):
    """Lifecycle state for a lesson row (design ``lessons.status``)."""

    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    INCOMPLETE = "INCOMPLETE"


class QuestionType(str, Enum):
    """Closed set of question types (Req 18.1, glossary)."""

    MULTIPLE_CHOICE = "MULTIPLE_CHOICE"
    IDENTIFICATION = "IDENTIFICATION"
    LOGICAL_REASONING = "LOGICAL_REASONING"
    READING_COMPREHENSION = "READING_COMPREHENSION"
    PROBLEM_SOLVING = "PROBLEM_SOLVING"


class Difficulty(str, Enum):
    """Closed set of difficulty values (Req 18.1)."""

    EASY = "EASY"
    MEDIUM = "MEDIUM"
    HARD = "HARD"


class LevelScope(str, Enum):
    """Which quiz scope a question belongs to (subtopic/topic/module bank).

    Subtopic, topic, and module banks are independent pools per Open
    Question 4 in ``requirements.md``: a topic quiz draws from the topic's
    own 50-q pool, not the union of its subtopics' 20-q pools.
    """

    SUBTOPIC = "SUBTOPIC"
    TOPIC = "TOPIC"
    MODULE = "MODULE"


# Reusable CHECK constraint string fragments. Inline-ing the SQL strings is
# fine but factoring them avoids drift if we ever add a new value.
_CATEGORY_VALUES = "('PROFESSIONAL', 'SUB_PROFESSIONAL')"
_LESSON_STATUS_VALUES = "('DRAFT', 'PUBLISHED', 'INCOMPLETE')"
_QUESTION_TYPE_VALUES = (
    "('MULTIPLE_CHOICE', 'IDENTIFICATION', 'LOGICAL_REASONING', "
    "'READING_COMPREHENSION', 'PROBLEM_SOLVING')"
)
_DIFFICULTY_VALUES = "('EASY', 'MEDIUM', 'HARD')"
_LEVEL_SCOPE_VALUES = "('SUBTOPIC', 'TOPIC', 'MODULE')"


class Module(Base):
    """A top-level content unit scoped to a single CSE category (Req 5.1, 5.2)."""

    __tablename__ = "modules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_published: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="1"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        CheckConstraint(
            f"category IN {_CATEGORY_VALUES}", name="ck_modules_category"
        ),
        # Slug is already UNIQUE via the column; an explicit named index
        # keeps DDL legible and matches the design's "Index unique on slug".
        Index("ix_modules_slug_unique", "slug", unique=True),
    )


class Topic(Base):
    """A child of a ``Module``."""

    __tablename__ = "topics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    module_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("modules.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    slug: Mapped[str] = mapped_column(String(255), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint("module_id", "slug", name="uq_topics_module_slug"),
    )


class Subtopic(Base):
    """A child of a ``Topic``; the unit a Lesson and its quiz pool attach to."""

    __tablename__ = "subtopics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    topic_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("topics.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    slug: Mapped[str] = mapped_column(String(255), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint("topic_id", "slug", name="uq_subtopics_topic_slug"),
    )


class Lesson(Base):
    """One lesson per subtopic (Req 6.3, 6.4).

    ``content_json`` is validated by ``LessonContent`` before write. If the
    payload fails the schema, the admin write surface either rejects it
    outright (current MVP behaviour, see ``schemas.py``) or stores it with
    ``status=INCOMPLETE`` for legacy migrations; either way it is never
    served to learners.
    """

    __tablename__ = "lessons"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    subtopic_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("subtopics.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    content_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=LessonStatus.DRAFT.value,
        server_default=LessonStatus.DRAFT.value,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        CheckConstraint(
            f"status IN {_LESSON_STATUS_VALUES}", name="ck_lessons_status"
        ),
    )


class Question(Base):
    """A single graded item.

    Denormalized ``topic_id`` / ``module_id`` / ``category`` keep the
    quality-gate filter and assembly queries to a single indexed scan.
    The service layer is responsible for the fan-out at admin write so
    these never drift from the canonical hierarchy.
    """

    __tablename__ = "questions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    subtopic_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("subtopics.id", ondelete="CASCADE"),
        nullable=False,
    )
    topic_id: Mapped[int] = mapped_column(Integer, nullable=False)
    module_id: Mapped[int] = mapped_column(Integer, nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    level_scope: Mapped[str] = mapped_column(String(16), nullable=False)
    stem: Mapped[str] = mapped_column(Text, nullable=False)
    options: Mapped[list | None] = mapped_column(JSON, nullable=True)
    correct_answer: Mapped[str] = mapped_column(Text, nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    difficulty: Mapped[str] = mapped_column(String(16), nullable=False)
    qtype: Mapped[str] = mapped_column(String(32), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="1"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        CheckConstraint(
            f"category IN {_CATEGORY_VALUES}", name="ck_questions_category"
        ),
        CheckConstraint(
            f"level_scope IN {_LEVEL_SCOPE_VALUES}",
            name="ck_questions_level_scope",
        ),
        CheckConstraint(
            f"difficulty IN {_DIFFICULTY_VALUES}",
            name="ck_questions_difficulty",
        ),
        CheckConstraint(
            f"qtype IN {_QUESTION_TYPE_VALUES}", name="ck_questions_qtype"
        ),
        # Indexes per design Req 22.2 — every assembly hot path is covered.
        Index("ix_questions_subtopic_active", "subtopic_id", "is_active"),
        Index(
            "ix_questions_topic_active_scope",
            "topic_id",
            "is_active",
            "level_scope",
        ),
        Index(
            "ix_questions_module_active_scope",
            "module_id",
            "is_active",
            "level_scope",
        ),
        Index("ix_questions_category_active", "category", "is_active"),
    )


class QuestionRejectionLog(Base):
    """Append-only log of quality-gate failures (Req 18.4).

    The service writes a row here whenever an admin write is rejected by
    ``is_question_quality_passing`` so the failed rule is captured for the
    "deficient pool admin review" obligation in Req 7.2 / 18.4. The read
    path does not log — bad questions are simply hidden by the SQL gate.
    """

    __tablename__ = "question_rejection_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    question_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("questions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    rule: Mapped[str] = mapped_column(String(64), nullable=False)
    rejected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
