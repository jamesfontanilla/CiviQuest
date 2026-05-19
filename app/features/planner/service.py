"""Business logic for the study planner and readiness predictor."""

from __future__ import annotations

from datetime import date, datetime, timezone

from fastapi import HTTPException, status

from app.features.content.repository import SubtopicRepository
from app.features.mastery.repository import MasteryRepository
from app.features.planner.algorithms.plan_generator import (
    PlanDay,
    SubtopicMasteryInput,
    generate_study_plan,
)
from app.features.planner.algorithms.readiness_predictor import (
    MasteryInput,
    ReadinessReport,
    predict_readiness,
)
from app.features.planner.models import StudyPlan, StudyPlanDay
from app.features.planner.repository import (
    StudyPlanDayRepository,
    StudyPlanRepository,
)
from app.features.planner.schemas import (
    PlanDayResponse,
    ReadinessResponse,
    StudyPlanResponse,
)


class StudyPlannerService:
    """Orchestrates study plan creation and management."""

    def __init__(
        self,
        *,
        plan_repo: StudyPlanRepository,
        day_repo: StudyPlanDayRepository,
        mastery_repo: MasteryRepository,
        subtopic_repo: SubtopicRepository,
    ) -> None:
        self._plan_repo = plan_repo
        self._day_repo = day_repo
        self._mastery_repo = mastery_repo
        self._subtopic_repo = subtopic_repo

    def create_plan(
        self,
        *,
        user_id: int,
        target_exam_date: date,
        available_hours_per_day: float,
        target_score: float,
    ) -> StudyPlanResponse:
        """Create a new study plan, abandoning any existing active plan."""
        now = date.today()

        if target_exam_date <= now:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Target exam date must be in the future",
            )

        # Abandon existing active plan
        existing = self._plan_repo.get_active_plan(user_id)
        if existing:
            self._plan_repo.abandon_plan(existing)

        # Get mastery data and all subtopics
        mastery_rows = list(self._mastery_repo.list_by_user(user_id))
        mastery_inputs = [
            SubtopicMasteryInput(
                subtopic_id=m.subtopic_id,
                mastery_score=m.mastery_score,
            )
            for m in mastery_rows
        ]

        all_subtopics = list(self._subtopic_repo.list(skip=0, limit=1000))
        all_subtopic_ids = [s.id for s in all_subtopics]

        # Generate plan days
        plan_days = generate_study_plan(
            target_exam_date=target_exam_date,
            available_hours_per_day=available_hours_per_day,
            target_score=target_score,
            mastery_data=mastery_inputs,
            all_subtopic_ids=all_subtopic_ids,
            now=now,
        )

        # Persist plan
        plan = StudyPlan(
            user_id=user_id,
            target_exam_date=target_exam_date,
            available_hours_per_day=available_hours_per_day,
            target_score=target_score,
            status="ACTIVE",
        )
        plan = self._plan_repo.create(plan)

        # Persist plan days
        for pd in plan_days:
            day = StudyPlanDay(
                plan_id=plan.id,
                plan_date=pd.plan_date,
                subtopic_id=pd.subtopic_id,
                activity_type=pd.activity_type,
                estimated_minutes=pd.estimated_minutes,
            )
            self._day_repo.create(day)

        return self._to_plan_response(plan)

    def get_active_plan(self, user_id: int) -> StudyPlanResponse | None:
        """Get the user's active study plan."""
        plan = self._plan_repo.get_active_plan(user_id)
        if plan is None:
            return None
        return self._to_plan_response(plan)

    def get_today_tasks(self, user_id: int) -> list[PlanDayResponse]:
        """Get today's tasks for the user's active plan."""
        plan = self._plan_repo.get_active_plan(user_id)
        if plan is None:
            return []

        today = date.today()
        tasks = self._day_repo.get_today_tasks(plan.id, today)
        return [self._to_day_response(t) for t in tasks]

    def mark_task_complete(self, user_id: int, task_id: int) -> None:
        """Mark a plan task as complete."""
        plan = self._plan_repo.get_active_plan(user_id)
        if plan is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No active plan found",
            )

        task = self._day_repo.get(task_id)
        if task is None or task.plan_id != plan.id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Task not found",
            )

        self._day_repo.mark_complete(task)

    def abandon_plan(self, user_id: int) -> None:
        """Abandon the user's active plan."""
        plan = self._plan_repo.get_active_plan(user_id)
        if plan is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No active plan found",
            )
        self._plan_repo.abandon_plan(plan)

    def _to_plan_response(self, plan: StudyPlan) -> StudyPlanResponse:
        """Convert a plan to response schema."""
        today = date.today()
        total_days = (plan.target_exam_date - today).days
        days_remaining = max(0, total_days)

        total_tasks = self._day_repo.count_total(plan.id)
        completed_tasks = self._day_repo.count_completed(plan.id)
        completion_pct = (
            (completed_tasks / total_tasks * 100.0) if total_tasks > 0 else 0.0
        )

        return StudyPlanResponse(
            id=plan.id,
            target_exam_date=plan.target_exam_date,
            available_hours_per_day=plan.available_hours_per_day,
            target_score=plan.target_score,
            status=plan.status,
            total_days=max(0, total_days),
            days_remaining=days_remaining,
            completion_percentage=round(completion_pct, 1),
        )

    def _to_day_response(self, task: StudyPlanDay) -> PlanDayResponse:
        """Convert a plan day to response schema."""
        subtopic = self._subtopic_repo.get(task.subtopic_id)
        title = subtopic.title if subtopic else f"Subtopic {task.subtopic_id}"
        return PlanDayResponse(
            id=task.id,
            plan_date=task.plan_date,
            subtopic_title=title,
            activity_type=task.activity_type,
            estimated_minutes=task.estimated_minutes,
            completed=task.completed,
        )


class ReadinessService:
    """Computes exam readiness predictions."""

    def __init__(
        self,
        *,
        mastery_repo: MasteryRepository,
        subtopic_repo: SubtopicRepository,
        db: object,
    ) -> None:
        self._mastery_repo = mastery_repo
        self._subtopic_repo = subtopic_repo
        self._db = db

    def get_readiness(self, user_id: int) -> ReadinessResponse:
        """Compute readiness report for the user."""
        from sqlalchemy import select
        from sqlalchemy.orm import Session

        from app.features.mock_exams.models import MockExamAttempt
        from app.features.quizzes.models import QuizAttempt
        from app.features.xp.models import UserXP

        db: Session = self._db  # type: ignore[assignment]

        # Get mastery data
        mastery_rows = list(self._mastery_repo.list_by_user(user_id))
        mastery_inputs: list[MasteryInput] = []
        for m in mastery_rows:
            subtopic = self._subtopic_repo.get(m.subtopic_id)
            title = subtopic.title if subtopic else f"Subtopic {m.subtopic_id}"
            mastery_inputs.append(MasteryInput(
                subtopic_id=m.subtopic_id,
                subtopic_title=title,
                mastery_score=m.mastery_score,
            ))

        # Get recent quiz scores (last 10 submitted)
        quiz_stmt = (
            select(QuizAttempt)
            .where(
                QuizAttempt.user_id == user_id,
                QuizAttempt.status == "SUBMITTED",
                QuizAttempt.score.isnot(None),
            )
            .order_by(QuizAttempt.submitted_at.desc())
            .limit(10)
        )
        quiz_attempts = list(db.execute(quiz_stmt).scalars().all())
        recent_quiz_scores = [
            a.score / a.max_score for a in quiz_attempts if a.max_score > 0
        ]

        # Get mock exam scores
        mock_stmt = (
            select(MockExamAttempt)
            .where(
                MockExamAttempt.user_id == user_id,
                MockExamAttempt.status.in_(["SUBMITTED", "AUTO_SUBMITTED"]),
                MockExamAttempt.score.isnot(None),
            )
            .order_by(MockExamAttempt.submitted_at.desc())
        )
        mock_attempts = list(db.execute(mock_stmt).scalars().all())
        mock_exam_scores = [
            a.score / a.max_score for a in mock_attempts if a.max_score > 0
        ]

        # Get XP data for streak
        user_xp = db.get(UserXP, user_id)
        streak_count = user_xp.streak_count if user_xp else 0

        # Total study sessions = total quiz attempts + mock attempts
        total_study_sessions = len(quiz_attempts) + len(mock_attempts)

        report = predict_readiness(
            mastery_data=mastery_inputs,
            recent_quiz_scores=recent_quiz_scores,
            mock_exam_scores=mock_exam_scores,
            streak_count=streak_count,
            total_study_sessions=total_study_sessions,
        )

        return ReadinessResponse(
            passing_probability=report.passing_probability,
            predicted_score=report.predicted_score,
            readiness_percentage=report.readiness_percentage,
            recommended_hours_remaining=report.recommended_hours_remaining,
            strengths=report.strengths,
            weaknesses=report.weaknesses,
            confidence_level=report.confidence_level,
        )
