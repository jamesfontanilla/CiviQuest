"""Unit tests for the wellness/burnout detection algorithm."""

from __future__ import annotations

from app.features.focus.algorithms.wellness import check_wellness


def test_high_fatigue_over_180_minutes() -> None:
    result = check_wellness(
        session_minutes_today=200,
        accuracy_last_10=0.8,
        accuracy_trend="stable",
        consecutive_wrong=0,
        current_streak_days=5,
    )
    assert result.is_fatigued is True
    assert result.fatigue_level == "high"
    assert result.suggestion == "stop_for_today"


def test_high_fatigue_consecutive_wrong_8() -> None:
    result = check_wellness(
        session_minutes_today=60,
        accuracy_last_10=0.2,
        accuracy_trend="declining",
        consecutive_wrong=8,
        current_streak_days=3,
    )
    assert result.is_fatigued is True
    assert result.fatigue_level == "high"
    assert result.suggestion == "switch_topic"


def test_moderate_fatigue_over_120_minutes() -> None:
    result = check_wellness(
        session_minutes_today=130,
        accuracy_last_10=0.7,
        accuracy_trend="stable",
        consecutive_wrong=0,
        current_streak_days=5,
    )
    assert result.is_fatigued is True
    assert result.fatigue_level == "moderate"
    assert result.suggestion == "take_break"


def test_moderate_fatigue_declining_accuracy() -> None:
    result = check_wellness(
        session_minutes_today=60,
        accuracy_last_10=0.5,
        accuracy_trend="declining",
        consecutive_wrong=5,
        current_streak_days=3,
    )
    assert result.is_fatigued is True
    assert result.fatigue_level == "moderate"
    assert result.suggestion == "switch_topic"


def test_moderate_fatigue_low_accuracy_long_session() -> None:
    result = check_wellness(
        session_minutes_today=70,
        accuracy_last_10=0.2,
        accuracy_trend="stable",
        consecutive_wrong=3,
        current_streak_days=2,
    )
    assert result.is_fatigued is True
    assert result.fatigue_level == "moderate"
    assert result.suggestion == "take_break"


def test_no_fatigue_normal_conditions() -> None:
    result = check_wellness(
        session_minutes_today=45,
        accuracy_last_10=0.8,
        accuracy_trend="improving",
        consecutive_wrong=1,
        current_streak_days=7,
    )
    assert result.is_fatigued is False
    assert result.fatigue_level == "none"
    assert result.suggestion == "keep_going"


def test_no_fatigue_short_session_low_accuracy() -> None:
    """Low accuracy but short session — not fatigued yet."""
    result = check_wellness(
        session_minutes_today=30,
        accuracy_last_10=0.2,
        accuracy_trend="declining",
        consecutive_wrong=4,
        current_streak_days=1,
    )
    assert result.is_fatigued is False
    assert result.fatigue_level == "none"
    assert result.suggestion == "keep_going"


def test_priority_180_over_consecutive_wrong() -> None:
    """180+ minutes takes priority over consecutive_wrong >= 8."""
    result = check_wellness(
        session_minutes_today=200,
        accuracy_last_10=0.1,
        accuracy_trend="declining",
        consecutive_wrong=10,
        current_streak_days=1,
    )
    assert result.fatigue_level == "high"
    assert result.suggestion == "stop_for_today"
