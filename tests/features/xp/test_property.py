"""Property-based tests for the XP slice (Task 9.4).

Three correctness properties from the design's catalog land here:

- **Property 19 — Level mapping correctness and monotonicity**
  (Req 11.4): for any ``cumulative_xp`` in the supported range,
  ``level_of(xp) == max{N : 50*N*(N+1) <= xp}``; the mapping is
  monotone non-decreasing in ``cumulative_xp``.
- **Property 20 — Streak rollover across multi-tz timelines**
  (Req 11.3, 11.6): for any ``(tz_name, last_state, now_utc)``
  triple the rollover function returns the correct
  ``(streak_count, awarded_streak_xp)`` per the four design A4
  branches.
- **Property 21 — XP monotonicity and closed-source ledger**
  (Req 11.1, 11.7): for any sequence of non-correction awards the
  cumulative XP is non-decreasing; for any sequence (including
  ``ADMIN_CORRECTION`` negatives) the cumulative XP stays at ``>= 0``;
  awards with sources outside the closed enum are rejected.

The Hypothesis settings mirror the progress slice's property-test
configuration: ``deadline=None`` because the DB-backed examples are
slower than Hypothesis's default budget, and ``function_scoped_fixture``
suppression because the ``db_session`` fixture is re-used across
generated examples (each example operates on disjoint data).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from fastapi import HTTPException
from hypothesis import HealthCheck, given, settings, strategies as st
from sqlalchemy.orm import Session

from app.features.users.models import (
    AccountState,
    Category,
    Role,
    User,
)
from app.features.users.repository import UserRepository
from app.features.users.schemas import UserCreate
from app.features.xp.algorithms.level import level_of
from app.features.xp.algorithms.streak import on_qualifying_activity
from app.features.xp.models import UserXP, XPSource
from app.features.xp.repository import XPRepository
from app.features.xp.service import XPService


_PBT_SETTINGS = dict(
    max_examples=50,
    deadline=None,
    suppress_health_check=[
        HealthCheck.too_slow,
        HealthCheck.function_scoped_fixture,
    ],
)


# --- helpers --------------------------------------------------------------


def _make_user(*, tz_name: str = "UTC") -> User:
    """Detached :class:`User` for pure-function property tests."""
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


def _persist_user(db: Session, *, email: str = "pbt@example.com") -> User:
    return UserRepository(db=db).create(
        UserCreate(
            email=email,
            display_name="Alice",
            age=25,
            category=Category.PROFESSIONAL.value,
            password="Strong1Pass!",
        ),
        password_hash="bcrypt$fake$hash",
    )


def _reset_xp_state(db: Session) -> None:
    """Clear any rows from prior Hypothesis examples so the next one
    starts on a clean slate. Mirrors the pattern in
    ``tests/features/progress/test_property.py``."""
    from app.features.xp.models import UserXP, XPEvent

    db.query(XPEvent).delete()
    db.query(UserXP).delete()
    db.query(User).delete()
    db.commit()


def _expected_level(cumulative_xp: int) -> int:
    """Brute-force reference: the largest N such that 50*N*(N+1) <= xp.

    Walks N from 0 upward; cheap because the test caps cumulative_xp at
    a few million and ``50*N*(N+1)`` grows quadratically (~316 levels at
    50 million XP).
    """
    if cumulative_xp < 100:
        return 0
    n = 0
    while 50 * (n + 1) * (n + 2) <= cumulative_xp:
        n += 1
    return n


# ===========================================================================
# Property 19: Level mapping correctness and monotonicity
# Validates: Requirements 11.4
# ===========================================================================


@given(cumulative_xp=st.integers(min_value=0, max_value=1_000_000))
@settings(max_examples=200, deadline=None)
def test_property_19_level_mapping_matches_brute_force(
    cumulative_xp: int,
) -> None:
    """Property 19 (Req 11.4): ``level_of`` agrees with the brute-force
    definition for every ``cumulative_xp`` in the supported range."""
    assert level_of(cumulative_xp) == _expected_level(cumulative_xp)


@given(
    xp1=st.integers(min_value=0, max_value=1_000_000),
    xp2=st.integers(min_value=0, max_value=1_000_000),
)
@settings(max_examples=200, deadline=None)
def test_property_19_level_is_monotonic(xp1: int, xp2: int) -> None:
    """Property 19: ``xp1 <= xp2 ⇒ level_of(xp1) <= level_of(xp2)``."""
    lo, hi = sorted([xp1, xp2])
    assert level_of(lo) <= level_of(hi)


# ===========================================================================
# Property 20: Streak rollover across multi-tz timelines
# Validates: Requirements 11.3, 11.6
# ===========================================================================

# A small set of representative timezones spanning sub-/super-UTC offsets so
# the rollover test covers the calendar-day-flip cases.
_TZ_NAMES = st.sampled_from(
    [
        "UTC",
        "Asia/Manila",  # +08:00 (target user base)
        "America/Los_Angeles",  # -08:00 / -07:00 (DST-aware)
        "Europe/London",  # 0 / +01:00 (DST-aware)
    ]
)


@given(
    tz_name=_TZ_NAMES,
    streak_count=st.integers(min_value=1, max_value=30),
    base_naive=st.datetimes(
        min_value=datetime(2025, 2, 1),
        max_value=datetime(2025, 11, 1),
    ),
    delta_hours=st.integers(min_value=0, max_value=80),
)
@settings(**_PBT_SETTINGS)
def test_property_20_streak_rollover_branches(
    tz_name: str,
    streak_count: int,
    base_naive: datetime,
    delta_hours: int,
) -> None:
    """Property 20 (Req 11.3, 11.6): for any ``(tz, last_state, now_utc)``,
    the rollover returns the streak count consistent with the four A4
    branches."""
    user = _make_user(tz_name=tz_name)
    last_activity_utc = base_naive.replace(tzinfo=timezone.utc)
    z = ZoneInfo(tz_name)
    last_streak_day = last_activity_utc.astimezone(z).date()
    user_xp = UserXP(
        user_id=1,
        cumulative_xp=0,
        level=0,
        streak_count=streak_count,
        last_activity_at=last_activity_utc,
        last_streak_day=last_streak_day,
    )

    now_utc = last_activity_utc + timedelta(hours=delta_hours)
    today_local = now_utc.astimezone(z).date()

    new_streak, award = on_qualifying_activity(
        user=user, user_xp=user_xp, now_utc=now_utc
    )

    # Reference oracle, mirroring the four A4 branches:
    if today_local == last_streak_day:
        # Same calendar day in user tz: no change.
        assert new_streak == streak_count
        assert award is False
    elif (
        today_local == last_streak_day + timedelta(days=1)
        and (now_utc - last_activity_utc) <= timedelta(hours=36)
    ):
        # Next calendar day, within 36h: extend by 1.
        assert new_streak == streak_count + 1
        assert award is True
    else:
        # Gap > 1 day (or > 36h on next day): reset to 1.
        assert new_streak == 1
        assert award is True


@given(
    tz_name=_TZ_NAMES,
    base_naive=st.datetimes(
        min_value=datetime(2025, 2, 1),
        max_value=datetime(2025, 11, 1),
    ),
)
@settings(**_PBT_SETTINGS)
def test_property_20_first_ever_activity_starts_streak_at_one(
    tz_name: str, base_naive: datetime
) -> None:
    """Property 20 — first-ever-activity branch: ``last_streak_day=None``
    always returns ``(1, True)``."""
    user = _make_user(tz_name=tz_name)
    user_xp = UserXP(user_id=1, last_streak_day=None, last_activity_at=None)
    now = base_naive.replace(tzinfo=timezone.utc)

    new_streak, award = on_qualifying_activity(
        user=user, user_xp=user_xp, now_utc=now
    )

    assert new_streak == 1
    assert award is True


# ===========================================================================
# Property 21: XP monotonicity and closed-source ledger
# Validates: Requirements 11.1, 11.7
# ===========================================================================


_NON_CORRECTION_SOURCES = [
    XPSource.LESSON_FIRST_COMPLETE,
    XPSource.QUIZ_PASS,
    XPSource.QUIZ_PERFECT,
    XPSource.MOCK_PASS,
]


@given(
    sources=st.lists(
        st.sampled_from(_NON_CORRECTION_SOURCES),
        min_size=1,
        max_size=6,
    )
)
@settings(**_PBT_SETTINGS)
def test_property_21_cumulative_xp_non_decreasing_for_non_correction(
    db_session: Session, sources: list[XPSource]
) -> None:
    """Property 21 (Req 11.1): any sequence of non-correction awards
    drives ``cumulative_xp`` non-decreasing (each step ``>= prior``).

    Note: each non-correction award also fires the streak rollover, which
    may insert an additional ``STREAK_DAY`` event. That extra event is
    also non-negative, so the invariant holds either way.
    """
    _reset_xp_state(db_session)
    user = _persist_user(db_session)
    service = XPService(
        xp_repo=XPRepository(db=db_session),
        user_repo=UserRepository(db=db_session),
    )

    last_total = 0
    base = datetime(2025, 6, 1, 12, 0, tzinfo=timezone.utc)
    for i, source in enumerate(sources):
        when = base + timedelta(hours=i)
        _, user_xp = service.award(user=user, source=source, occurred_at=when)
        assert user_xp.cumulative_xp >= last_total
        last_total = user_xp.cumulative_xp


@given(
    earned=st.integers(min_value=0, max_value=500),
    correction=st.integers(min_value=-10_000, max_value=-1),
)
@settings(**_PBT_SETTINGS)
def test_property_21_cumulative_xp_clamped_at_zero_under_corrections(
    db_session: Session, earned: int, correction: int
) -> None:
    """Property 21 (Req 11.7): ``cumulative_xp`` never goes negative,
    even when an ``ADMIN_CORRECTION`` would underflow."""
    _reset_xp_state(db_session)
    user = _persist_user(db_session)
    service = XPService(
        xp_repo=XPRepository(db=db_session),
        user_repo=UserRepository(db=db_session),
    )

    if earned > 0:
        service.award(
            user=user, source=XPSource.QUIZ_PASS, amount=earned
        )
    _, user_xp = service.award(
        user=user, source=XPSource.ADMIN_CORRECTION, amount=correction
    )

    assert user_xp.cumulative_xp >= 0


@given(
    decoy_source=st.text(min_size=1, max_size=32).filter(
        lambda s: s not in {m.value for m in XPSource}
    ),
)
@settings(max_examples=20, deadline=None)
def test_property_21_unknown_source_is_rejected(decoy_source: str) -> None:
    """Property 21 (Req 11.1): awards with sources outside the closed
    enum are rejected before they can hit the DB."""
    from unittest.mock import MagicMock

    xp_repo = MagicMock(spec=XPRepository)
    user_repo = MagicMock(spec=UserRepository)
    service = XPService(xp_repo=xp_repo, user_repo=user_repo)
    user = _make_user()

    with pytest.raises(HTTPException) as exc_info:
        service.award(user=user, source=decoy_source)  # type: ignore[arg-type]

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "invalid_xp_source"
    xp_repo.insert_event_and_recompute.assert_not_called()
