"""Unit tests for leaderboard windowing primitives (Task 14.1).

Pure-function checks for :func:`iso_week_bounds` and
:func:`calendar_month_bounds`. These are the bounds passed into
:meth:`LeaderboardRepository.top_in_window`; getting them wrong means
the weekly / monthly leaderboards include or exclude events on the
wrong day.

Coverage targets:

- ISO-week boundaries: Sunday -> Monday rollover (the ISO week ends on
  Sunday, so the rollover is right at midnight Mon UTC), mid-week,
  exactly-Monday-00:00, exactly-Sunday-end-of-day.
- Calendar-month boundaries: first-of-month, mid-month, last-of-month,
  December → January rollover, leap-year February.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.features.leaderboards.algorithms.windowing import (
    calendar_month_bounds,
    iso_week_bounds,
)


# ===========================================================================
# iso_week_bounds
# ===========================================================================


def test_iso_week_bounds_for_midweek_wednesday() -> None:
    """2025-06-04 is Wednesday — ISO week starts Monday 2025-06-02."""
    wed = datetime(2025, 6, 4, 12, 30, tzinfo=timezone.utc)

    start, end = iso_week_bounds(wed)

    assert start == datetime(2025, 6, 2, 0, 0, 0, 0, tzinfo=timezone.utc)
    # End is Sunday 2025-06-08 23:59:59.999999.
    assert end == datetime(
        2025, 6, 8, 23, 59, 59, 999_999, tzinfo=timezone.utc
    )


def test_iso_week_bounds_when_now_is_monday_midnight() -> None:
    """``now`` exactly at the start of the ISO week — bounds are
    ``[now, now + 7d - 1us]``."""
    monday = datetime(2025, 6, 2, 0, 0, 0, 0, tzinfo=timezone.utc)

    start, end = iso_week_bounds(monday)

    assert start == monday
    assert end == datetime(
        2025, 6, 8, 23, 59, 59, 999_999, tzinfo=timezone.utc
    )


def test_iso_week_bounds_when_now_is_sunday_end_of_day() -> None:
    """``now`` at the very last microsecond of Sunday — still in the
    same ISO week."""
    sunday_end = datetime(
        2025, 6, 8, 23, 59, 59, 999_999, tzinfo=timezone.utc
    )

    start, end = iso_week_bounds(sunday_end)

    assert start == datetime(2025, 6, 2, 0, 0, 0, 0, tzinfo=timezone.utc)
    assert end == sunday_end


def test_iso_week_bounds_when_now_is_just_after_sunday_end() -> None:
    """One microsecond after Sunday end ⇒ next ISO week."""
    next_monday = datetime(
        2025, 6, 9, 0, 0, 0, 0, tzinfo=timezone.utc
    )

    start, end = iso_week_bounds(next_monday)

    assert start == next_monday
    assert end == datetime(
        2025, 6, 15, 23, 59, 59, 999_999, tzinfo=timezone.utc
    )


def test_iso_week_bounds_handles_naive_datetime_as_utc() -> None:
    """A tz-naive input is treated as UTC."""
    naive_wed = datetime(2025, 6, 4, 12, 30)

    start, end = iso_week_bounds(naive_wed)

    assert start == datetime(2025, 6, 2, 0, 0, 0, 0, tzinfo=timezone.utc)
    assert end == datetime(
        2025, 6, 8, 23, 59, 59, 999_999, tzinfo=timezone.utc
    )


def test_iso_week_bounds_normalizes_non_utc_aware_input() -> None:
    """A tz-aware non-UTC input is converted to UTC before computing."""
    # 2025-06-09 06:00 Manila (+08) == 2025-06-08 22:00 UTC == still
    # the previous ISO week (Mon 2025-06-02 .. Sun 2025-06-08).
    manila = datetime(
        2025, 6, 9, 6, 0, tzinfo=ZoneInfo("Asia/Manila")
    )

    start, end = iso_week_bounds(manila)

    assert start == datetime(2025, 6, 2, 0, 0, 0, 0, tzinfo=timezone.utc)
    assert end == datetime(
        2025, 6, 8, 23, 59, 59, 999_999, tzinfo=timezone.utc
    )


def test_iso_week_bounds_span_is_exactly_seven_days_minus_one_microsecond() -> None:
    """The window is end-inclusive; ``end - start`` should be 7d - 1µs."""
    sample = datetime(2025, 1, 15, tzinfo=timezone.utc)

    start, end = iso_week_bounds(sample)

    assert end - start == timedelta(days=7) - timedelta(microseconds=1)


# ===========================================================================
# calendar_month_bounds
# ===========================================================================


def test_calendar_month_bounds_for_mid_month() -> None:
    mid_june = datetime(2025, 6, 15, 9, 0, tzinfo=timezone.utc)

    start, end = calendar_month_bounds(mid_june)

    assert start == datetime(2025, 6, 1, 0, 0, 0, 0, tzinfo=timezone.utc)
    assert end == datetime(
        2025, 6, 30, 23, 59, 59, 999_999, tzinfo=timezone.utc
    )


def test_calendar_month_bounds_for_first_of_month() -> None:
    first = datetime(2025, 6, 1, 0, 0, tzinfo=timezone.utc)

    start, end = calendar_month_bounds(first)

    assert start == first
    assert end == datetime(
        2025, 6, 30, 23, 59, 59, 999_999, tzinfo=timezone.utc
    )


def test_calendar_month_bounds_for_last_of_month() -> None:
    """Last day at the end of the day still falls inside this month."""
    last = datetime(
        2025, 6, 30, 23, 59, 59, 999_999, tzinfo=timezone.utc
    )

    start, end = calendar_month_bounds(last)

    assert start == datetime(2025, 6, 1, 0, 0, 0, 0, tzinfo=timezone.utc)
    assert end == last


def test_calendar_month_bounds_for_december_rolls_to_january() -> None:
    """December's ``next_month`` is January of the following year."""
    mid_dec = datetime(2025, 12, 15, 12, 0, tzinfo=timezone.utc)

    start, end = calendar_month_bounds(mid_dec)

    assert start == datetime(2025, 12, 1, 0, 0, 0, 0, tzinfo=timezone.utc)
    assert end == datetime(
        2025, 12, 31, 23, 59, 59, 999_999, tzinfo=timezone.utc
    )


def test_calendar_month_bounds_for_february_leap_year() -> None:
    """2024 is a leap year — February has 29 days."""
    feb_2024 = datetime(2024, 2, 14, tzinfo=timezone.utc)

    start, end = calendar_month_bounds(feb_2024)

    assert start == datetime(2024, 2, 1, 0, 0, 0, 0, tzinfo=timezone.utc)
    assert end == datetime(
        2024, 2, 29, 23, 59, 59, 999_999, tzinfo=timezone.utc
    )


def test_calendar_month_bounds_for_february_common_year() -> None:
    """2025 is a common year — February has 28 days."""
    feb_2025 = datetime(2025, 2, 14, tzinfo=timezone.utc)

    start, end = calendar_month_bounds(feb_2025)

    assert start == datetime(2025, 2, 1, 0, 0, 0, 0, tzinfo=timezone.utc)
    assert end == datetime(
        2025, 2, 28, 23, 59, 59, 999_999, tzinfo=timezone.utc
    )


def test_calendar_month_bounds_handles_naive_datetime_as_utc() -> None:
    naive = datetime(2025, 6, 15, 9, 0)

    start, end = calendar_month_bounds(naive)

    assert start == datetime(2025, 6, 1, 0, 0, 0, 0, tzinfo=timezone.utc)
    assert end == datetime(
        2025, 6, 30, 23, 59, 59, 999_999, tzinfo=timezone.utc
    )


def test_calendar_month_bounds_normalizes_non_utc_aware_input() -> None:
    """2025-07-01 06:00 Manila == 2025-06-30 22:00 UTC ⇒ June bounds."""
    manila = datetime(
        2025, 7, 1, 6, 0, tzinfo=ZoneInfo("Asia/Manila")
    )

    start, end = calendar_month_bounds(manila)

    assert start == datetime(2025, 6, 1, 0, 0, 0, 0, tzinfo=timezone.utc)
    assert end == datetime(
        2025, 6, 30, 23, 59, 59, 999_999, tzinfo=timezone.utc
    )
