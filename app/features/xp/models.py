"""SQLAlchemy ORM models for the XP slice (Task 9.1).

Two tables live here per design ``XP, level, streak``:

- :class:`UserXP` — single denormalized cache row per user containing
  ``cumulative_xp``, ``level``, ``level_reached_at``, ``streak_count``,
  ``last_activity_at``, and ``last_streak_day``. Every read of XP / level /
  streak goes through this row; every write of an :class:`XPEvent` updates
  it within the same transaction. ``cumulative_xp`` is a denormalized cache
  of ``SUM(xp_events.amount)`` and is reconcilable.
- :class:`XPEvent` — append-only ledger row per XP-awarding event. The
  ``source`` column is constrained to a closed enum (Req 11.1); negative
  amounts are only allowed for ``ADMIN_CORRECTION`` (Req 11.7).

Why two tables, not one: the cache row is read on every page render
(profile, leaderboard summary, streak badge); building those numbers from
``SUM(xp_events.amount)`` on every read would O(n) scan the ledger. Caching
on write keeps reads at O(1) PK lookup. Reconciliation script (out of MVP
scope) walks the ledger and rewrites the cache.

``client_event_id`` design notes:

- Stored as a nullable ``String(64)`` column with a UNIQUE constraint.
  Mirrors :class:`LessonCompletion` from the progress slice.
- The repository's idempotency lookup goes through this column. On
  conflict the existing event is returned (caller-side); we never raise
  ``IntegrityError`` into the service layer for an idempotent retry.

Foreign-key cascades match design — deleting a User cascades to every XP
row (Req 15.4 admin delete).
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base


class XPSource(str, Enum):
    """Closed enum of XP-award sources (Req 11.1).

    The DB-side ``CHECK`` constraint on :class:`XPEvent` mirrors this set so
    an attempt to insert any other source value fails at the SQL layer in
    addition to the application-level guard in :class:`~app.features.xp.service.XPService`.
    """

    LESSON_FIRST_COMPLETE = "LESSON_FIRST_COMPLETE"
    QUIZ_PASS = "QUIZ_PASS"
    QUIZ_PERFECT = "QUIZ_PERFECT"
    MOCK_PASS = "MOCK_PASS"
    STREAK_DAY = "STREAK_DAY"
    ADMIN_CORRECTION = "ADMIN_CORRECTION"


class UserXP(Base):
    """Denormalized cache of XP, level, and streak per user.

    One row per user, lazily created on first access via
    :meth:`~app.features.xp.repository.XPRepository.get_or_create_user_xp`.
    Updated transactionally by every
    :meth:`~app.features.xp.repository.XPRepository.insert_event_and_recompute`
    call so the cache stays in sync with the ledger.

    Field semantics:

    - ``cumulative_xp`` — sum of ``xp_events.amount`` for this user, clamped
      at 0 (Req 11.7 — never negative).
    - ``level`` — derived from ``cumulative_xp`` via
      :func:`app.features.xp.algorithms.level.level_of` (Req 11.4).
    - ``level_reached_at`` — UTC timestamp of the most recent level-up. Used
      by leaderboard tie-breaking (Req 12.1, A5).
    - ``streak_count`` — current consecutive-day streak (Req 11.3).
    - ``last_activity_at`` — UTC timestamp of the most recent qualifying
      activity. Drives the 36-hour decay rule (Req 11.6).
    - ``last_streak_day`` — calendar date (in user's tz) of the last day
      that contributed to the streak. Drives the same-day / next-day branch
      in the rollover algorithm (A4).
    """

    __tablename__ = "user_xp"

    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    cumulative_xp: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    level: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    level_reached_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    streak_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    last_activity_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_streak_day: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        # Covering index for the global leaderboard query (Task 14.1,
        # Req 12.1, design A5). The query orders by ``cumulative_xp DESC,
        # level_reached_at ASC, user_id ASC`` and reads
        # ``(cumulative_xp, level, level_reached_at)`` per row; SQLite
        # will use this index to satisfy the ORDER BY without a sort.
        # On Postgres the equivalent ``DESC, ASC`` index would be
        # spelled out per-column, but SQLite ignores ``DESC`` qualifiers
        # in CREATE INDEX and walks the same index in either direction.
        Index(
            "ix_user_xp_global_leaderboard",
            "cumulative_xp",
            "level_reached_at",
            "user_id",
        ),
    )


class XPEvent(Base):
    """Append-only XP ledger row.

    The CHECK constraint enforces ``amount >= 0`` for every source except
    ``ADMIN_CORRECTION`` (Req 11.7). Combined with the source-enum CHECK
    constraint, this gives the schema two layers of defense against bad
    inserts: the service layer validates first, then the DB rejects anything
    that slipped through.

    Index ``ix_xp_events_user_occurred`` covers the windowed-sum queries used
    by the weekly / monthly leaderboards (Req 12.2, 12.3) and the future
    reconciliation pass.
    """

    __tablename__ = "xp_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    # Cross-feature reference (e.g. quiz_attempt_id, mock_exam_attempt_id).
    # Not enforced as a foreign key because the target table varies by source
    # — the audit trail lives in the source-specific feature.
    source_ref_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    # Offline-sync idempotency key (Req 20.3). UNIQUE so a retry with the
    # same client-generated id is detected at the SQL layer in addition to
    # the application-level check.
    client_event_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        CheckConstraint(
            "source IN ("
            "'LESSON_FIRST_COMPLETE', 'QUIZ_PASS', 'QUIZ_PERFECT', "
            "'MOCK_PASS', 'STREAK_DAY', 'ADMIN_CORRECTION'"
            ")",
            name="ck_xp_events_source",
        ),
        CheckConstraint(
            "amount >= 0 OR source = 'ADMIN_CORRECTION'",
            name="ck_xp_events_amount_nonneg_or_correction",
        ),
        UniqueConstraint(
            "client_event_id", name="uq_xp_events_client_event_id"
        ),
        # Covers the (user_id, occurred_at) windowed sums used by the
        # weekly / monthly leaderboards (Req 12.2, 12.3).
        Index(
            "ix_xp_events_user_occurred",
            "user_id",
            "occurred_at",
        ),
    )
