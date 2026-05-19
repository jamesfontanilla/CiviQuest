"""Repository for the XP slice (Task 9.1).

A single :class:`XPRepository` owns reads and writes for both XP tables.
The class extends ``BaseRepository[UserXP]`` because the cache row is the
busy table — most reads target it. :class:`~app.features.xp.models.XPEvent`
gets dedicated helpers on the same class rather than a separate repository
because the slice convention is "one ``repository.py`` per feature" and the
two tables co-evolve transactionally.

Key design choices:

- **Atomic event-and-cache update.**
  :meth:`insert_event_and_recompute` is the single mutation entry point. It
  inserts the ledger row, refreshes ``cumulative_xp`` (clamped at 0 per
  Req 11.7), recomputes ``level``, and stamps ``level_reached_at`` on a
  level-up — all within one ``commit``. The service layer never writes the
  cache row directly.
- **Lazy-create the cache row.**
  :meth:`get_or_create_user_xp` materialises the ``user_xp`` row on first
  access. Callers don't have to worry about whether the row exists; the
  signup flow doesn't insert one upfront because the vast majority of
  ``user_xp`` reads happen on users who have already earned XP.
- **Idempotency lookup is cheap.**
  :meth:`get_event_by_client_event_id` is a single-row UNIQUE-index hit;
  the service layer calls it before any write to short-circuit replays.
- **Windowed sums use the (user_id, occurred_at) index.**
  :meth:`sum_in_window` is the leaderboard primitive (Req 12.2, 12.3).
  The query plan is index-scan + ``SUM(amount)``.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.features.xp.algorithms.level import level_of
from app.features.xp.models import UserXP, XPEvent, XPSource
from app.infrastructure.repositories.base import BaseRepository


class XPRepository(BaseRepository[UserXP]):
    """Persistence for XP cache rows and the XP event ledger."""

    model = UserXP

    def __init__(self, db: Session) -> None:
        super().__init__(db=db)

    # ------------------------------------------------------------------
    # UserXP
    # ------------------------------------------------------------------

    def get_user_xp(self, user_id: int) -> UserXP | None:
        """Return the cache row for ``user_id`` or ``None`` if absent."""
        return self.db.get(UserXP, user_id)

    def get_or_create_user_xp(self, user_id: int) -> UserXP:
        """Materialise the cache row on first access.

        Defaults: ``cumulative_xp=0``, ``level=0``, ``streak_count=0``,
        ``level_reached_at=None``, ``last_activity_at=None``,
        ``last_streak_day=None``. The caller is responsible for triggering
        any subsequent updates (typically via
        :meth:`insert_event_and_recompute`).
        """
        existing = self.get_user_xp(user_id)
        if existing is not None:
            return existing
        row = UserXP(user_id=user_id)
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    # ------------------------------------------------------------------
    # XPEvent
    # ------------------------------------------------------------------

    def get_event_by_client_event_id(
        self, client_event_id: str
    ) -> XPEvent | None:
        """Idempotency lookup for offline sync (Req 20.3)."""
        stmt = select(XPEvent).where(
            XPEvent.client_event_id == client_event_id
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def insert_event_and_recompute(
        self,
        *,
        user_id: int,
        source: XPSource,
        amount: int,
        occurred_at: datetime,
        source_ref_id: int | None = None,
        client_event_id: str | None = None,
    ) -> tuple[XPEvent, UserXP]:
        """Append ``XPEvent`` and refresh the ``UserXP`` cache atomically.

        Steps (per design A3):

        1. Get-or-create the cache row.
        2. Insert the ``XPEvent`` row.
        3. Recompute ``cumulative_xp = max(0, cumulative_xp + amount)``
           (clamp at 0 per Req 11.7).
        4. Recompute ``level`` from the new ``cumulative_xp``.
        5. If the level moved up, set ``level_reached_at = occurred_at``.
        6. Commit.

        Returns:
            ``(event, user_xp)`` — both refreshed from the DB so callers
            can read server-defaulted columns (``id``, ``created_at``,
            etc.) without an extra round trip.

        Note:
            The ``CHECK`` constraints on :class:`XPEvent` enforce the
            closed-source enum and the ``amount >= 0 OR ADMIN_CORRECTION``
            invariant. The service layer validates the same rules
            beforehand so user-facing errors come back as 4xx instead of
            500. The CHECK is the belt-and-suspenders backstop.
        """
        user_xp = self.get_or_create_user_xp(user_id)

        event = XPEvent(
            user_id=user_id,
            source=source.value,
            source_ref_id=source_ref_id,
            amount=amount,
            occurred_at=occurred_at,
            client_event_id=client_event_id,
        )
        self.db.add(event)

        prior_level = user_xp.level
        # Clamp at 0 (Req 11.7 — never produce a negative balance).
        new_cumulative = max(0, user_xp.cumulative_xp + amount)
        new_level = level_of(new_cumulative)

        user_xp.cumulative_xp = new_cumulative
        user_xp.level = new_level
        if new_level > prior_level:
            user_xp.level_reached_at = occurred_at

        self.db.commit()
        self.db.refresh(event)
        self.db.refresh(user_xp)
        return event, user_xp

    def sum_in_window(
        self, user_id: int, *, since: datetime, until: datetime
    ) -> int:
        """Sum XP awarded in the inclusive window ``[since, until]``.

        Used by the weekly / monthly leaderboards (Req 12.2, 12.3) and by
        any future windowed analytics. Implementation hits the
        ``ix_xp_events_user_occurred`` composite index.

        Returns ``0`` for an empty window.
        """
        stmt = (
            select(func.coalesce(func.sum(XPEvent.amount), 0))
            .where(XPEvent.user_id == user_id)
            .where(XPEvent.occurred_at >= since)
            .where(XPEvent.occurred_at <= until)
        )
        return int(self.db.execute(stmt).scalar_one())

    # ------------------------------------------------------------------
    # Persistence helpers used by the service layer for streak fields.
    # ------------------------------------------------------------------

    def commit_streak_update(self, user_xp: UserXP) -> UserXP:
        """Persist ``streak_count``, ``last_activity_at``, ``last_streak_day``.

        The service layer mutates these fields on the ORM-attached instance
        and then asks the repository to flush. Kept as an explicit method
        rather than ``self.db.commit()`` directly so the slice's "service
        does not touch the session" rule is preserved.
        """
        self.db.commit()
        self.db.refresh(user_xp)
        return user_xp
