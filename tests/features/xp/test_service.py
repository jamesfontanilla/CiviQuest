"""Service tests for the XP slice (Task 9.3).

Following ``testing-standards.md``:

- **Validation paths** use ``MagicMock(spec=...)`` repositories. The
  service should reject bad input before touching the DB, so a mock
  proves the rejection without needing a real session.
- **Behavioral paths** that exercise the streak rollover, level
  recompute, and XP cache mutation use a real ``db_session`` fixture
  because the rollover state machine couples the cache row to the
  ledger and re-reads its own work.

The split keeps validation tests fast and deterministic while the
behavior tests catch real ORM-level bugs.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.features.users.models import (
    AccountState,
    Category,
    Role,
    User,
)
from app.features.users.repository import UserRepository
from app.features.users.schemas import UserCreate
from app.features.xp.models import XPSource
from app.features.xp.repository import XPRepository
from app.features.xp.service import (
    DEFAULT_AMOUNT_BY_SOURCE,
    XPService,
)


# --- factories --------------------------------------------------------------


def _make_user_orm(**overrides: object) -> User:
    """Build a detached :class:`User` for mock-based tests."""
    defaults: dict[str, object] = {
        "id": 1,
        "email": "alice@example.com",
        "display_name": "Alice",
        "age": 25,
        "category": Category.PROFESSIONAL.value,
        "role": Role.LEARNER.value,
        "account_state": AccountState.VERIFIED.value,
        "is_banned": False,
        "tz_name": "UTC",
        "password_hash": "x",
        "cross_category_preview": False,
    }
    return User(**{**defaults, **overrides})


def _make_user(db: Session, *, email: str = "alice@example.com") -> User:
    """Persist a real :class:`User` for behavior tests."""
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


def _build_mocked_service() -> tuple[XPService, MagicMock, MagicMock]:
    xp_repo = MagicMock(spec=XPRepository)
    user_repo = MagicMock(spec=UserRepository)
    return XPService(xp_repo=xp_repo, user_repo=user_repo), xp_repo, user_repo


# ===========================================================================
# Validation paths (mocked repository)
# ===========================================================================


def test_award_rejects_non_xpsource_type() -> None:
    """A bare string source is rejected with 400 (closed enum, Req 11.1)."""
    service, xp_repo, _ = _build_mocked_service()
    user = _make_user_orm()

    with pytest.raises(HTTPException) as exc_info:
        # Pass a non-enum value to bypass typing.
        service.award(user=user, source="DECOY")  # type: ignore[arg-type]

    assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
    assert exc_info.value.detail == "invalid_xp_source"
    xp_repo.insert_event_and_recompute.assert_not_called()


def test_award_rejects_negative_amount_for_non_admin_correction() -> None:
    """Req 11.7 — only ADMIN_CORRECTION can carry a negative amount."""
    service, xp_repo, _ = _build_mocked_service()
    user = _make_user_orm()

    with pytest.raises(HTTPException) as exc_info:
        service.award(user=user, source=XPSource.QUIZ_PASS, amount=-10)

    assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
    assert exc_info.value.detail == "negative_amount_not_allowed"
    xp_repo.insert_event_and_recompute.assert_not_called()


def test_award_rejects_admin_correction_without_explicit_amount() -> None:
    """ADMIN_CORRECTION must not fall through to a default amount."""
    service, xp_repo, _ = _build_mocked_service()
    user = _make_user_orm()

    with pytest.raises(HTTPException) as exc_info:
        service.award(user=user, source=XPSource.ADMIN_CORRECTION)

    assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
    assert exc_info.value.detail == "admin_correction_requires_amount"
    xp_repo.insert_event_and_recompute.assert_not_called()


def test_award_idempotent_replay_short_circuits_repository() -> None:
    """Replay with the same client_event_id returns prior event without
    calling insert_event_and_recompute again."""
    service, xp_repo, _ = _build_mocked_service()
    user = _make_user_orm()

    prior_event = MagicMock()
    prior_event.user_id = user.id
    cache_row = MagicMock()

    xp_repo.get_event_by_client_event_id.return_value = prior_event
    xp_repo.get_or_create_user_xp.return_value = cache_row

    event, user_xp = service.award(
        user=user,
        source=XPSource.QUIZ_PASS,
        amount=20,
        client_event_id="evt-1",
    )

    assert event is prior_event
    assert user_xp is cache_row
    xp_repo.insert_event_and_recompute.assert_not_called()


def test_award_idempotent_replay_only_for_same_user() -> None:
    """A client_event_id that matches a *different* user's prior event
    must fall through to a fresh insert."""
    service, xp_repo, _ = _build_mocked_service()
    user = _make_user_orm(id=2)

    prior_event = MagicMock()
    prior_event.user_id = 99  # different user
    fresh_event = MagicMock()
    fresh_cache = MagicMock()

    xp_repo.get_event_by_client_event_id.return_value = prior_event
    xp_repo.get_or_create_user_xp.return_value = MagicMock(
        last_streak_day=None, streak_count=0, last_activity_at=None
    )
    xp_repo.insert_event_and_recompute.return_value = (
        fresh_event,
        fresh_cache,
    )

    # ADMIN_CORRECTION skips the streak rollover so we don't have to
    # worry about that side effect in this validation-focused test.
    event, _ = service.award(
        user=user,
        source=XPSource.ADMIN_CORRECTION,
        amount=10,
        client_event_id="cross-user-evt",
    )

    assert event is fresh_event
    xp_repo.insert_event_and_recompute.assert_called_once()


# ===========================================================================
# Behavior paths (real db_session)
# ===========================================================================


def _build_real_service(db: Session) -> XPService:
    return XPService(
        xp_repo=XPRepository(db=db),
        user_repo=UserRepository(db=db),
    )


def test_award_lesson_first_complete_uses_default_20_xp(
    db_session: Session,
) -> None:
    user = _make_user(db_session)
    service = _build_real_service(db_session)

    event, user_xp = service.award(
        user=user, source=XPSource.LESSON_FIRST_COMPLETE
    )

    assert event.amount == 20
    # Cumulative reflects activity (20) + first STREAK_DAY (25) = 45.
    assert user_xp.cumulative_xp == 45


def test_award_quiz_pass_uses_default_20_xp(db_session: Session) -> None:
    user = _make_user(db_session)
    service = _build_real_service(db_session)

    event, _ = service.award(user=user, source=XPSource.QUIZ_PASS)

    assert event.amount == DEFAULT_AMOUNT_BY_SOURCE[XPSource.QUIZ_PASS]


def test_award_quiz_perfect_uses_default_50_xp(db_session: Session) -> None:
    user = _make_user(db_session)
    service = _build_real_service(db_session)

    event, _ = service.award(user=user, source=XPSource.QUIZ_PERFECT)

    assert event.amount == 50


def test_award_mock_pass_uses_default_500_xp(db_session: Session) -> None:
    user = _make_user(db_session)
    service = _build_real_service(db_session)

    event, _ = service.award(user=user, source=XPSource.MOCK_PASS)

    assert event.amount == 500


def test_award_topic_quiz_caller_supplies_explicit_100_xp(
    db_session: Session,
) -> None:
    """Topic quizzes (Req 8.4) bypass the default and pass amount=100."""
    user = _make_user(db_session)
    service = _build_real_service(db_session)

    event, _ = service.award(
        user=user, source=XPSource.QUIZ_PASS, amount=100
    )

    assert event.amount == 100


def test_award_admin_correction_accepts_negative_amount(
    db_session: Session,
) -> None:
    """ADMIN_CORRECTION can drive cumulative XP down (Req 11.7)."""
    user = _make_user(db_session)
    service = _build_real_service(db_session)

    # Earn 100 first (with streak XP that's actually 100 + 25 = 125).
    service.award(user=user, source=XPSource.QUIZ_PASS, amount=100)
    # Correction.
    _, user_xp = service.award(
        user=user, source=XPSource.ADMIN_CORRECTION, amount=-50
    )

    # 100 + 25 (STREAK_DAY) - 50 = 75
    assert user_xp.cumulative_xp == 75


def test_award_admin_correction_clamps_at_zero(db_session: Session) -> None:
    """A correction big enough to underflow clamps at 0 (Req 11.7)."""
    user = _make_user(db_session)
    service = _build_real_service(db_session)

    service.award(user=user, source=XPSource.QUIZ_PASS, amount=20)
    _, user_xp = service.award(
        user=user, source=XPSource.ADMIN_CORRECTION, amount=-9999
    )

    assert user_xp.cumulative_xp == 0


def test_award_lesson_first_complete_triggers_streak_rollover(
    db_session: Session,
) -> None:
    """LESSON_FIRST_COMPLETE is a qualifying activity ⇒ STREAK_DAY fires."""
    user = _make_user(db_session)
    service = _build_real_service(db_session)

    _, user_xp = service.award(
        user=user, source=XPSource.LESSON_FIRST_COMPLETE
    )

    # First-ever activity ⇒ streak count 1, STREAK_DAY event awarded.
    assert user_xp.streak_count == 1
    # 20 (lesson) + 25 (streak) = 45
    assert user_xp.cumulative_xp == 45


def test_award_admin_correction_does_not_trigger_streak(
    db_session: Session,
) -> None:
    user = _make_user(db_session)
    service = _build_real_service(db_session)

    _, user_xp = service.award(
        user=user, source=XPSource.ADMIN_CORRECTION, amount=10
    )

    # No streak rollover for ADMIN_CORRECTION.
    assert user_xp.streak_count == 0
    assert user_xp.last_activity_at is None
    assert user_xp.cumulative_xp == 10


def test_award_streak_extends_across_consecutive_days(
    db_session: Session,
) -> None:
    user = _make_user(db_session)
    service = _build_real_service(db_session)

    day1 = datetime(2025, 6, 1, 12, 0, tzinfo=timezone.utc)
    day2 = datetime(2025, 6, 2, 12, 0, tzinfo=timezone.utc)

    service.award(
        user=user,
        source=XPSource.LESSON_FIRST_COMPLETE,
        occurred_at=day1,
    )
    _, user_xp = service.award(
        user=user,
        source=XPSource.LESSON_FIRST_COMPLETE,
        occurred_at=day2,
    )

    assert user_xp.streak_count == 2
    assert user_xp.last_streak_day == date(2025, 6, 2)


def test_award_persists_event_and_cache_atomically(
    db_session: Session,
) -> None:
    """The returned event has an id and the cache reflects it."""
    user = _make_user(db_session)
    service = _build_real_service(db_session)

    event, user_xp = service.award(
        user=user, source=XPSource.QUIZ_PERFECT, source_ref_id=999
    )

    assert event.id is not None
    assert event.source_ref_id == 999
    # 50 (perfect) + 25 (streak) = 75
    assert user_xp.cumulative_xp == 75


# ===========================================================================
# get_user_xp_view
# ===========================================================================


def test_get_user_xp_view_returns_zeros_for_fresh_user(
    db_session: Session,
) -> None:
    user = _make_user(db_session)
    service = _build_real_service(db_session)

    view = service.get_user_xp_view(user)

    assert view.cumulative_xp == 0
    assert view.level == 0
    assert view.streak == 0


def test_get_user_xp_view_returns_current_streak_within_36h(
    db_session: Session,
) -> None:
    user = _make_user(db_session)
    service = _build_real_service(db_session)

    base = datetime(2025, 6, 1, 12, 0, tzinfo=timezone.utc)
    service.award(
        user=user,
        source=XPSource.LESSON_FIRST_COMPLETE,
        occurred_at=base,
    )

    # Read 10h later — within 36h, streak active.
    view = service.get_user_xp_view(user, now=base + timedelta(hours=10))

    assert view.streak == 1


def test_get_user_xp_view_decays_streak_after_36h(
    db_session: Session,
) -> None:
    """Req 11.6 — gap > 36h returns streak=0 on read without persisting."""
    user = _make_user(db_session)
    service = _build_real_service(db_session)

    base = datetime(2025, 6, 1, 12, 0, tzinfo=timezone.utc)
    service.award(
        user=user,
        source=XPSource.LESSON_FIRST_COMPLETE,
        occurred_at=base,
    )

    # 50h later — stale.
    view = service.get_user_xp_view(user, now=base + timedelta(hours=50))

    assert view.streak == 0
    # The cache row's streak_count is *not* mutated by the read.
    cached = XPRepository(db=db_session).get_user_xp(user.id)
    assert cached is not None
    assert cached.streak_count == 1
