"""ISO-week and calendar-month bound resolvers (Task 14.1, design A5).

The leaderboard windowing rules from Req 12.2 / 12.3 are:

- Weekly: Monday 00:00 UTC through Sunday 23:59:59.999999 UTC of the
  ISO week containing ``now_utc``.
- Monthly: first day 00:00 UTC through the last microsecond of the
  last day of the calendar month containing ``now_utc`` (UTC).

Both helpers are pure functions; they normalize ``now_utc`` to UTC
before computing bounds, so callers may pass either a tz-aware
datetime in any zone or a naive datetime that's intended as UTC. The
returned bounds are always tz-aware UTC datetimes ready to plug into
:meth:`~app.features.xp.repository.XPRepository.sum_in_window` or the
``BETWEEN``-style filter the leaderboard repository uses.

The bounds are inclusive on both ends. The ``end`` value is one
microsecond before the next-period boundary so a ``BETWEEN since AND
until`` filter cannot accidentally pull in events stamped at the
next-period start.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


def _to_utc(now: datetime) -> datetime:
    """Return ``now`` as a tz-aware UTC datetime.

    Naive inputs are interpreted as UTC; aware inputs in any zone are
    converted. The leaderboard windowing rules are defined in UTC, so
    every downstream comparison uses the converted value.
    """
    if now.tzinfo is None:
        return now.replace(tzinfo=timezone.utc)
    return now.astimezone(timezone.utc)


def iso_week_bounds(now_utc: datetime) -> tuple[datetime, datetime]:
    """Return ``(since_utc, until_utc)`` bounding the ISO week of ``now_utc``.

    Per design A5: Monday 00:00:00.000000 UTC to Sunday
    23:59:59.999999 UTC. ISO weekday Monday=1..Sunday=7.

    Examples:
        >>> from datetime import datetime, timezone
        >>> # 2025-06-04 is a Wednesday; the ISO week starts 2025-06-02 Mon.
        >>> wed = datetime(2025, 6, 4, 12, 0, tzinfo=timezone.utc)
        >>> start, end = iso_week_bounds(wed)
        >>> (start.year, start.month, start.day, start.weekday())
        (2025, 6, 2, 0)
        >>> (end.year, end.month, end.day, end.weekday())
        (2025, 6, 8, 6)
    """
    today = _to_utc(now_utc)
    # ``isoweekday()``: Monday=1..Sunday=7. Subtract (n-1) days to land
    # on Monday of the same ISO week.
    monday = (today - timedelta(days=today.isoweekday() - 1)).replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
        tzinfo=timezone.utc,
    )
    sunday_end = monday + timedelta(days=7) - timedelta(microseconds=1)
    return monday, sunday_end


def calendar_month_bounds(now_utc: datetime) -> tuple[datetime, datetime]:
    """Return ``(since_utc, until_utc)`` bounding the calendar month of ``now_utc``.

    Per design A5: first-of-month 00:00:00.000000 UTC to last day
    23:59:59.999999 UTC. December rolls forward to January of the
    following year for the ``end`` calculation; February's last day
    derives from ``next_month - 1µs`` so leap years (29 days) and
    common years (28 days) both come out correct without a calendar
    table.

    Examples:
        >>> from datetime import datetime, timezone
        >>> # December 2025 — rollover to 2026 January.
        >>> mid_dec = datetime(2025, 12, 15, 9, 0, tzinfo=timezone.utc)
        >>> start, end = calendar_month_bounds(mid_dec)
        >>> (start.year, start.month, start.day)
        (2025, 12, 1)
        >>> (end.year, end.month, end.day)
        (2025, 12, 31)
        >>> # 2024 is a leap year.
        >>> feb_2024 = datetime(2024, 2, 10, tzinfo=timezone.utc)
        >>> _, leap_end = calendar_month_bounds(feb_2024)
        >>> leap_end.day
        29
    """
    today = _to_utc(now_utc)
    start = today.replace(
        day=1,
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )
    if start.month == 12:
        next_month = start.replace(year=start.year + 1, month=1)
    else:
        next_month = start.replace(month=start.month + 1)
    end = next_month - timedelta(microseconds=1)
    return start, end
