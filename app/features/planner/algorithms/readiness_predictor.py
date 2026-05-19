"""Exam readiness prediction algorithm.

Uses a weighted model combining mastery scores, quiz performance,
mock exam scores, and consistency metrics to predict exam readiness.
No ML — just a simple weighted formula with a sigmoid mapping.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class ReadinessReport:
    """Complete readiness assessment."""

    passing_probability: float  # 0.0 to 1.0
    predicted_score: float  # 0.0 to 1.0
    readiness_percentage: float  # 0.0 to 100.0
    recommended_hours_remaining: float
    strengths: list[str]  # subtopic titles
    weaknesses: list[str]  # subtopic titles
    confidence_level: str  # "low", "moderate", "high", "very_high"


@dataclass
class MasteryInput:
    """Mastery data for a single subtopic."""

    subtopic_id: int
    subtopic_title: str
    mastery_score: float


def _sigmoid(x: float) -> float:
    """Standard sigmoid function, clamped to avoid overflow."""
    x = max(-10.0, min(10.0, x))
    return 1.0 / (1.0 + math.exp(-x))


def predict_readiness(
    *,
    mastery_data: list[MasteryInput],
    recent_quiz_scores: list[float],
    mock_exam_scores: list[float],
    streak_count: int,
    total_study_sessions: int,
) -> ReadinessReport:
    """Predict exam readiness using a weighted model.

    Factors and weights:
    - Average mastery score across all subtopics: 30%
    - Recent quiz performance (last 10): 25%
    - Mock exam performance: 25%
    - Consistency (streak + sessions): 10%
    - Coverage (% of subtopics practiced): 10%

    Passing probability formula:
    weighted_score = sum(factor * weight)
    passing_prob = sigmoid(weighted_score * 5 - 2.5)

    Confidence level:
    - < 0.4: "low"
    - 0.4-0.6: "moderate"
    - 0.6-0.8: "high"
    - > 0.8: "very_high"

    Recommended hours = (1.0 - readiness) * 40
    """
    # Factor 1: Average mastery (30%)
    if mastery_data:
        avg_mastery = sum(m.mastery_score for m in mastery_data) / len(mastery_data)
    else:
        avg_mastery = 0.0

    # Factor 2: Recent quiz performance (25%)
    if recent_quiz_scores:
        avg_quiz = sum(recent_quiz_scores) / len(recent_quiz_scores)
    else:
        avg_quiz = 0.0

    # Factor 3: Mock exam performance (25%)
    if mock_exam_scores:
        avg_mock = sum(mock_exam_scores) / len(mock_exam_scores)
    else:
        avg_mock = 0.0

    # Factor 4: Consistency (10%)
    # Normalize streak (max useful value ~30 days) and sessions (max ~100)
    streak_factor = min(1.0, streak_count / 30.0)
    session_factor = min(1.0, total_study_sessions / 100.0)
    consistency = (streak_factor + session_factor) / 2.0

    # Factor 5: Coverage (10%)
    # Proportion of subtopics that have been practiced (mastery_score > 0)
    if mastery_data:
        practiced = sum(1 for m in mastery_data if m.mastery_score > 0)
        coverage = practiced / len(mastery_data)
    else:
        coverage = 0.0

    # Weighted score
    weighted_score = (
        0.30 * avg_mastery
        + 0.25 * avg_quiz
        + 0.25 * avg_mock
        + 0.10 * consistency
        + 0.10 * coverage
    )

    # Passing probability via sigmoid
    passing_probability = _sigmoid(weighted_score * 5.0 - 2.5)

    # Predicted score is the weighted average itself (0-1 scale)
    predicted_score = weighted_score

    # Readiness percentage
    readiness_percentage = round(weighted_score * 100.0, 1)

    # Recommended hours remaining
    recommended_hours = max(0.0, (1.0 - weighted_score) * 40.0)
    recommended_hours = round(recommended_hours, 1)

    # Strengths and weaknesses
    sorted_mastery = sorted(mastery_data, key=lambda m: m.mastery_score, reverse=True)
    strengths = [m.subtopic_title for m in sorted_mastery[:5] if m.mastery_score >= 0.7]
    weaknesses = [
        m.subtopic_title
        for m in sorted(mastery_data, key=lambda m: m.mastery_score)[:5]
        if m.mastery_score < 0.5
    ]

    # Confidence level
    if passing_probability < 0.4:
        confidence_level = "low"
    elif passing_probability < 0.6:
        confidence_level = "moderate"
    elif passing_probability < 0.8:
        confidence_level = "high"
    else:
        confidence_level = "very_high"

    return ReadinessReport(
        passing_probability=round(passing_probability, 4),
        predicted_score=round(predicted_score, 4),
        readiness_percentage=readiness_percentage,
        recommended_hours_remaining=recommended_hours,
        strengths=strengths,
        weaknesses=weaknesses,
        confidence_level=confidence_level,
    )
