"""Streak rollover and decay-on-read (Task 9.2, design A4).

Two pure functions:

- :func:`on_qualifying_activity` — called by the service layer when an XP
  event from a qualifying source (lesson completion, quiz pass, mock pass)
  fires. Returns ``(new_streak_count, awarded_streak_xp)``. The caller
  is responsible for persisting the new streak fields and for inserting the
  ``STREAK_DAY`` XP event when ``awarded_streak_xp`` is True.
- :func:`streak_for_read` — applies the 36-hour decay rule (Req 11.6) at
  read time. Returns 0 if the gap since ``last_activity_at`` exceeds 36
  hours; otherwise returns the cached ``streak_count``.

Both functions take ``now_utc`` as an explicit argument so property tests
can pin the clock.

Cross-cutting note: SQLite's ``DATETIME`` column strips the timezone offset
on round-trip. The repository writes timezone-aware ``datetime``\\ s but
reads them back naive. We treat naive ``last_activity_at`` values as UTC.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.features.users.models import User
from app.features.xp.models import UserXP


def _ensure_utc(dt: datetime | None) -> datetime | None:
    """Treat naive datetimes from SQLite round-trip as UTC."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def on_qualifying_activity(
    *,
    user: User,
    user_xp: UserXP,
    now_utc: datetime,
) -> tuple[int, bool]:
    """Apply the Req 11.3 streak rollover.

    Args:
        user: The user whose ``tz_name`` defines the calendar-day boundary.
        user_xp: The current cached streak state.
        now_utc: The activity timestamp (UTC).

    Returns:
        ``(new_streak_count, awarded_streak_xp)``. The caller is responsible
        for writing ``new_streak_count`` plus updated ``last_streak_day`` /
        ``last_activity_at`` to the row, and for inserting the corresponding
        ``STREAK_DAY`` XP event when the second tuple element is True.

    Branches (per design A4):

    1. **First activity ever** (``last_streak_day is None``): streak resets
       to 1, award fires.
    2. **Same calendar day as ``last_streak_day``** (in user tz): no change,
       no award. Multiple activities in one day count once.
    3. **Next calendar day AND within 36h** of ``last_activity_at``: streak
       extends by 1, award fires.
    4. **Otherwise** (gap > 1 day or > 36h): streak resets to 1, award
       fires.
    """
    z = ZoneInfo(user.tz_name)
    today_local = now_utc.astimezone(z).date()

    # Branch 1: fresh state.
    if user_xp.last_streak_day is None:
        return (1, True)

    # Branch 2: same local-calendar day.
    if today_local == user_xp.last_streak_day:
        return (user_xp.streak_count, False)

    # Branch 3: next local-calendar day, within 36h on the wall clock.
    last_activity = _ensure_utc(user_xp.last_activity_at)
    if (
        today_local == user_xp.last_streak_day + timedelta(days=1)
        and last_activity is not None
        and (now_utc - last_activity) <= timedelta(hours=36)
    ):
        return (user_xp.streak_count + 1, True)

    # Branch 4: gap too large — reset to 1.
    return (1, True)


def streak_for_read(
    *,
    user: User,  # noqa: ARG001 - kept for symmetric signature with on_qualifying_activity
    user_xp: UserXP,
    now_utc: datetime,
) -> int:
    """Decay-on-read streak count (Req 11.6).

    Returns:
        ``0`` if there is no activity yet OR the gap since
        ``last_activity_at`` exceeds 36 hours; otherwise the cached
        ``streak_count``.

    Note:
        Decay is computed-on-read but **not** persisted. The next write call
        will overwrite ``streak_count`` to the correct value via
        :func:`on_qualifying_activity` (the "gap > 36h ⇒ reset to 1"
        branch). Read-side decay avoids write amplification on every GET.
    """
    last_activity = _ensure_utc(user_xp.last_activity_at)
    if last_activity is None:
        return 0
    if (now_utc - last_activity) > timedelta(hours=36):
        return 0
    return user_xp.streak_count
