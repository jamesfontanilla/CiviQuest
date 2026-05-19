"""Pydantic schemas for the XP slice (Task 9.3, 9.5).

Only one response shape is needed for MVP:

- :class:`UserXPResponse` — payload for ``GET /v1/xp/me`` (Req 11.4, 11.6).
  ``streak`` is the decay-on-read value, never the raw cached
  ``streak_count``: clients always see the up-to-the-second decayed value
  without the server having to write the cache back on every GET.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class UserXPResponse(BaseModel):
    """Read-side view of XP / level / streak (Req 11.4, 11.6)."""

    cumulative_xp: int = Field(ge=0)
    level: int = Field(ge=0)
    streak: int = Field(ge=0)
