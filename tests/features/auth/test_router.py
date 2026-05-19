"""Router tests for the auth feature.

Per ``testing-standards.md``, router tests use ``TestClient`` plus
``app.dependency_overrides[get_auth_service]`` to inject a mocked service.
The DB never runs in these tests; ``AuthService`` itself is exercised in
``test_service.py``.

The test app stacks the production middleware set so the canonical
``ErrorResponse`` envelope (Task 1.5) is what assertions see, not FastAPI's
default ``{"detail": "..."}``. Without ``register_exception_handlers`` the
401/403/409 envelope tests below would not match.

Coverage shape (per Task 4.10 acceptance bullets):

* One happy-path + one 422 per endpoint.
* 401 on missing token for ``DELETE /v1/auth/sessions/me``.
* 403 on banned user attempting logout.
* ``X-Request-ID`` echoed on success and error responses (Property 34 at
  the integration boundary).
* Canonical error envelope shape on common service exceptions.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI, HTTPException, status
from fastapi.testclient import TestClient

from app.common.middlewares.auth import AuthMiddleware
from app.common.middlewares.error_handler import register_exception_handlers
from app.common.middlewares.logging import RequestLoggingMiddleware
from app.features.auth.router import (
    get_auth_service,
    get_otp_service,
    router as auth_router,
)
from app.features.auth.service import AuthService
from app.features.otp.service import OTPService
from app.features.users.models import AccountState, Category, Role, User
from app.infrastructure.security.jwt import encode_token


# --- fixtures --------------------------------------------------------------

# 32 bytes — RFC 7518 §3.2 minimum so pyjwt is quiet.
_TEST_JWT_SECRET = "test-secret-please-ignore-32byte!!"


@pytest.fixture(autouse=True)
def _jwt_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin ``JWT_SECRET`` so logout's ``encode_token`` calls succeed."""
    monkeypatch.setenv("JWT_SECRET", _TEST_JWT_SECRET)


@pytest.fixture
def mock_service() -> MagicMock:
    """Mocked ``AuthService`` — every route override resolves to this."""
    return MagicMock(spec=AuthService)


@pytest.fixture
def app(mock_service: MagicMock) -> Iterator[FastAPI]:
    """Build a FastAPI app with the production middleware + handlers stack.

    Mounting ``register_exception_handlers`` matters: without it FastAPI's
    default handler returns ``{"detail": "..."}`` instead of the canonical
    ``ErrorResponse`` envelope, and several assertions below would break.
    """
    fastapi_app = FastAPI()
    # Order matches main.py: logging -> auth -> route handlers.
    fastapi_app.add_middleware(AuthMiddleware)
    fastapi_app.add_middleware(RequestLoggingMiddleware)
    register_exception_handlers(fastapi_app)
    fastapi_app.include_router(auth_router)

    fastapi_app.dependency_overrides[get_auth_service] = lambda: mock_service
    # ``get_otp_service`` would otherwise pull a real DB session from the
    # production ``get_db`` factory; we never invoke it here, but overriding
    # to a no-op keeps the dependency graph closed if a future test does.
    fastapi_app.dependency_overrides[get_otp_service] = lambda: MagicMock(
        spec=OTPService
    )

    try:
        yield fastapi_app
    finally:
        fastapi_app.dependency_overrides.clear()


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


# --- factory helpers -------------------------------------------------------


def _make_user(**overrides: object) -> User:
    """Build a detached ``User`` mirroring the ``UserResponse`` shape.

    FastAPI serializes via ``response_model=UserResponse`` with
    ``from_attributes=True``, so any subset of these attributes is enough
    for the response schema to round-trip.
    """
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
        "password_hash": "x",
        "cross_category_preview": False,
    }
    return User(**{**defaults, **overrides})


def _signup_payload(**overrides: object) -> dict[str, object]:
    """Default valid signup body. Overrides win."""
    base: dict[str, object] = {
        "email": "alice@example.com",
        "display_name": "Alice",
        "age": 25,
        "category": "PROFESSIONAL",
        "password": "Strong1Pass!",
    }
    return {**base, **overrides}


def _bearer(jti: str = "router-test-jti", sub: str = "1") -> str:
    """Mint a signed bearer token whose middleware-decoded claims carry ``jti``."""
    token, _ = encode_token(sub=sub, jti=jti)
    return f"Bearer {token}"


# --- POST /v1/auth/signups -------------------------------------------------


def test_signup_201(client: TestClient, mock_service: MagicMock) -> None:
    mock_service.signup.return_value = _make_user()

    response = client.post("/v1/auth/signups", json=_signup_payload())

    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "alice@example.com"
    assert body["account_state"] == AccountState.UNVERIFIED.value
    assert body["role"] == Role.LEARNER.value
    # The plaintext password must never round-trip back to the client.
    assert "password" not in body and "password_hash" not in body


def test_signup_422_missing_password(client: TestClient) -> None:
    response = client.post(
        "/v1/auth/signups", json={"email": "alice@example.com"}
    )
    assert response.status_code == 422


def test_signup_409_for_existing_email(
    client: TestClient, mock_service: MagicMock
) -> None:
    mock_service.signup.side_effect = HTTPException(
        status_code=status.HTTP_409_CONFLICT, detail="email_already_registered"
    )

    response = client.post("/v1/auth/signups", json=_signup_payload())

    assert response.status_code == 409
    assert response.json() == {
        "error": {"message": "email_already_registered", "code": "HTTP_409"}
    }


def test_signup_echoes_x_request_id(
    client: TestClient, mock_service: MagicMock
) -> None:
    """Property 34 (correlation propagation) at the integration boundary."""
    mock_service.signup.return_value = _make_user()

    response = client.post(
        "/v1/auth/signups",
        json=_signup_payload(),
        headers={"X-Request-ID": "my-id-123"},
    )

    assert response.status_code == 201
    assert response.headers["X-Request-ID"] == "my-id-123"


def test_signup_echoes_x_request_id_on_error(
    client: TestClient, mock_service: MagicMock
) -> None:
    """Correlation header is echoed on error responses too."""
    mock_service.signup.side_effect = HTTPException(
        status_code=status.HTTP_409_CONFLICT, detail="email_already_registered"
    )

    response = client.post(
        "/v1/auth/signups",
        json=_signup_payload(),
        headers={"X-Request-ID": "err-id-999"},
    )

    assert response.status_code == 409
    assert response.headers["X-Request-ID"] == "err-id-999"


# --- POST /v1/auth/email-verifications ------------------------------------


def test_verify_email_200(
    client: TestClient, mock_service: MagicMock
) -> None:
    mock_service.verify_email.return_value = _make_user(
        account_state=AccountState.VERIFIED.value
    )

    response = client.post(
        "/v1/auth/email-verifications",
        json={
            "email": "alice@example.com",
            "code": "123456",
            "purpose": "VERIFY_EMAIL",
        },
    )

    assert response.status_code == 200
    assert response.json()["account_state"] == AccountState.VERIFIED.value


def test_verify_email_422_for_short_code(client: TestClient) -> None:
    response = client.post(
        "/v1/auth/email-verifications",
        json={
            "email": "alice@example.com",
            "code": "12345",  # 5 digits — fails the regex
            "purpose": "VERIFY_EMAIL",
        },
    )
    assert response.status_code == 422


def test_verify_email_400_for_invalid_otp(
    client: TestClient, mock_service: MagicMock
) -> None:
    mock_service.verify_email.side_effect = HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="otp_invalid_or_expired",
    )

    response = client.post(
        "/v1/auth/email-verifications",
        json={
            "email": "alice@example.com",
            "code": "123456",
            "purpose": "VERIFY_EMAIL",
        },
    )

    assert response.status_code == 400
    assert response.json() == {
        "error": {"message": "otp_invalid_or_expired", "code": "HTTP_400"}
    }


# --- POST /v1/auth/email-verifications:resend -----------------------------


def test_resend_204(client: TestClient, mock_service: MagicMock) -> None:
    mock_service.resend_verify_email.return_value = None

    response = client.post(
        "/v1/auth/email-verifications:resend",
        json={"email": "alice@example.com", "purpose": "VERIFY_EMAIL"},
    )

    assert response.status_code == 204
    assert response.content == b""
    mock_service.resend_verify_email.assert_called_once()


def test_resend_422_for_missing_email(client: TestClient) -> None:
    response = client.post("/v1/auth/email-verifications:resend", json={})
    assert response.status_code == 422


# --- POST /v1/auth/sessions (login) ---------------------------------------


def test_login_201(client: TestClient, mock_service: MagicMock) -> None:
    iat = int(datetime.now(tz=timezone.utc).timestamp())
    claims = {
        "sub": "1",
        "jti": "fresh-jti",
        "iat": iat,
        "exp": iat + 24 * 3600,
    }
    mock_service.login.return_value = ("signed.jwt.token", claims)

    response = client.post(
        "/v1/auth/sessions",
        json={"email": "alice@example.com", "password": "Strong1Pass!"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["access_token"] == "signed.jwt.token"
    assert body["token_type"] == "Bearer"
    assert body["expires_in"] == 24 * 3600


def test_login_422_for_missing_password(client: TestClient) -> None:
    response = client.post(
        "/v1/auth/sessions", json={"email": "alice@example.com"}
    )
    assert response.status_code == 422


def test_login_401_for_invalid_credentials(
    client: TestClient, mock_service: MagicMock
) -> None:
    mock_service.login.side_effect = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_credentials"
    )

    response = client.post(
        "/v1/auth/sessions",
        json={"email": "alice@example.com", "password": "Wrong1Pass!"},
    )

    assert response.status_code == 401
    assert response.json() == {
        "error": {"message": "invalid_credentials", "code": "HTTP_401"}
    }


def test_login_401_for_temporarily_locked(
    client: TestClient, mock_service: MagicMock
) -> None:
    mock_service.login.side_effect = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED, detail="temporarily_locked"
    )

    response = client.post(
        "/v1/auth/sessions",
        json={"email": "alice@example.com", "password": "Strong1Pass!"},
    )

    assert response.status_code == 401
    assert response.json()["error"]["message"] == "temporarily_locked"


def test_login_403_for_banned(
    client: TestClient, mock_service: MagicMock
) -> None:
    mock_service.login.side_effect = HTTPException(
        status_code=status.HTTP_403_FORBIDDEN, detail="account_banned"
    )

    response = client.post(
        "/v1/auth/sessions",
        json={"email": "alice@example.com", "password": "Strong1Pass!"},
    )

    assert response.status_code == 403
    assert response.json() == {
        "error": {"message": "account_banned", "code": "HTTP_403"}
    }


# --- DELETE /v1/auth/sessions/me (logout) ---------------------------------


def test_logout_204_with_valid_token(
    client: TestClient, mock_service: MagicMock
) -> None:
    """Authenticated logout returns 204 and revokes the session by JTI."""
    mock_service.get_current_user_from_jti.return_value = _make_user(
        account_state=AccountState.VERIFIED.value
    )
    mock_service.logout.return_value = None

    response = client.delete(
        "/v1/auth/sessions/me",
        headers={"Authorization": _bearer(jti="logout-jti")},
    )

    assert response.status_code == 204
    mock_service.get_current_user_from_jti.assert_called_once_with("logout-jti")
    mock_service.logout.assert_called_once_with("logout-jti")


def test_logout_401_without_token(client: TestClient) -> None:
    response = client.delete("/v1/auth/sessions/me")

    assert response.status_code == 401
    assert response.json() == {
        "error": {"message": "invalid_credentials", "code": "HTTP_401"}
    }


def test_logout_403_for_banned_user(
    client: TestClient, mock_service: MagicMock
) -> None:
    mock_service.get_current_user_from_jti.side_effect = HTTPException(
        status_code=status.HTTP_403_FORBIDDEN, detail="account_banned"
    )

    response = client.delete(
        "/v1/auth/sessions/me",
        headers={"Authorization": _bearer(jti="banned-jti")},
    )

    assert response.status_code == 403
    assert response.json() == {
        "error": {"message": "account_banned", "code": "HTTP_403"}
    }
    # When the user is banned we MUST NOT silently revoke their session;
    # the route should short-circuit before calling logout.
    mock_service.logout.assert_not_called()


# --- POST /v1/auth/password-reset-requests --------------------------------


def test_request_password_reset_204_for_known_email(
    client: TestClient, mock_service: MagicMock
) -> None:
    mock_service.request_password_reset.return_value = None

    response = client.post(
        "/v1/auth/password-reset-requests",
        json={"email": "alice@example.com"},
    )

    assert response.status_code == 204
    assert response.content == b""


def test_request_password_reset_204_for_unknown_email(
    client: TestClient, mock_service: MagicMock
) -> None:
    """Req 4.2: byte-equal response across known/unknown email."""
    mock_service.request_password_reset.return_value = None

    known = client.post(
        "/v1/auth/password-reset-requests",
        json={"email": "alice@example.com"},
        headers={"X-Request-ID": "stable-id"},
    )
    unknown = client.post(
        "/v1/auth/password-reset-requests",
        json={"email": "ghost@example.com"},
        headers={"X-Request-ID": "stable-id"},
    )

    assert known.status_code == unknown.status_code == 204
    assert known.content == unknown.content == b""


def test_request_password_reset_422_for_invalid_email(
    client: TestClient,
) -> None:
    response = client.post(
        "/v1/auth/password-reset-requests", json={"email": "not-an-email"}
    )
    assert response.status_code == 422


# --- POST /v1/auth/password-resets ----------------------------------------


def test_reset_password_204(
    client: TestClient, mock_service: MagicMock
) -> None:
    mock_service.reset_password.return_value = None

    response = client.post(
        "/v1/auth/password-resets",
        json={
            "email": "alice@example.com",
            "code": "123456",
            "new_password": "BrandNew2!Pass",
        },
    )

    assert response.status_code == 204
    assert response.content == b""


def test_reset_password_422_for_short_code(client: TestClient) -> None:
    response = client.post(
        "/v1/auth/password-resets",
        json={
            "email": "alice@example.com",
            "code": "12345",  # 5 digits — schema-level rejection
            "new_password": "BrandNew2!Pass",
        },
    )
    assert response.status_code == 422


def test_reset_password_400_for_invalid_otp(
    client: TestClient, mock_service: MagicMock
) -> None:
    mock_service.reset_password.side_effect = HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="otp_invalid_or_expired",
    )

    response = client.post(
        "/v1/auth/password-resets",
        json={
            "email": "alice@example.com",
            "code": "123456",
            "new_password": "BrandNew2!Pass",
        },
    )

    assert response.status_code == 400
    assert response.json() == {
        "error": {"message": "otp_invalid_or_expired", "code": "HTTP_400"}
    }
