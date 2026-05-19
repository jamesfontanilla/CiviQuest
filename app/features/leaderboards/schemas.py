"""Pydantic schemas for the leaderboard slice (Task 14.2).

A single response shape is sufficient for global / weekly / monthly
because the wire surface is identical (Req 12.5): each entry exposes
``display_name``, ``level``, ``xp_window``, ``category``. The
``user_id`` is included so the client can render avatars / link to
profiles without an extra round-trip — leaking the ``id`` is
acceptable here because every leaderboard row is for a VERIFIED,
non-banned user (the eligibility filter has already excluded
sensitive cases).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.features.users.models import Category


class LeaderboardEntry(BaseModel):
    """One entry on a leaderboard response (Req 12.5)."""

    model_config = ConfigDict(from_attributes=True)

    user_id: int
    display_name: str
    level: int = Field(ge=0)
    xp_window: int = Field(
        ge=0,
        description=(
            "Cumulative XP for the global view; sum of XP earned in the "
            "ISO-week window for weekly; sum of XP earned in the calendar "
            "month for monthly."
        ),
    )
    category: Category
