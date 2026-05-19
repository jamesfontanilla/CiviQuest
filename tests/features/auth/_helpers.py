"""Shared helpers for the auth slice's service-layer tests.

Pytest does not collect modules whose filename begins with an underscore, so
this module is import-only — both ``test_service.py`` and ``test_property.py``
import the factories from here. Keeping a single source of truth means the
property-tests cannot drift from the unit-test fixture shape.

The canonical "right password" is hashed once at module import to keep
wall-clock cost low: bcrypt cost 12 is expensive enough that every call
inside a hypothesis loop would balloon test runtime.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from app.features.auth.repository import AuthRepository
from app.features.auth.service import AuthService
from app.features.otp.service import OTPService
from app.features.users.models import AccountState, Category, Role, User
from app.features.users.repository import UserRepository
from app.features.users.schemas import UserCreate
from app.infrastructure.security.passwords import hash_password

# Canonical password fixtures, computed once.
_RIGHT_PASSWORD = "Strong1Pass!"
_RIGHT_HASH = hash_password(_RIGHT_PASSWORD)
_NEW_PASSWORD = "BrandNew2!Pass"

# 32 bytes — meets the RFC 7518 §3.2 minimum so pyjwt is quiet.
_TEST_JWT_SECRET = "test-secret-please-ignore-32byte!!"


def _make_user(**overrides: object) -> User:
    """Construct a detached ``User`` with safe defaults."""
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
        "password_hash": _RIGHT_HASH,
        "cross_category_preview": False,
    }
    return User(**{**defaults, **overrides})


def _make_signup_payload(**overrides: object) -> UserCreate:
    defaults: dict[str, object] = {
        "email": "alice@example.com",
        "display_name": "Alice",
        "age": 25,
        "category": "PROFESSIONAL",
        "password": _RIGHT_PASSWORD,
    }
    return UserCreate(**{**defaults, **overrides})


def _make_service(
    *,
    user_repo: MagicMock | None = None,
    auth_repo: MagicMock | None = None,
    otp_service: MagicMock | None = None,
) -> tuple[AuthService, MagicMock, MagicMock, MagicMock]:
    """Build an ``AuthService`` wired to mocked dependencies.

    Default repository behaviour: ``get_by_email`` returns ``None`` (no such
    user), no lockout, zero failed attempts. ``user_repo.create`` echoes a
    plausible persisted row so signup tests can introspect the call kwargs.
    """
    user_repo = user_repo or MagicMock(spec=UserRepository)
    auth_repo = auth_repo or MagicMock(spec=AuthRepository)
    otp_service = otp_service or MagicMock(spec=OTPService)

    user_repo.get_by_email.return_value = None
    auth_repo.get_lockout.return_value = None
    auth_repo.failed_count_in_window.return_value = 0

    def _fake_create(payload: UserCreate, **kwargs: object) -> User:
        return _make_user(
            email=payload.email,
            display_name=payload.display_name,
            age=payload.age,
            category=payload.category.value,
            account_state=(
                kwargs.get("account_state", AccountState.UNVERIFIED).value
                if hasattr(kwargs.get("account_state", AccountState.UNVERIFIED), "value")
                else str(kwargs.get("account_state", AccountState.UNVERIFIED.value))
            ),
            password_hash=str(kwargs.get("password_hash", "x")),
        )

    user_repo.create.side_effect = _fake_create

    service = AuthService(
        user_repo=user_repo,
        auth_repo=auth_repo,
        otp_service=otp_service,
    )
    return service, user_repo, auth_repo, otp_service
