"""Recommendation engine for personalized study suggestions.

Generates prioritized recommendations based on mastery data and
spaced repetition schedules. Priority rules:
1. Due reviews (overdue by most days) -> highest priority
2. Weak areas (lowest mastery_score) -> high priority
3. Next in sequence (uncompleted subtopics) -> medium priority
4. Challenge mode (mastered topics for reinforcement) -> low priority
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.features.mastery.algorithms.difficulty import (
    DifficultyLevel,
    recommend_difficulty,
)
from app.features.mastery.models import (
    MasteryLevel,
    ReviewSchedule,
    UserSubtopicMastery,
)


@dataclass
class Recommendation:
    """A single study recommendation."""

    subtopic_id: int
    subtopic_title: str
    reason: str  # "weak_area", "due_for_review", "next_in_sequence", "challenge"
    priority: float  # 0.0 to 1.0 (higher = more urgent)
    recommended_difficulty: DifficultyLevel


def generate_recommendations(
    *,
    mastery_data: list[UserSubtopicMastery],
    review_schedules: list[ReviewSchedule],
    now: datetime,
    subtopic_titles: dict[int, str] | None = None,
) -> list[Recommendation]:
    """Generate personalized study recommendations.

    Returns top 10 recommendations sorted by priority DESC.
    """
    titles = subtopic_titles or {}
    recommendations: list[Recommendation] = []

    # Build lookup for review schedules.
    schedule_by_subtopic: dict[int, ReviewSchedule] = {
        rs.subtopic_id: rs for rs in review_schedules
    }

    # Build lookup for mastery data.
    mastery_by_subtopic: dict[int, UserSubtopicMastery] = {
        m.subtopic_id: m for m in mastery_data
    }

    # 1. Due reviews (overdue by most days) -> highest priority.
    for rs in review_schedules:
        if rs.next_review_at <= now:
            overdue_seconds = (now - rs.next_review_at).total_seconds()
            overdue_days = overdue_seconds / 86400.0
            # Priority scales from 0.7 to 1.0 based on how overdue.
            priority = min(1.0, 0.7 + (overdue_days / 30.0) * 0.3)
            mastery = mastery_by_subtopic.get(rs.subtopic_id)
            difficulty = _difficulty_for_mastery(mastery)
            recommendations.append(
                Recommendation(
                    subtopic_id=rs.subtopic_id,
                    subtopic_title=titles.get(rs.subtopic_id, f"Subtopic {rs.subtopic_id}"),
                    reason="due_for_review",
                    priority=priority,
                    recommended_difficulty=difficulty,
                )
            )

    # Track which subtopics already have recommendations.
    seen_ids = {r.subtopic_id for r in recommendations}

    # 2. Weak areas (lowest mastery_score) -> high priority.
    weak_items = sorted(mastery_data, key=lambda m: m.mastery_score)
    for m in weak_items:
        if m.subtopic_id in seen_ids:
            continue
        if m.mastery_score >= 0.75:
            break  # No longer "weak"
        # Priority: 0.4 to 0.7 inversely proportional to mastery.
        priority = 0.7 - (m.mastery_score * 0.4)
        difficulty = _difficulty_for_mastery(m)
        recommendations.append(
            Recommendation(
                subtopic_id=m.subtopic_id,
                subtopic_title=titles.get(m.subtopic_id, f"Subtopic {m.subtopic_id}"),
                reason="weak_area",
                priority=priority,
                recommended_difficulty=difficulty,
            )
        )
        seen_ids.add(m.subtopic_id)

    # 4. Challenge mode (mastered topics for reinforcement) -> low priority.
    for m in mastery_data:
        if m.subtopic_id in seen_ids:
            continue
        if m.mastery_level == MasteryLevel.MASTERED.value:
            recommendations.append(
                Recommendation(
                    subtopic_id=m.subtopic_id,
                    subtopic_title=titles.get(m.subtopic_id, f"Subtopic {m.subtopic_id}"),
                    reason="challenge",
                    priority=0.1,
                    recommended_difficulty=DifficultyLevel.EXPERT,
                )
            )
            seen_ids.add(m.subtopic_id)

    # Sort by priority DESC and return top 10.
    recommendations.sort(key=lambda r: r.priority, reverse=True)
    return recommendations[:10]


def _difficulty_for_mastery(mastery: UserSubtopicMastery | None) -> DifficultyLevel:
    """Determine recommended difficulty from mastery data."""
    if mastery is None:
        return DifficultyLevel.EASY
    accuracy = (
        mastery.correct_attempts / mastery.total_attempts
        if mastery.total_attempts > 0
        else 0.0
    )
    return recommend_difficulty(
        mastery_score=mastery.mastery_score,
        recent_accuracy=accuracy,
        avg_response_time_ms=mastery.avg_response_time_ms or 15000,
        confidence_score=mastery.confidence_score,
    )
