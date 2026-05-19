"""OTP business logic: issuance, verification, attempt tracking.

This service orchestrates the OTP state machine described in design "Key
Algorithms" and Requirements 2.1-2.8. The high-level shape:

- ``issue`` enforces the rolling-60-minute issuance cap (Req 2.6),
  invalidates any prior unused OTP for the (user, purpose) pair (Req 2.5),
  generates a 6-digit code via the cryptographic RNG (Req 2.1), bcrypt-hashes
  it before persistence (Req 2.3 + ``security-policy.md``), and dispatches to
  the offline file writer and/or SMTP stub depending on ``mode``. The
  plaintext code is delivered to the user via the adapter and otherwise
  discarded; only the hash and metadata are persisted.

- ``verify`` looks up the latest active OTP for the user/purpose, bumps the
  attempt counter unconditionally, invalidates after the 6th attempt
  (Req 2.7), and bcrypt-checks the supplied code. ALL failure paths
  (unknown email, no active OTP, hash mismatch, attempt cap exceeded) raise
  the same ``HTTPException(400, "otp_invalid_or_expired")`` so the response
  envelope is byte-identical regardless of which branch failed (Req 2.3).

Constructor injection per ``code-conventions.md``; the FastAPI factory wires
the dependencies in the auth router task.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Final

from fastapi import HTTPException, status

from app.features.otp.models import OTP, OTPPurpose
from app.features.otp.repository import OTPRepository
from app.features.users.models import User
from app.features.users.repository import UserRepository
from app.infrastructure.external.offline_otp_writer import OfflineOtpWriter
from app.infrastructure.external.smtp_otp_sender import SmtpOtpSender
from app.infrastructure.security.passwords import hash_password, verify_password
from app.infrastructure.security.rng import randbelow_six_digits

# Canonical, snake_case error strings. Tests assert on these literally.
_ERR_RATE_LIMITED: Final[str] = "rate_limited"
_ERR_INVALID_OR_EXPIRED: Final[str] = "otp_invalid_or_expired"

_OTP_TTL_MINUTES: Final[int] = 5

# Allowed delivery modes.
_MODE_OFFLINE: Final[str] = "offline"
_MODE_ONLINE: Final[str] = "online"
_MODE_BOTH: Final[str] = "both"


def _utcnow() -> datetime:
    """Aware UTC `now` so callers can pin time during tests."""
    return datetime.now(tz=timezone.utc)


class OTPService:
    """Issue and verify one-time passwords.

    Constructor injection only — the FastAPI factory wires this in the auth
    router task. No DB session is held directly; persistence flows through
    the injected repositories per ``code-conventions.md``.
    """

    def __init__(
        self,
        *,
        user_repo: UserRepository,
        otp_repo: OTPRepository,
        offline_writer: OfflineOtpWriter,
        smtp_sender: SmtpOtpSender,
        rate_limit_per_60min: int = 5,
        max_verify_attempts: int = 5,
    ) -> None:
        self._user_repo = user_repo
        self._otp_repo = otp_repo
        self._offline_writer = offline_writer
        self._smtp_sender = smtp_sender
        self._rate_limit_per_60min = rate_limit_per_60min
        self._max_verify_attempts = max_verify_attempts

    # ------------------------------------------------------------------
    # issue
    # ------------------------------------------------------------------

    def issue(
        self,
        *,
        user: User,
        purpose: OTPPurpose,
        mode: str = _MODE_OFFLINE,
        now: datetime | None = None,
    ) -> OTP:
        """Issue a fresh OTP for ``user`` and ``purpose``.

        Steps (Req 2.1, 2.5, 2.6, 2.8):

        1. Enforce the rolling 60-minute issuance cap (Req 2.6).
        2. Invalidate any prior unused OTP for the (user, purpose) pair so
           the previous code can no longer be used (Req 2.5).
        3. Generate a 6-digit code via the cryptographic RNG (Req 2.1).
        4. bcrypt-hash the code and persist the OTP row with a 5-minute
           expiry (Req 2.1, 2.3 + security-policy).
        5. Deliver the plaintext code via the adapter(s) selected by
           ``mode``: ``offline`` writes to the local OTP log (Req 2.8),
           ``online`` invokes the SMTP stub, ``both`` does both. MVP
           default is offline-only.

        Returns:
            The persisted ``OTP`` row. The plaintext code is not returned.

        Raises:
            HTTPException 429 ``rate_limited`` when the cap is exceeded.
        """
        now = now or _utcnow()

        # --- Req 2.6: rolling 60-minute issuance cap.
        prior_count = self._otp_repo.count_issuances_in_last_60min(user.id, now=now)
        if prior_count >= self._rate_limit_per_60min:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=_ERR_RATE_LIMITED,
            )

        # --- Req 2.5: invalidate any prior unused OTP for this (user, purpose).
        self._otp_repo.invalidate_unused_for(user.id, purpose)

        # --- Req 2.1: generate, hash, persist.
        code = randbelow_six_digits()
        code_hash = hash_password(code)
        otp = OTP(
            user_id=user.id,
            purpose=purpose.value,
            code_hash=code_hash,
            expires_at=now + timedelta(minutes=_OTP_TTL_MINUTES),
        )
        otp = self._otp_repo.create(otp)

        # --- Req 2.1, 2.8: deliver via adapter(s).
        self._deliver(user=user, purpose=purpose, code=code, mode=mode)

        return otp

    def _deliver(
        self, *, user: User, purpose: OTPPurpose, code: str, mode: str
    ) -> None:
        """Dispatch OTP delivery to the appropriate adapter(s)."""
        if mode == _MODE_OFFLINE:
            self._offline_writer.write_otp(
                email=user.email, purpose=purpose.value, code=code
            )
        elif mode == _MODE_ONLINE:
            self._smtp_sender.send_otp(
                to_email=user.email, code=code, purpose=purpose.value
            )
        elif mode == _MODE_BOTH:
            self._offline_writer.write_otp(
                email=user.email, purpose=purpose.value, code=code
            )
            self._smtp_sender.send_otp(
                to_email=user.email, code=code, purpose=purpose.value
            )
        else:
            # Defensive: an unknown mode is a programmer error, not a user
            # error. Fail loudly rather than silently swallowing the OTP.
            raise ValueError(f"unknown OTP delivery mode: {mode!r}")

    # ------------------------------------------------------------------
    # verify
    # ------------------------------------------------------------------

    def verify(
        self,
        *,
        email: str,
        code: str,
        purpose: OTPPurpose,
        now: datetime | None = None,
    ) -> User:
        """Verify ``code`` for the ``(email, purpose)`` pair.

        Returns the matching ``User`` on success and raises the canonical
        ``HTTPException(400, "otp_invalid_or_expired")`` on every failure
        path. Per Req 2.3, callers cannot tell from the response which of
        the following caused the failure:

        - ``email`` does not belong to any user
        - the user has no active OTP for ``purpose``
        - the OTP has been invalidated by the attempt cap (Req 2.7)
        - the supplied code does not match the stored bcrypt hash
        - the OTP has expired (the repository excludes expired rows from
          ``get_latest_active``, so this collapses into "no active OTP")

        On the success path, the OTP is marked used (Req 2.2). The attempt
        counter is bumped on every verify call regardless of outcome so the
        6-attempt cap (Req 2.7) is enforced.
        """
        now = now or _utcnow()

        user = self._user_repo.get_by_email(email)
        if user is None:
            raise self._canonical_failure()

        otp = self._otp_repo.get_latest_active(user.id, purpose, now=now)
        if otp is None:
            raise self._canonical_failure()

        # Req 2.7: bump first so attempt_count reflects every call. After the
        # bump, if we are at or past the cap, invalidate and reject.
        self._otp_repo.bump_attempt(otp)
        if otp.attempt_count >= self._max_verify_attempts + 1:
            self._otp_repo.mark_invalidated(otp)
            raise self._canonical_failure()

        if not verify_password(code, otp.code_hash):
            raise self._canonical_failure()

        self._otp_repo.mark_used(otp)
        return user

    @staticmethod
    def _canonical_failure() -> HTTPException:
        """Return the single canonical 400 error used for all verify failures."""
        return HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_ERR_INVALID_OR_EXPIRED,
        )
