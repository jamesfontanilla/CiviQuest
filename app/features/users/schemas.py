"""Pydantic request/response schemas for users.

Three schemas per ``code-conventions.md``: ``UserCreate`` for signup,
``UserUpdate`` for the limited self-edit surface, and ``UserResponse`` for
read-side output (with ``from_attributes=True`` so ORM rows serialize
directly).

Email validation: we use a project-local regex rather than ``EmailStr`` so
the test suite does not depend on the ``email-validator`` package being
installed alongside ``pydantic[email]``. The regex is intentionally permissive
(it is not RFC 5321 compliant) and is sufficient for the MVP. Swap in
``EmailStr`` once ``email-validator`` is part of the runtime deps.

Password validation enforces Req 1.3 in five independent checks so the error
message identifies the failed rule.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.features.users.models import AccountState, Category, Role

# Project-local email regex. See module docstring for the deviation note.
_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")

# Symbol set per Req 1.3.
_PASSWORD_SYMBOLS = frozenset("!@#$%^&*()-_=+[]{};:,.<>?/")


def _validate_email(value: str) -> str:
    """Strip, lowercase, and validate against the local email regex.

    Raises:
        ValueError: when ``value`` does not look like an email address.
    """
    normalized = value.strip().lower()
    if not _EMAIL_RE.fullmatch(normalized):
        raise ValueError("invalid email format")
    return normalized


def _validate_password(value: str) -> str:
    """Apply Req 1.3 password rules and return the value unchanged.

    Each rule is checked independently so the failure message names the
    specific rule that was missed; the auth service surfaces this verbatim.
    """
    if len(value) < 8:
        raise ValueError("password must be at least 8 characters")
    if not any(c.isupper() for c in value):
        raise ValueError("password must contain an uppercase letter")
    if not any(c.islower() for c in value):
        raise ValueError("password must contain a lowercase letter")
    if not any(c.isdigit() for c in value):
        raise ValueError("password must contain a digit")
    if not any(c in _PASSWORD_SYMBOLS for c in value):
        raise ValueError("password must contain a symbol from the allowed set")
    return value


# Public alias so other slices (auth.reset_password) can re-validate without
# round-tripping through ``UserCreate``. The underscore-prefixed original
# stays so existing imports still resolve.
validate_password = _validate_password


class UserCreate(BaseModel):
    """Signup payload (Req 1.1, 1.3, 1.4, 1.5)."""

    email: str
    display_name: str = Field(min_length=1, max_length=255)
    age: int = Field(ge=15, le=100)
    category: Category
    password: str

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, v: str) -> str:
        return _validate_email(v)

    @field_validator("password")
    @classmethod
    def _password_rules(cls, v: str) -> str:
        return _validate_password(v)


class UserUpdate(BaseModel):
    """Self-edit payload. ``PATCH`` semantics: omitted fields stay unchanged."""

    display_name: str | None = Field(default=None, min_length=1, max_length=255)
    tz_name: str | None = None


class UserResponse(BaseModel):
    """Read-side projection. ``from_attributes`` enables ORM-row serialization."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    display_name: str
    age: int
    category: Category
    role: Role
    account_state: AccountState
    is_banned: bool
    tz_name: str
