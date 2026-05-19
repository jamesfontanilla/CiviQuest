"""Service tests for the leaderboard slice (Task 14.2).

Per ``testing-standards.md`` service tests use ``MagicMock(spec=...)``
for the repository. The service is thin (window-bound resolution +
row-to-entry translation), so the tests focus on:

- correct window bounds passed to ``top_in_window`` for weekly /
  monthly,
- correct row-to-entry translation (Req 12.5 field mapping),
- ``limit`` parameter forwarded verbatim,
- ``now`` parameter forwarded verbatim (used by deterministic tests).
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

from app.features.leaderboards.algorithms.windowing import (
    calendar_month_bounds,
    iso_week_bounds,
)
from app.features.leaderboards.repository import (
    LeaderboardRepository,
    LeaderboardRow,
)
from app.features.leaderboards.schemas import LeaderboardEntry
from app.features.leaderboards.service import LeaderboardService
from app.features.users.models import Category


# --- factories -------------------------------------------------------------


def _make_row(
    *,
    user_id: int = 1,
    display_name: str = "Alice",
    level: int = 2,
    xp_window: int = 420,
    category: str = Category.PROFESSIONAL.value,
) -> LeaderboardRow:
    return LeaderboardRow(
        user_id=user_id,
        display_name=display_name,
        level=level,
        xp_window=xp_window,
        category=category,
    )


def _build_service() -> tuple[LeaderboardService, MagicMock]:
    repo = MagicMock(spec=LeaderboardRepository)
    return LeaderboardService(leaderboard_repo=repo), repo


# ===========================================================================
# global_top
# ===========================================================================


def test_global_top_calls_repo_with_default_limit_100() -> None:
    service, repo = _build_service()
    repo.top_global.return_value = []

    service.global_top()

    repo.top_global.assert_called_once_with(limit=100)


def test_global_top_forwards_explicit_limit() -> None:
    service, repo = _build_service()
    repo.top_global.return_value = []

    service.global_top(limit=10)

    repo.top_global.assert_called_once_with(limit=10)


def test_global_top_translates_row_to_entry() -> None:
    service, repo = _build_service()
    repo.top_global.return_value = [
        _make_row(user_id=7, display_name="Alice", level=3, xp_window=999),
        _make_row(
            user_id=9,
            display_name="Bob",
            level=1,
            xp_window=200,
            category=Category.SUB_PROFESSIONAL.value,
        ),
    ]

    entries = service.global_top()

    assert entries == [
        LeaderboardEntry(
            user_id=7,
            display_name="Alice",
            level=3,
            xp_window=999,
            category=Category.PROFESSIONAL,
        ),
        LeaderboardEntry(
            user_id=9,
            display_name="Bob",
            level=1,
            xp_window=200,
            category=Category.SUB_PROFESSIONAL,
        ),
    ]


def test_global_top_returns_empty_list_when_no_rows() -> None:
    service, repo = _build_service()
    repo.top_global.return_value = []

    assert service.global_top() == []


# ===========================================================================
# weekly_top
# ===========================================================================


def test_weekly_top_uses_iso_week_bounds_for_supplied_now() -> None:
    """The service must pass ISO-week bounds derived from ``now`` to
    the repository."""
    service, repo = _build_service()
    repo.top_in_window.return_value = []
    # 2025-06-04 is a Wednesday → week starts Mon 2025-06-02.
    now = datetime(2025, 6, 4, 12, 0, tzinfo=timezone.utc)

    service.weekly_top(now=now)

    expected_since, expected_until = iso_week_bounds(now)
    repo.top_in_window.assert_called_once_with(
        since=expected_since, until=expected_until, limit=100
    )


def test_weekly_top_forwards_explicit_limit() -> None:
    service, repo = _build_service()
    repo.top_in_window.return_value = []
    now = datetime(2025, 6, 4, 12, 0, tzinfo=timezone.utc)

    service.weekly_top(now=now, limit=25)

    _, kwargs = repo.top_in_window.call_args
    assert kwargs["limit"] == 25


def test_weekly_top_uses_current_utc_when_now_is_none() -> None:
    service, repo = _build_service()
    repo.top_in_window.return_value = []

    service.weekly_top()

    args, kwargs = repo.top_in_window.call_args
    since = kwargs["since"]
    until = kwargs["until"]
    # Bounds must straddle "now" — i.e. now lies inside the window.
    now = datetime.now(tz=timezone.utc)
    assert since <= now <= until


def test_weekly_top_translates_rows() -> None:
    service, repo = _build_service()
    repo.top_in_window.return_value = [
        _make_row(user_id=1, display_name="Alice", xp_window=70)
    ]
    now = datetime(2025, 6, 4, 12, 0, tzinfo=timezone.utc)

    entries = service.weekly_top(now=now)

    assert entries == [
        LeaderboardEntry(
            user_id=1,
            display_name="Alice",
            level=2,
            xp_window=70,
            category=Category.PROFESSIONAL,
        )
    ]


# ===========================================================================
# monthly_top
# ===========================================================================


def test_monthly_top_uses_calendar_month_bounds_for_supplied_now() -> None:
    service, repo = _build_service()
    repo.top_in_window.return_value = []
    now = datetime(2025, 6, 15, 9, 0, tzinfo=timezone.utc)

    service.monthly_top(now=now)

    expected_since, expected_until = calendar_month_bounds(now)
    repo.top_in_window.assert_called_once_with(
        since=expected_since, until=expected_until, limit=100
    )


def test_monthly_top_forwards_explicit_limit() -> None:
    service, repo = _build_service()
    repo.top_in_window.return_value = []
    now = datetime(2025, 6, 15, tzinfo=timezone.utc)

    service.monthly_top(now=now, limit=50)

    _, kwargs = repo.top_in_window.call_args
    assert kwargs["limit"] == 50


def test_monthly_top_uses_current_utc_when_now_is_none() -> None:
    service, repo = _build_service()
    repo.top_in_window.return_value = []

    service.monthly_top()

    _, kwargs = repo.top_in_window.call_args
    since = kwargs["since"]
    until = kwargs["until"]
    now = datetime.now(tz=timezone.utc)
    assert since <= now <= until


def test_monthly_top_translates_rows() -> None:
    service, repo = _build_service()
    repo.top_in_window.return_value = [
        _make_row(
            user_id=2,
            display_name="Bob",
            level=1,
            xp_window=15,
            category=Category.SUB_PROFESSIONAL.value,
        )
    ]
    now = datetime(2025, 6, 15, tzinfo=timezone.utc)

    entries = service.monthly_top(now=now)

    assert entries == [
        LeaderboardEntry(
            user_id=2,
            display_name="Bob",
            level=1,
            xp_window=15,
            category=Category.SUB_PROFESSIONAL,
        )
    ]
