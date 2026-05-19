"""FastAPI dependencies for authenticated routes.

Three building blocks every authenticated route needs:

* ``get_current_user`` — pull the bearer JWT, validate the session, return a
  ``User`` row. Raises 401 on missing/expired/revoked tokens and 403 on
  banned users (Req 3.5, 15.3).
* ``require_admin`` — depends on ``get_current_user`` and gates on
  ``role == ADMIN`` (Req 15.1). Returns the user so routes can chain off
  this dep without re-declaring ``get_current_user``.
* ``require_no_active_mock`` — gates on the absence of an in-progress mock
  exam attempt for the user (Req 19.1). Returns 409 ``exam_in_progress``
  when one exists.

The mock-exam check queries the partial unique index on
``mock_exam_attempts(user_id) WHERE status='IN_PROGRESS'`` so it stays a
single indexed lookup at request time.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.features.auth.repository import AuthRepository
from app.features.auth.service import AuthService
from app.features.otp.repository import OTPRepository
from app.features.otp.service import OTPService
from app.features.users.models import Role, User
from app.features.users.repository import UserRepository
from app.infrastructure.database.session import get_db
from app.infrastructure.external.offline_otp_writer import OfflineOtpWriter
from app.infrastructure.external.smtp_otp_sender import SmtpOtpSender


def _build_auth_service(db: Session) -> AuthService:
    """Construct an :class:`AuthService` for the request scope.

    Kept here rather than imported from ``app/features/auth/router.py`` to
    avoid a cross-feature ``router -> deps`` edge: ``deps`` is consumed by
    every feature router, so depending on one of them would create a cycle
    the moment a second feature was wired up.

    The shape mirrors ``app.features.auth.router.get_auth_service`` exactly
    (same repos + OTP service composition); only the import seam differs.
    """
    return AuthService(
        user_repo=UserRepository(db=db),
        auth_repo=AuthRepository(db=db),
        otp_service=OTPService(
            user_repo=UserRepository(db=db),
            otp_repo=OTPRepository(db=db),
            offline_writer=OfflineOtpWriter(),
            smtp_sender=SmtpOtpSender(),
        ),
    )


def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
) -> User:
    """Resolve the bearer-token user; raise 401/403 as appropriate.

    Reads ``request.state.token_claims`` populated by ``AuthMiddleware``
    (the permissive decoder). When no token is present, the token is
    malformed, or the token is expired, ``token_claims`` is ``None`` and
    we raise 401. When the JTI is present, the heavy lifting (session
    active + user load + ban check) is delegated to
    ``AuthService.get_current_user_from_jti`` so the policy lives in one
    place. (Req 3.5, 15.3)
    """
    claims = getattr(request.state, "token_claims", None)
    if claims is None or "jti" not in claims:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid_credentials",
        )
    service = _build_auth_service(db)
    return service.get_current_user_from_jti(str(claims["jti"]))


def require_admin(user: User = Depends(get_current_user)) -> User:
    """Gate a route on ``user.role == ADMIN``; else 403 (Req 15.1).

    Returns the user so chained routes can ``Depends(require_admin)`` and
    still receive the ``User`` object without a second declaration. The
    detail string is the generic ``forbidden`` rather than something like
    ``not_admin`` so the response does not echo authorization shape back
    to the caller.
    """
    if user.role != Role.ADMIN.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="forbidden",
        )
    return user


def require_no_active_mock(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> User:
    """Refuse the request if the user has an in-progress mock-exam attempt.

    Spec ref: Req 19.1 — every ``/v1/{subtopics|topics|modules|quiz-attempts}/**``
    returns 409 ``exam_in_progress`` while a mock is IN_PROGRESS. Returns
    the user so callers can compose this with ``get_current_user`` without
    re-declaring it.

    The check is a single indexed lookup against the partial unique
    index on ``mock_exam_attempts(user_id) WHERE status='IN_PROGRESS'``
    so concurrent reads do not race the storage-level uniqueness
    guarantee.
    """
    from sqlalchemy import select

    from app.features.mock_exams.models import (
        MockExamAttempt,
        MockExamAttemptStatus,
    )

    stmt = select(MockExamAttempt).where(
        MockExamAttempt.user_id == user.id,
        MockExamAttempt.status == MockExamAttemptStatus.IN_PROGRESS.value,
    )
    found = db.execute(stmt).scalar_one_or_none()
    if found is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="exam_in_progress",
        )
    return user
