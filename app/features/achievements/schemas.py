"""Pydantic schemas for the achievements slice (Task 15.4).

One response shape:

- :class:`UserAchievementResponse` — payload entry for
  ``GET /v1/achievements/me``. Joins :class:`Achievement` (for title +
  description) with :class:`UserAchievement` (for granted_at) so the
  client can render a badge in one round-trip.

The wire surface intentionally **omits** ``criterion_kind`` and
``criterion_value`` — those are server-internal evaluator details that
shouldn't leak to clients (Req 13.4 wants the *list* of earned
achievements; the criterion encoding is implementation, not API).
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class UserAchievementResponse(BaseModel):
    """One earned achievement for the current user (Req 13.4)."""

    model_config = ConfigDict(from_attributes=True)

    achievement_id: str
    title: str
    description: str
    rarity: str = "COMMON"
    icon: str | None = None
    xp_reward: int = 0
    granted_at: datetime
