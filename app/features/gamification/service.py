"""Service layer for daily goals and streak freezes."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from fastapi import HTTPException, status

from app.features.gamification.models import StreakFreeze, UserDailyGoal
from app.features.gamification.repository import (
    DailyGoalRepository,
    StreakFreezeRepository,
)
from app.features.gamification.schemas import DaySummary, WeeklySummary


# Valid daily XP targets.
VALID_TARGETS = {25, 50, 100, 150}
DEFAULT_TARGET = 50


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


def _today(now: datetime | None = None) -> date:
    when = now or _utcnow()
    return when.date()


class DailyGoalService:
    """Manage daily XP goals."""

    def __init__(self, *, goal_repo: DailyGoalRepository) -> None:
        self._goal_repo = goal_repo

    def get_or_create_today(
        self, user_id: int, *, now: datetime | None = None
    ) -> UserDailyGoal:
        """Get today's goal or create one with the user's last target."""
        today = _today(now)
        existing = self._goal_repo.get_for_date(user_id, today)
        if existing is not None:
            return existing

        # Use the user's most recent target or the default.
        latest_target = self._goal_repo.get_latest_target(user_id)
        target = latest_target if latest_target is not None else DEFAULT_TARGET

        return self._goal_repo.create_goal(
            user_id=user_id, target_xp=target, goal_date=today
        )

    def record_xp_earned(
        self, user_id: int, amount: int, *, now: datetime | None = None
    ) -> UserDailyGoal:
        """Increment current_xp on today's goal. Mark completed if target met."""
        goal = self.get_or_create_today(user_id, now=now)
        goal.current_xp += amount
        when = now or _utcnow()
        if not goal.completed and goal.current_xp >= goal.target_xp:
            goal.completed = True
            goal.completed_at = when
        return self._goal_repo.save(goal)

    def set_target(self, user_id: int, target_xp: int) -> None:
        """Set the user's daily XP goal target."""
        if target_xp not in VALID_TARGETS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="invalid_target_xp",
            )
        # Update today's goal if it exists and isn't completed yet.
        today = _today()
        existing = self._goal_repo.get_for_date(user_id, today)
        if existing is not None and not existing.completed:
            existing.target_xp = target_xp
            self._goal_repo.save(existing)
        elif existing is None:
            self._goal_repo.create_goal(
                user_id=user_id, target_xp=target_xp, goal_date=today
            )

    def get_weekly_summary(
        self, user_id: int, *, now: datetime | None = None
    ) -> WeeklySummary:
        """Return last 7 days of goal completion."""
        today = _today(now)
        since = today - timedelta(days=6)
        goals = self._goal_repo.get_last_n_days(user_id, since=since, until=today)

        goal_map = {g.goal_date: g for g in goals}
        days: list[DaySummary] = []
        for i in range(7):
            d = since + timedelta(days=i)
            if d in goal_map:
                g = goal_map[d]
                days.append(
                    DaySummary(
                        goal_date=g.goal_date,
                        target_xp=g.target_xp,
                        current_xp=g.current_xp,
                        completed=g.completed,
                    )
                )
            else:
                days.append(
                    DaySummary(
                        goal_date=d,
                        target_xp=DEFAULT_TARGET,
                        current_xp=0,
                        completed=False,
                    )
                )

        completed_count = sum(1 for d in days if d.completed)
        return WeeklySummary(
            days=days, completed_count=completed_count, total_days=7
        )


class StreakFreezeService:
    """Manage streak freeze tokens."""

    MAX_FREEZES = 2

    def __init__(self, *, freeze_repo: StreakFreezeRepository) -> None:
        self._freeze_repo = freeze_repo

    def use_freeze(self, user_id: int, *, now: datetime | None = None) -> bool:
        """Consume a freeze to protect the streak for today. Returns True if successful."""
        when = now or _utcnow()
        today = when.date()
        result = self._freeze_repo.use_oldest(user_id, used_on=today)
        return result is not None

    def grant_freeze(
        self, user_id: int, *, now: datetime | None = None
    ) -> StreakFreeze:
        """Grant a freeze. Respects max cap."""
        when = now or _utcnow()
        current_count = self._freeze_repo.count_available(user_id)
        if current_count >= self.MAX_FREEZES:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="max_freezes_reached",
            )
        return self._freeze_repo.grant(user_id=user_id, granted_at=when)

    def get_available(self, user_id: int) -> int:
        """Return count of unused freezes."""
        return self._freeze_repo.count_available(user_id)
