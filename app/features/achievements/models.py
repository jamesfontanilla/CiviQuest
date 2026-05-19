"""SQLAlchemy ORM models for achievements (Task 15.1).

Two tables live here per design ``Table specifications -> Achievements``:

- :class:`Achievement` — metadata row describing a single achievement
  definition. The seed table is small (a few dozen rows even at full
  Phase 2 scale) and is loaded by the seed loader on app startup or by
  an admin import. The actual evaluation rule lives in code (see
  :mod:`app.features.achievements.service`); this row is **only**
  metadata + the criterion descriptor that the evaluator switches on.
- :class:`UserAchievement` — one row per (user, achievement) grant.
  The UNIQUE constraint on ``(user_id, achievement_id)`` is the
  storage-level guarantee for Property 23 (achievement uniqueness):
  even under racing evaluator passes, only the first insert wins.

Why a string primary key on :class:`Achievement`: every grant
references the achievement by its semantic id (``FIRST_LESSON``,
``STREAK_7_DAYS``, ...), and the wire shape (``GET /v1/achievements/me``)
echoes that id verbatim. Using a string PK eliminates a layer of
indirection — clients render badges directly off the id without an
extra lookup, and the seed loader can write rows by id without
caring about auto-incrementing surrogate keys.

``criterion_kind`` is a free-form ``String(64)`` rather than a
:class:`Enum` so that adding a new criterion in Phase 2 doesn't
require a schema migration; the evaluator's switch statement is the
canonical list. ``criterion_value`` is JSON because each criterion
kind carries a different shape (``{}`` for first-lesson, ``{"days": 7}``
for streak, ``{"level": 10}`` for level milestones).

``source_xp_event_id`` on the grant row is a soft FK back into
``xp_events``: when present, it pins the exact ledger event that
satisfied the criterion (Property 23 — ``granted_at`` equals the first
satisfying event's timestamp). Nullable + ``ON DELETE SET NULL`` so
admin reconciliation that purges old XP events doesn't cascade-delete
the grant.

Foreign-key cascades match design — deleting a User cascades to every
grant (Req 15.4 admin delete); deleting an Achievement also cascades
to its grants (admin removes a definition).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base


class Achievement(Base):
    """An achievement definition (seed-data + criterion metadata).

    ``id`` is a stable string slug (``FIRST_LESSON``, ``STREAK_7_DAYS``,
    ...) used as the foreign-key target on :class:`UserAchievement`.
    """

    __tablename__ = "achievements"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    criterion_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    criterion_value: Mapped[dict] = mapped_column(JSON, nullable=False)
    rarity: Mapped[str] = mapped_column(
        String(16), nullable=False, default="COMMON", server_default="COMMON"
    )
    icon: Mapped[str | None] = mapped_column(String(64), nullable=True)
    xp_reward: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
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


class UserAchievement(Base):
    """A grant: this user earned this achievement (Req 13.2, 13.3).

    The UNIQUE constraint on ``(user_id, achievement_id)`` is the
    storage-level guarantee that Property 23 holds: a second insert
    with the same pair raises ``IntegrityError`` regardless of the
    evaluator's idempotency check.

    ``source_xp_event_id`` is nullable because not every criterion
    pins to a single XP event (e.g. STREAK_N_DAYS satisfies on a
    cache-row read of ``streak_count``). When the criterion *does*
    correspond to a single triggering event (``FIRST_LESSON``,
    ``QUIZ_PERFECT``, ...), the evaluator threads the originating
    event id through so audits can reconstruct the chain.
    """

    __tablename__ = "user_achievements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    achievement_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("achievements.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    source_xp_event_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("xp_events.id", ondelete="SET NULL"),
        nullable=True,
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
        UniqueConstraint(
            "user_id",
            "achievement_id",
            name="uq_user_achievements_user_achievement",
        ),
    )
