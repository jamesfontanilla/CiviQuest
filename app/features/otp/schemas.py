"""Pydantic schemas for OTP issuance and verification.

The 6-digit numeric pattern is enforced via ``Field(pattern=...)`` so a
non-numeric or wrong-length code is rejected as a 422 by FastAPI before the
service layer is reached. Email is normalised the same way as ``UserCreate``
so a mixed-case input matches the stored row.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from app.features.otp.models import OTPPurpose
from app.features.users.schemas import _validate_email


class OTPIssueRequest(BaseModel):
    """Payload for ``POST /v1/auth/email-verifications:resend`` and
    ``POST /v1/auth/password-reset-requests``."""

    email: str
    purpose: OTPPurpose

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, v: str) -> str:
        return _validate_email(v)


class OTPVerifyRequest(BaseModel):
    """Payload for OTP verification (Req 2.2 and Req 4.3 share this shape).

    The ``code`` field is constrained to exactly six ASCII digits at the
    schema layer; this is the same regex the canonical 6-digit OTP must
    satisfy, so any stray whitespace or non-digit input fails validation
    before reaching the service.
    """

    email: str
    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")
    purpose: OTPPurpose

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, v: str) -> str:
        return _validate_email(v)
