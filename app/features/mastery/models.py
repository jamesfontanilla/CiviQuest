"""SQLAlchemy ORM models for the mastery feature.

Owns the per-user, per-subtopic mastery tracking and spaced repetition
scheduling tables. These power the adaptive learning system that adjusts
difficulty and recommends review sessions based on SM-2 intervals.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base


class MasteryLevel(str, Enum):
    """Mastery progression levels based on mastery_score thresholds."""

    BEGINNER = "BEGINNER"
    FAMILIAR = "FAMILIAR"
    PROFICIENT = "PROFICIENT"
    ADVANCED = "ADVANCED"
    MASTERED = "MASTERED"


def mastery_level_from_score(score: float) -> MasteryLevel:
    """Determine mastery level from a score value (0.0 to 1.0)."""
    if score < 0.2:
        return MasteryLevel.BEGINNER
    if score < 0.5:
        return MasteryLevel.FAMILIAR
    if score < 0.75:
        return MasteryLevel.PROFICIENT
    if score < 0.9:
        return MasteryLevel.ADVANCED
    return MasteryLevel.MASTERED


class UserSubtopicMastery(Base):
    """Per-user, per-subtopic mastery tracking."""

    __tablename__ = "user_subtopic_mastery"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    subtopic_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("subtopics.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    mastery_level: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=MasteryLevel.BEGINNER.value,
        server_default=MasteryLevel.BEGINNER.value,
    )
    mastery_score: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0, server_default="0.0"
    )
    total_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    correct_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    avg_response_time_ms: Mapped[int | None] = mapped_column(
        Integer, nullable=True, default=None
    )
    last_practiced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
    confidence_score: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0, server_default="0.0"
    )
    retention_score: Mapped[float] = mapped_column(
        Float, nullable=False, default=1.0, server_default="1.0"
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
        UniqueConstraint("user_id", "subtopic_id", name="uq_user_subtopic_mastery"),
    )


class ReviewSchedule(Base):
    """Spaced repetition schedule per (user, subtopic)."""

    __tablename__ = "review_schedules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    subtopic_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("subtopics.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    next_review_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    interval_days: Mapped[float] = mapped_column(
        Float, nullable=False, default=1.0, server_default="1.0"
    )
    ease_factor: Mapped[float] = mapped_column(
        Float, nullable=False, default=2.5, server_default="2.5"
    )
    repetitions: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    last_reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
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
        UniqueConstraint("user_id", "subtopic_id", name="uq_review_schedule_user_subtopic"),
        Index("ix_review_schedules_user_next", "user_id", "next_review_at"),
    )
