"""Auth business logic: signup, login, logout, password reset.

This service orchestrates the auth state machine described in design and
Requirements 1, 3, 4, plus the verify-email transition from Req 2.

Constructor injection per ``code-conventions.md``: the FastAPI factory
(Task 4.9) wires :class:`UserRepository`, :class:`AuthRepository`, and
:class:`OTPService`. No DB session lives on the service.

Canonical error messages (snake_case detail strings):
``email_already_registered`` (409), ``invalid_credentials`` (401),
``temporarily_locked`` (401), ``account_banned`` (403),
``email_not_verified`` (403), ``otp_invalid_or_expired`` (400 — propagated
from the OTP service), ``rate_limited`` (429 — propagated from the OTP
service). Tests assert on these literal strings.

Time injection: every method that depends on wall-clock time accepts a
``now`` keyword so property tests can pin the clock without monkeypatching.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Final

from fastapi import HTTPException, status

from app.features.auth.repository import AuthRepository
from app.features.auth.schemas import (
    LoginRequest,  # noqa: F401  -- used by router; re-exported for clarity
    PasswordResetConfirmRequest,
    PasswordResetRequest,
)
from app.features.otp.models import OTPPurpose
from app.features.otp.schemas import OTPIssueRequest, OTPVerifyRequest
from app.features.otp.service import OTPService
from app.features.users.models import AccountState, User
from app.features.users.repository import UserRepository
from app.features.users.schemas import UserCreate, validate_password
from app.infrastructure.external.google_oauth import GoogleOAuthVerifier, GoogleUserInfo
from app.infrastructure.security.jwt import encode_token
from app.infrastructure.security.passwords import hash_password, verify_password

# Canonical error strings.
_ERR_EMAIL_TAKEN: Final[str] = "email_already_registered"
_ERR_INVALID_CREDENTIALS: Final[str] = "invalid_credentials"
_ERR_LOCKED: Final[str] = "temporarily_locked"
_ERR_BANNED: Final[str] = "account_banned"
_ERR_NOT_VERIFIED: Final[str] = "email_not_verified"
_ERR_GOOGLE_TOKEN_INVALID: Final[str] = "google_token_invalid"
_ERR_CATEGORY_REQUIRED: Final[str] = "category_required"


def _utcnow() -> datetime:
    """Aware UTC `now` so callers can pin time during tests."""
    return datetime.now(tz=timezone.utc)


class AuthService:
    """Auth orchestration: signup, login, logout, password reset.

    Dependencies are passed via constructor; the FastAPI factory wires the
    request-scoped repositories and OTP service. Lockout knobs default to
    Req 3.3 values (5 failures / 15 min window / 15 min duration) but are
    overridable so admin-tunable tests can vary them.
    """

    def __init__(
        self,
        *,
        user_repo: UserRepository,
        auth_repo: AuthRepository,
        otp_service: OTPService,
        google_verifier: GoogleOAuthVerifier | None = None,
        lockout_threshold: int = 5,
        lockout_window_minutes: int = 15,
        lockout_duration_minutes: int = 15,
    ) -> None:
        self._user_repo = user_repo
        self._auth_repo = auth_repo
        self._otp_service = otp_service
        self._google_verifier = google_verifier
        self._lockout_threshold = lockout_threshold
        self._lockout_window_minutes = lockout_window_minutes
        self._lockout_duration_minutes = lockout_duration_minutes

    # ------------------------------------------------------------------
    # signup
    # ------------------------------------------------------------------

    def signup(self, payload: UserCreate, *, mode: str = "online") -> User:
        """Create an UNVERIFIED account and issue a VERIFY_EMAIL OTP.

        The account cannot log in until the OTP is verified via
        ``POST /v1/auth/email-verifications``.
        """
        if self._user_repo.get_by_email(payload.email) is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=_ERR_EMAIL_TAKEN,
            )

        password_hash = hash_password(payload.password)
        user = self._user_repo.create(
            payload,
            password_hash=password_hash,
            account_state=AccountState.UNVERIFIED,
        )

        self._otp_service.issue(
            user=user,
            purpose=OTPPurpose.VERIFY_EMAIL,
            mode=mode,
        )
        return user

    # ------------------------------------------------------------------
    # email verification
    # ------------------------------------------------------------------

    def verify_email(self, payload: OTPVerifyRequest) -> User:
        """Verify a VERIFY_EMAIL OTP and transition the account to VERIFIED.

        Failures from the OTP service (canonical 400 ``otp_invalid_or_expired``)
        propagate unchanged so the response shape is byte-identical across
        all OTP-failure paths (Req 2.3).
        """
        user = self._otp_service.verify(
            email=payload.email,
            code=payload.code,
            purpose=OTPPurpose.VERIFY_EMAIL,
        )
        return self._user_repo.set_account_state(user, AccountState.VERIFIED)

    def resend_verify_email(
        self, payload: OTPIssueRequest, *, mode: str = "online"
    ) -> None:
        """Re-issue a VERIFY_EMAIL OTP for ``payload.email`` if applicable.

        Silent no-ops:

        - Unknown email — never reveal whether an account exists (Req 4.2
          mirrors this enumeration-resistance posture).
        - Already-verified account — re-issuing a verification OTP is
          meaningless and would surface the same enumeration signal.

        Otherwise issues a fresh VERIFY_EMAIL OTP via the OTP service. The
        purpose carried in ``payload`` is ignored on purpose: this endpoint
        is dedicated to the email-verification flow, and accepting an
        attacker-controlled purpose would let a caller pivot the resend
        endpoint into a password-reset oracle.
        """
        user = self._user_repo.get_by_email(payload.email)
        if user is None:
            return
        if user.account_state == AccountState.VERIFIED.value:
            return
        self._otp_service.issue(
            user=user,
            purpose=OTPPurpose.VERIFY_EMAIL,
            mode=mode,
        )

    # ------------------------------------------------------------------
    # login / logout
    # ------------------------------------------------------------------

    def login(
        self,
        *,
        email: str,
        password: str,
        now: datetime | None = None,
    ) -> tuple[str, dict[str, Any]]:
        """Authenticate and mint a session token.

        Branches (Req 2.4, 3.1, 3.2, 3.3, 15.3):

        - Unknown email -> record a no-user failed attempt, raise 401
          ``invalid_credentials`` (Req 3.2: same response as bad password).
        - Active lockout -> 401 ``temporarily_locked`` (Req 3.3).
        - Banned user -> 403 ``account_banned`` (Req 15.3).
        - Wrong password -> record failure, advance lockout if threshold
          crossed, raise 401 ``invalid_credentials``.
        - UNVERIFIED account -> 403 ``email_not_verified`` (Req 2.4).
        - Success -> mint JWT, persist session row, return ``(token, claims)``.

        The order of the lockout / banned / not-verified branches matters:
        lockout is checked before password verification so a locked attacker
        cannot brute-force; banned is checked before password verification
        for the same reason; not-verified is checked AFTER successful
        password verification so we don't leak the existence of an
        unverified account on a wrong-password attempt.
        """
        now = now or _utcnow()

        user = self._user_repo.get_by_email(email)
        if user is None:
            self._auth_repo.record_login_attempt(
                user_id=None, attempted_at=now, success=False
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=_ERR_INVALID_CREDENTIALS,
            )

        # Active lockout check (Req 3.3) — done before password verification
        # so a locked account is consistently rejected.
        lockout = self._auth_repo.get_lockout(user.id)
        if lockout is not None and self._is_locked(lockout.locked_until, now):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=_ERR_LOCKED,
            )

        # Banned check (Req 15.3) — checked before password to keep banned
        # accounts from being a brute-force oracle.
        if user.is_banned:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=_ERR_BANNED,
            )

        # Google-only accounts have no password_hash; reject with the same
        # generic error to avoid leaking that the account is Google-linked.
        if user.password_hash is None or not verify_password(password, user.password_hash):
            self._auth_repo.record_login_attempt(
                user_id=user.id, attempted_at=now, success=False
            )
            window_start = now - timedelta(minutes=self._lockout_window_minutes)
            failed = self._auth_repo.failed_count_in_window(
                user.id, since=window_start
            )
            if failed >= self._lockout_threshold:
                self._auth_repo.set_lockout(
                    user.id,
                    locked_until=now
                    + timedelta(minutes=self._lockout_duration_minutes),
                )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=_ERR_INVALID_CREDENTIALS,
            )

        # Password is correct; require email verification (Req 2.4).
        if user.account_state != AccountState.VERIFIED.value:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=_ERR_NOT_VERIFIED,
            )

        # Success: record, mint JWT, persist session row.
        self._auth_repo.record_login_attempt(
            user_id=user.id, attempted_at=now, success=True
        )
        token, claims = encode_token(sub=user.id)
        self._auth_repo.create_session(
            jti=claims["jti"],
            user_id=user.id,
            issued_at=datetime.fromtimestamp(claims["iat"], tz=timezone.utc),
            expires_at=datetime.fromtimestamp(claims["exp"], tz=timezone.utc),
        )
        return token, claims

    @staticmethod
    def _is_locked(locked_until: datetime, now: datetime) -> bool:
        """Return True iff ``locked_until > now``, normalising naive datetimes.

        SQLite ``DateTime(timezone=True)`` round-trips strip the offset; the
        existing repository tests assert on naive comparison. We treat a
        naive ``locked_until`` as UTC-naive so the comparison still works
        correctly under SQLite while staying exact under Postgres.
        """
        if locked_until.tzinfo is None:
            locked_until = locked_until.replace(tzinfo=timezone.utc)
        return locked_until > now

    def logout(self, jti: str) -> None:
        """Revoke a session by its JTI (Req 3.4).

        Idempotent: calling twice is a no-op on the second call. Returning
        nothing keeps the surface aligned with the ``DELETE`` endpoint that
        wraps it.
        """
        self._auth_repo.revoke_session_by_jti(jti)

    def get_current_user_from_jti(
        self, jti: str, *, now: datetime | None = None
    ) -> User:
        """Resolve the user behind ``jti`` for routes that need claims-only auth.

        TODO(Task 5.1): replace direct callers with ``Depends(get_current_user)``
        once that dependency lands. Until then, the logout endpoint uses this
        helper because the auth middleware is permissive (no DB access) and
        we still need to enforce ban + revoked-session policy at logout time.

        Failure modes (Req 3.4, 3.5, 15.3):

        - Session row missing — 401 ``invalid_credentials``.
        - Session revoked or expired — 401 ``invalid_credentials``.
        - User row missing (cascade deleted) — 401 ``invalid_credentials``.
        - User banned — 403 ``account_banned``.
        """
        cutoff = now or _utcnow()
        session = self._auth_repo.get_session_by_jti(jti)
        if session is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=_ERR_INVALID_CREDENTIALS,
            )

        revoked_at = session.revoked_at
        expires_at = session.expires_at
        # SQLite drops tz info on round-trip; treat naive as UTC for the
        # comparison so the same code works under Postgres.
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if revoked_at is not None or expires_at <= cutoff:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=_ERR_INVALID_CREDENTIALS,
            )

        user = self._user_repo.get(session.user_id)
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=_ERR_INVALID_CREDENTIALS,
            )
        if user.is_banned:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=_ERR_BANNED,
            )
        return user

    # ------------------------------------------------------------------
    # password reset
    # ------------------------------------------------------------------

    def request_password_reset(
        self, payload: PasswordResetRequest, *, mode: str = "online"
    ) -> None:
        """Issue a PASSWORD_RESET OTP if the email exists; otherwise no-op.

        Per Req 4.2, the response shape MUST NOT differ between
        existing-email and unknown-email paths so the endpoint is not an
        enumeration oracle. Always returns ``None``; the router emits a
        fixed 200 envelope.
        """
        user = self._user_repo.get_by_email(payload.email)
        if user is not None:
            self._otp_service.issue(
                user=user,
                purpose=OTPPurpose.PASSWORD_RESET,
                mode=mode,
            )

    def reset_password(self, payload: PasswordResetConfirmRequest) -> None:
        """Verify a reset OTP, set the new password, revoke all sessions.

        Steps (Req 4.3, 4.4):

        1. Re-validate the new password against Req 1.3 rules. The schema
           layer doesn't run the full check (the field is just ``str``),
           so the service is the enforcement point.
        2. Verify the PASSWORD_RESET OTP via the OTP service. Failures
           propagate as the canonical 400 ``otp_invalid_or_expired``.
        3. Hash and persist the new password.
        4. Revoke every session for the user (Req 4.4).
        """
        try:
            validate_password(payload.new_password)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc

        user = self._otp_service.verify(
            email=payload.email,
            code=payload.code,
            purpose=OTPPurpose.PASSWORD_RESET,
        )

        new_hash = hash_password(payload.new_password)
        self._user_repo.update(user, password_hash=new_hash)
        self._auth_repo.revoke_all_for_user(user.id)

    # ------------------------------------------------------------------
    # Google OAuth
    # ------------------------------------------------------------------

    def google_authenticate(
        self,
        *,
        id_token: str,
        category: str | None = None,
    ) -> tuple[str, dict[str, Any], User, bool]:
        """Authenticate via Google ID token. Handles both login and signup.

        Flow:
        1. Verify the Google ID token and extract user info.
        2. Look up user by ``google_id``.
        3. If found → login (mint JWT, return existing user).
        4. If not found → check by email.
           a. If email exists and no google_id → link Google account, login.
           b. If email does not exist → signup (requires ``category``).

        Returns:
            ``(token, claims, user, is_new_user)`` — ``is_new_user`` is True
            when a new account was created (signup), False for login.

        Raises:
            HTTPException 401: Invalid Google token.
            HTTPException 403: User is banned.
            HTTPException 422: Category required for new signup.
            HTTPException 409: Email already registered with password-only
                account and user should link via a different flow (future).
        """
        if self._google_verifier is None:
            raise HTTPException(
                status_code=status.HTTP_501_NOT_IMPLEMENTED,
                detail="google_oauth_not_configured",
            )

        # Step 1: Verify the token
        try:
            google_info = self._google_verifier.verify_token(id_token)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=_ERR_GOOGLE_TOKEN_INVALID,
            )

        if not google_info.email:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=_ERR_GOOGLE_TOKEN_INVALID,
            )

        # Step 2: Look up by google_id
        user = self._user_repo.get_by_google_id(google_info.google_id)

        is_new_user = False

        if user is None:
            # Step 4: Check by email
            user = self._user_repo.get_by_email(google_info.email)

            if user is not None:
                # 4a: Existing email-based account — link Google ID
                if user.is_banned:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail=_ERR_BANNED,
                    )
                self._user_repo.link_google_id(user, google_info.google_id)
                # Also mark as verified since Google verified the email
                if user.account_state != AccountState.VERIFIED.value:
                    self._user_repo.set_account_state(user, AccountState.VERIFIED)
            else:
                # 4b: Brand new user — requires category
                if not category:
                    raise HTTPException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        detail=_ERR_CATEGORY_REQUIRED,
                    )
                user = self._user_repo.create_from_google(
                    email=google_info.email,
                    display_name=google_info.name or google_info.email.split("@")[0],
                    google_id=google_info.google_id,
                    category=category,
                )
                is_new_user = True
        else:
            # Step 3: Existing Google-linked user — login
            if user.is_banned:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=_ERR_BANNED,
                )

        # Mint JWT session
        token, claims = encode_token(sub=user.id)
        self._auth_repo.create_session(
            jti=claims["jti"],
            user_id=user.id,
            issued_at=datetime.fromtimestamp(claims["iat"], tz=timezone.utc),
            expires_at=datetime.fromtimestamp(claims["exp"], tz=timezone.utc),
        )
        return token, claims, user, is_new_user
