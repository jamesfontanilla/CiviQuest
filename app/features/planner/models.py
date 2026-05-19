"""SQLAlchemy ORM models for the study planner feature.

Two tables:
- StudyPlan: the top-level plan with target date, hours, and score goal.
- StudyPlanDay: individual daily tasks within a plan.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base


_PLAN_STATUS_VALUES = "('ACTIVE', 'COMPLETED', 'ABANDONED')"
_ACTIVITY_TYPE_VALUES = "('lesson', 'quiz', 'review', 'mock_exam')"


class StudyPlan(Base):
    """A user's study plan with target exam date and goals."""

    __tablename__ = "study_plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    target_exam_date: Mapped[date] = mapped_column(Date, nullable=False)
    available_hours_per_day: Mapped[float] = mapped_column(
        Float, nullable=False
    )
    target_score: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="ACTIVE",
        server_default="ACTIVE",
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
            f"status IN {_PLAN_STATUS_VALUES}",
            name="ck_study_plans_status",
        ),
    )


class StudyPlanDay(Base):
    """A single task within a study plan for a specific day."""

    __tablename__ = "study_plan_days"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    plan_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("study_plans.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    plan_date: Mapped[date] = mapped_column(Date, nullable=False)
    subtopic_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("subtopics.id", ondelete="CASCADE"),
        nullable=False,
    )
    activity_type: Mapped[str] = mapped_column(String(16), nullable=False)
    estimated_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    completed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
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
            f"activity_type IN {_ACTIVITY_TYPE_VALUES}",
            name="ck_study_plan_days_activity_type",
        ),
        UniqueConstraint(
            "plan_id", "plan_date", "subtopic_id", "activity_type",
            name="uq_study_plan_days_unique_task",
        ),
    )
