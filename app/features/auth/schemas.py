"""Pydantic request/response schemas for the auth feature.

These shape the wire API consumed by the auth router. The OTP-shaped
schemas (``OTPVerifyRequest``) live in ``app/features/otp/schemas.py`` and
are reused by the email-verification endpoint via the auth router.

Email normalization reuses the project-local ``_validate_email`` helper so
inputs are matched against stored rows lowercase-insensitively.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

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


class GoogleAuthRequest(BaseModel):
    """Payload for ``POST /v1/auth/google`` — Google OAuth login/signup.

    ``id_token`` is the credential string returned by Google Identity Services
    on the client side. The backend verifies it against Google's public keys.

    ``category`` is required only for first-time signup (when the Google user
    does not yet have an account). For returning users it is ignored.
    """

    id_token: str = Field(min_length=1)
    category: str | None = None

    @field_validator("category")
    @classmethod
    def _validate_category(cls, v: str | None) -> str | None:
        if v is None:
            return None
        upper = v.strip().upper()
        if upper not in ("PROFESSIONAL", "SUB_PROFESSIONAL"):
            raise ValueError("category must be PROFESSIONAL or SUB_PROFESSIONAL")
        return upper


class GoogleAuthResponse(BaseModel):
    """Response shape for ``POST /v1/auth/google``.

    Extends ``LoginResponse`` with user info and a flag indicating whether
    this was a new signup (so the client can redirect to onboarding/category
    confirmation) or a returning login.
    """

    access_token: str
    token_type: str = "Bearer"
    expires_in: int
    is_new_user: bool
    user: "GoogleUserResponse"


class GoogleUserResponse(BaseModel):
    """Minimal user info returned after Google auth."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    display_name: str
    category: str
