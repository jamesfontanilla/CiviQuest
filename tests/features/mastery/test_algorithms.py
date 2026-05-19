"""Unit tests for mastery algorithms (spaced repetition, difficulty, recommendations)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.features.mastery.algorithms.difficulty import (
    DifficultyLevel,
    recommend_difficulty,
)
from app.features.mastery.algorithms.spaced_repetition import (
    calculate_next_review,
    quality_from_score,
)
from app.features.mastery.models import (
    MasteryLevel,
    mastery_level_from_score,
)


# ---------------------------------------------------------------------------
# mastery_level_from_score
# ---------------------------------------------------------------------------


class TestMasteryLevelFromScore:
    def test_beginner(self):
        assert mastery_level_from_score(0.0) == MasteryLevel.BEGINNER
        assert mastery_level_from_score(0.19) == MasteryLevel.BEGINNER

    def test_familiar(self):
        assert mastery_level_from_score(0.2) == MasteryLevel.FAMILIAR
        assert mastery_level_from_score(0.49) == MasteryLevel.FAMILIAR

    def test_proficient(self):
        assert mastery_level_from_score(0.5) == MasteryLevel.PROFICIENT
        assert mastery_level_from_score(0.74) == MasteryLevel.PROFICIENT

    def test_advanced(self):
        assert mastery_level_from_score(0.75) == MasteryLevel.ADVANCED
        assert mastery_level_from_score(0.89) == MasteryLevel.ADVANCED

    def test_mastered(self):
        assert mastery_level_from_score(0.9) == MasteryLevel.MASTERED
        assert mastery_level_from_score(1.0) == MasteryLevel.MASTERED


# ---------------------------------------------------------------------------
# SM-2 spaced repetition
# ---------------------------------------------------------------------------


class TestCalculateNextReview:
    def test_quality_below_3_resets(self):
        """Quality < 3 resets repetitions to 0 and interval to 1."""
        interval, ef, reps = calculate_next_review(
            quality=2,
            current_interval=10.0,
            ease_factor=2.5,
            repetitions=5,
        )
        assert interval == 1.0
        assert reps == 0
        assert ef >= 1.3

    def test_quality_0_resets(self):
        interval, ef, reps = calculate_next_review(
            quality=0,
            current_interval=30.0,
            ease_factor=2.5,
            repetitions=10,
        )
        assert interval == 1.0
        assert reps == 0

    def test_quality_3_first_rep(self):
        """First successful review: interval = 1."""
        interval, ef, reps = calculate_next_review(
            quality=3,
            current_interval=1.0,
            ease_factor=2.5,
            repetitions=0,
        )
        assert interval == 1.0
        assert reps == 1

    def test_quality_4_second_rep(self):
        """Second successful review: interval = 3."""
        interval, ef, reps = calculate_next_review(
            quality=4,
            current_interval=1.0,
            ease_factor=2.5,
            repetitions=1,
        )
        assert interval == 3.0
        assert reps == 2

    def test_quality_5_third_rep(self):
        """Third+ successful review: interval = previous * ease_factor."""
        interval, ef, reps = calculate_next_review(
            quality=5,
            current_interval=3.0,
            ease_factor=2.5,
            repetitions=2,
        )
        # interval = 3.0 * new_ef (which is 2.5 + adjustment for quality=5)
        # new_ef = 2.5 + (0.1 - 0*0.08) = 2.6
        assert reps == 3
        assert interval == pytest.approx(3.0 * 2.6, rel=1e-3)

    def test_ease_factor_minimum_clamp(self):
        """Ease factor never drops below 1.3."""
        _, ef, _ = calculate_next_review(
            quality=0,
            current_interval=1.0,
            ease_factor=1.3,
            repetitions=0,
        )
        assert ef >= 1.3

    def test_invalid_quality_raises(self):
        with pytest.raises(ValueError):
            calculate_next_review(
                quality=6,
                current_interval=1.0,
                ease_factor=2.5,
                repetitions=0,
            )
        with pytest.raises(ValueError):
            calculate_next_review(
                quality=-1,
                current_interval=1.0,
                ease_factor=2.5,
                repetitions=0,
            )


class TestQualityFromScore:
    def test_perfect(self):
        assert quality_from_score(1.0) == 5
        assert quality_from_score(0.91) == 5

    def test_good(self):
        assert quality_from_score(0.85) == 4
        assert quality_from_score(0.7) == 4

    def test_moderate(self):
        assert quality_from_score(0.6) == 3
        assert quality_from_score(0.5) == 3

    def test_hard(self):
        assert quality_from_score(0.4) == 2
        assert quality_from_score(0.35) == 2

    def test_fail(self):
        assert quality_from_score(0.1) == 0
        assert quality_from_score(0.0) == 0


# ---------------------------------------------------------------------------
# Difficulty recommendation
# ---------------------------------------------------------------------------


class TestRecommendDifficulty:
    def test_easy_low_mastery_low_accuracy(self):
        result = recommend_difficulty(
            mastery_score=0.1,
            recent_accuracy=0.3,
            avg_response_time_ms=20000,
            confidence_score=0.2,
        )
        assert result == DifficultyLevel.EASY

    def test_medium_low_mastery(self):
        result = recommend_difficulty(
            mastery_score=0.4,
            recent_accuracy=0.6,
            avg_response_time_ms=20000,
            confidence_score=0.5,
        )
        assert result == DifficultyLevel.MEDIUM

    def test_medium_low_accuracy(self):
        result = recommend_difficulty(
            mastery_score=0.6,
            recent_accuracy=0.5,
            avg_response_time_ms=20000,
            confidence_score=0.5,
        )
        assert result == DifficultyLevel.MEDIUM

    def test_hard_moderate_mastery(self):
        result = recommend_difficulty(
            mastery_score=0.6,
            recent_accuracy=0.75,
            avg_response_time_ms=20000,
            confidence_score=0.7,
        )
        assert result == DifficultyLevel.HARD

    def test_expert_high_mastery_high_accuracy(self):
        result = recommend_difficulty(
            mastery_score=0.85,
            recent_accuracy=0.9,
            avg_response_time_ms=20000,
            confidence_score=0.9,
        )
        assert result == DifficultyLevel.EXPERT

    def test_speed_bonus_bumps_up(self):
        """Fast response + high accuracy bumps difficulty up one level."""
        # Without speed bonus this would be MEDIUM.
        result = recommend_difficulty(
            mastery_score=0.4,
            recent_accuracy=0.85,
            avg_response_time_ms=3000,
            confidence_score=0.5,
        )
        # mastery < 0.5 -> MEDIUM base, but speed bonus bumps to HARD
        assert result == DifficultyLevel.HARD

    def test_speed_bonus_caps_at_expert(self):
        """Speed bonus doesn't go above EXPERT."""
        result = recommend_difficulty(
            mastery_score=0.85,
            recent_accuracy=0.95,
            avg_response_time_ms=3000,
            confidence_score=0.9,
        )
        assert result == DifficultyLevel.EXPERT
