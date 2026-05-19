"""Repository for the achievements slice (Task 15.1).

Owns reads and writes for both achievement tables. Extends
:class:`BaseRepository[Achievement]` because :class:`Achievement` is the
"primary" table — its rows are seeded once and rarely change.
:class:`UserAchievement` operations are dedicated helpers on the same
class rather than a separate repository, mirroring the XP slice's
"one repository per feature" convention.

Design highlights:

- :meth:`grant` is **idempotent** at the application level via the
  ``list_user_achievement_ids`` short-circuit, and at the storage level
  via the UNIQUE constraint on ``(user_id, achievement_id)``. We catch
  :class:`IntegrityError` and return the existing row rather than
  surfacing a 500 for a benign race between two concurrent evaluator
  passes.
- :meth:`upsert_achievement` is the seed primitive. It performs
  ``INSERT ... ON CONFLICT DO UPDATE`` semantics manually because
  SQLite's ``INSERT ... ON CONFLICT`` syntax is not directly exposed by
  SQLAlchemy 2.0's ``Session.merge`` for our "string PK + JSON column"
  shape. The implementation reads-then-writes; concurrent seeders are
  not a concern (seeding runs once at startup).
- :meth:`list_user_achievement_ids` returns a ``set[str]`` so the
  evaluator's "already granted?" check is O(1).
- :meth:`list_by_criterion_kind` is the evaluator's primary read: it
  fetches every achievement of a given criterion kind in one indexed
  query so the evaluator can iterate them without N+1.

The slice does **not** add a covering index on ``criterion_kind``; the
table is small enough (max ~15 rows at full scale) that a sequential
scan is faster than an index lookup. If the criterion catalog grows
beyond a few hundred rows, revisit.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.features.achievements.models import Achievement, UserAchievement
from app.infrastructure.repositories.base import BaseRepository


class AchievementRepository(BaseRepository[Achievement]):
    """Persistence for achievement metadata and user grants."""

    model = Achievement

    def __init__(self, db: Session) -> None:
        super().__init__(db=db)

    # ------------------------------------------------------------------
    # Achievement (metadata)
    # ------------------------------------------------------------------

    def list_all(self) -> list[Achievement]:
        """Return every achievement definition.

        Used by the evaluator on every XP event. The metadata table is
        small enough that a full scan is cheaper than a per-criterion
        filter.
        """
        stmt = select(Achievement).order_by(Achievement.id)
        return list(self.db.execute(stmt).scalars().all())

    def list_by_criterion_kind(self, kind: str) -> list[Achievement]:
        """Return every achievement whose ``criterion_kind == kind``."""
        stmt = (
            select(Achievement)
            .where(Achievement.criterion_kind == kind)
            .order_by(Achievement.id)
        )
        return list(self.db.execute(stmt).scalars().all())

    def upsert_achievement(self, achievement: Achievement) -> Achievement:
        """Insert or update an achievement definition idempotently.

        Used by :func:`app.features.achievements.seed.seed_mvp_achievements`
        and the all-achievements seeder so re-running the seeder on an
        already-seeded DB is safe.

        Implementation: read by primary key first; if missing, ``add``;
        if present, copy the seed row's metadata fields onto the
        attached row and let SQLAlchemy flush. Either path commits.
        """
        existing = self.db.get(Achievement, achievement.id)
        if existing is None:
            self.db.add(achievement)
            self.db.commit()
            self.db.refresh(achievement)
            return achievement

        existing.title = achievement.title
        existing.description = achievement.description
        existing.criterion_kind = achievement.criterion_kind
        existing.criterion_value = achievement.criterion_value
        # Only update rarity/icon/xp_reward if explicitly provided (not None),
        # so existing tests that don't set these fields don't break.
        if getattr(achievement, "rarity", None) is not None:
            existing.rarity = achievement.rarity
        if getattr(achievement, "icon", None) is not None:
            existing.icon = achievement.icon
        if getattr(achievement, "xp_reward", None) is not None:
            existing.xp_reward = achievement.xp_reward
        self.db.commit()
        self.db.refresh(existing)
        return existing

    # ------------------------------------------------------------------
    # UserAchievement (grants)
    # ------------------------------------------------------------------

    def list_for_user(self, user_id: int) -> list[UserAchievement]:
        """Return ``user_id``'s grants ordered by ``granted_at`` ASC.

        Stable ordering matters for the wire response so two clients
        rendering the same profile see the same badge order.
        """
        stmt = (
            select(UserAchievement)
            .where(UserAchievement.user_id == user_id)
            .order_by(
                UserAchievement.granted_at.asc(), UserAchievement.id.asc()
            )
        )
        return list(self.db.execute(stmt).scalars().all())

    def list_user_achievement_ids(self, user_id: int) -> set[str]:
        """Return the set of achievement ids ``user_id`` has been granted.

        Used by the evaluator's "already granted?" check. Returning a
        ``set[str]`` makes the membership test O(1).
        """
        stmt = select(UserAchievement.achievement_id).where(
            UserAchievement.user_id == user_id
        )
        return set(self.db.execute(stmt).scalars().all())

    def grant(
        self,
        *,
        user_id: int,
        achievement_id: str,
        granted_at: datetime,
        source_xp_event_id: int | None = None,
    ) -> UserAchievement:
        """Grant ``achievement_id`` to ``user_id`` idempotently.

        Property 23 — exactly one ``user_achievements`` row per
        ``(user_id, achievement_id)``. Two layers of defense:

        1. Application: a pre-insert lookup short-circuits the duplicate
           path so racing evaluators don't collide on every event.
        2. Storage: the UNIQUE constraint catches the race window
           between the lookup and the insert. We catch the
           :class:`IntegrityError`, roll back, re-read, and return.

        Returns the (newly inserted or pre-existing) grant row.
        """
        existing = self._get_grant(
            user_id=user_id, achievement_id=achievement_id
        )
        if existing is not None:
            return existing

        grant = UserAchievement(
            user_id=user_id,
            achievement_id=achievement_id,
            granted_at=granted_at,
            source_xp_event_id=source_xp_event_id,
        )
        self.db.add(grant)
        try:
            self.db.commit()
        except IntegrityError:
            # Lost the race? Another evaluator pass may have inserted
            # first. Roll back, re-check, and return the existing row
            # if found. If still missing, the IntegrityError was for a
            # different constraint (FK violation, etc.); re-raise so the
            # caller sees the real cause instead of a misleading assert.
            self.db.rollback()
            again = self._get_grant(
                user_id=user_id, achievement_id=achievement_id
            )
            if again is None:
                raise
            return again

        self.db.refresh(grant)
        return grant

    # ------------------------------------------------------------------
    # internal
    # ------------------------------------------------------------------

    def _get_grant(
        self, *, user_id: int, achievement_id: str
    ) -> UserAchievement | None:
        """Single-row lookup by the natural key."""
        stmt = (
            select(UserAchievement)
            .where(UserAchievement.user_id == user_id)
            .where(UserAchievement.achievement_id == achievement_id)
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def list_grants(
        self, *, skip: int = 0, limit: int = 100
    ) -> Sequence[UserAchievement]:
        """Admin-side paginated list of every grant.

        Not used by MVP routes; kept here so future admin analytics can
        skip a separate query module. Pagination bounds are enforced
        upstream by ``PaginationParams``.
        """
        stmt = (
            select(UserAchievement)
            .order_by(UserAchievement.id.asc())
            .offset(skip)
            .limit(limit)
        )
        return self.db.execute(stmt).scalars().all()
