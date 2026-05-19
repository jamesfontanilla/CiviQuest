"""Pydantic request/response schemas for the auth feature.

These shape the wire API consumed by the auth router. The OTP-shaped
schemas (``OTPVerifyRequest``) live in ``app/features/otp/schemas.py`` and
are reused by the email-verification endpoint via the auth router.

Email normalization reuses the project-local ``_validate_email`` helper so
inputs are matched against stored rows lowercase-insensitively.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from app.features.users.schemas import _validate_email


class LoginRequest(BaseModel):
    """Payload for ``POST /v1/auth/sessions`` (Req 3.1)."""

    email: str
    password: str

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, v: str) -> str:
        return _validate_email(v)


class LoginResponse(BaseModel):
    """Response shape for a successful login.

    ``expires_in`` is a number of seconds rather than an absolute timestamp
    so clients don't need to reason about clock skew (per OAuth 2 §5.1).
    """

    access_token: str
    token_type: str = "Bearer"
    expires_in: int


class PasswordResetRequest(BaseModel):
    """Payload for ``POST /v1/auth/password-reset-requests`` (Req 4.1, 4.2).

    The response shape is identical regardless of whether the email exists
    so the endpoint is not an enumeration oracle.
    """

    email: str

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, v: str) -> str:
        return _validate_email(v)


class PasswordResetConfirmRequest(BaseModel):
    """Payload for ``POST /v1/auth/password-resets`` (Req 4.3).

    The 6-digit code regex matches the OTP schema so a malformed code is
    rejected at the FastAPI 422 layer rather than reaching the service.
    Password rules are re-applied inside the service via
    :func:`app.features.users.schemas.validate_password` to keep the
    Req 1.3 enforcement in exactly one place.
    """

    email: str
    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")
    new_password: str

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, v: str) -> str:
        return _validate_email(v)
