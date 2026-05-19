"""Study plan generation algorithm.

Generates a personalized study schedule based on mastery data,
available time, and target exam date. Deterministic given the same inputs.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta


@dataclass
class PlanDay:
    """A single planned activity for a day."""

    plan_date: date
    subtopic_id: int
    activity_type: str  # 'lesson', 'quiz', 'review', 'mock_exam'
    estimated_minutes: int


@dataclass
class SubtopicMasteryInput:
    """Simplified mastery data for plan generation."""

    subtopic_id: int
    mastery_score: float  # 0.0 to 1.0


def generate_study_plan(
    *,
    target_exam_date: date,
    available_hours_per_day: float,
    target_score: float,
    mastery_data: list[SubtopicMasteryInput],
    all_subtopic_ids: list[int],
    now: date,
) -> list[PlanDay]:
    """Generate a personalized study schedule.

    Algorithm:
    1. Calculate days until exam.
    2. Calculate total available study minutes.
    3. Prioritize subtopics by: (1 - mastery_score) * weight.
    4. Distribute activities across days:
       - Weak subtopics get more time (lessons + quizzes)
       - Medium subtopics get review sessions
       - Strong subtopics get occasional reinforcement
       - Schedule mock exams in the last 20% of the plan
    5. Each day's total doesn't exceed available_hours_per_day.
    """
    days_until_exam = (target_exam_date - now).days
    if days_until_exam <= 0:
        return []

    available_minutes_per_day = int(available_hours_per_day * 60)

    # Build mastery lookup
    mastery_map: dict[int, float] = {
        m.subtopic_id: m.mastery_score for m in mastery_data
    }

    # Prioritize subtopics: lower mastery = higher priority
    prioritized: list[tuple[int, float]] = []
    for sid in all_subtopic_ids:
        score = mastery_map.get(sid, 0.0)
        priority = 1.0 - score
        prioritized.append((sid, priority))

    # Sort by priority descending (weakest first)
    prioritized.sort(key=lambda x: x[1], reverse=True)

    # Categorize subtopics
    weak = [(sid, p) for sid, p in prioritized if p > 0.6]
    medium = [(sid, p) for sid, p in prioritized if 0.3 < p <= 0.6]
    strong = [(sid, p) for sid, p in prioritized if p <= 0.3]

    plan_days: list[PlanDay] = []
    current_date = now + timedelta(days=1)
    mock_exam_start = now + timedelta(days=int(days_until_exam * 0.8))

    day_index = 0
    while current_date <= target_exam_date:
        day_minutes_remaining = available_minutes_per_day
        day_index += 1

        # Mock exam days in the last 20%
        if current_date >= mock_exam_start and day_index % 3 == 0:
            if weak:
                sid = weak[day_index % len(weak)][0] if weak else all_subtopic_ids[0]
            elif all_subtopic_ids:
                sid = all_subtopic_ids[0]
            else:
                current_date += timedelta(days=1)
                continue
            plan_days.append(PlanDay(
                plan_date=current_date,
                subtopic_id=sid,
                activity_type="mock_exam",
                estimated_minutes=min(60, day_minutes_remaining),
            ))
            day_minutes_remaining -= 60
            if day_minutes_remaining <= 0:
                current_date += timedelta(days=1)
                continue

        # Weak subtopics: lessons and quizzes
        if weak and day_minutes_remaining >= 20:
            idx = day_index % len(weak)
            sid = weak[idx][0]
            activity = "lesson" if day_index % 2 == 0 else "quiz"
            minutes = min(30, day_minutes_remaining)
            plan_days.append(PlanDay(
                plan_date=current_date,
                subtopic_id=sid,
                activity_type=activity,
                estimated_minutes=minutes,
            ))
            day_minutes_remaining -= minutes

        # Medium subtopics: review
        if medium and day_minutes_remaining >= 15:
            idx = day_index % len(medium)
            sid = medium[idx][0]
            minutes = min(20, day_minutes_remaining)
            plan_days.append(PlanDay(
                plan_date=current_date,
                subtopic_id=sid,
                activity_type="review",
                estimated_minutes=minutes,
            ))
            day_minutes_remaining -= minutes

        # Strong subtopics: occasional reinforcement
        if strong and day_minutes_remaining >= 10 and day_index % 3 == 0:
            idx = day_index % len(strong)
            sid = strong[idx][0]
            minutes = min(15, day_minutes_remaining)
            plan_days.append(PlanDay(
                plan_date=current_date,
                subtopic_id=sid,
                activity_type="review",
                estimated_minutes=minutes,
            ))
            day_minutes_remaining -= minutes

        current_date += timedelta(days=1)

    return plan_days
