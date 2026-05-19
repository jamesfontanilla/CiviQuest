"""Repository tests for ``OTPRepository`` against in-memory SQLite.

A real ``User`` row is created via ``UserRepository`` so the FK constraint
holds; this is more useful than disabling FKs because it surfaces real-world
referential bugs at the test layer.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.features.otp.models import OTP, OTPPurpose
from app.features.otp.repository import OTPRepository
from app.features.users.models import User
from app.features.users.repository import UserRepository
from app.features.users.schemas import UserCreate


def _make_user(db: Session, email: str = "alice@example.com") -> User:
    repo = UserRepository(db=db)
    payload = UserCreate(
        email=email,
        display_name="Alice",
        age=25,
        category="PROFESSIONAL",
        password="Strong1Pass!",
    )
    return repo.create(payload, password_hash="bcrypt$fake$hash")


def _make_otp(
    db: Session,
    user_id: int,
    *,
    purpose: OTPPurpose = OTPPurpose.VERIFY_EMAIL,
    expires_in_minutes: int = 5,
    used: bool = False,
    invalidated: bool = False,
    code_hash: str = "bcrypt$fake$code",
) -> OTP:
    """Insert an OTP directly via the session and return the persisted row."""
    now = datetime.now(tz=timezone.utc)
    otp = OTP(
        user_id=user_id,
        purpose=purpose.value,
        code_hash=code_hash,
        expires_at=now + timedelta(minutes=expires_in_minutes),
        used=used,
        invalidated=invalidated,
    )
    db.add(otp)
    db.commit()
    db.refresh(otp)
    return otp


def test_create_persists_otp_with_defaults(db_session: Session) -> None:
    user = _make_user(db_session)
    otp = _make_otp(db_session, user.id)

    repo = OTPRepository(db=db_session)
    fetched = repo.get(otp.id)

    assert fetched is not None
    assert fetched.used is False
    assert fetched.invalidated is False
    assert fetched.attempt_count == 0
    assert fetched.user_id == user.id
    assert fetched.purpose == OTPPurpose.VERIFY_EMAIL.value


def test_count_issuances_in_last_60min(db_session: Session) -> None:
    user = _make_user(db_session)
    repo = OTPRepository(db=db_session)
    now = datetime.now(tz=timezone.utc)

    # Three "recent" OTPs and one outside the window.
    for _ in range(3):
        _make_otp(db_session, user.id)

    # Backdate one OTP by 90 minutes via direct attribute set.
    old = _make_otp(db_session, user.id)
    old.created_at = now - timedelta(minutes=90)
    db_session.commit()

    count = repo.count_issuances_in_last_60min(user.id, now=now)
    assert count == 3


def test_invalidate_unused_for(db_session: Session) -> None:
    user = _make_user(db_session)
    repo = OTPRepository(db=db_session)

    o1 = _make_otp(db_session, user.id)
    o2 = _make_otp(db_session, user.id)
    # An already-used row should not be touched.
    o3 = _make_otp(db_session, user.id, used=True)
    # A different-purpose row should not be touched.
    o4 = _make_otp(db_session, user.id, purpose=OTPPurpose.PASSWORD_RESET)

    affected = repo.invalidate_unused_for(user.id, OTPPurpose.VERIFY_EMAIL)

    assert affected == 2
    db_session.refresh(o1)
    db_session.refresh(o2)
    db_session.refresh(o3)
    db_session.refresh(o4)
    assert o1.invalidated is True
    assert o2.invalidated is True
    assert o3.invalidated is False
    assert o4.invalidated is False


def test_get_latest_active_excludes_expired_used_invalidated(db_session: Session) -> None:
    user = _make_user(db_session)
    repo = OTPRepository(db=db_session)
    now = datetime.now(tz=timezone.utc)

    # Three active OTPs; the latest by created_at must win.
    o_old = _make_otp(db_session, user.id)
    o_old.created_at = now - timedelta(minutes=4)
    db_session.commit()

    o_used = _make_otp(db_session, user.id, used=True)
    o_used.created_at = now - timedelta(minutes=3)
    db_session.commit()

    o_invalidated = _make_otp(db_session, user.id, invalidated=True)
    o_invalidated.created_at = now - timedelta(minutes=2)
    db_session.commit()

    o_expired = _make_otp(db_session, user.id, expires_in_minutes=-1)
    o_expired.created_at = now - timedelta(minutes=1)
    db_session.commit()

    o_latest_active = _make_otp(db_session, user.id)

    found = repo.get_latest_active(user.id, OTPPurpose.VERIFY_EMAIL, now=now)
    assert found is not None
    assert found.id == o_latest_active.id


def test_get_latest_active_returns_none_when_no_match(db_session: Session) -> None:
    user = _make_user(db_session)
    repo = OTPRepository(db=db_session)

    found = repo.get_latest_active(user.id, OTPPurpose.VERIFY_EMAIL)

    assert found is None


def test_bump_attempt_increments_counter(db_session: Session) -> None:
    user = _make_user(db_session)
    otp = _make_otp(db_session, user.id)
    repo = OTPRepository(db=db_session)

    repo.bump_attempt(otp)
    repo.bump_attempt(otp)

    refetched = repo.get(otp.id)
    assert refetched is not None
    assert refetched.attempt_count == 2


def test_mark_used_sets_used_true(db_session: Session) -> None:
    user = _make_user(db_session)
    otp = _make_otp(db_session, user.id)
    repo = OTPRepository(db=db_session)

    repo.mark_used(otp)

    refetched = repo.get(otp.id)
    assert refetched is not None
    assert refetched.used is True


def test_mark_invalidated_sets_invalidated_true(db_session: Session) -> None:
    user = _make_user(db_session)
    otp = _make_otp(db_session, user.id)
    repo = OTPRepository(db=db_session)

    repo.mark_invalidated(otp)

    refetched = repo.get(otp.id)
    assert refetched is not None
    assert refetched.invalidated is True
