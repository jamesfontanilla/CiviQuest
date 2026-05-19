"""Service layer for XP multipliers."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.features.gamification.models import XPMultiplier
from app.features.gamification.repository import XPMultiplierRepository


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


class XPMultiplierService:
    """Manage XP multipliers: create, query active, compute effective multiplier."""

    def __init__(self, *, multiplier_repo: XPMultiplierRepository) -> None:
        self._multiplier_repo = multiplier_repo

    def get_active(
        self, user_id: int, *, now: datetime | None = None
    ) -> list[XPMultiplier]:
        """Return all active (non-expired) multipliers for the user."""
        when = now or _utcnow()
        return self._multiplier_repo.get_active(user_id, now=when)

    def compute_effective_multiplier(
        self, user_id: int, *, now: datetime | None = None
    ) -> float:
        """Compute the effective multiplier by stacking all active multipliers.

        Multiple multipliers stack additively on top of the base 1.0x.
        E.g., 1.5x + 2.0x = base 1.0 + 0.5 + 1.0 = 2.5x total.
        """
        when = now or _utcnow()
        active = self._multiplier_repo.get_active(user_id, now=when)
        if not active:
            return 1.0
        # Stack additively: sum of (multiplier - 1.0) for each, then add 1.0
        bonus = sum(m.multiplier - 1.0 for m in active)
        return 1.0 + bonus

    def apply_multiplier(
        self, user_id: int, base_amount: int, *, now: datetime | None = None
    ) -> int:
        """Apply the effective multiplier to a base XP amount. Returns the final amount."""
        effective = self.compute_effective_multiplier(user_id, now=now)
        return int(base_amount * effective)

    def grant_streak_multiplier(
        self, user_id: int, streak_count: int, *, now: datetime | None = None
    ) -> XPMultiplier | None:
        """Grant a multiplier based on streak milestones. Returns None if no milestone hit."""
        when = now or _utcnow()
        if streak_count == 14:
            return self._multiplier_repo.create_multiplier(
                user_id=user_id,
                multiplier=2.0,
                reason="streak_14",
                expires_at=when + timedelta(hours=24),
            )
        elif streak_count == 7:
            return self._multiplier_repo.create_multiplier(
                user_id=user_id,
                multiplier=1.5,
                reason="streak_7",
                expires_at=when + timedelta(hours=24),
            )
        return None

    def grant_weekend_bonus(
        self, user_id: int, *, now: datetime | None = None
    ) -> XPMultiplier | None:
        """Grant a weekend bonus if today is Saturday or Sunday."""
        when = now or _utcnow()
        if when.weekday() in (5, 6):  # Saturday=5, Sunday=6
            # Check if already granted today
            active = self._multiplier_repo.get_active(user_id, now=when)
            for m in active:
                if m.reason == "weekend_bonus":
                    return None  # Already has one
            # Expires at end of day (midnight next day)
            end_of_day = when.replace(
                hour=23, minute=59, second=59, microsecond=0
            )
            return self._multiplier_repo.create_multiplier(
                user_id=user_id,
                multiplier=1.25,
                reason="weekend_bonus",
                expires_at=end_of_day,
            )
        return None

    def grant_tournament_win_multiplier(
        self, user_id: int, *, now: datetime | None = None
    ) -> XPMultiplier:
        """Grant a 2x multiplier for 48 hours after winning a tournament."""
        when = now or _utcnow()
        return self._multiplier_repo.create_multiplier(
            user_id=user_id,
            multiplier=2.0,
            reason="tournament_win",
            expires_at=when + timedelta(hours=48),
        )
