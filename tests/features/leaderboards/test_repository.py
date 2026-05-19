"""Repository tests for the leaderboard slice (Task 14.1).

Per ``testing-standards.md`` repository tests run against in-memory
SQLite. Each test seeds real :class:`User` rows + a mix of cached
:class:`UserXP` rows / :class:`XPEvent` ledger rows, and drives
:class:`LeaderboardRepository` directly.

Coverage:

- ``top_global``: ordering by ``cumulative_xp DESC``, tie-break on
  earliest ``level_reached_at`` then ``user_id``, NULLS LAST for
  never-leveled-up rows, exclusion of UNVERIFIED + banned users,
  ``limit`` cap.
- ``top_in_window``: per-user SUM over ``[since, until]``, ordering,
  tie-break, exclusion rules, zero-XP exclusion (the window-empty
  user must not appear), ``limit`` cap.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

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


# --- helpers ---------------------------------------------------------------


def _make_user(
    db: Session,
    *,
    email: str,
    display_name: str = "User",
    category: Category = Category.PROFESSIONAL,
    account_state: AccountState = AccountState.VERIFIED,
    is_banned: bool = False,
) -> User:
    """Persist a :class:`User` directly (no signup-validation
    round-trip) so tests can mint banned/unverified rows easily."""
    user = User(
        email=email,
        display_name=display_name,
        age=25,
        category=category.value,
        role=Role.LEARNER.value,
        account_state=account_state.value,
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
    level: int = 0,
    level_reached_at: datetime | None = None,
) -> UserXP:
    row = UserXP(
        user_id=user_id,
        cumulative_xp=cumulative_xp,
        level=level,
        level_reached_at=level_reached_at,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _add_xp_event(
    db: Session,
    *,
    user_id: int,
    amount: int,
    occurred_at: datetime,
    source: XPSource = XPSource.QUIZ_PASS,
) -> XPEvent:
    event = XPEvent(
        user_id=user_id,
        source=source.value,
        amount=amount,
        occurred_at=occurred_at,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


# ===========================================================================
# top_global
# ===========================================================================


def test_top_global_returns_empty_list_when_no_users(
    db_session: Session,
) -> None:
    repo = LeaderboardRepository(db=db_session)
    assert repo.top_global() == []


def test_top_global_orders_by_cumulative_xp_desc(
    db_session: Session,
) -> None:
    alice = _make_user(db_session, email="alice@example.com", display_name="Alice")
    bob = _make_user(db_session, email="bob@example.com", display_name="Bob")
    carol = _make_user(db_session, email="carol@example.com", display_name="Carol")
    _set_user_xp(db_session, user_id=alice.id, cumulative_xp=100)
    _set_user_xp(db_session, user_id=bob.id, cumulative_xp=500)
    _set_user_xp(db_session, user_id=carol.id, cumulative_xp=250)

    rows = LeaderboardRepository(db=db_session).top_global()

    assert [r.display_name for r in rows] == ["Bob", "Carol", "Alice"]
    assert [r.xp_window for r in rows] == [500, 250, 100]


def test_top_global_returns_correct_row_shape(db_session: Session) -> None:
    """Row carries display_name, level, xp_window=cumulative, category."""
    alice = _make_user(
        db_session,
        email="alice@example.com",
        display_name="Alice",
        category=Category.SUB_PROFESSIONAL,
    )
    _set_user_xp(
        db_session,
        user_id=alice.id,
        cumulative_xp=420,
        level=2,
        level_reached_at=datetime(2025, 6, 1, tzinfo=timezone.utc),
    )

    rows = LeaderboardRepository(db=db_session).top_global()

    assert rows == [
        LeaderboardRow(
            user_id=alice.id,
            display_name="Alice",
            level=2,
            xp_window=420,
            category=Category.SUB_PROFESSIONAL.value,
        )
    ]


def test_top_global_tie_break_uses_earlier_level_reached_at(
    db_session: Session,
) -> None:
    """Two users with equal XP — the earlier level-up wins the tie."""
    earlier = _make_user(
        db_session, email="earlier@example.com", display_name="Earlier"
    )
    later = _make_user(
        db_session, email="later@example.com", display_name="Later"
    )
    _set_user_xp(
        db_session,
        user_id=earlier.id,
        cumulative_xp=300,
        level=2,
        level_reached_at=datetime(2025, 5, 1, tzinfo=timezone.utc),
    )
    _set_user_xp(
        db_session,
        user_id=later.id,
        cumulative_xp=300,
        level=2,
        level_reached_at=datetime(2025, 6, 1, tzinfo=timezone.utc),
    )

    rows = LeaderboardRepository(db=db_session).top_global()

    assert [r.display_name for r in rows] == ["Earlier", "Later"]


def test_top_global_tie_break_falls_back_to_user_id(
    db_session: Session,
) -> None:
    """Equal XP and equal (or both null) level_reached_at: lowest
    user_id wins."""
    first = _make_user(db_session, email="first@example.com", display_name="First")
    second = _make_user(db_session, email="second@example.com", display_name="Second")
    same_ts = datetime(2025, 5, 1, tzinfo=timezone.utc)
    _set_user_xp(
        db_session, user_id=first.id, cumulative_xp=200, level=1, level_reached_at=same_ts
    )
    _set_user_xp(
        db_session, user_id=second.id, cumulative_xp=200, level=1, level_reached_at=same_ts
    )

    rows = LeaderboardRepository(db=db_session).top_global()

    assert rows[0].user_id == first.id
    assert rows[1].user_id == second.id


def test_top_global_nulls_last_for_level_reached_at(db_session: Session) -> None:
    """A row with NULL ``level_reached_at`` (never leveled up) sorts
    after a row with a timestamped level-up at the same XP."""
    timestamped = _make_user(
        db_session, email="ts@example.com", display_name="TS"
    )
    never_leveled = _make_user(
        db_session, email="nul@example.com", display_name="NUL"
    )
    _set_user_xp(
        db_session,
        user_id=timestamped.id,
        cumulative_xp=50,
        level=0,
        level_reached_at=datetime(2025, 5, 1, tzinfo=timezone.utc),
    )
    _set_user_xp(
        db_session,
        user_id=never_leveled.id,
        cumulative_xp=50,
        level=0,
        level_reached_at=None,
    )

    rows = LeaderboardRepository(db=db_session).top_global()

    assert [r.display_name for r in rows] == ["TS", "NUL"]


def test_top_global_excludes_unverified_users(db_session: Session) -> None:
    verified = _make_user(
        db_session,
        email="verified@example.com",
        display_name="V",
        account_state=AccountState.VERIFIED,
    )
    unverified = _make_user(
        db_session,
        email="unverified@example.com",
        display_name="U",
        account_state=AccountState.UNVERIFIED,
    )
    _set_user_xp(db_session, user_id=verified.id, cumulative_xp=10)
    _set_user_xp(db_session, user_id=unverified.id, cumulative_xp=99999)

    rows = LeaderboardRepository(db=db_session).top_global()

    assert [r.display_name for r in rows] == ["V"]


def test_top_global_excludes_banned_users(db_session: Session) -> None:
    clean = _make_user(db_session, email="clean@example.com", display_name="Clean")
    banned = _make_user(
        db_session, email="banned@example.com", display_name="Banned", is_banned=True
    )
    _set_user_xp(db_session, user_id=clean.id, cumulative_xp=10)
    _set_user_xp(db_session, user_id=banned.id, cumulative_xp=99999)

    rows = LeaderboardRepository(db=db_session).top_global()

    assert [r.display_name for r in rows] == ["Clean"]


def test_top_global_respects_limit(db_session: Session) -> None:
    for i in range(150):
        u = _make_user(
            db_session, email=f"u{i}@example.com", display_name=f"U{i}"
        )
        _set_user_xp(db_session, user_id=u.id, cumulative_xp=1000 - i)

    rows_default = LeaderboardRepository(db=db_session).top_global()
    rows_5 = LeaderboardRepository(db=db_session).top_global(limit=5)

    assert len(rows_default) == 100
    assert len(rows_5) == 5
    # Ordering preserved across limits — top-5 must match the first 5
    # of the top-100.
    assert [r.user_id for r in rows_5] == [r.user_id for r in rows_default[:5]]


def test_top_global_user_without_user_xp_row_is_excluded(
    db_session: Session,
) -> None:
    """A learner who has never earned XP has no UserXP cache row.
    The INNER JOIN drops them — they should not appear in the
    leaderboard."""
    alice = _make_user(db_session, email="alice@example.com", display_name="Alice")
    _make_user(db_session, email="ghost@example.com", display_name="Ghost")
    _set_user_xp(db_session, user_id=alice.id, cumulative_xp=100)

    rows = LeaderboardRepository(db=db_session).top_global()

    assert [r.display_name for r in rows] == ["Alice"]


# ===========================================================================
# top_in_window
# ===========================================================================


def test_top_in_window_returns_empty_when_no_events(db_session: Session) -> None:
    alice = _make_user(db_session, email="alice@example.com", display_name="Alice")
    _set_user_xp(db_session, user_id=alice.id, cumulative_xp=999)

    rows = LeaderboardRepository(db=db_session).top_in_window(
        since=datetime(2025, 6, 1, tzinfo=timezone.utc),
        until=datetime(2025, 6, 30, tzinfo=timezone.utc),
    )

    assert rows == []


def test_top_in_window_sums_per_user_inside_window(db_session: Session) -> None:
    alice = _make_user(db_session, email="alice@example.com", display_name="Alice")
    bob = _make_user(db_session, email="bob@example.com", display_name="Bob")
    _set_user_xp(db_session, user_id=alice.id, cumulative_xp=1000)
    _set_user_xp(db_session, user_id=bob.id, cumulative_xp=200)

    base = datetime(2025, 6, 15, 12, 0, tzinfo=timezone.utc)
    # Alice earns 30 in-window, 100 out-of-window.
    _add_xp_event(db_session, user_id=alice.id, amount=30, occurred_at=base)
    _add_xp_event(
        db_session,
        user_id=alice.id,
        amount=100,
        occurred_at=base - timedelta(days=10),
    )
    # Bob earns 50 in-window.
    _add_xp_event(
        db_session,
        user_id=bob.id,
        amount=50,
        occurred_at=base + timedelta(hours=1),
    )

    rows = LeaderboardRepository(db=db_session).top_in_window(
        since=base - timedelta(days=1),
        until=base + timedelta(days=1),
    )

    assert [r.display_name for r in rows] == ["Bob", "Alice"]
    assert [r.xp_window for r in rows] == [50, 30]


def test_top_in_window_excludes_users_with_zero_window_sum(
    db_session: Session,
) -> None:
    """A learner with no XP in the window must not appear."""
    alice = _make_user(db_session, email="alice@example.com", display_name="Alice")
    bob = _make_user(db_session, email="bob@example.com", display_name="Bob")
    _set_user_xp(db_session, user_id=alice.id, cumulative_xp=500)
    _set_user_xp(db_session, user_id=bob.id, cumulative_xp=0)

    base = datetime(2025, 6, 15, 12, 0, tzinfo=timezone.utc)
    _add_xp_event(db_session, user_id=alice.id, amount=10, occurred_at=base)
    # Bob earns 0 in-window (no events in range).
    _add_xp_event(
        db_session,
        user_id=bob.id,
        amount=20,
        occurred_at=base - timedelta(days=10),
    )

    rows = LeaderboardRepository(db=db_session).top_in_window(
        since=base - timedelta(hours=1),
        until=base + timedelta(hours=1),
    )

    assert [r.display_name for r in rows] == ["Alice"]


def test_top_in_window_inclusive_at_both_ends(db_session: Session) -> None:
    """Events stamped exactly at ``since`` or exactly at ``until`` are
    counted."""
    alice = _make_user(db_session, email="alice@example.com", display_name="Alice")
    _set_user_xp(db_session, user_id=alice.id, cumulative_xp=0)

    since = datetime(2025, 6, 1, 0, 0, 0, 0, tzinfo=timezone.utc)
    until = datetime(2025, 6, 7, 23, 59, 59, 999_999, tzinfo=timezone.utc)
    _add_xp_event(db_session, user_id=alice.id, amount=10, occurred_at=since)
    _add_xp_event(db_session, user_id=alice.id, amount=20, occurred_at=until)

    rows = LeaderboardRepository(db=db_session).top_in_window(
        since=since, until=until
    )

    assert len(rows) == 1
    assert rows[0].xp_window == 30


def test_top_in_window_excludes_unverified_users(db_session: Session) -> None:
    verified = _make_user(
        db_session,
        email="v@example.com",
        display_name="V",
        account_state=AccountState.VERIFIED,
    )
    unverified = _make_user(
        db_session,
        email="u@example.com",
        display_name="U",
        account_state=AccountState.UNVERIFIED,
    )
    _set_user_xp(db_session, user_id=verified.id, cumulative_xp=0)
    _set_user_xp(db_session, user_id=unverified.id, cumulative_xp=0)

    base = datetime(2025, 6, 15, tzinfo=timezone.utc)
    _add_xp_event(db_session, user_id=verified.id, amount=10, occurred_at=base)
    _add_xp_event(
        db_session, user_id=unverified.id, amount=999, occurred_at=base
    )

    rows = LeaderboardRepository(db=db_session).top_in_window(
        since=base - timedelta(days=1), until=base + timedelta(days=1)
    )

    assert [r.display_name for r in rows] == ["V"]


def test_top_in_window_excludes_banned_users(db_session: Session) -> None:
    clean = _make_user(db_session, email="clean@example.com", display_name="Clean")
    banned = _make_user(
        db_session, email="banned@example.com", display_name="Banned", is_banned=True
    )
    _set_user_xp(db_session, user_id=clean.id, cumulative_xp=0)
    _set_user_xp(db_session, user_id=banned.id, cumulative_xp=0)
    base = datetime(2025, 6, 15, tzinfo=timezone.utc)
    _add_xp_event(db_session, user_id=clean.id, amount=10, occurred_at=base)
    _add_xp_event(db_session, user_id=banned.id, amount=999, occurred_at=base)

    rows = LeaderboardRepository(db=db_session).top_in_window(
        since=base - timedelta(days=1), until=base + timedelta(days=1)
    )

    assert [r.display_name for r in rows] == ["Clean"]


def test_top_in_window_tie_break_uses_earlier_level_reached_at(
    db_session: Session,
) -> None:
    earlier = _make_user(
        db_session, email="earlier@example.com", display_name="Earlier"
    )
    later = _make_user(
        db_session, email="later@example.com", display_name="Later"
    )
    _set_user_xp(
        db_session,
        user_id=earlier.id,
        cumulative_xp=0,
        level=2,
        level_reached_at=datetime(2025, 5, 1, tzinfo=timezone.utc),
    )
    _set_user_xp(
        db_session,
        user_id=later.id,
        cumulative_xp=0,
        level=2,
        level_reached_at=datetime(2025, 5, 15, tzinfo=timezone.utc),
    )
    base = datetime(2025, 6, 15, tzinfo=timezone.utc)
    _add_xp_event(db_session, user_id=earlier.id, amount=50, occurred_at=base)
    _add_xp_event(db_session, user_id=later.id, amount=50, occurred_at=base)

    rows = LeaderboardRepository(db=db_session).top_in_window(
        since=base - timedelta(days=1), until=base + timedelta(days=1)
    )

    assert [r.display_name for r in rows] == ["Earlier", "Later"]


def test_top_in_window_tie_break_falls_back_to_user_id(
    db_session: Session,
) -> None:
    first = _make_user(db_session, email="a@example.com", display_name="A")
    second = _make_user(db_session, email="b@example.com", display_name="B")
    same_ts = datetime(2025, 5, 1, tzinfo=timezone.utc)
    _set_user_xp(
        db_session, user_id=first.id, cumulative_xp=0, level_reached_at=same_ts
    )
    _set_user_xp(
        db_session, user_id=second.id, cumulative_xp=0, level_reached_at=same_ts
    )
    base = datetime(2025, 6, 15, tzinfo=timezone.utc)
    _add_xp_event(db_session, user_id=first.id, amount=10, occurred_at=base)
    _add_xp_event(db_session, user_id=second.id, amount=10, occurred_at=base)

    rows = LeaderboardRepository(db=db_session).top_in_window(
        since=base - timedelta(days=1), until=base + timedelta(days=1)
    )

    assert rows[0].user_id == first.id
    assert rows[1].user_id == second.id


def test_top_in_window_respects_limit(db_session: Session) -> None:
    base = datetime(2025, 6, 15, tzinfo=timezone.utc)
    for i in range(20):
        u = _make_user(
            db_session, email=f"u{i}@example.com", display_name=f"U{i}"
        )
        _set_user_xp(db_session, user_id=u.id, cumulative_xp=0)
        _add_xp_event(
            db_session, user_id=u.id, amount=100 - i, occurred_at=base
        )

    rows_3 = LeaderboardRepository(db=db_session).top_in_window(
        since=base - timedelta(days=1),
        until=base + timedelta(days=1),
        limit=3,
    )

    assert len(rows_3) == 3
    assert [r.xp_window for r in rows_3] == [100, 99, 98]


def test_top_in_window_row_shape_matches_spec(db_session: Session) -> None:
    """Row carries display_name, level, xp_window=window-sum, category."""
    alice = _make_user(
        db_session,
        email="alice@example.com",
        display_name="Alice",
        category=Category.SUB_PROFESSIONAL,
    )
    _set_user_xp(db_session, user_id=alice.id, cumulative_xp=0, level=3)

    base = datetime(2025, 6, 15, tzinfo=timezone.utc)
    _add_xp_event(db_session, user_id=alice.id, amount=70, occurred_at=base)

    rows = LeaderboardRepository(db=db_session).top_in_window(
        since=base - timedelta(days=1), until=base + timedelta(days=1)
    )

    assert rows == [
        LeaderboardRow(
            user_id=alice.id,
            display_name="Alice",
            level=3,
            xp_window=70,
            category=Category.SUB_PROFESSIONAL.value,
        )
    ]
