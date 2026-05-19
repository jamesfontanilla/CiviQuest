"""Adaptive difficulty engine.

Determines the optimal difficulty level for the next set of questions
based on the learner's mastery score, recent accuracy, response time,
and confidence.
"""

from __future__ import annotations

from enum import Enum


class DifficultyLevel(str, Enum):
    """Adaptive difficulty levels for question selection."""

    EASY = "EASY"
    MEDIUM = "MEDIUM"
    HARD = "HARD"
    EXPERT = "EXPERT"


_DIFFICULTY_ORDER = [
    DifficultyLevel.EASY,
    DifficultyLevel.MEDIUM,
    DifficultyLevel.HARD,
    DifficultyLevel.EXPERT,
]


def _bump_up(level: DifficultyLevel) -> DifficultyLevel:
    """Move one level up, capped at EXPERT."""
    idx = _DIFFICULTY_ORDER.index(level)
    return _DIFFICULTY_ORDER[min(idx + 1, len(_DIFFICULTY_ORDER) - 1)]


def recommend_difficulty(
    *,
    mastery_score: float,
    recent_accuracy: float,
    avg_response_time_ms: int,
    confidence_score: float,
) -> DifficultyLevel:
    """Determine optimal difficulty for next questions.

    Rules:
    - mastery < 0.3 AND accuracy < 0.5 -> EASY
    - mastery < 0.5 OR accuracy < 0.7 -> MEDIUM
    - mastery < 0.8 AND accuracy > 0.7 -> HARD
    - mastery >= 0.8 AND accuracy > 0.85 -> EXPERT

    Speed bonus: if avg_response_time < 5000ms AND accuracy > 0.8,
    bump up one level.
    """
    # Determine base level from mastery + accuracy.
    if mastery_score < 0.3 and recent_accuracy < 0.5:
        level = DifficultyLevel.EASY
    elif mastery_score < 0.5 or recent_accuracy < 0.7:
        level = DifficultyLevel.MEDIUM
    elif mastery_score >= 0.8 and recent_accuracy > 0.85:
        level = DifficultyLevel.EXPERT
    else:
        level = DifficultyLevel.HARD

    # Speed bonus.
    if avg_response_time_ms < 5000 and recent_accuracy > 0.8:
        level = _bump_up(level)

    return level
