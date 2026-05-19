"""Schema-validation tests for the OTP slice.

Verifies the 6-digit numeric pattern (Req 2.1) and email normalisation.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.features.otp.models import OTPPurpose
from app.features.otp.schemas import OTPIssueRequest, OTPVerifyRequest


def test_otp_verify_rejects_letters() -> None:
    with pytest.raises(ValidationError):
        OTPVerifyRequest(
            email="alice@example.com",
            code="abcdef",
            purpose=OTPPurpose.VERIFY_EMAIL,
        )


def test_otp_verify_rejects_short_code() -> None:
    with pytest.raises(ValidationError):
        OTPVerifyRequest(
            email="alice@example.com",
            code="12345",
            purpose=OTPPurpose.VERIFY_EMAIL,
        )


def test_otp_verify_rejects_long_code() -> None:
    with pytest.raises(ValidationError):
        OTPVerifyRequest(
            email="alice@example.com",
            code="1234567",
            purpose=OTPPurpose.VERIFY_EMAIL,
        )


def test_otp_verify_accepts_six_digits() -> None:
    req = OTPVerifyRequest(
        email="alice@example.com",
        code="123456",
        purpose=OTPPurpose.VERIFY_EMAIL,
    )
    assert req.code == "123456"
    assert req.purpose is OTPPurpose.VERIFY_EMAIL


def test_otp_verify_lowercases_email() -> None:
    req = OTPVerifyRequest(
        email="MIXED@Example.com",
        code="123456",
        purpose=OTPPurpose.PASSWORD_RESET,
    )
    assert req.email == "mixed@example.com"


def test_otp_issue_lowercases_email() -> None:
    req = OTPIssueRequest(
        email="MIXED@Example.com", purpose=OTPPurpose.VERIFY_EMAIL
    )
    assert req.email == "mixed@example.com"


def test_otp_issue_rejects_invalid_purpose() -> None:
    with pytest.raises(ValidationError):
        OTPIssueRequest(email="alice@example.com", purpose="UNLOCK")  # type: ignore[arg-type]
