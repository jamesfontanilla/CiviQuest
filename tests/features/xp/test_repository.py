"""Repository tests for the XP slice (Task 9.1).

Per ``testing-standards.md`` repository tests run against in-memory
SQLite with no mocks. Each test seeds a real :class:`User` (the FK
target) and drives :class:`XPRepository` directly.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.features.users.models import Category, User
from app.features.users.repository import UserRepository
from app.features.users.schemas import UserCreate
from app.features.xp.models import UserXP, XPEvent, XPSource
from app.features.xp.repository import XPRepository


# --- factories --------------------------------------------------------------


def _make_user(db: Session, *, email: str = "alice@example.com") -> User:
    repo = UserRepository(db=db)
    return repo.create(
        UserCreate(
            email=email,
            display_name="Alice",
            age=25,
            category=Category.PROFESSIONAL.value,
            password="Strong1Pass!",
        ),
        password_hash="bcrypt$fake$hash",
    )


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


# --- get_or_create_user_xp -------------------------------------------------


def test_get_or_create_user_xp_creates_row_when_absent(
    db_session: Session,
) -> None:
    user = _make_user(db_session)
    repo = XPRepository(db=db_session)

    row = repo.get_or_create_user_xp(user.id)

    assert row.user_id == user.id
    assert row.cumulative_xp == 0
    assert row.level == 0
    assert row.streak_count == 0
    assert row.level_reached_at is None
    assert row.last_activity_at is None
    assert row.last_streak_day is None


def test_get_or_create_user_xp_returns_existing_row(
    db_session: Session,
) -> None:
    user = _make_user(db_session)
    repo = XPRepository(db=db_session)

    first = repo.get_or_create_user_xp(user.id)
    second = repo.get_or_create_user_xp(user.id)

    assert first.user_id == second.user_id
    # Only one row in user_xp.
    assert db_session.query(UserXP).filter_by(user_id=user.id).count() == 1


def test_get_user_xp_returns_none_when_absent(db_session: Session) -> None:
    user = _make_user(db_session)
    repo = XPRepository(db=db_session)

    assert repo.get_user_xp(user.id) is None


# --- insert_event_and_recompute -------------------------------------------


def test_insert_event_updates_cumulative_xp(db_session: Session) -> None:
    user = _make_user(db_session)
    repo = XPRepository(db=db_session)

    event, user_xp = repo.insert_event_and_recompute(
        user_id=user.id,
        source=XPSource.LESSON_FIRST_COMPLETE,
        amount=20,
        occurred_at=_now(),
    )

    assert event.id is not None
    assert event.user_id == user.id
    assert event.amount == 20
    assert event.source == XPSource.LESSON_FIRST_COMPLETE.value
    assert user_xp.cumulative_xp == 20
    assert user_xp.level == 0  # 20 < 100, still level 0


def test_insert_event_accumulates_across_calls(db_session: Session) -> None:
    user = _make_user(db_session)
    repo = XPRepository(db=db_session)
    when = _now()

    repo.insert_event_and_recompute(
        user_id=user.id,
        source=XPSource.QUIZ_PASS,
        amount=20,
        occurred_at=when,
    )
    _, user_xp = repo.insert_event_and_recompute(
        user_id=user.id,
        source=XPSource.QUIZ_PASS,
        amount=80,
        occurred_at=when,
    )

    assert user_xp.cumulative_xp == 100
    assert user_xp.level == 1


def test_insert_event_clamps_negative_correction_at_zero(
    db_session: Session,
) -> None:
    """Req 11.7 — never produce a negative XP balance."""
    user = _make_user(db_session)
    repo = XPRepository(db=db_session)
    when = _now()

    # Earn 50 XP, then admin-correct -1000.
    repo.insert_event_and_recompute(
        user_id=user.id,
        source=XPSource.QUIZ_PASS,
        amount=50,
        occurred_at=when,
    )
    _, user_xp = repo.insert_event_and_recompute(
        user_id=user.id,
        source=XPSource.ADMIN_CORRECTION,
        amount=-1000,
        occurred_at=when,
    )

    assert user_xp.cumulative_xp == 0
    assert user_xp.level == 0


def test_insert_event_updates_level_on_threshold_cross(
    db_session: Session,
) -> None:
    """Cumulative 300 -> level 2 (50 * 2 * 3 = 300)."""
    user = _make_user(db_session)
    repo = XPRepository(db=db_session)
    when = _now()

    _, user_xp = repo.insert_event_and_recompute(
        user_id=user.id,
        source=XPSource.MOCK_PASS,
        amount=300,
        occurred_at=when,
    )

    assert user_xp.cumulative_xp == 300
    assert user_xp.level == 2


def test_insert_event_sets_level_reached_at_on_level_up(
    db_session: Session,
) -> None:
    user = _make_user(db_session)
    repo = XPRepository(db=db_session)
    when = datetime(2025, 6, 1, 12, 0, tzinfo=timezone.utc)

    _, user_xp = repo.insert_event_and_recompute(
        user_id=user.id,
        source=XPSource.LESSON_FIRST_COMPLETE,
        amount=100,
        occurred_at=when,
    )

    assert user_xp.level == 1
    assert user_xp.level_reached_at is not None
    # SQLite drops tz on round-trip; compare naive.
    assert user_xp.level_reached_at.replace(tzinfo=None) == when.replace(
        tzinfo=None
    )


def test_insert_event_does_not_change_level_reached_at_when_level_unchanged(
    db_session: Session,
) -> None:
    """A second event that doesn't trigger a level-up must not move the
    timestamp."""
    user = _make_user(db_session)
    repo = XPRepository(db=db_session)
    first_when = datetime(2025, 6, 1, 12, 0, tzinfo=timezone.utc)
    second_when = datetime(2025, 6, 5, 12, 0, tzinfo=timezone.utc)

    repo.insert_event_and_recompute(
        user_id=user.id,
        source=XPSource.LESSON_FIRST_COMPLETE,
        amount=100,
        occurred_at=first_when,
    )
    _, user_xp = repo.insert_event_and_recompute(
        user_id=user.id,
        source=XPSource.LESSON_FIRST_COMPLETE,
        amount=20,
        occurred_at=second_when,
    )

    # cumulative_xp = 120 still level 1.
    assert user_xp.level == 1
    assert user_xp.level_reached_at is not None
    assert user_xp.level_reached_at.replace(tzinfo=None) == first_when.replace(
        tzinfo=None
    )


# --- CHECK constraints ----------------------------------------------------


def test_negative_amount_for_non_correction_source_raises(
    db_session: Session,
) -> None:
    """The ``amount >= 0 OR ADMIN_CORRECTION`` CHECK rejects bad inserts."""
    user = _make_user(db_session)
    # Materialise the cache row so the only violation is the amount CHECK.
    repo = XPRepository(db=db_session)
    repo.get_or_create_user_xp(user.id)

    bad = XPEvent(
        user_id=user.id,
        source=XPSource.QUIZ_PASS.value,
        amount=-5,
        occurred_at=_now(),
    )
    db_session.add(bad)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_negative_amount_allowed_for_admin_correction(
    db_session: Session,
) -> None:
    user = _make_user(db_session)
    repo = XPRepository(db=db_session)
    repo.get_or_create_user_xp(user.id)

    ok = XPEvent(
        user_id=user.id,
        source=XPSource.ADMIN_CORRECTION.value,
        amount=-50,
        occurred_at=_now(),
    )
    db_session.add(ok)
    db_session.commit()  # must not raise

    assert ok.id is not None


def test_unknown_source_rejected_by_check_constraint(
    db_session: Session,
) -> None:
    """Closed-source enum (Req 11.1) — the CHECK rejects anything outside."""
    user = _make_user(db_session)
    repo = XPRepository(db=db_session)
    repo.get_or_create_user_xp(user.id)

    bad = XPEvent(
        user_id=user.id,
        source="DECOY_SOURCE",
        amount=10,
        occurred_at=_now(),
    )
    db_session.add(bad)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


# --- client_event_id idempotency -----------------------------------------


def test_get_event_by_client_event_id_returns_row_or_none(
    db_session: Session,
) -> None:
    user = _make_user(db_session)
    repo = XPRepository(db=db_session)

    assert repo.get_event_by_client_event_id("nope") is None

    repo.insert_event_and_recompute(
        user_id=user.id,
        source=XPSource.QUIZ_PASS,
        amount=20,
        occurred_at=_now(),
        client_event_id="evt-1",
    )

    found = repo.get_event_by_client_event_id("evt-1")
    assert found is not None
    assert found.user_id == user.id


def test_unique_client_event_id_violation(db_session: Session) -> None:
    user = _make_user(db_session)
    user2 = _make_user(db_session, email="bob@example.com")
    repo = XPRepository(db=db_session)
    when = _now()

    repo.insert_event_and_recompute(
        user_id=user.id,
        source=XPSource.QUIZ_PASS,
        amount=20,
        occurred_at=when,
        client_event_id="shared-evt",
    )
    with pytest.raises(IntegrityError):
        repo.insert_event_and_recompute(
            user_id=user2.id,
            source=XPSource.QUIZ_PASS,
            amount=20,
            occurred_at=when,
            client_event_id="shared-evt",
        )
    db_session.rollback()


# --- sum_in_window --------------------------------------------------------


def test_sum_in_window_sums_events_inside_window(db_session: Session) -> None:
    user = _make_user(db_session)
    repo = XPRepository(db=db_session)
    base = datetime(2025, 6, 1, 12, 0, tzinfo=timezone.utc)

    repo.insert_event_and_recompute(
        user_id=user.id,
        source=XPSource.QUIZ_PASS,
        amount=20,
        occurred_at=base,
    )
    repo.insert_event_and_recompute(
        user_id=user.id,
        source=XPSource.QUIZ_PERFECT,
        amount=50,
        occurred_at=base + timedelta(hours=1),
    )

    window_start = base - timedelta(minutes=1)
    window_end = base + timedelta(hours=2)

    total = repo.sum_in_window(user.id, since=window_start, until=window_end)

    assert total == 70


def test_sum_in_window_excludes_events_outside_window(
    db_session: Session,
) -> None:
    user = _make_user(db_session)
    repo = XPRepository(db=db_session)
    base = datetime(2025, 6, 15, 12, 0, tzinfo=timezone.utc)

    # Outside (too early).
    repo.insert_event_and_recompute(
        user_id=user.id,
        source=XPSource.QUIZ_PASS,
        amount=10,
        occurred_at=base - timedelta(days=10),
    )
    # Inside.
    repo.insert_event_and_recompute(
        user_id=user.id,
        source=XPSource.QUIZ_PASS,
        amount=30,
        occurred_at=base,
    )
    # Outside (too late).
    repo.insert_event_and_recompute(
        user_id=user.id,
        source=XPSource.QUIZ_PASS,
        amount=99,
        occurred_at=base + timedelta(days=10),
    )

    window_start = base - timedelta(days=1)
    window_end = base + timedelta(days=1)
    total = repo.sum_in_window(user.id, since=window_start, until=window_end)

    assert total == 30


def test_sum_in_window_returns_zero_for_empty_window(
    db_session: Session,
) -> None:
    user = _make_user(db_session)
    repo = XPRepository(db=db_session)

    base = datetime(2025, 6, 1, tzinfo=timezone.utc)
    total = repo.sum_in_window(
        user.id, since=base, until=base + timedelta(days=1)
    )

    assert total == 0


def test_sum_in_window_isolated_per_user(db_session: Session) -> None:
    alice = _make_user(db_session)
    bob = _make_user(db_session, email="bob@example.com")
    repo = XPRepository(db=db_session)
    when = datetime(2025, 6, 1, tzinfo=timezone.utc)

    repo.insert_event_and_recompute(
        user_id=alice.id,
        source=XPSource.QUIZ_PASS,
        amount=20,
        occurred_at=when,
    )
    repo.insert_event_and_recompute(
        user_id=bob.id,
        source=XPSource.QUIZ_PASS,
        amount=999,
        occurred_at=when,
    )

    alice_total = repo.sum_in_window(
        alice.id,
        since=when - timedelta(days=1),
        until=when + timedelta(days=1),
    )

    assert alice_total == 20
