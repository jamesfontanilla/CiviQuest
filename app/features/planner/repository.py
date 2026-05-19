"""Repository for study plans and plan days."""

from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.features.planner.models import StudyPlan, StudyPlanDay
from app.infrastructure.repositories.base import BaseRepository


class StudyPlanRepository(BaseRepository[StudyPlan]):
    """Data access for study plans."""

    model = StudyPlan

    def __init__(self, db: Session) -> None:
        super().__init__(db)

    def get_active_plan(self, user_id: int) -> StudyPlan | None:
        """Get the user's active study plan."""
        stmt = select(StudyPlan).where(
            StudyPlan.user_id == user_id,
            StudyPlan.status == "ACTIVE",
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def abandon_plan(self, plan: StudyPlan) -> StudyPlan:
        """Mark a plan as abandoned."""
        plan.status = "ABANDONED"
        self.db.commit()
        self.db.refresh(plan)
        return plan


class StudyPlanDayRepository(BaseRepository[StudyPlanDay]):
    """Data access for study plan days."""

    model = StudyPlanDay

    def __init__(self, db: Session) -> None:
        super().__init__(db)

    def get_days_for_plan(self, plan_id: int) -> list[StudyPlanDay]:
        """Get all days for a plan."""
        stmt = (
            select(StudyPlanDay)
            .where(StudyPlanDay.plan_id == plan_id)
            .order_by(StudyPlanDay.plan_date)
        )
        return list(self.db.execute(stmt).scalars().all())

    def get_today_tasks(self, plan_id: int, today: date) -> list[StudyPlanDay]:
        """Get tasks for today."""
        stmt = select(StudyPlanDay).where(
            StudyPlanDay.plan_id == plan_id,
            StudyPlanDay.plan_date == today,
        )
        return list(self.db.execute(stmt).scalars().all())

    def mark_complete(self, task: StudyPlanDay) -> StudyPlanDay:
        """Mark a task as completed."""
        from datetime import datetime, timezone

        task.completed = True
        task.completed_at = datetime.now(tz=timezone.utc)
        self.db.commit()
        self.db.refresh(task)
        return task

    def count_completed(self, plan_id: int) -> int:
        """Count completed tasks in a plan."""
        stmt = select(StudyPlanDay).where(
            StudyPlanDay.plan_id == plan_id,
            StudyPlanDay.completed == True,  # noqa: E712
        )
        return len(list(self.db.execute(stmt).scalars().all()))

    def count_total(self, plan_id: int) -> int:
        """Count total tasks in a plan."""
        stmt = select(StudyPlanDay).where(
            StudyPlanDay.plan_id == plan_id,
        )
        return len(list(self.db.execute(stmt).scalars().all()))
