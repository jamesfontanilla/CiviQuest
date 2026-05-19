"""Business logic for the mastery and spaced repetition features.

MasteryService handles recording quiz attempts and computing mastery scores.
SpacedRepetitionService manages review scheduling using the SM-2 algorithm.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.features.content.repository import SubtopicRepository
from app.features.mastery.algorithms.recommendations import (
    Recommendation,
    generate_recommendations,
)
from app.features.mastery.algorithms.spaced_repetition import (
    calculate_next_review,
)
from app.features.mastery.models import (
    MasteryLevel,
    ReviewSchedule,
    UserSubtopicMastery,
    mastery_level_from_score,
)
from app.features.mastery.repository import (
    MasteryRepository,
    ReviewScheduleRepository,
)
from app.features.mastery.schemas import (
    RecommendationResponse,
    ReviewDueResponse,
    SubtopicMasteryResponse,
)


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


class MasteryService:
    """Manages mastery score computation and tracking."""

    def __init__(
        self,
        *,
        mastery_repo: MasteryRepository,
        subtopic_repo: SubtopicRepository,
    ) -> None:
        self._mastery_repo = mastery_repo
        self._subtopic_repo = subtopic_repo

    def record_attempt(
        self,
        *,
        user_id: int,
        subtopic_id: int,
        is_correct: bool,
        response_time_ms: int,
        now: datetime | None = None,
    ) -> UserSubtopicMastery:
        """Called after every quiz answer. Updates mastery_score using weighted formula.

        new_score = (0.6 * accuracy) + (0.2 * speed_factor) + (0.2 * consistency)

        Where:
        - accuracy = correct_attempts / total_attempts
        - speed_factor = 1.0 if response_time < 10s, scales down to 0.0 at 60s
        - consistency = based on recent accuracy trend
        """
        when = now or _utcnow()

        mastery = self._mastery_repo.get_by_user_and_subtopic(user_id, subtopic_id)
        if mastery is None:
            mastery = UserSubtopicMastery(
                user_id=user_id,
                subtopic_id=subtopic_id,
                mastery_level=MasteryLevel.BEGINNER.value,
                mastery_score=0.0,
                total_attempts=0,
                correct_attempts=0,
                avg_response_time_ms=None,
                last_practiced_at=None,
                confidence_score=0.0,
                retention_score=1.0,
            )

        # Update attempt counts.
        mastery.total_attempts += 1
        if is_correct:
            mastery.correct_attempts += 1

        # Update average response time (running average).
        if mastery.avg_response_time_ms is None:
            mastery.avg_response_time_ms = response_time_ms
        else:
            mastery.avg_response_time_ms = int(
                (mastery.avg_response_time_ms * (mastery.total_attempts - 1) + response_time_ms)
                / mastery.total_attempts
            )

        # Compute mastery score components.
        accuracy = mastery.correct_attempts / mastery.total_attempts

        # Speed factor: 1.0 at <=10s, linear decay to 0.0 at 60s.
        speed_factor = _compute_speed_factor(mastery.avg_response_time_ms)

        # Consistency: use accuracy as a proxy (improves with more correct answers).
        consistency = accuracy

        # Weighted mastery score.
        new_score = (0.6 * accuracy) + (0.2 * speed_factor) + (0.2 * consistency)
        new_score = max(0.0, min(1.0, new_score))

        mastery.mastery_score = new_score
        mastery.mastery_level = mastery_level_from_score(new_score).value
        mastery.last_practiced_at = when

        # Confidence grows with more attempts.
        mastery.confidence_score = min(1.0, mastery.total_attempts / 20.0)

        # Retention decays if not practiced recently (simplified model).
        mastery.retention_score = min(1.0, new_score + 0.1)

        return self._mastery_repo.upsert(mastery)

    def get_user_mastery(self, user_id: int) -> list[SubtopicMasteryResponse]:
        """Return all subtopic mastery data for a user."""
        rows = self._mastery_repo.list_by_user(user_id)
        return [self._to_response(m) for m in rows]

    def get_weakest_subtopics(
        self, user_id: int, *, limit: int = 5
    ) -> list[SubtopicMasteryResponse]:
        """Return the N subtopics with lowest mastery_score."""
        rows = self._mastery_repo.list_weakest(user_id, limit=limit)
        return [self._to_response(m) for m in rows]

    def get_recommended_next(self, user_id: int) -> list[RecommendationResponse]:
        """Smart recommendations: prioritize weak + due-for-review subtopics."""
        mastery_data = list(self._mastery_repo.list_by_user(user_id))

        # Build subtopic title lookup.
        subtopic_ids = [m.subtopic_id for m in mastery_data]
        titles: dict[int, str] = {}
        for sid in subtopic_ids:
            st = self._subtopic_repo.get(sid)
            if st is not None:
                titles[sid] = st.title

        # We need review schedules but don't have the repo here;
        # generate recommendations with empty schedules (the router
        # service composition handles the full version).
        recs = generate_recommendations(
            mastery_data=mastery_data,
            review_schedules=[],
            now=_utcnow(),
            subtopic_titles=titles,
        )
        return [
            RecommendationResponse(
                subtopic_id=r.subtopic_id,
                subtopic_title=r.subtopic_title,
                reason=r.reason,
                priority=r.priority,
                recommended_difficulty=r.recommended_difficulty.value,
            )
            for r in recs
        ]

    def _to_response(self, m: UserSubtopicMastery) -> SubtopicMasteryResponse:
        """Convert a mastery ORM row to a response schema."""
        subtopic = self._subtopic_repo.get(m.subtopic_id)
        title = subtopic.title if subtopic else f"Subtopic {m.subtopic_id}"
        return SubtopicMasteryResponse(
            subtopic_id=m.subtopic_id,
            subtopic_title=title,
            mastery_level=MasteryLevel(m.mastery_level),
            mastery_score=m.mastery_score,
            confidence_score=m.confidence_score,
            retention_score=m.retention_score,
            total_attempts=m.total_attempts,
            correct_attempts=m.correct_attempts,
            last_practiced_at=m.last_practiced_at,
        )


def _compute_speed_factor(avg_response_time_ms: int) -> float:
    """Compute speed factor: 1.0 at <=10s, linear decay to 0.0 at 60s."""
    if avg_response_time_ms <= 10000:
        return 1.0
    if avg_response_time_ms >= 60000:
        return 0.0
    return 1.0 - (avg_response_time_ms - 10000) / 50000.0


class SpacedRepetitionService:
    """Manages spaced repetition scheduling using SM-2."""

    def __init__(
        self,
        *,
        review_repo: ReviewScheduleRepository,
        subtopic_repo: SubtopicRepository,
    ) -> None:
        self._review_repo = review_repo
        self._subtopic_repo = subtopic_repo

    def get_due_reviews(
        self, user_id: int, *, now: datetime | None = None, limit: int = 10
    ) -> list[ReviewDueResponse]:
        """Return subtopics due for review (next_review_at <= now)."""
        when = now or _utcnow()
        schedules = self._review_repo.list_due(user_id, now=when, limit=limit)
        results: list[ReviewDueResponse] = []
        for s in schedules:
            subtopic = self._subtopic_repo.get(s.subtopic_id)
            title = subtopic.title if subtopic else f"Subtopic {s.subtopic_id}"
            overdue_seconds = (when - s.next_review_at).total_seconds()
            days_overdue = max(0.0, overdue_seconds / 86400.0)
            results.append(
                ReviewDueResponse(
                    subtopic_id=s.subtopic_id,
                    subtopic_title=title,
                    next_review_at=s.next_review_at,
                    days_overdue=round(days_overdue, 2),
                    interval_days=s.interval_days,
                )
            )
        return results

    def record_review(
        self,
        *,
        user_id: int,
        subtopic_id: int,
        quality: int,
        now: datetime | None = None,
    ) -> ReviewSchedule:
        """After a review session, update the schedule using SM-2."""
        when = now or _utcnow()

        schedule = self._review_repo.get_by_user_and_subtopic(user_id, subtopic_id)
        if schedule is None:
            # Create a new schedule if one doesn't exist.
            schedule = ReviewSchedule(
                user_id=user_id,
                subtopic_id=subtopic_id,
                next_review_at=when + timedelta(days=1),
                interval_days=1.0,
                ease_factor=2.5,
                repetitions=0,
            )

        new_interval, new_ef, new_reps = calculate_next_review(
            quality=quality,
            current_interval=schedule.interval_days,
            ease_factor=schedule.ease_factor,
            repetitions=schedule.repetitions,
        )

        schedule.interval_days = new_interval
        schedule.ease_factor = new_ef
        schedule.repetitions = new_reps
        schedule.last_reviewed_at = when
        schedule.next_review_at = when + timedelta(days=new_interval)

        return self._review_repo.upsert(schedule)

    def schedule_initial_review(
        self,
        *,
        user_id: int,
        subtopic_id: int,
        now: datetime | None = None,
    ) -> ReviewSchedule:
        """Called when a user first completes a subtopic quiz. Sets first review to +1 day."""
        when = now or _utcnow()

        existing = self._review_repo.get_by_user_and_subtopic(user_id, subtopic_id)
        if existing is not None:
            # Already scheduled; don't overwrite.
            return existing

        schedule = ReviewSchedule(
            user_id=user_id,
            subtopic_id=subtopic_id,
            next_review_at=when + timedelta(days=1),
            interval_days=1.0,
            ease_factor=2.5,
            repetitions=0,
        )
        return self._review_repo.upsert(schedule)
