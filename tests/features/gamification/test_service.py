"""Service tests for the gamification slice.

Per testing-standards.md: mocked repositories, test business logic.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.features.gamification.models import StreakFreeze, UserDailyGoal, XPMultiplier
from app.features.gamification.multiplier_service import XPMultiplierService
from app.features.gamification.repository import (
    DailyGoalRepository,
    StreakFreezeRepository,
    XPMultiplierRepository,
)
from app.features.gamification.service import DailyGoalService, StreakFreezeService


def _now() -> datetime:
    return datetime(2025, 6, 15, 12, 0, 0, tzinfo=timezone.utc)


# --- DailyGoalService -------------------------------------------------------


class TestDailyGoalService:
    def _make_service(self) -> tuple[DailyGoalService, MagicMock]:
        mock_repo = MagicMock(spec=DailyGoalRepository)
        service = DailyGoalService(goal_repo=mock_repo)
        return service, mock_repo

    def test_get_or_create_today_returns_existing(self) -> None:
        service, mock_repo = self._make_service()
        existing = MagicMock(spec=UserDailyGoal)
        mock_repo.get_for_date.return_value = existing

        result = service.get_or_create_today(1, now=_now())

        assert result is existing
        mock_repo.create_goal.assert_not_called()

    def test_get_or_create_today_creates_with_default_target(self) -> None:
        service, mock_repo = self._make_service()
        mock_repo.get_for_date.return_value = None
        mock_repo.get_latest_target.return_value = None
        new_goal = MagicMock(spec=UserDailyGoal)
        mock_repo.create_goal.return_value = new_goal

        result = service.get_or_create_today(1, now=_now())

        assert result is new_goal
        mock_repo.create_goal.assert_called_once_with(
            user_id=1, target_xp=50, goal_date=date(2025, 6, 15)
        )

    def test_get_or_create_today_uses_latest_target(self) -> None:
        service, mock_repo = self._make_service()
        mock_repo.get_for_date.return_value = None
        mock_repo.get_latest_target.return_value = 100
        new_goal = MagicMock(spec=UserDailyGoal)
        mock_repo.create_goal.return_value = new_goal

        service.get_or_create_today(1, now=_now())

        mock_repo.create_goal.assert_called_once_with(
            user_id=1, target_xp=100, goal_date=date(2025, 6, 15)
        )

    def test_record_xp_earned_increments_and_completes(self) -> None:
        service, mock_repo = self._make_service()
        goal = MagicMock(spec=UserDailyGoal)
        goal.current_xp = 40
        goal.target_xp = 50
        goal.completed = False
        mock_repo.get_for_date.return_value = goal
        mock_repo.save.return_value = goal

        service.record_xp_earned(1, 15, now=_now())

        assert goal.current_xp == 55
        assert goal.completed is True
        mock_repo.save.assert_called_once()

    def test_record_xp_earned_does_not_re_complete(self) -> None:
        service, mock_repo = self._make_service()
        goal = MagicMock(spec=UserDailyGoal)
        goal.current_xp = 60
        goal.target_xp = 50
        goal.completed = True
        mock_repo.get_for_date.return_value = goal
        mock_repo.save.return_value = goal

        service.record_xp_earned(1, 10, now=_now())

        # completed stays True, completed_at not overwritten
        assert goal.completed is True

    def test_set_target_rejects_invalid(self) -> None:
        service, mock_repo = self._make_service()

        with pytest.raises(HTTPException) as exc_info:
            service.set_target(1, 999)
        assert exc_info.value.status_code == 400


# --- StreakFreezeService ----------------------------------------------------


class TestStreakFreezeService:
    def _make_service(self) -> tuple[StreakFreezeService, MagicMock]:
        mock_repo = MagicMock(spec=StreakFreezeRepository)
        service = StreakFreezeService(freeze_repo=mock_repo)
        return service, mock_repo

    def test_use_freeze_returns_true_on_success(self) -> None:
        service, mock_repo = self._make_service()
        mock_repo.use_oldest.return_value = MagicMock(spec=StreakFreeze)

        assert service.use_freeze(1, now=_now()) is True

    def test_use_freeze_returns_false_when_none_available(self) -> None:
        service, mock_repo = self._make_service()
        mock_repo.use_oldest.return_value = None

        assert service.use_freeze(1, now=_now()) is False

    def test_grant_freeze_raises_when_at_max(self) -> None:
        service, mock_repo = self._make_service()
        mock_repo.count_available.return_value = 2

        with pytest.raises(HTTPException) as exc_info:
            service.grant_freeze(1, now=_now())
        assert exc_info.value.status_code == 409

    def test_grant_freeze_succeeds_below_max(self) -> None:
        service, mock_repo = self._make_service()
        mock_repo.count_available.return_value = 1
        freeze = MagicMock(spec=StreakFreeze)
        mock_repo.grant.return_value = freeze

        result = service.grant_freeze(1, now=_now())
        assert result is freeze


# --- XPMultiplierService ----------------------------------------------------


class TestXPMultiplierService:
    def _make_service(self) -> tuple[XPMultiplierService, MagicMock]:
        mock_repo = MagicMock(spec=XPMultiplierRepository)
        service = XPMultiplierService(multiplier_repo=mock_repo)
        return service, mock_repo

    def test_compute_effective_multiplier_no_active(self) -> None:
        service, mock_repo = self._make_service()
        mock_repo.get_active.return_value = []

        assert service.compute_effective_multiplier(1, now=_now()) == 1.0

    def test_compute_effective_multiplier_stacks_additively(self) -> None:
        service, mock_repo = self._make_service()
        m1 = MagicMock(spec=XPMultiplier)
        m1.multiplier = 1.5
        m2 = MagicMock(spec=XPMultiplier)
        m2.multiplier = 2.0
        mock_repo.get_active.return_value = [m1, m2]

        # 1.0 + (0.5 + 1.0) = 2.5
        result = service.compute_effective_multiplier(1, now=_now())
        assert result == 2.5

    def test_apply_multiplier(self) -> None:
        service, mock_repo = self._make_service()
        m1 = MagicMock(spec=XPMultiplier)
        m1.multiplier = 1.5
        mock_repo.get_active.return_value = [m1]

        result = service.apply_multiplier(1, 100, now=_now())
        assert result == 150

    def test_grant_streak_multiplier_7_day(self) -> None:
        service, mock_repo = self._make_service()
        m = MagicMock(spec=XPMultiplier)
        mock_repo.create_multiplier.return_value = m

        result = service.grant_streak_multiplier(1, 7, now=_now())
        assert result is m
        mock_repo.create_multiplier.assert_called_once()
        call_kwargs = mock_repo.create_multiplier.call_args.kwargs
        assert call_kwargs["multiplier"] == 1.5
        assert call_kwargs["reason"] == "streak_7"

    def test_grant_streak_multiplier_14_day(self) -> None:
        service, mock_repo = self._make_service()
        m = MagicMock(spec=XPMultiplier)
        mock_repo.create_multiplier.return_value = m

        result = service.grant_streak_multiplier(1, 14, now=_now())
        assert result is m
        call_kwargs = mock_repo.create_multiplier.call_args.kwargs
        assert call_kwargs["multiplier"] == 2.0
        assert call_kwargs["reason"] == "streak_14"

    def test_grant_streak_multiplier_no_milestone(self) -> None:
        service, mock_repo = self._make_service()

        result = service.grant_streak_multiplier(1, 5, now=_now())
        assert result is None
