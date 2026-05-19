"""Repository tests for ``AuthRepository`` (sessions, login attempts, lockouts).

Each test uses the ``db_session`` fixture against in-memory SQLite. A real
``User`` row backs every FK so the database enforces referential integrity
during the test.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session as DBSession

from app.features.auth.repository import AuthRepository
from app.features.users.models import User
from app.features.users.repository import UserRepository
from app.features.users.schemas import UserCreate


def _make_user(db: DBSession, email: str = "alice@example.com") -> User:
    repo = UserRepository(db=db)
    payload = UserCreate(
        email=email,
        display_name="Alice",
        age=25,
        category="PROFESSIONAL",
        password="Strong1Pass!",
    )
    return repo.create(payload, password_hash="bcrypt$fake$hash")


def _new_jti() -> str:
    return str(uuid.uuid4())


# --- sessions --------------------------------------------------------------


def test_create_session_persists_jti(db_session: DBSession) -> None:
    user = _make_user(db_session)
    repo = AuthRepository(db=db_session)
    now = datetime.now(tz=timezone.utc)
    jti = _new_jti()

    created = repo.create_session(
        jti=jti,
        user_id=user.id,
        issued_at=now,
        expires_at=now + timedelta(hours=24),
    )

    assert created.jti == jti
    assert created.user_id == user.id
    assert created.revoked_at is None


def test_revoke_session_by_jti_updates_revoked_at(db_session: DBSession) -> None:
    user = _make_user(db_session)
    repo = AuthRepository(db=db_session)
    now = datetime.now(tz=timezone.utc)
    jti = _new_jti()
    repo.create_session(
        jti=jti,
        user_id=user.id,
        issued_at=now,
        expires_at=now + timedelta(hours=24),
    )

    revoke_at = now + timedelta(minutes=5)
    updated = repo.revoke_session_by_jti(jti, now=revoke_at)
    assert updated is True

    # Active check now returns False.
    assert repo.is_jti_active(jti, now=now + timedelta(minutes=10)) is False


def test_revoke_session_by_jti_returns_false_for_unknown(db_session: DBSession) -> None:
    repo = AuthRepository(db=db_session)
    assert repo.revoke_session_by_jti("does-not-exist") is False


def test_revoke_all_for_user_revokes_only_unrevoked(db_session: DBSession) -> None:
    user = _make_user(db_session)
    other = _make_user(db_session, email="bob@example.com")
    repo = AuthRepository(db=db_session)
    now = datetime.now(tz=timezone.utc)
    expires = now + timedelta(hours=24)

    s1 = _new_jti()
    s2 = _new_jti()
    s3_already_revoked = _new_jti()
    s_other = _new_jti()

    repo.create_session(jti=s1, user_id=user.id, issued_at=now, expires_at=expires)
    repo.create_session(jti=s2, user_id=user.id, issued_at=now, expires_at=expires)
    repo.create_session(
        jti=s3_already_revoked,
        user_id=user.id,
        issued_at=now,
        expires_at=expires,
    )
    repo.revoke_session_by_jti(s3_already_revoked, now=now)
    repo.create_session(
        jti=s_other, user_id=other.id, issued_at=now, expires_at=expires
    )

    count = repo.revoke_all_for_user(user.id, now=now + timedelta(seconds=1))

    # s3 is already revoked so it is not counted again.
    assert count == 2
    # The other user's session is unaffected.
    assert repo.is_jti_active(s_other, now=now) is True


def test_is_jti_active_false_for_revoked_or_expired(db_session: DBSession) -> None:
    user = _make_user(db_session)
    repo = AuthRepository(db=db_session)
    now = datetime.now(tz=timezone.utc)

    # An expired session.
    expired_jti = _new_jti()
    repo.create_session(
        jti=expired_jti,
        user_id=user.id,
        issued_at=now - timedelta(hours=25),
        expires_at=now - timedelta(hours=1),
    )

    # A revoked but not yet expired session.
    revoked_jti = _new_jti()
    repo.create_session(
        jti=revoked_jti,
        user_id=user.id,
        issued_at=now,
        expires_at=now + timedelta(hours=24),
    )
    repo.revoke_session_by_jti(revoked_jti, now=now)

    # An active one for sanity.
    live_jti = _new_jti()
    repo.create_session(
        jti=live_jti,
        user_id=user.id,
        issued_at=now,
        expires_at=now + timedelta(hours=24),
    )

    assert repo.is_jti_active(expired_jti, now=now) is False
    assert repo.is_jti_active(revoked_jti, now=now) is False
    assert repo.is_jti_active(live_jti, now=now) is True
    assert repo.is_jti_active("nonexistent", now=now) is False


# --- login attempts --------------------------------------------------------


def test_record_login_attempt_persists(db_session: DBSession) -> None:
    user = _make_user(db_session)
    repo = AuthRepository(db=db_session)
    now = datetime.now(tz=timezone.utc)

    attempt = repo.record_login_attempt(
        user_id=user.id, attempted_at=now, success=False
    )

    assert attempt.id is not None
    assert attempt.user_id == user.id
    assert attempt.success is False


def test_record_login_attempt_accepts_null_user(db_session: DBSession) -> None:
    repo = AuthRepository(db=db_session)
    now = datetime.now(tz=timezone.utc)

    attempt = repo.record_login_attempt(
        user_id=None, attempted_at=now, success=False
    )

    assert attempt.id is not None
    assert attempt.user_id is None


def test_failed_count_in_window_excludes_successes_and_old_failures(
    db_session: DBSession,
) -> None:
    user = _make_user(db_session)
    repo = AuthRepository(db=db_session)
    now = datetime.now(tz=timezone.utc)
    since = now - timedelta(minutes=15)

    # Three failures inside the window.
    for delta in (1, 5, 10):
        repo.record_login_attempt(
            user_id=user.id,
            attempted_at=now - timedelta(minutes=delta),
            success=False,
        )
    # A success inside the window — should not count.
    repo.record_login_attempt(user_id=user.id, attempted_at=now, success=True)
    # A failure outside the window — should not count.
    repo.record_login_attempt(
        user_id=user.id,
        attempted_at=now - timedelta(minutes=30),
        success=False,
    )

    count = repo.failed_count_in_window(user.id, since=since)
    assert count == 3


# --- lockouts --------------------------------------------------------------


def test_set_lockout_upsert_creates_then_updates(db_session: DBSession) -> None:
    user = _make_user(db_session)
    repo = AuthRepository(db=db_session)
    now = datetime.now(tz=timezone.utc)

    lockout1 = repo.set_lockout(user.id, locked_until=now + timedelta(minutes=15))
    assert lockout1.user_id == user.id

    # Updating moves the lock forward. SQLite's ``DateTime(timezone=True)``
    # does not actually preserve the offset on read (Postgres will), so we
    # compare the naive wall-clock value instead.
    new_until = now + timedelta(minutes=30)
    lockout2 = repo.set_lockout(user.id, locked_until=new_until)
    assert lockout2.locked_until.replace(tzinfo=None) == new_until.replace(tzinfo=None)

    fetched = repo.get_lockout(user.id)
    assert fetched is not None
    assert fetched.locked_until.replace(tzinfo=None) == new_until.replace(tzinfo=None)


def test_get_lockout_returns_none_when_absent(db_session: DBSession) -> None:
    user = _make_user(db_session)
    repo = AuthRepository(db=db_session)

    assert repo.get_lockout(user.id) is None



def test_get_session_by_jti_returns_row_or_none(db_session: DBSession) -> None:
    user = _make_user(db_session)
    repo = AuthRepository(db=db_session)
    now = datetime.now(tz=timezone.utc)
    jti = _new_jti()
    repo.create_session(
        jti=jti,
        user_id=user.id,
        issued_at=now,
        expires_at=now + timedelta(hours=24),
    )

    row = repo.get_session_by_jti(jti)
    assert row is not None
    assert row.jti == jti
    assert row.user_id == user.id

    assert repo.get_session_by_jti("nonexistent-jti") is None
