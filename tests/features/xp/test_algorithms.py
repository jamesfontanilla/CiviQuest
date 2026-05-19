"""Unit tests for XP algorithms (Task 9.2).

Two pure-function modules to exercise:

- :mod:`app.features.xp.algorithms.level` — the cumulative XP -> level
  mapping per design A3.
- :mod:`app.features.xp.algorithms.streak` — the streak rollover and
  decay-on-read primitives per design A4.

These tests run without a DB; the streak tests construct
:class:`UserXP` instances detached from any session.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from app.features.users.models import AccountState, Category, Role, User
from app.features.xp.algorithms.level import level_of
from app.features.xp.algorithms.streak import (
    on_qualifying_activity,
    streak_for_read,
)
from app.features.xp.models import UserXP


# --- factories --------------------------------------------------------------


def _make_user(*, tz_name: str = "UTC") -> User:
    return User(
        id=1,
        email="alice@example.com",
        display_name="Alice",
        age=25,
        category=Category.PROFESSIONAL.value,
        role=Role.LEARNER.value,
        account_state=AccountState.VERIFIED.value,
        is_banned=False,
        tz_name=tz_name,
        password_hash="x",
        cross_category_preview=False,
    )


def _make_user_xp(
    *,
    streak_count: int = 0,
    last_activity_at: datetime | None = None,
    last_streak_day: date | None = None,
) -> UserXP:
    return UserXP(
        user_id=1,
        cumulative_xp=0,
        level=0,
        level_reached_at=None,
        streak_count=streak_count,
        last_activity_at=last_activity_at,
        last_streak_day=last_streak_day,
    )


# ===========================================================================
# level_of
# ===========================================================================


def test_level_of_zero_xp() -> None:
    assert level_of(0) == 0


def test_level_of_just_below_level_1_threshold() -> None:
    assert level_of(99) == 0


def test_level_of_at_level_1_threshold() -> None:
    """Level 1: 50 * 1 * 2 = 100."""
    assert level_of(100) == 1


def test_level_of_just_below_level_2_threshold() -> None:
    assert level_of(299) == 1


def test_level_of_at_level_2_threshold() -> None:
    """Level 2: 50 * 2 * 3 = 300."""
    assert level_of(300) == 2


def test_level_of_at_level_3_threshold() -> None:
    """Level 3: 50 * 3 * 4 = 600."""
    assert level_of(600) == 3


def test_level_of_at_level_4_threshold() -> None:
    """Level 4: 50 * 4 * 5 = 1000."""
    assert level_of(1000) == 4


def test_level_of_high_value_is_monotonic() -> None:
    """Sanity check at the high end: 50 * 50 * 51 = 127500 ⇒ level 50."""
    assert level_of(127_500) == 50
    assert level_of(127_499) == 49


def test_level_of_negative_returns_zero() -> None:
    """Defensive: negative inputs (shouldn't happen post-clamp) ⇒ 0."""
    assert level_of(-100) == 0


# ===========================================================================
# on_qualifying_activity
# ===========================================================================


def test_on_qualifying_activity_first_ever_returns_streak_1_with_award() -> None:
    user = _make_user()
    user_xp = _make_user_xp()
    now = datetime(2025, 6, 1, 10, 0, tzinfo=timezone.utc)

    new_streak, award = on_qualifying_activity(
        user=user, user_xp=user_xp, now_utc=now
    )

    assert new_streak == 1
    assert award is True


def test_on_qualifying_activity_same_day_no_change() -> None:
    """Activity twice on the same calendar day in user tz: no change."""
    user = _make_user(tz_name="UTC")
    last_activity = datetime(2025, 6, 1, 8, 0, tzinfo=timezone.utc)
    user_xp = _make_user_xp(
        streak_count=3,
        last_activity_at=last_activity,
        last_streak_day=date(2025, 6, 1),
    )
    now = datetime(2025, 6, 1, 20, 0, tzinfo=timezone.utc)

    new_streak, award = on_qualifying_activity(
        user=user, user_xp=user_xp, now_utc=now
    )

    assert new_streak == 3
    assert award is False


def test_on_qualifying_activity_next_day_within_36h_extends() -> None:
    user = _make_user(tz_name="UTC")
    last_activity = datetime(2025, 6, 1, 22, 0, tzinfo=timezone.utc)
    user_xp = _make_user_xp(
        streak_count=4,
        last_activity_at=last_activity,
        last_streak_day=date(2025, 6, 1),
    )
    # 14h later — next calendar day, within 36h.
    now = datetime(2025, 6, 2, 12, 0, tzinfo=timezone.utc)

    new_streak, award = on_qualifying_activity(
        user=user, user_xp=user_xp, now_utc=now
    )

    assert new_streak == 5
    assert award is True


def test_on_qualifying_activity_gap_over_36h_resets() -> None:
    user = _make_user(tz_name="UTC")
    last_activity = datetime(2025, 6, 1, 8, 0, tzinfo=timezone.utc)
    user_xp = _make_user_xp(
        streak_count=10,
        last_activity_at=last_activity,
        last_streak_day=date(2025, 6, 1),
    )
    # Next calendar day BUT 50h later.
    now = last_activity + timedelta(hours=50)

    new_streak, award = on_qualifying_activity(
        user=user, user_xp=user_xp, now_utc=now
    )

    # > 36h gap ⇒ reset to 1, award fires (fresh start day).
    assert new_streak == 1
    assert award is True


def test_on_qualifying_activity_two_calendar_days_later_resets() -> None:
    user = _make_user(tz_name="UTC")
    last_activity = datetime(2025, 6, 1, 12, 0, tzinfo=timezone.utc)
    user_xp = _make_user_xp(
        streak_count=7,
        last_activity_at=last_activity,
        last_streak_day=date(2025, 6, 1),
    )
    # Two calendar days later — fails the next-day branch.
    now = datetime(2025, 6, 3, 10, 0, tzinfo=timezone.utc)

    new_streak, award = on_qualifying_activity(
        user=user, user_xp=user_xp, now_utc=now
    )

    assert new_streak == 1
    assert award is True


def test_on_qualifying_activity_respects_user_timezone() -> None:
    """A user in Asia/Manila experiences a calendar-day flip earlier
    (UTC+8) than a UTC user would. Confirm the local-tz date drives the
    decision."""
    user = _make_user(tz_name="Asia/Manila")
    # Last activity at 2025-06-01 18:00 UTC = 2025-06-02 02:00 Manila.
    last_activity = datetime(2025, 6, 1, 18, 0, tzinfo=timezone.utc)
    user_xp = _make_user_xp(
        streak_count=1,
        last_activity_at=last_activity,
        last_streak_day=date(2025, 6, 2),  # Manila-local
    )
    # Now 2025-06-02 19:00 UTC = 2025-06-03 03:00 Manila — next
    # Manila-local day, 25h after the last activity.
    now = datetime(2025, 6, 2, 19, 0, tzinfo=timezone.utc)

    new_streak, award = on_qualifying_activity(
        user=user, user_xp=user_xp, now_utc=now
    )

    assert new_streak == 2
    assert award is True


def test_on_qualifying_activity_naive_last_activity_treated_as_utc() -> None:
    """SQLite drops tz on round-trip; the algorithm must tolerate naive
    ``last_activity_at`` and treat it as UTC."""
    user = _make_user(tz_name="UTC")
    naive_last = datetime(2025, 6, 1, 22, 0)  # tz-naive, intended UTC
    user_xp = _make_user_xp(
        streak_count=2,
        last_activity_at=naive_last,
        last_streak_day=date(2025, 6, 1),
    )
    now = datetime(2025, 6, 2, 12, 0, tzinfo=timezone.utc)

    new_streak, award = on_qualifying_activity(
        user=user, user_xp=user_xp, now_utc=now
    )

    assert new_streak == 3
    assert award is True


# ===========================================================================
# streak_for_read
# ===========================================================================


def test_streak_for_read_zero_when_no_activity() -> None:
    user = _make_user()
    user_xp = _make_user_xp(streak_count=0, last_activity_at=None)
    now = datetime(2025, 6, 1, tzinfo=timezone.utc)

    assert streak_for_read(user=user, user_xp=user_xp, now_utc=now) == 0


def test_streak_for_read_returns_count_within_36h() -> None:
    user = _make_user()
    last = datetime(2025, 6, 1, 12, 0, tzinfo=timezone.utc)
    user_xp = _make_user_xp(streak_count=4, last_activity_at=last)
    now = last + timedelta(hours=10)

    assert streak_for_read(user=user, user_xp=user_xp, now_utc=now) == 4


def test_streak_for_read_decays_to_zero_after_36h() -> None:
    """Req 11.6 — gap > 36h since last activity ⇒ streak = 0 on read."""
    user = _make_user()
    last = datetime(2025, 6, 1, 12, 0, tzinfo=timezone.utc)
    user_xp = _make_user_xp(streak_count=10, last_activity_at=last)
    now = last + timedelta(hours=37)

    assert streak_for_read(user=user, user_xp=user_xp, now_utc=now) == 0


def test_streak_for_read_at_36h_boundary_does_not_decay() -> None:
    """Boundary: gap exactly 36h ⇒ still active (the decay rule is
    strictly > 36h)."""
    user = _make_user()
    last = datetime(2025, 6, 1, 12, 0, tzinfo=timezone.utc)
    user_xp = _make_user_xp(streak_count=4, last_activity_at=last)
    now = last + timedelta(hours=36)

    assert streak_for_read(user=user, user_xp=user_xp, now_utc=now) == 4


def test_streak_for_read_handles_naive_last_activity() -> None:
    """SQLite-stripped naive timestamps treated as UTC."""
    user = _make_user()
    naive_last = datetime(2025, 6, 1, 12, 0)
    user_xp = _make_user_xp(streak_count=2, last_activity_at=naive_last)
    now = datetime(2025, 6, 1, 14, 0, tzinfo=timezone.utc)

    assert streak_for_read(user=user, user_xp=user_xp, now_utc=now) == 2
