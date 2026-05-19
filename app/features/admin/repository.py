"""Repository for admin aggregations spanning multiple feature tables.

Provides analytics queries (Req 17.2) and the mock-attempt reset (Req 17.1).
User management queries live on UserRepository; content queries on the
content repositories. This repository handles cross-slice aggregations that
don't belong to any single feature.
"""

from __future__ import annotations

from sqlalchemy import Float, case, cast, func, select
from sqlalchemy.orm import Session

from app.features.content.models import Subtopic
from app.features.mock_exams.models import MockExamAttempt, MockExamAttemptStatus
from app.features.progress.models import LessonCompletion
from app.features.quizzes.models import QuizAttempt, QuizAttemptStatus
from app.features.users.models import AccountState, User


class AdminRepository:
    """Cross-slice aggregation queries for admin analytics and operations."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def get_analytics(self) -> dict:
        """Compute platform analytics (Req 17.2).

        Returns a dict with:
        - total_users, verified_users, banned_users
        - total_lessons_completed, total_quiz_attempts, total_mock_attempts
        - mock_pass_rate
        - weakest_subtopics (10 lowest avg quiz score)
        """
        # User counts
        total_users = int(
            self.db.execute(select(func.count()).select_from(User)).scalar_one()
        )
        verified_users = int(
            self.db.execute(
                select(func.count())
                .select_from(User)
                .where(User.account_state == AccountState.VERIFIED.value)
            ).scalar_one()
        )
        banned_users = int(
            self.db.execute(
                select(func.count())
                .select_from(User)
                .where(User.is_banned.is_(True))
            ).scalar_one()
        )

        # Progress counts
        total_lessons_completed = int(
            self.db.execute(
                select(func.count()).select_from(LessonCompletion)
            ).scalar_one()
        )
        total_quiz_attempts = int(
            self.db.execute(
                select(func.count()).select_from(QuizAttempt)
            ).scalar_one()
        )
        total_mock_attempts = int(
            self.db.execute(
                select(func.count()).select_from(MockExamAttempt)
            ).scalar_one()
        )

        # Mock pass rate
        submitted_mocks = int(
            self.db.execute(
                select(func.count())
                .select_from(MockExamAttempt)
                .where(
                    MockExamAttempt.status.in_([
                        MockExamAttemptStatus.SUBMITTED.value,
                        MockExamAttemptStatus.AUTO_SUBMITTED.value,
                    ])
                )
            ).scalar_one()
        )
        if submitted_mocks > 0:
            passed_mocks = int(
                self.db.execute(
                    select(func.count())
                    .select_from(MockExamAttempt)
                    .where(
                        MockExamAttempt.status.in_([
                            MockExamAttemptStatus.SUBMITTED.value,
                            MockExamAttemptStatus.AUTO_SUBMITTED.value,
                        ]),
                        MockExamAttempt.score.isnot(None),
                        MockExamAttempt.max_score > 0,
                        cast(MockExamAttempt.score, Float)
                        / cast(MockExamAttempt.max_score, Float)
                        >= 0.80,
                    )
                ).scalar_one()
            )
            mock_pass_rate = round(passed_mocks / submitted_mocks, 4)
        else:
            mock_pass_rate = 0.0

        # 10 weakest subtopics (lowest avg quiz score)
        # Join quiz_attempts (scope_level=SUBTOPIC) with subtopics
        weakest_subtopics = self._get_weakest_subtopics()

        return {
            "total_users": total_users,
            "verified_users": verified_users,
            "banned_users": banned_users,
            "total_lessons_completed": total_lessons_completed,
            "total_quiz_attempts": total_quiz_attempts,
            "total_mock_attempts": total_mock_attempts,
            "mock_pass_rate": mock_pass_rate,
            "weakest_subtopics": weakest_subtopics,
        }

    def _get_weakest_subtopics(self) -> list[dict]:
        """Return 10 subtopics with lowest average quiz score."""
        # Only consider submitted subtopic quizzes
        stmt = (
            select(
                QuizAttempt.scope_id.label("subtopic_id"),
                func.avg(
                    cast(QuizAttempt.score, Float)
                    / case(
                        (QuizAttempt.max_score == 0, 1.0),
                        else_=cast(QuizAttempt.max_score, Float),
                    )
                ).label("avg_score"),
            )
            .where(
                QuizAttempt.scope_level == "SUBTOPIC",
                QuizAttempt.status == QuizAttemptStatus.SUBMITTED.value,
                QuizAttempt.score.isnot(None),
            )
            .group_by(QuizAttempt.scope_id)
            .order_by(func.avg(
                cast(QuizAttempt.score, Float)
                / case(
                    (QuizAttempt.max_score == 0, 1.0),
                    else_=cast(QuizAttempt.max_score, Float),
                )
            ).asc())
            .limit(10)
        )
        rows = self.db.execute(stmt).all()

        result = []
        for row in rows:
            subtopic = self.db.get(Subtopic, row.subtopic_id)
            title = subtopic.title if subtopic else f"Subtopic {row.subtopic_id}"
            result.append({
                "subtopic_id": row.subtopic_id,
                "title": title,
                "avg_score": round(float(row.avg_score), 4),
            })
        return result

    def delete_mock_attempts_for_user(self, user_id: int) -> int:
        """Delete all mock exam attempts for a user (Req 17.1).

        Returns the count of deleted attempts. CASCADE handles answer rows.
        """
        stmt = select(MockExamAttempt).where(
            MockExamAttempt.user_id == user_id
        )
        attempts = list(self.db.execute(stmt).scalars().all())
        count = len(attempts)
        for attempt in attempts:
            self.db.delete(attempt)
        if count > 0:
            self.db.commit()
        return count
