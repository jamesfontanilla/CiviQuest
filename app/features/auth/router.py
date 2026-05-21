"""FastAPI router for the auth feature.

Wires HTTP endpoints to :class:`AuthService` per the Req 1-4 surface area.
The factory functions (``get_otp_service``, ``get_auth_service``) are the
dependency-injection seams used by the test suite via
``app.dependency_overrides``.

Routes mounted under ``/v1/auth``:

* ``POST   /signups`` — create an UNVERIFIED account and trigger an OTP.
* ``POST   /email-verifications`` — verify the OTP and transition to VERIFIED.
* ``POST   /email-verifications:resend`` — re-issue the verification OTP.
* ``POST   /sessions`` — login, mint a JWT, persist a session row.
* ``DELETE /sessions/me`` — logout the current session by JTI.
* ``POST   /password-reset-requests`` — issue a reset OTP if the email exists.
* ``POST   /password-resets`` — verify a reset OTP and rotate the password.

The logout route reads ``request.state.token_claims`` rather than depending
on ``get_current_user``. The auth middleware is permissive (it never raises),
and ``get_current_user`` lands in Task 5.1; this manual claims-check is
explicitly transitional.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.features.auth.repository import AuthRepository
from app.features.auth.schemas import (
    GoogleAuthRequest,
    GoogleAuthResponse,
    LoginRequest,
    LoginResponse,
    PasswordResetConfirmRequest,
    PasswordResetRequest,
)
from app.features.auth.service import AuthService
from app.features.otp.repository import OTPRepository
from app.features.otp.schemas import OTPIssueRequest, OTPVerifyRequest
from app.features.otp.service import OTPService
from app.features.users.models import User
from app.features.users.repository import UserRepository
from app.features.users.schemas import UserCreate, UserResponse
from app.infrastructure.database.session import get_db
from app.infrastructure.external.google_oauth import GoogleOAuthVerifier
from app.infrastructure.external.offline_otp_writer import OfflineOtpWriter
from app.infrastructure.external.smtp_otp_sender import SmtpOtpSender

router = APIRouter(prefix="/v1/auth", tags=["auth"])


# --- factories -------------------------------------------------------------


def get_otp_service(db: Session = Depends(get_db)) -> OTPService:
    """Construct an :class:`OTPService` wired against the request DB session."""
    return OTPService(
        user_repo=UserRepository(db=db),
        otp_repo=OTPRepository(db=db),
        offline_writer=OfflineOtpWriter(),
        smtp_sender=SmtpOtpSender(),
    )


def get_auth_service(
    db: Session = Depends(get_db),
    otp_service: OTPService = Depends(get_otp_service),
) -> AuthService:
    """Construct an :class:`AuthService` for the request scope.

    The service depends on the OTP service so signup, resend, and password
    reset can issue OTPs through the same code path. Both share the same
    DB session.
    """
    return AuthService(
        user_repo=UserRepository(db=db),
        auth_repo=AuthRepository(db=db),
        otp_service=otp_service,
        google_verifier=GoogleOAuthVerifier(),
    )


# --- routes ----------------------------------------------------------------


@router.post(
    "/signups",
    status_code=status.HTTP_201_CREATED,
    response_model=UserResponse,
)
def signup(
    payload: UserCreate,
    service: AuthService = Depends(get_auth_service),
) -> User:
    """Create an account and trigger an email-verification OTP (Req 1.1, 2.1)."""
    return service.signup(payload)


@router.post("/email-verifications", response_model=UserResponse)
def verify_email(
    payload: OTPVerifyRequest,
    service: AuthService = Depends(get_auth_service),
) -> User:
    """Verify the email-verification OTP and mark the account VERIFIED (Req 2.2)."""
    return service.verify_email(payload)


@router.post(
    "/email-verifications:resend",
    status_code=status.HTTP_204_NO_CONTENT,
)
def resend_email_verification(
    payload: OTPIssueRequest,
    service: AuthService = Depends(get_auth_service),
) -> Response:
    """Re-issue a VERIFY_EMAIL OTP for the given email if it exists.

    Returns 204 unconditionally so the endpoint cannot be used to enumerate
    registered accounts (mirrors the password-reset semantics from Req 4.2).
    """
    service.resend_verify_email(payload)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/sessions",
    status_code=status.HTTP_201_CREATED,
    response_model=LoginResponse,
)
def login(
    payload: LoginRequest,
    service: AuthService = Depends(get_auth_service),
) -> LoginResponse:
    """Authenticate and mint a JWT session token (Req 3.1).

    ``expires_in`` is reported in seconds (``exp - iat``) rather than as an
    absolute timestamp so clients don't have to reason about clock skew.
    """
    token, claims = service.login(email=payload.email, password=payload.password)
    expires_in = int(claims["exp"]) - int(claims["iat"])
    return LoginResponse(access_token=token, token_type="Bearer", expires_in=expires_in)


@router.delete("/sessions/me", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    request: Request,
    service: AuthService = Depends(get_auth_service),
) -> Response:
    """Revoke the current session (Req 3.4).

    Reads the JTI claim from ``request.state.token_claims`` (set by the
    permissive ``AuthMiddleware``). Returns 401 when no token is present.
    Resolves the user behind the JTI so banned users hit 403 instead of
    silently revoking — matches the Task 4.10 acceptance bullet "403 on
    banned user attempting DELETE /v1/auth/sessions/me".

    TODO(Task 5.1): swap the manual claims handling for
    ``user: User = Depends(get_current_user)`` so this route stops touching
    ``request.state`` directly.
    """
    claims = getattr(request.state, "token_claims", None)
    if claims is None or "jti" not in claims:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid_credentials",
        )
    jti = str(claims["jti"])
    # Banned + revoked + expired checks; raises before we touch the session.
    service.get_current_user_from_jti(jti)
    service.logout(jti)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/password-reset-requests",
    status_code=status.HTTP_204_NO_CONTENT,
)
def request_password_reset(
    payload: PasswordResetRequest,
    service: AuthService = Depends(get_auth_service),
) -> Response:
    """Issue a password-reset OTP iff the email exists (Req 4.1, 4.2).

    Always returns 204; the byte-equal response prevents enumeration.
    """
    service.request_password_reset(payload)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/password-resets", status_code=status.HTTP_204_NO_CONTENT)
def reset_password(
    payload: PasswordResetConfirmRequest,
    service: AuthService = Depends(get_auth_service),
) -> Response:
    """Verify a reset OTP, rotate the password, revoke all sessions (Req 4.3, 4.4)."""
    service.reset_password(payload)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/google",
    status_code=status.HTTP_200_OK,
    response_model=GoogleAuthResponse,
)
def google_authenticate(
    payload: GoogleAuthRequest,
    service: AuthService = Depends(get_auth_service),
) -> dict:
    """Authenticate via Google OAuth (login or signup).

    For new users: ``category`` is required in the payload. The user is
    created with VERIFIED status (Google already verified the email) and
    a JWT is minted immediately.

    For returning users: ``category`` is ignored. The existing account is
    logged in and a JWT is minted.

    If the Google email matches an existing email+password account, the
    Google ID is linked to that account automatically.
    """
    token, claims, user, is_new_user = service.google_authenticate(
        id_token=payload.id_token,
        category=payload.category,
    )
    expires_in = int(claims["exp"]) - int(claims["iat"])
    return {
        "access_token": token,
        "token_type": "Bearer",
        "expires_in": expires_in,
        "is_new_user": is_new_user,
        "user": user,
    }
