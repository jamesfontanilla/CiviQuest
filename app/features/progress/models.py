"""SQLAlchemy ORM models for the progress slice.

Three tables live here per design ``Progress and attempts``:

- :class:`LessonCompletion` — append-only record of "user finished
  reading a lesson". Required by Req 6.2 (record completion event),
  Req 14.1 (persist before responding), and Req 20.3 (offline sync
  idempotency via the optional ``client_event_id``).
- :class:`UserTopicProgress` — derived row written when every subtopic
  quiz under a topic has been passed AND the topic quiz has been passed
  (Req 8.5). One row per ``(user_id, topic_id)`` pair.
- :class:`UserModuleProgress` — derived row written when every topic
  quiz under a module has been passed AND the module quiz has been
  passed (Req 9.4). One row per ``(user_id, module_id)`` pair.

Why three tables, not one polymorphic ``Progress``: the schema for each
level is genuinely different (lessons need ``client_event_id`` for
offline sync; topic/module rows do not), and the read patterns diverge
(snapshot reads lesson rows; the gate predicates read topic / module
rows). Three lean tables keep every read path a single indexed lookup.

``client_event_id`` design notes:
- Stored as a nullable ``String(64)`` column (UNIQUE). UUIDv4 fits in 36
  characters; 64 leaves headroom for client-chosen prefixes.
- The repository's idempotency lookup goes through this column. On
  conflict the existing row is returned (caller-side); we never raise
  IntegrityError into the service layer for an idempotent retry.

Foreign-key cascades match design — deleting a User cascades to every
progress row (Req 15.4 admin delete).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base


class LessonCompletion(Base):
    """One row per (user, lesson) completion event (Req 6.2, 14.1, 20.3).

    The UNIQUE constraint on ``(user_id, lesson_id)`` enforces "first
    completion only" semantics — the XP award for ``LESSON_FIRST_COMPLETE``
    in Task 9.3 keys off the absence of a row before insert. The repo
    layer detects existence first to avoid raising IntegrityError into
    the service path on a duplicate retry.
    """

    __tablename__ = "lesson_completions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    lesson_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("lessons.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    completed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    # Offline-sync idempotency key (Req 20.3). Stored UNIQUE so a retry
    # with the same client-generated id is detected at the SQL layer in
    # addition to the application-level check.
    client_event_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, unique=True
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
        UniqueConstraint(
            "user_id", "lesson_id", name="uq_lesson_completions_user_lesson"
        ),
    )


class UserTopicProgress(Base):
    """One row per (user, topic) topic-completion event (Req 8.5)."""

    __tablename__ = "user_topic_progress"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    topic_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("topics.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    completed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
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
        UniqueConstraint(
            "user_id", "topic_id", name="uq_user_topic_progress_user_topic"
        ),
    )


class UserModuleProgress(Base):
    """One row per (user, module) module-completion event (Req 9.4)."""

    __tablename__ = "user_module_progress"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    module_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("modules.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    completed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
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
        UniqueConstraint(
            "user_id", "module_id", name="uq_user_module_progress_user_module"
        ),
    )
