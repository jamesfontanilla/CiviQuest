"""Shared helpers for the OTP slice's service-layer tests.

Pytest does not collect modules whose filename begins with an underscore, so
this module is import-only — both ``test_service.py`` and ``test_property.py``
import the factories from here. Keeping a single source of truth means the
property-tests cannot drift from the unit-test fixture shape.

Bcrypt cost factor 12 is expensive; computing :data:`_SUCCESS_HASH` once at
module import keeps every consumer's wall-clock budget bounded.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from app.features.otp.models import OTP, OTPPurpose
from app.features.otp.repository import OTPRepository
from app.features.otp.service import OTPService
from app.features.users.models import AccountState, Category, Role, User
from app.features.users.repository import UserRepository
from app.infrastructure.external.offline_otp_writer import OfflineOtpWriter
from app.infrastructure.external.smtp_otp_sender import SmtpOtpSender
from app.infrastructure.security.passwords import hash_password

# Reused across tests so we only pay the bcrypt cost once.
_SUCCESS_CODE = "111222"
_SUCCESS_HASH = hash_password(_SUCCESS_CODE)


def _make_user(**overrides: object) -> User:
    """Construct a detached ``User`` row with safe defaults."""
    defaults: dict[str, object] = {
        "id": 1,
        "email": "alice@example.com",
        "display_name": "Alice",
        "age": 25,
        "category": Category.PROFESSIONAL.value,
        "role": Role.LEARNER.value,
        "account_state": AccountState.UNVERIFIED.value,
        "is_banned": False,
        "tz_name": "UTC",
        "password_hash": "bcrypt$fake$hash",
        "cross_category_preview": False,
    }
    return User(**{**defaults, **overrides})


def _make_otp(
    *,
    user_id: int = 1,
    purpose: OTPPurpose = OTPPurpose.VERIFY_EMAIL,
    code_hash: str = _SUCCESS_HASH,
    attempt_count: int = 0,
    used: bool = False,
    invalidated: bool = False,
    expires_in_minutes: int = 5,
) -> OTP:
    """Build a detached ``OTP`` row mirroring what the repo would return."""
    now = datetime.now(tz=timezone.utc)
    otp = OTP(
        user_id=user_id,
        purpose=purpose.value,
        code_hash=code_hash,
        expires_at=now + timedelta(minutes=expires_in_minutes),
        used=used,
        invalidated=invalidated,
        attempt_count=attempt_count,
    )
    otp.id = 100
    return otp


def _make_service(
    *,
    user_repo: MagicMock | None = None,
    otp_repo: MagicMock | None = None,
    offline_writer: MagicMock | None = None,
    smtp_sender: MagicMock | None = None,
    rate_limit_per_60min: int = 5,
    max_verify_attempts: int = 5,
) -> tuple[OTPService, MagicMock, MagicMock, MagicMock, MagicMock]:
    """Build an ``OTPService`` wired to mocked dependencies.

    Default repo behaviour: no rate-limit pressure, no prior unused OTPs,
    ``create`` returns whatever is passed in (the real repo refreshes and
    returns the persisted row, but tests rarely care about the exact identity).
    """
    user_repo = user_repo or MagicMock(spec=UserRepository)
    otp_repo = otp_repo or MagicMock(spec=OTPRepository)
    offline_writer = offline_writer or MagicMock(spec=OfflineOtpWriter)
    smtp_sender = smtp_sender or MagicMock(spec=SmtpOtpSender)

    otp_repo.count_issuances_in_last_60min.return_value = 0
    otp_repo.invalidate_unused_for.return_value = 0
    otp_repo.create.side_effect = lambda otp: otp

    service = OTPService(
        user_repo=user_repo,
        otp_repo=otp_repo,
        offline_writer=offline_writer,
        smtp_sender=smtp_sender,
        rate_limit_per_60min=rate_limit_per_60min,
        max_verify_attempts=max_verify_attempts,
    )
    return service, user_repo, otp_repo, offline_writer, smtp_sender
