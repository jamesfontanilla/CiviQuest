"""Service tests for ``OTPService``.

Per ``testing-standards.md``, service tests use ``MagicMock(spec=...)`` for
repositories and adapters; no real DB is involved. ``hash_password`` /
``verify_password`` are exercised for real (rather than mocked) so we
actually validate the bcrypt round-trip semantics that the service relies
on. To keep wall-clock cost low, we hash one canonical "success" code at
module import and reuse it across tests.

Helpers (``_make_user``, ``_make_otp``, ``_make_service``, ``_SUCCESS_CODE``,
``_SUCCESS_HASH``) live in ``_helpers.py`` so they can be reused by the
property-test module without duplication. Pytest skips files whose name
begins with ``_``, so the helper module is not collected as tests.
"""

from __future__ import annotations

import re

import pytest
from fastapi import HTTPException

from app.features.otp.models import OTP, OTPPurpose
from tests.features.otp._helpers import (
    _SUCCESS_CODE,
    _SUCCESS_HASH,
    _make_otp,
    _make_service,
    _make_user,
)


# --- issue -----------------------------------------------------------------


def test_issue_invalidates_prior_unused() -> None:
    service, _, otp_repo, _, _ = _make_service()
    user = _make_user()

    service.issue(user=user, purpose=OTPPurpose.VERIFY_EMAIL)

    otp_repo.invalidate_unused_for.assert_called_once_with(
        user.id, OTPPurpose.VERIFY_EMAIL
    )


def test_issue_persists_hashed_code_not_plaintext() -> None:
    service, _, otp_repo, _, _ = _make_service()
    user = _make_user()

    service.issue(user=user, purpose=OTPPurpose.VERIFY_EMAIL)

    # The repo's ``create`` was called with an ORM instance; capture and
    # inspect ``code_hash``. It must look like a bcrypt hash, not a digit
    # string.
    otp_repo.create.assert_called_once()
    persisted: OTP = otp_repo.create.call_args.args[0]
    assert persisted.code_hash.startswith("$2")
    assert not re.fullmatch(r"\d{6}", persisted.code_hash)


def test_issue_writes_to_offline_in_offline_mode() -> None:
    service, _, _, offline_writer, smtp_sender = _make_service()
    user = _make_user()

    service.issue(user=user, purpose=OTPPurpose.VERIFY_EMAIL, mode="offline")

    offline_writer.write_otp.assert_called_once()
    call = offline_writer.write_otp.call_args
    assert call.kwargs["email"] == user.email
    assert call.kwargs["purpose"] == OTPPurpose.VERIFY_EMAIL.value
    assert re.fullmatch(r"\d{6}", call.kwargs["code"])
    smtp_sender.send_otp.assert_not_called()


def test_issue_calls_smtp_in_online_mode() -> None:
    service, _, _, offline_writer, smtp_sender = _make_service()
    user = _make_user()

    service.issue(user=user, purpose=OTPPurpose.VERIFY_EMAIL, mode="online")

    smtp_sender.send_otp.assert_called_once()
    call = smtp_sender.send_otp.call_args
    assert call.kwargs["to_email"] == user.email
    assert call.kwargs["purpose"] == OTPPurpose.VERIFY_EMAIL.value
    assert re.fullmatch(r"\d{6}", call.kwargs["code"])
    offline_writer.write_otp.assert_not_called()


def test_issue_writes_to_both_in_both_mode() -> None:
    service, _, _, offline_writer, smtp_sender = _make_service()
    user = _make_user()

    service.issue(user=user, purpose=OTPPurpose.VERIFY_EMAIL, mode="both")

    offline_writer.write_otp.assert_called_once()
    smtp_sender.send_otp.assert_called_once()


def test_issue_raises_429_when_rate_limit_exceeded() -> None:
    service, _, otp_repo, offline_writer, smtp_sender = _make_service(
        rate_limit_per_60min=5
    )
    otp_repo.count_issuances_in_last_60min.return_value = 5
    user = _make_user()

    with pytest.raises(HTTPException) as exc_info:
        service.issue(user=user, purpose=OTPPurpose.VERIFY_EMAIL)

    assert exc_info.value.status_code == 429
    assert exc_info.value.detail == "rate_limited"
    # No side effects after rate-limit rejection.
    otp_repo.invalidate_unused_for.assert_not_called()
    otp_repo.create.assert_not_called()
    offline_writer.write_otp.assert_not_called()
    smtp_sender.send_otp.assert_not_called()


# --- verify ----------------------------------------------------------------


def test_verify_returns_user_on_success() -> None:
    service, user_repo, otp_repo, _, _ = _make_service()
    user = _make_user()
    otp = _make_otp()
    user_repo.get_by_email.return_value = user
    otp_repo.get_latest_active.return_value = otp

    result = service.verify(
        email=user.email,
        code=_SUCCESS_CODE,
        purpose=OTPPurpose.VERIFY_EMAIL,
    )

    assert result is user


def test_verify_marks_otp_used_on_success() -> None:
    service, user_repo, otp_repo, _, _ = _make_service()
    user = _make_user()
    otp = _make_otp()
    user_repo.get_by_email.return_value = user
    otp_repo.get_latest_active.return_value = otp

    service.verify(
        email=user.email,
        code=_SUCCESS_CODE,
        purpose=OTPPurpose.VERIFY_EMAIL,
    )

    otp_repo.mark_used.assert_called_once_with(otp)


def test_verify_raises_canonical_400_for_unknown_email() -> None:
    service, user_repo, _, _, _ = _make_service()
    user_repo.get_by_email.return_value = None

    with pytest.raises(HTTPException) as exc_info:
        service.verify(
            email="ghost@example.com",
            code=_SUCCESS_CODE,
            purpose=OTPPurpose.VERIFY_EMAIL,
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "otp_invalid_or_expired"


def test_verify_raises_canonical_400_for_no_active_otp() -> None:
    service, user_repo, otp_repo, _, _ = _make_service()
    user_repo.get_by_email.return_value = _make_user()
    otp_repo.get_latest_active.return_value = None

    with pytest.raises(HTTPException) as exc_info:
        service.verify(
            email="alice@example.com",
            code=_SUCCESS_CODE,
            purpose=OTPPurpose.VERIFY_EMAIL,
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "otp_invalid_or_expired"


def test_verify_raises_canonical_400_for_wrong_code() -> None:
    service, user_repo, otp_repo, _, _ = _make_service()
    user = _make_user()
    # Hash for a different code.
    otp = _make_otp(code_hash=_SUCCESS_HASH)
    user_repo.get_by_email.return_value = user
    otp_repo.get_latest_active.return_value = otp

    with pytest.raises(HTTPException) as exc_info:
        service.verify(
            email=user.email,
            code="999999",  # not _SUCCESS_CODE
            purpose=OTPPurpose.VERIFY_EMAIL,
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "otp_invalid_or_expired"
    otp_repo.mark_used.assert_not_called()


def test_verify_invalidates_on_sixth_attempt() -> None:
    service, user_repo, otp_repo, _, _ = _make_service()
    user = _make_user()

    # Pre-existing OTP with attempt_count=5; the bump_attempt side-effect
    # will push it to 6 which crosses ``max_verify_attempts + 1 == 6``.
    otp = _make_otp(attempt_count=5)

    def _bump(o: OTP) -> OTP:
        o.attempt_count += 1
        return o

    otp_repo.bump_attempt.side_effect = _bump
    user_repo.get_by_email.return_value = user
    otp_repo.get_latest_active.return_value = otp

    with pytest.raises(HTTPException) as exc_info:
        service.verify(
            email=user.email,
            code=_SUCCESS_CODE,  # Even with the right code, cap takes precedence.
            purpose=OTPPurpose.VERIFY_EMAIL,
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "otp_invalid_or_expired"
    otp_repo.mark_invalidated.assert_called_once_with(otp)
    otp_repo.mark_used.assert_not_called()


def test_verify_uses_same_message_for_all_failures() -> None:
    """All failure paths must surface the exact same canonical detail string.

    Req 2.3: the response shape must not differ across failure modes.
    """
    user = _make_user()

    # Case 1: unknown email.
    service1, user_repo1, _, _, _ = _make_service()
    user_repo1.get_by_email.return_value = None
    with pytest.raises(HTTPException) as e1:
        service1.verify(
            email="ghost@example.com",
            code=_SUCCESS_CODE,
            purpose=OTPPurpose.VERIFY_EMAIL,
        )

    # Case 2: no active OTP.
    service2, user_repo2, otp_repo2, _, _ = _make_service()
    user_repo2.get_by_email.return_value = user
    otp_repo2.get_latest_active.return_value = None
    with pytest.raises(HTTPException) as e2:
        service2.verify(
            email=user.email,
            code=_SUCCESS_CODE,
            purpose=OTPPurpose.VERIFY_EMAIL,
        )

    # Case 3: wrong code.
    service3, user_repo3, otp_repo3, _, _ = _make_service()
    user_repo3.get_by_email.return_value = user
    otp_repo3.get_latest_active.return_value = _make_otp()
    with pytest.raises(HTTPException) as e3:
        service3.verify(
            email=user.email,
            code="999999",
            purpose=OTPPurpose.VERIFY_EMAIL,
        )

    # Case 4: attempt cap exceeded.
    service4, user_repo4, otp_repo4, _, _ = _make_service()
    user_repo4.get_by_email.return_value = user

    def _bump(o: OTP) -> OTP:
        o.attempt_count += 1
        return o

    otp_repo4.bump_attempt.side_effect = _bump
    otp_repo4.get_latest_active.return_value = _make_otp(attempt_count=5)
    with pytest.raises(HTTPException) as e4:
        service4.verify(
            email=user.email,
            code=_SUCCESS_CODE,
            purpose=OTPPurpose.VERIFY_EMAIL,
        )

    details = {e1.value.detail, e2.value.detail, e3.value.detail, e4.value.detail}
    statuses = {
        e1.value.status_code,
        e2.value.status_code,
        e3.value.status_code,
        e4.value.status_code,
    }
    assert details == {"otp_invalid_or_expired"}
    assert statuses == {400}
