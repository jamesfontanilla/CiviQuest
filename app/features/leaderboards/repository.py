"""Repository for the leaderboard slice (Task 14.1).

Two read primitives:

- :meth:`LeaderboardRepository.top_global` — Req 12.1. Joins
  :class:`~app.features.xp.models.UserXP` to :class:`~app.features.users.models.User`,
  filters out unverified / banned learners (Req 12.4), orders by
  ``cumulative_xp DESC, level_reached_at ASC NULLS LAST, user_id ASC``,
  caps at ``limit`` (default 100). Backed by the
  ``ix_user_xp_global_leaderboard`` covering index on ``user_xp``.
- :meth:`LeaderboardRepository.top_in_window` — Req 12.2 / 12.3.
  Aggregates ``SUM(xp_events.amount)`` per user in the inclusive
  ``[since, until]`` window, joins to ``users`` + ``user_xp`` for the
  display fields, applies the same eligibility filter, orders by
  ``xp_window DESC, level_reached_at ASC NULLS LAST, user_id ASC``,
  caps at ``limit``. Backed by ``ix_xp_events_user_occurred``.

Why a single shared shape: the global query is a special case of the
windowed one where the "window sum" is replaced by ``cumulative_xp``.
Keeping :class:`LeaderboardRow` shared lets the service layer treat
all three responses uniformly without translating between two row
types.

NULLS LAST handling: ``level_reached_at`` is ``NULL`` for any learner
who has not yet reached level 1 (no level-up has been recorded). Pure
``ORDER BY level_reached_at ASC`` would put NULLs first under SQLite
default. Per design A5 ties should fall back on the *earliest*
level-reached time, so a NULL (never-leveled-up) row should sort
**after** any timestamped row of the same xp_window. The repository
sorts on ``(level_reached_at IS NULL, level_reached_at)`` — the
boolean term places NULL rows after non-NULL rows, then the timestamp
breaks ties among the non-NULL rows.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.features.users.models import AccountState, User
from app.features.xp.models import UserXP, XPEvent


@dataclass(frozen=True)
class LeaderboardRow:
    """One row in a leaderboard response (Req 12.5).

    Shared by global / weekly / monthly. ``xp_window`` carries
    ``cumulative_xp`` for the global view and the per-user ``SUM`` of
    ``xp_events.amount`` for the windowed views; the service layer
    surfaces the value verbatim under the same key.
    """

    user_id: int
    display_name: str
    level: int
    xp_window: int
    category: str


class LeaderboardRepository:
    """Read-only persistence for leaderboard queries.

    Does not extend :class:`BaseRepository` because there is no single
    owning ORM model — the queries cross :class:`UserXP`,
    :class:`XPEvent`, and :class:`User`.
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # Global
    # ------------------------------------------------------------------

    def top_global(self, *, limit: int = 100) -> list[LeaderboardRow]:
        """Return the top ``limit`` learners by ``cumulative_xp`` (Req 12.1).

        Excludes UNVERIFIED accounts and banned users (Req 12.4). Tie-break
        is by earliest ``level_reached_at`` (NULLs last) then ``user_id``.
        """
        # Boolean term that's ``True`` when the timestamp is NULL.
        # Sorting ascending on this term puts non-NULLs (False) first
        # and NULLs (True) last — i.e. NULLS LAST.
        nulls_last = case(
            (UserXP.level_reached_at.is_(None), 1), else_=0
        )

        stmt = (
            select(
                User.id,
                User.display_name,
                UserXP.level,
                UserXP.cumulative_xp,
                User.category,
            )
            .join(UserXP, UserXP.user_id == User.id)
            .where(User.account_state == AccountState.VERIFIED.value)
            .where(User.is_banned.is_(False))
            .order_by(
                UserXP.cumulative_xp.desc(),
                nulls_last.asc(),
                UserXP.level_reached_at.asc(),
                User.id.asc(),
            )
            .limit(limit)
        )

        rows = self.db.execute(stmt).all()
        return [
            LeaderboardRow(
                user_id=row.id,
                display_name=row.display_name,
                level=row.level,
                xp_window=row.cumulative_xp,
                category=row.category,
            )
            for row in rows
        ]

    # ------------------------------------------------------------------
    # Windowed (weekly / monthly)
    # ------------------------------------------------------------------

    def top_in_window(
        self,
        *,
        since: datetime,
        until: datetime,
        limit: int = 100,
    ) -> list[LeaderboardRow]:
        """Return the top ``limit`` learners by XP earned in ``[since, until]``.

        Used by both the weekly leaderboard (Req 12.2, ISO-week bounds)
        and the monthly leaderboard (Req 12.3, calendar-month bounds);
        the only difference between the two is the bounds the caller
        supplies.

        Implementation: aggregate ``SUM(xp_events.amount)`` grouped by
        ``user_id`` in the window, join the aggregate back to ``users``
        + ``user_xp`` for the display fields, filter out
        unverified/banned learners (Req 12.4), and exclude users with a
        zero window sum (otherwise every eligible user with no recent
        XP would pad the response). Hits the
        ``ix_xp_events_user_occurred`` composite index for the
        date-range scan.
        """
        # Per-user XP earned in the window. Subquery so the outer
        # query can join the aggregate back to users / user_xp without
        # GROUP BY-ing the entire join (which would force every
        # ``users`` column into the GROUP BY clause on Postgres).
        window_sum = (
            select(
                XPEvent.user_id.label("user_id"),
                func.coalesce(
                    func.sum(XPEvent.amount), 0
                ).label("xp_window"),
            )
            .where(XPEvent.occurred_at >= since)
            .where(XPEvent.occurred_at <= until)
            .group_by(XPEvent.user_id)
            .subquery("xp_window")
        )

        nulls_last = case(
            (UserXP.level_reached_at.is_(None), 1), else_=0
        )

        stmt = (
            select(
                User.id,
                User.display_name,
                UserXP.level,
                window_sum.c.xp_window,
                User.category,
            )
            .join(window_sum, window_sum.c.user_id == User.id)
            .join(UserXP, UserXP.user_id == User.id)
            .where(User.account_state == AccountState.VERIFIED.value)
            .where(User.is_banned.is_(False))
            .where(window_sum.c.xp_window > 0)
            .order_by(
                window_sum.c.xp_window.desc(),
                nulls_last.asc(),
                UserXP.level_reached_at.asc(),
                User.id.asc(),
            )
            .limit(limit)
        )

        rows = self.db.execute(stmt).all()
        return [
            LeaderboardRow(
                user_id=row.id,
                display_name=row.display_name,
                level=row.level,
                xp_window=int(row.xp_window),
                category=row.category,
            )
            for row in rows
        ]
