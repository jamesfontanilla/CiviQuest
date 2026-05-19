"""Leaderboard service (Task 14.2).

Three read-only entry points, one per Req 12.1 / 12.2 / 12.3:

- :meth:`LeaderboardService.global_top` — top 100 by cumulative XP.
- :meth:`LeaderboardService.weekly_top` — top 100 by XP earned in the
  current ISO week (Mon 00:00 UTC .. Sun 23:59:59.999999 UTC).
- :meth:`LeaderboardService.monthly_top` — top 100 by XP earned in the
  current calendar month (UTC).

Each method delegates to :class:`LeaderboardRepository` for the SQL
work and converts the resulting :class:`LeaderboardRow` dataclasses
into :class:`LeaderboardEntry` Pydantic models for the wire. The
service deliberately stays thin: there is no caching, no
permission check beyond the filter the repository already applies
(Req 12.4 — VERIFIED + not-banned), and no business logic that
diverges between the three windows. The only real "logic" here is
window-bound resolution, which is itself delegated to the windowing
algorithm.

The ``now`` parameter on the windowed methods is injectable so tests
can pin the clock; production callers omit it and the service uses
``datetime.now(tz=timezone.utc)``.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.features.leaderboards.algorithms.windowing import (
    calendar_month_bounds,
    iso_week_bounds,
)
from app.features.leaderboards.repository import (
    LeaderboardRepository,
    LeaderboardRow,
)
from app.features.leaderboards.schemas import LeaderboardEntry
from app.features.users.models import Category


def _utcnow() -> datetime:
    """Aware UTC ``now`` so tests can pin time."""
    return datetime.now(tz=timezone.utc)


def _to_entry(row: LeaderboardRow) -> LeaderboardEntry:
    """Translate a repository row into the wire-shape Pydantic entry."""
    return LeaderboardEntry(
        user_id=row.user_id,
        display_name=row.display_name,
        level=row.level,
        xp_window=row.xp_window,
        category=Category(row.category),
    )


class LeaderboardService:
    """Read-only orchestration for the three leaderboard windows."""

    def __init__(
        self, *, leaderboard_repo: LeaderboardRepository
    ) -> None:
        self._repo = leaderboard_repo

    # ------------------------------------------------------------------
    # Global
    # ------------------------------------------------------------------

    def global_top(self, *, limit: int = 100) -> list[LeaderboardEntry]:
        """Return the global top ``limit`` learners (Req 12.1)."""
        rows = self._repo.top_global(limit=limit)
        return [_to_entry(r) for r in rows]

    # ------------------------------------------------------------------
    # Weekly
    # ------------------------------------------------------------------

    def weekly_top(
        self,
        *,
        now: datetime | None = None,
        limit: int = 100,
    ) -> list[LeaderboardEntry]:
        """Return the weekly top ``limit`` learners (Req 12.2).

        Window = ISO week containing ``now`` (default: current UTC
        time). Monday 00:00 UTC through Sunday 23:59:59.999999 UTC.
        """
        since, until = iso_week_bounds(now or _utcnow())
        rows = self._repo.top_in_window(
            since=since, until=until, limit=limit
        )
        return [_to_entry(r) for r in rows]

    # ------------------------------------------------------------------
    # Monthly
    # ------------------------------------------------------------------

    def monthly_top(
        self,
        *,
        now: datetime | None = None,
        limit: int = 100,
    ) -> list[LeaderboardEntry]:
        """Return the monthly top ``limit`` learners (Req 12.3).

        Window = calendar month containing ``now`` (default: current
        UTC time). First-of-month 00:00 UTC through last-of-month
        23:59:59.999999 UTC.
        """
        since, until = calendar_month_bounds(now or _utcnow())
        rows = self._repo.top_in_window(
            since=since, until=until, limit=limit
        )
        return [_to_entry(r) for r in rows]
