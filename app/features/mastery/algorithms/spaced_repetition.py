"""SM-2 spaced repetition algorithm variant.

Implements the SuperMemo-2 algorithm for calculating review intervals.
The quality parameter maps from quiz performance to a 0-5 scale:
- 0-1: complete failure (score < 20%)
- 2: hard (score 20-50%)
- 3: moderate (score 50-70%)
- 4: good (score 70-90%)
- 5: perfect (score > 90%)
"""

from __future__ import annotations

_MIN_EASE_FACTOR = 1.3


def calculate_next_review(
    *,
    quality: int,
    current_interval: float,
    ease_factor: float,
    repetitions: int,
) -> tuple[float, float, int]:
    """SM-2 algorithm. Returns (new_interval_days, new_ease_factor, new_repetitions).

    If quality < 3: reset repetitions to 0, interval to 1 day.
    If quality >= 3:
      - repetitions += 1
      - if repetitions == 1: interval = 1
      - if repetitions == 2: interval = 3
      - else: interval = previous_interval * ease_factor

    Ease factor adjustment:
      new_ef = ef + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02))
      Clamp to minimum 1.3.
    """
    if quality < 0 or quality > 5:
        raise ValueError(f"quality must be 0-5, got {quality}")

    # Ease factor adjustment (always applied).
    new_ef = ease_factor + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02))
    new_ef = max(new_ef, _MIN_EASE_FACTOR)

    if quality < 3:
        # Failed review: reset.
        return 1.0, new_ef, 0

    # Successful review.
    new_reps = repetitions + 1
    if new_reps == 1:
        new_interval = 1.0
    elif new_reps == 2:
        new_interval = 3.0
    else:
        new_interval = current_interval * new_ef

    return new_interval, new_ef, new_reps


def quality_from_score(score: float) -> int:
    """Map a percentage score (0.0-1.0) to SM-2 quality (0-5)."""
    if score < 0.2:
        return 0
    if score < 0.35:
        return 1
    if score < 0.5:
        return 2
    if score < 0.7:
        return 3
    if score < 0.9:
        return 4
    return 5
