"""Burnout prevention / cognitive fatigue detection.

Rule-based algorithm that checks session duration, accuracy trends, and
consecutive errors to determine if the user should take a break.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class WellnessCheck:
    """Result of a wellness/fatigue check."""

    is_fatigued: bool
    fatigue_level: str  # "none", "mild", "moderate", "high"
    message: str
    suggestion: str  # "take_break", "switch_topic", "stop_for_today", "keep_going"


def check_wellness(
    *,
    session_minutes_today: int,
    accuracy_last_10: float,
    accuracy_trend: str,  # "improving", "stable", "declining"
    consecutive_wrong: int,
    current_streak_days: int,
) -> WellnessCheck:
    """Detect cognitive fatigue and suggest actions.

    Rules (evaluated in priority order):
    - session_minutes_today > 180 → high fatigue, suggest stop
    - consecutive_wrong >= 8 → high fatigue, suggest switch topic
    - session_minutes_today > 120 → moderate fatigue, suggest break
    - accuracy_trend == "declining" AND consecutive_wrong >= 5 → moderate fatigue
    - accuracy_last_10 < 0.3 AND session_minutes_today > 60 → moderate, suggest break
    - Otherwise → no fatigue, keep going

    Messages are motivational and supportive (not punitive).
    """
    # High fatigue: too many hours today
    if session_minutes_today > 180:
        hours = session_minutes_today // 60
        return WellnessCheck(
            is_fatigued=True,
            fatigue_level="high",
            message=(
                f"You've been studying for {hours}+ hours today. "
                "Great consistency! But rest is important too. "
                "Come back tomorrow refreshed! 🌙"
            ),
            suggestion="stop_for_today",
        )

    # High fatigue: too many consecutive wrong answers
    if consecutive_wrong >= 8:
        return WellnessCheck(
            is_fatigued=True,
            fatigue_level="high",
            message=(
                "You seem to be hitting a wall on this topic. "
                "Try switching to something different — a fresh perspective helps! 🔄"
            ),
            suggestion="switch_topic",
        )

    # Moderate fatigue: long session
    if session_minutes_today > 120:
        hours = session_minutes_today // 60
        return WellnessCheck(
            is_fatigued=True,
            fatigue_level="moderate",
            message=(
                f"You've been studying for {hours}+ hours. "
                "Time for a break? Your brain will thank you! 🧘"
            ),
            suggestion="take_break",
        )

    # Moderate fatigue: declining accuracy with consecutive errors
    if accuracy_trend == "declining" and consecutive_wrong >= 5:
        return WellnessCheck(
            is_fatigued=True,
            fatigue_level="moderate",
            message=(
                "Your accuracy is dropping. "
                "Try switching to a different topic! 🔄"
            ),
            suggestion="switch_topic",
        )

    # Moderate fatigue: low accuracy after extended session
    if accuracy_last_10 < 0.3 and session_minutes_today > 60:
        return WellnessCheck(
            is_fatigued=True,
            fatigue_level="moderate",
            message=(
                "Your recent accuracy is low and you've been at it for a while. "
                "A short break might help you refocus! ☕"
            ),
            suggestion="take_break",
        )

    # No fatigue
    return WellnessCheck(
        is_fatigued=False,
        fatigue_level="none",
        message="You're doing great! Keep up the momentum! 🚀",
        suggestion="keep_going",
    )
