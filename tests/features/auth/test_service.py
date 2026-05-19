"""Service tests for ``AuthService``.

Per ``testing-standards.md``, service tests use ``MagicMock(spec=...)`` for
repositories and the OTP service; no real DB is involved. ``hash_password``
/ ``verify_password`` and the JWT primitives are exercised for real so the
end-to-end token shape is validated.

A single bcrypt hash for the canonical "right password" is computed once at
module import to keep wall-clock cost low.

Helpers (``_make_user``, ``_make_signup_payload``, ``_make_service``,
``_RIGHT_PASSWORD``, ``_NEW_PASSWORD``, ``_TEST_JWT_SECRET``) live in
``_helpers.py`` so they can be reused by the property-test module without
duplication. Pytest skips files whose name begins with ``_``.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.features.auth.schemas import (
    PasswordResetConfirmRequest,
    PasswordResetRequest,
)
from app.features.otp.models import OTPPurpose
from app.features.otp.schemas import OTPIssueRequest, OTPVerifyRequest
from app.features.users.models import AccountState
from tests.features.auth._helpers import (
    _NEW_PASSWORD,
    _RIGHT_PASSWORD,
    _TEST_JWT_SECRET,
    _make_service,
    _make_signup_payload,
    _make_user,
)


@pytest.fixture(autouse=True)
def _set_jwt_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every login test needs ``JWT_SECRET`` set for ``encode_token``."""
    monkeypatch.setenv("JWT_SECRET", _TEST_JWT_SECRET)


# --- signup ----------------------------------------------------------------


def test_signup_rejects_existing_email_with_409() -> None:
    service, user_repo, _, otp_service = _make_service()
    user_repo.get_by_email.return_value = _make_user()

    with pytest.raises(HTTPException) as exc_info:
        service.signup(_make_signup_payload())

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "email_already_registered"
    user_repo.create.assert_not_called()
    otp_service.issue.assert_not_called()


def test_signup_persists_hashed_password_not_plaintext() -> None:
    service, user_repo, _, _ = _make_service()

    service.signup(_make_signup_payload())

    user_repo.create.assert_called_once()
    call = user_repo.create.call_args
    persisted_hash = call.kwargs["password_hash"]
    # bcrypt hashes start with ``$2`` and are not equal to the plaintext.
    assert persisted_hash.startswith("$2")
    assert persisted_hash != _RIGHT_PASSWORD


def test_signup_creates_user_unverified() -> None:
    service, user_repo, _, _ = _make_service()

    service.signup(_make_signup_payload())

    user_repo.create.assert_called_once()
    assert user_repo.create.call_args.kwargs["account_state"] == AccountState.UNVERIFIED


def test_signup_triggers_otp_issuance_for_verify_email() -> None:
    service, _, _, otp_service = _make_service()

    service.signup(_make_signup_payload(), mode="offline")

    otp_service.issue.assert_called_once()
    call = otp_service.issue.call_args
    assert call.kwargs["purpose"] == OTPPurpose.VERIFY_EMAIL
    assert call.kwargs["mode"] == "offline"


# --- verify_email ----------------------------------------------------------


def test_verify_email_transitions_to_verified() -> None:
    service, user_repo, _, otp_service = _make_service()
    user = _make_user(account_state=AccountState.UNVERIFIED.value)
    otp_service.verify.return_value = user

    payload = OTPVerifyRequest(
        email=user.email,
        code="123456",
        purpose=OTPPurpose.VERIFY_EMAIL,
    )
    service.verify_email(payload)

    user_repo.set_account_state.assert_called_once_with(user, AccountState.VERIFIED)


# --- login -----------------------------------------------------------------


def test_login_returns_token_for_verified_user() -> None:
    service, user_repo, auth_repo, _ = _make_service()
    user_repo.get_by_email.return_value = _make_user()

    token, claims = service.login(email="alice@example.com", password=_RIGHT_PASSWORD)

    assert isinstance(token, str) and token.count(".") == 2  # JWT shape
    assert claims["sub"] == "1"
    assert "jti" in claims and "iat" in claims and "exp" in claims
    assert claims["exp"] - claims["iat"] == 24 * 3600
    auth_repo.record_login_attempt.assert_called_with(
        user_id=1, attempted_at=auth_repo.record_login_attempt.call_args.kwargs["attempted_at"], success=True
    )


def test_login_persists_session_row() -> None:
    service, user_repo, auth_repo, _ = _make_service()
    user_repo.get_by_email.return_value = _make_user()

    _, claims = service.login(email="alice@example.com", password=_RIGHT_PASSWORD)

    auth_repo.create_session.assert_called_once()
    call = auth_repo.create_session.call_args
    assert call.kwargs["jti"] == claims["jti"]
    assert call.kwargs["user_id"] == 1
    assert isinstance(call.kwargs["issued_at"], datetime)
    assert isinstance(call.kwargs["expires_at"], datetime)


def test_login_raises_401_for_unknown_email() -> None:
    service, user_repo, auth_repo, _ = _make_service()
    user_repo.get_by_email.return_value = None

    with pytest.raises(HTTPException) as exc_info:
        service.login(email="ghost@example.com", password=_RIGHT_PASSWORD)

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "invalid_credentials"
    # We still record the failure so the response shape doesn't leak the
    # email-existence question (Req 3.2). user_id is None.
    auth_repo.record_login_attempt.assert_called_once()
    assert auth_repo.record_login_attempt.call_args.kwargs["user_id"] is None


def test_login_raises_401_for_wrong_password() -> None:
    service, user_repo, auth_repo, _ = _make_service()
    user_repo.get_by_email.return_value = _make_user()

    with pytest.raises(HTTPException) as exc_info:
        service.login(email="alice@example.com", password="WrongPass1!")

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "invalid_credentials"
    auth_repo.record_login_attempt.assert_called_once()
    assert auth_repo.record_login_attempt.call_args.kwargs["success"] is False


def test_login_raises_403_for_banned_user() -> None:
    service, user_repo, _, _ = _make_service()
    user_repo.get_by_email.return_value = _make_user(is_banned=True)

    with pytest.raises(HTTPException) as exc_info:
        service.login(email="alice@example.com", password=_RIGHT_PASSWORD)

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "account_banned"


def test_login_raises_403_for_unverified_email() -> None:
    service, user_repo, _, _ = _make_service()
    user_repo.get_by_email.return_value = _make_user(
        account_state=AccountState.UNVERIFIED.value
    )

    with pytest.raises(HTTPException) as exc_info:
        service.login(email="alice@example.com", password=_RIGHT_PASSWORD)

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "email_not_verified"


def test_login_raises_401_when_locked() -> None:
    service, user_repo, auth_repo, _ = _make_service()
    user_repo.get_by_email.return_value = _make_user()
    future = datetime.now(tz=timezone.utc) + timedelta(minutes=10)
    lockout = MagicMock()
    lockout.locked_until = future
    auth_repo.get_lockout.return_value = lockout

    with pytest.raises(HTTPException) as exc_info:
        service.login(email="alice@example.com", password=_RIGHT_PASSWORD)

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "temporarily_locked"


def test_login_sets_lockout_on_fifth_failure_in_window() -> None:
    service, user_repo, auth_repo, _ = _make_service()
    user_repo.get_by_email.return_value = _make_user()
    # Five prior failures — this attempt will be the 5th (or however the
    # service counts) so the threshold is met after recording.
    auth_repo.failed_count_in_window.return_value = 5

    with pytest.raises(HTTPException) as exc_info:
        service.login(email="alice@example.com", password="WrongPass1!")

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "invalid_credentials"
    auth_repo.set_lockout.assert_called_once()
    locked_until = auth_repo.set_lockout.call_args.kwargs["locked_until"]
    # Lockout is 15 minutes from now (the service's default duration).
    delta = locked_until - datetime.now(tz=timezone.utc)
    assert timedelta(minutes=14) < delta <= timedelta(minutes=15)


# --- logout ----------------------------------------------------------------


def test_logout_revokes_session_by_jti() -> None:
    service, _, auth_repo, _ = _make_service()

    service.logout("jti-123")

    auth_repo.revoke_session_by_jti.assert_called_once_with("jti-123")


# --- request_password_reset -----------------------------------------------


def test_request_password_reset_no_op_for_unknown_email() -> None:
    service, user_repo, _, otp_service = _make_service()
    user_repo.get_by_email.return_value = None

    result = service.request_password_reset(
        PasswordResetRequest(email="ghost@example.com")
    )

    assert result is None
    otp_service.issue.assert_not_called()


def test_request_password_reset_issues_otp_for_known_email() -> None:
    service, user_repo, _, otp_service = _make_service()
    user = _make_user()
    user_repo.get_by_email.return_value = user

    service.request_password_reset(PasswordResetRequest(email=user.email))

    otp_service.issue.assert_called_once()
    call = otp_service.issue.call_args
    assert call.kwargs["user"] is user
    assert call.kwargs["purpose"] == OTPPurpose.PASSWORD_RESET


# --- reset_password -------------------------------------------------------


def test_reset_password_revokes_all_sessions_on_success() -> None:
    service, user_repo, auth_repo, otp_service = _make_service()
    user = _make_user()
    otp_service.verify.return_value = user

    payload = PasswordResetConfirmRequest(
        email=user.email,
        code="123456",
        new_password=_NEW_PASSWORD,
    )
    service.reset_password(payload)

    # Verify the OTP service was called for PASSWORD_RESET.
    otp_service.verify.assert_called_once()
    assert otp_service.verify.call_args.kwargs["purpose"] == OTPPurpose.PASSWORD_RESET

    # The user's password hash was updated via repo.update.
    user_repo.update.assert_called_once()
    update_call = user_repo.update.call_args
    assert update_call.args[0] is user
    new_hash = update_call.kwargs["password_hash"]
    assert new_hash.startswith("$2")
    assert new_hash != _NEW_PASSWORD

    # Every session for this user was revoked (Req 4.4).
    auth_repo.revoke_all_for_user.assert_called_once_with(user.id)


def test_reset_password_rejects_weak_new_password() -> None:
    service, _, _, otp_service = _make_service()

    payload = PasswordResetConfirmRequest(
        email="alice@example.com",
        code="123456",
        new_password="short",  # fails Req 1.3 length rule
    )
    with pytest.raises(HTTPException) as exc_info:
        service.reset_password(payload)

    assert exc_info.value.status_code == 400
    # Service does not invoke the OTP service if password validation fails.
    otp_service.verify.assert_not_called()


# --- resend_verify_email --------------------------------------------------


def test_resend_verify_email_no_op_for_unknown_email() -> None:
    service, user_repo, _, otp_service = _make_service()
    user_repo.get_by_email.return_value = None

    result = service.resend_verify_email(
        OTPIssueRequest(email="ghost@example.com", purpose=OTPPurpose.VERIFY_EMAIL)
    )

    assert result is None
    otp_service.issue.assert_not_called()


def test_resend_verify_email_no_op_for_already_verified() -> None:
    service, user_repo, _, otp_service = _make_service()
    user_repo.get_by_email.return_value = _make_user(
        account_state=AccountState.VERIFIED.value
    )

    service.resend_verify_email(
        OTPIssueRequest(email="alice@example.com", purpose=OTPPurpose.VERIFY_EMAIL)
    )

    otp_service.issue.assert_not_called()


def test_resend_verify_email_issues_otp_for_unverified() -> None:
    service, user_repo, _, otp_service = _make_service()
    user = _make_user(account_state=AccountState.UNVERIFIED.value)
    user_repo.get_by_email.return_value = user

    service.resend_verify_email(
        OTPIssueRequest(email=user.email, purpose=OTPPurpose.VERIFY_EMAIL)
    )

    otp_service.issue.assert_called_once()
    call = otp_service.issue.call_args
    assert call.kwargs["user"] is user
    # The endpoint always issues VERIFY_EMAIL regardless of payload.purpose
    # (which is currently constrained to that value at the schema layer too).
    assert call.kwargs["purpose"] == OTPPurpose.VERIFY_EMAIL


# --- get_current_user_from_jti --------------------------------------------


def test_get_current_user_from_jti_returns_user_for_active_session() -> None:
    service, user_repo, auth_repo, _ = _make_service()
    now = datetime.now(tz=timezone.utc)
    session_row = MagicMock()
    session_row.user_id = 1
    session_row.revoked_at = None
    session_row.expires_at = now + timedelta(hours=1)
    auth_repo.get_session_by_jti.return_value = session_row
    user = _make_user()
    user_repo.get.return_value = user

    result = service.get_current_user_from_jti("jti-abc", now=now)

    assert result is user


def test_get_current_user_from_jti_raises_401_for_unknown_jti() -> None:
    service, _, auth_repo, _ = _make_service()
    auth_repo.get_session_by_jti.return_value = None

    with pytest.raises(HTTPException) as exc_info:
        service.get_current_user_from_jti("jti-missing")

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "invalid_credentials"


def test_get_current_user_from_jti_raises_401_for_revoked_session() -> None:
    service, _, auth_repo, _ = _make_service()
    now = datetime.now(tz=timezone.utc)
    session_row = MagicMock()
    session_row.user_id = 1
    session_row.revoked_at = now - timedelta(seconds=1)
    session_row.expires_at = now + timedelta(hours=1)
    auth_repo.get_session_by_jti.return_value = session_row

    with pytest.raises(HTTPException) as exc_info:
        service.get_current_user_from_jti("jti-revoked", now=now)

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "invalid_credentials"


def test_get_current_user_from_jti_raises_403_for_banned_user() -> None:
    service, user_repo, auth_repo, _ = _make_service()
    now = datetime.now(tz=timezone.utc)
    session_row = MagicMock()
    session_row.user_id = 1
    session_row.revoked_at = None
    session_row.expires_at = now + timedelta(hours=1)
    auth_repo.get_session_by_jti.return_value = session_row
    user_repo.get.return_value = _make_user(is_banned=True)

    with pytest.raises(HTTPException) as exc_info:
        service.get_current_user_from_jti("jti-banned", now=now)

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "account_banned"
