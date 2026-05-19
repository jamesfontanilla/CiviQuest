"""Property-based tests for the leaderboard slice (Task 14.3).

One named property from the design's catalog lands here:

- **Property 22 — Leaderboard ordering and eligibility.**
  *For any* user population and XP distribution, the response from
  :meth:`LeaderboardRepository.top_global` /
  :meth:`LeaderboardRepository.top_in_window` is a list of length
  ``<= limit``, sorted by ``(xp_window DESC, level_reached_at ASC
  with NULLs last, user_id ASC)``, containing only learners with
  ``account_state == VERIFIED`` and ``is_banned == False``. Each
  entry is a :class:`LeaderboardRow` with the spec shape
  (``user_id``, ``display_name``, ``level``, ``xp_window``,
  ``category``). Weekly / monthly window math is exercised
  separately by the unit tests in ``test_algorithms.py``; this
  property test pins the ordering + eligibility invariants for both
  the global and window-sum query paths.

The Hypothesis settings mirror the XP slice's PBT configuration.
``function_scoped_fixture`` is suppressed so the ``db_session``
fixture can be shared across generated examples; each example
explicitly clears the relevant tables before seeding so generated
inputs do not leak between examples.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from hypothesis import HealthCheck, given, settings, strategies as st
from sqlalchemy.orm import Session

from app.features.leaderboards.repository import (
    LeaderboardRepository,
    LeaderboardRow,
)
from app.features.users.models import (
    AccountState,
    Category,
    Role,
    User,
)
from app.features.xp.models import UserXP, XPEvent, XPSource


_PBT_SETTINGS = dict(
    max_examples=20,
    deadline=None,
    suppress_health_check=[
        HealthCheck.too_slow,
        HealthCheck.function_scoped_fixture,
    ],
)


# --- helpers --------------------------------------------------------------


def _reset_state(db: Session) -> None:
    """Clear every table this property test writes to."""
    db.query(XPEvent).delete()
    db.query(UserXP).delete()
    db.query(User).delete()
    db.commit()


def _seed_user(
    db: Session,
    *,
    email: str,
    display_name: str,
    is_verified: bool,
    is_banned: bool,
    category: Category,
) -> User:
    user = User(
        email=email,
        display_name=display_name,
        age=25,
        category=category.value,
        role=Role.LEARNER.value,
        account_state=(
            AccountState.VERIFIED.value
            if is_verified
            else AccountState.UNVERIFIED.value
        ),
        is_banned=is_banned,
        tz_name="UTC",
        password_hash="bcrypt$fake$hash",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _set_user_xp(
    db: Session,
    *,
    user_id: int,
    cumulative_xp: int,
    level: int,
    level_reached_at: datetime | None,
) -> None:
    db.add(
        UserXP(
            user_id=user_id,
            cumulative_xp=cumulative_xp,
            level=level,
            level_reached_at=level_reached_at,
        )
    )
    db.commit()


# Strategy for one generated user record. ``cumulative_xp`` is bounded
# at 1_000_000 so the brute-force level computation in the test stays
# fast; ``level_reached_at_offset`` is the offset (in days) from a
# fixed base date — the actual datetime is materialised inside the
# test so Hypothesis can reuse compact integers.
_user_strategy = st.fixed_dictionaries(
    {
        "cumulative_xp": st.integers(min_value=0, max_value=1_000_000),
        "is_verified": st.booleans(),
        "is_banned": st.booleans(),
        "category": st.sampled_from(list(Category)),
        "level": st.integers(min_value=0, max_value=20),
        "level_reached_at_offset": st.one_of(
            st.none(),
            st.integers(min_value=0, max_value=365),
        ),
    }
)


# ===========================================================================
# Property 22: Leaderboard ordering and eligibility (global query)
# Validates: Requirements 12.1, 12.4, 12.5
# ===========================================================================


@given(
    users=st.lists(_user_strategy, min_size=0, max_size=15),
    limit=st.integers(min_value=1, max_value=100),
)
@settings(**_PBT_SETTINGS)
def test_property_22_top_global_invariants(
    db_session: Session,
    users: list[dict],
    limit: int,
) -> None:
    """Property 22 (Req 12.1, 12.4, 12.5): for any seeded user
    population, ``top_global`` returns at most ``limit`` rows, sorts
    by ``(cumulative_xp DESC, level_reached_at ASC nulls-last, user_id
    ASC)``, includes only VERIFIED + not-banned users, and every row
    carries the spec shape."""
    _reset_state(db_session)

    base = datetime(2025, 1, 1, tzinfo=timezone.utc)
    seeded: list[tuple[User, dict]] = []
    for i, spec in enumerate(users):
        u = _seed_user(
            db_session,
            email=f"user{i}@example.com",
            display_name=f"U{i}",
            is_verified=spec["is_verified"],
            is_banned=spec["is_banned"],
            category=spec["category"],
        )
        offset = spec["level_reached_at_offset"]
        ts = base + timedelta(days=offset) if offset is not None else None
        _set_user_xp(
            db_session,
            user_id=u.id,
            cumulative_xp=spec["cumulative_xp"],
            level=spec["level"],
            level_reached_at=ts,
        )
        seeded.append((u, spec))

    rows = LeaderboardRepository(db=db_session).top_global(limit=limit)

    # ---- Length invariant -------------------------------------------------
    assert len(rows) <= limit

    # ---- Eligibility invariant (Req 12.4) --------------------------------
    eligible_ids = {
        u.id
        for u, spec in seeded
        if spec["is_verified"] and not spec["is_banned"]
    }
    for row in rows:
        assert row.user_id in eligible_ids

    # ---- Shape invariant (Req 12.5) --------------------------------------
    for row in rows:
        assert isinstance(row, LeaderboardRow)
        assert isinstance(row.user_id, int)
        assert isinstance(row.display_name, str)
        assert isinstance(row.level, int)
        assert isinstance(row.xp_window, int)
        assert row.category in {c.value for c in Category}

    # ---- Ordering invariant (Req 12.1) -----------------------------------
    # Build the reference ordering: filter eligible, sort by the
    # documented key, then truncate to limit.
    def _level_reached_for(user_id: int) -> datetime | None:
        for u, spec in seeded:
            if u.id == user_id:
                offset = spec["level_reached_at_offset"]
                return (
                    base + timedelta(days=offset)
                    if offset is not None
                    else None
                )
        raise AssertionError("user not found in seeded fixture")

    expected_user_ids = sorted(
        (u.id for u, spec in seeded
         if spec["is_verified"] and not spec["is_banned"]),
        key=lambda uid: (
            -next(s["cumulative_xp"] for u, s in seeded if u.id == uid),
            # NULLS LAST: rows with None timestamp sort after timestamped
            # rows of the same XP. Use ``isinstance(None, ...)``-style
            # boolean key — ``None first => 1``, ``timestamped => 0``,
            # ascending puts timestamped first.
            1 if _level_reached_for(uid) is None else 0,
            _level_reached_for(uid) or datetime.min.replace(tzinfo=timezone.utc),
            uid,
        ),
    )[:limit]

    assert [r.user_id for r in rows] == expected_user_ids


# ===========================================================================
# Property 22: Leaderboard ordering and eligibility (window query)
# Validates: Requirements 12.2, 12.3, 12.4, 12.5
# ===========================================================================


@given(
    users=st.lists(
        st.fixed_dictionaries(
            {
                "is_verified": st.booleans(),
                "is_banned": st.booleans(),
                "category": st.sampled_from(list(Category)),
                "level": st.integers(min_value=0, max_value=10),
                "level_reached_at_offset": st.one_of(
                    st.none(),
                    st.integers(min_value=0, max_value=365),
                ),
                # Each user has 0..3 events, each with a small amount.
                "events": st.lists(
                    st.integers(min_value=1, max_value=200),
                    min_size=0,
                    max_size=3,
                ),
            }
        ),
        min_size=0,
        max_size=10,
    ),
    limit=st.integers(min_value=1, max_value=100),
)
@settings(**_PBT_SETTINGS)
def test_property_22_top_in_window_invariants(
    db_session: Session,
    users: list[dict],
    limit: int,
) -> None:
    """Property 22 (Req 12.2, 12.3, 12.4, 12.5): for any seeded
    population + xp-event distribution, ``top_in_window`` returns at
    most ``limit`` rows ordered by ``(xp_window DESC,
    level_reached_at ASC nulls-last, user_id ASC)``, with only
    VERIFIED + not-banned users and only users with a positive
    window sum, and every row carries the spec shape."""
    _reset_state(db_session)

    # All events fall inside this window so the SUM equals the user's
    # total event amount.
    since = datetime(2025, 6, 1, 0, 0, 0, 0, tzinfo=timezone.utc)
    until = datetime(2025, 6, 30, 23, 59, 59, 999_999, tzinfo=timezone.utc)
    base = datetime(2025, 1, 1, tzinfo=timezone.utc)
    event_when = datetime(2025, 6, 15, 12, 0, tzinfo=timezone.utc)

    seeded: list[tuple[User, dict, int]] = []
    for i, spec in enumerate(users):
        u = _seed_user(
            db_session,
            email=f"user{i}@example.com",
            display_name=f"U{i}",
            is_verified=spec["is_verified"],
            is_banned=spec["is_banned"],
            category=spec["category"],
        )
        offset = spec["level_reached_at_offset"]
        ts = base + timedelta(days=offset) if offset is not None else None
        _set_user_xp(
            db_session,
            user_id=u.id,
            cumulative_xp=sum(spec["events"]),
            level=spec["level"],
            level_reached_at=ts,
        )

        for ev_amount in spec["events"]:
            db_session.add(
                XPEvent(
                    user_id=u.id,
                    source=XPSource.QUIZ_PASS.value,
                    amount=ev_amount,
                    occurred_at=event_when,
                )
            )
        db_session.commit()
        seeded.append((u, spec, sum(spec["events"])))

    rows = LeaderboardRepository(db=db_session).top_in_window(
        since=since, until=until, limit=limit
    )

    # ---- Length invariant -------------------------------------------------
    assert len(rows) <= limit

    # ---- Eligibility invariant (Req 12.4) + zero-sum exclusion ----------
    eligible_with_xp = {
        u.id
        for u, spec, total in seeded
        if spec["is_verified"] and not spec["is_banned"] and total > 0
    }
    for row in rows:
        assert row.user_id in eligible_with_xp
        assert row.xp_window > 0

    # ---- Shape invariant (Req 12.5) --------------------------------------
    for row in rows:
        assert isinstance(row, LeaderboardRow)
        assert isinstance(row.user_id, int)
        assert isinstance(row.display_name, str)
        assert isinstance(row.level, int)
        assert isinstance(row.xp_window, int)
        assert row.category in {c.value for c in Category}

    # ---- Ordering invariant (Req 12.2 / 12.3) ---------------------------
    def _level_reached_for(user_id: int) -> datetime | None:
        for u, spec, _total in seeded:
            if u.id == user_id:
                offset = spec["level_reached_at_offset"]
                return (
                    base + timedelta(days=offset)
                    if offset is not None
                    else None
                )
        raise AssertionError("user not found in seeded fixture")

    def _total_for(user_id: int) -> int:
        for u, _spec, total in seeded:
            if u.id == user_id:
                return total
        raise AssertionError("user not found in seeded fixture")

    expected_user_ids = sorted(
        (u.id for u, spec, total in seeded
         if spec["is_verified"] and not spec["is_banned"] and total > 0),
        key=lambda uid: (
            -_total_for(uid),
            1 if _level_reached_for(uid) is None else 0,
            _level_reached_for(uid) or datetime.min.replace(tzinfo=timezone.utc),
            uid,
        ),
    )[:limit]

    assert [r.user_id for r in rows] == expected_user_ids
