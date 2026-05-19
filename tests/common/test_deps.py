"""Tests for ``app.common.deps``: get_current_user, require_admin,
require_no_active_mock.

These exercise the dependency stack end-to-end against a tiny FastAPI app:
mount ``AuthMiddleware`` so the bearer token is decoded, mount the global
exception handlers so error envelopes match the production shape, then
declare three trivial routes that depend on each guard. Per
``testing-standards.md`` this is closer to a router test than a service
test, but the task spec asks for "service-layer tests for guards" — the
``TestClient`` shape is the simplest faithful reproduction of how guards
behave in production, so we stick with it.

Coverage shape (per Task 5.2 acceptance bullets):

* Happy path through ``get_current_user``.
* Expired bearer token → 401 from the middleware-decode-then-dep flow.
* Revoked token → 401 (service raises canonical ``invalid_credentials``).
* Banned user → 403 ``account_banned``.
* Non-admin hitting an admin route → 403 ``forbidden``.
* Mock-exam guard passes through while ``MockExamAttempt`` is unimplemented
  (Task 12.1 is the seam where the 409 path lights up).
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import jwt
import pytest
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.testclient import TestClient

from app.common.deps import (
    get_current_user,
    require_admin,
    require_no_active_mock,
)
from app.common.middlewares.auth import AuthMiddleware
from app.common.middlewares.error_handler import register_exception_handlers
from app.features.auth.service import AuthService
from app.features.users.models import AccountState, Category, Role, User
from app.infrastructure.database.session import get_db
from app.infrastructure.security.jwt import encode_token


# 32 bytes — RFC 7518 §3.2 minimum so pyjwt does not warn.
_TEST_JWT_SECRET = "test-secret-please-ignore-32byte!!"


@pytest.fixture(autouse=True)
def _jwt_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin ``JWT_SECRET`` so the middleware decoder and ``encode_token`` agree."""
    monkeypatch.setenv("JWT_SECRET", _TEST_JWT_SECRET)


def _make_user(**overrides: object) -> User:
    """Build a detached ``User`` for the auth-service mock to return."""
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
        "password_hash": "x",
        "cross_category_preview": False,
    }
    return User(**{**defaults, **overrides})


def _bearer(jti: str = "test-jti", sub: str = "1") -> dict[str, str]:
    """Mint a valid Authorization header carrying ``jti``."""
    token, _ = encode_token(sub=sub, jti=jti)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def mock_auth_service() -> MagicMock:
    """Mocked ``AuthService`` returned by the patched factory."""
    return MagicMock(spec=AuthService)


@pytest.fixture
def app(mock_auth_service: MagicMock) -> Iterator[FastAPI]:
    """Tiny FastAPI app that mounts the deps under test.

    The ``get_db`` override returns a ``MagicMock`` because the deps never
    touch the session once ``_build_auth_service`` is patched. The patch
    replaces the factory so any call site inside ``deps.py`` resolves to
    our mock service without spinning up real repositories.
    """
    fastapi_app = FastAPI()
    fastapi_app.add_middleware(AuthMiddleware)
    register_exception_handlers(fastapi_app)

    fastapi_app.dependency_overrides[get_db] = lambda: MagicMock()

    @fastapi_app.get("/me")
    def me_route(user: User = Depends(get_current_user)) -> dict[str, object]:
        return {"id": user.id, "role": user.role}

    @fastapi_app.get("/admin")
    def admin_route(user: User = Depends(require_admin)) -> dict[str, object]:
        return {"id": user.id, "role": user.role}

    @fastapi_app.get("/study")
    def study_route(
        user: User = Depends(require_no_active_mock),
    ) -> dict[str, object]:
        return {"id": user.id}

    with patch(
        "app.common.deps._build_auth_service",
        return_value=mock_auth_service,
    ):
        try:
            yield fastapi_app
        finally:
            fastapi_app.dependency_overrides.clear()


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


# --- get_current_user ------------------------------------------------------


def test_get_current_user_happy_path(
    client: TestClient, mock_auth_service: MagicMock
) -> None:
    mock_auth_service.get_current_user_from_jti.return_value = _make_user()

    response = client.get("/me", headers=_bearer(jti="abc"))

    assert response.status_code == 200
    assert response.json() == {"id": 1, "role": Role.LEARNER.value}
    mock_auth_service.get_current_user_from_jti.assert_called_once_with("abc")


def test_get_current_user_401_when_no_token(client: TestClient) -> None:
    response = client.get("/me")

    assert response.status_code == 401
    assert response.json() == {
        "error": {"message": "invalid_credentials", "code": "HTTP_401"}
    }


def test_get_current_user_401_when_token_expired(
    client: TestClient, mock_auth_service: MagicMock
) -> None:
    """An expired bearer token decodes to ``None`` claims via the middleware,
    so the dep raises 401 without touching the auth service."""
    iat = int((datetime.now(tz=timezone.utc) - timedelta(days=2)).timestamp())
    exp = int((datetime.now(tz=timezone.utc) - timedelta(days=1)).timestamp())
    expired = jwt.encode(
        {"sub": "1", "jti": "exp", "iat": iat, "exp": exp},
        _TEST_JWT_SECRET,
        algorithm="HS256",
    )

    response = client.get(
        "/me", headers={"Authorization": f"Bearer {expired}"}
    )

    assert response.status_code == 401
    assert response.json() == {
        "error": {"message": "invalid_credentials", "code": "HTTP_401"}
    }
    # The service must not be invoked when the middleware rejects the token.
    mock_auth_service.get_current_user_from_jti.assert_not_called()


def test_get_current_user_401_when_token_revoked(
    client: TestClient, mock_auth_service: MagicMock
) -> None:
    """A valid-looking JWT whose session row is revoked still flows through
    the middleware, but the service raises ``invalid_credentials``."""
    mock_auth_service.get_current_user_from_jti.side_effect = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="invalid_credentials",
    )

    response = client.get("/me", headers=_bearer())

    assert response.status_code == 401
    assert response.json() == {
        "error": {"message": "invalid_credentials", "code": "HTTP_401"}
    }


def test_get_current_user_403_when_banned(
    client: TestClient, mock_auth_service: MagicMock
) -> None:
    mock_auth_service.get_current_user_from_jti.side_effect = HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="account_banned",
    )

    response = client.get("/me", headers=_bearer())

    assert response.status_code == 403
    assert response.json() == {
        "error": {"message": "account_banned", "code": "HTTP_403"}
    }


# --- require_admin ---------------------------------------------------------


def test_require_admin_allows_admin(
    client: TestClient, mock_auth_service: MagicMock
) -> None:
    mock_auth_service.get_current_user_from_jti.return_value = _make_user(
        role=Role.ADMIN.value
    )

    response = client.get("/admin", headers=_bearer())

    assert response.status_code == 200
    assert response.json()["role"] == Role.ADMIN.value


def test_require_admin_403_for_learner(
    client: TestClient, mock_auth_service: MagicMock
) -> None:
    mock_auth_service.get_current_user_from_jti.return_value = _make_user(
        role=Role.LEARNER.value
    )

    response = client.get("/admin", headers=_bearer())

    assert response.status_code == 403
    assert response.json() == {
        "error": {"message": "forbidden", "code": "HTTP_403"}
    }


def test_require_admin_401_without_token(client: TestClient) -> None:
    response = client.get("/admin")

    assert response.status_code == 401
    assert response.json() == {
        "error": {"message": "invalid_credentials", "code": "HTTP_401"}
    }


# --- require_no_active_mock ------------------------------------------------


def test_require_no_active_mock_passes_when_no_in_progress_attempt(
    app: FastAPI,
    db_session,
    mock_auth_service: MagicMock,
) -> None:
    """Without any IN_PROGRESS row, the dep is a pass-through.

    Wires ``get_db`` to the real ``db_session`` so the dep walks an
    empty ``mock_exam_attempts`` table; the SELECT returns ``None``
    and the route runs.
    """
    from app.features.users.models import Category
    from app.features.users.repository import UserRepository
    from app.features.users.schemas import UserCreate
    from app.infrastructure.database.session import get_db

    user_repo = UserRepository(db=db_session)
    seeded = user_repo.create(
        UserCreate(
            email="alice-clean@example.com",
            display_name="Alice",
            age=25,
            category=Category.PROFESSIONAL.value,
            password="Strong1Pass!",
        ),
        password_hash="bcrypt$fake$hash",
    )
    mock_auth_service.get_current_user_from_jti.return_value = seeded

    app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(app)

    response = client.get("/study", headers=_bearer())

    assert response.status_code == 200
    assert response.json() == {"id": seeded.id}


def test_require_no_active_mock_409_when_attempt_in_progress(
    app: FastAPI,
    db_session,
    mock_auth_service: MagicMock,
) -> None:
    """An IN_PROGRESS row in ``mock_exam_attempts`` causes 409 ``exam_in_progress``.

    Uses the shared ``db_session`` fixture so a real row exists in the
    in-memory DB. Override ``get_db`` so the dep walks the same session.
    """
    from datetime import datetime, timezone

    from app.features.mock_exams.models import (
        MockExamAttempt,
        MockExamAttemptStatus,
    )
    from app.features.users.models import Category, User
    from app.features.users.repository import UserRepository
    from app.features.users.schemas import UserCreate
    from app.infrastructure.database.session import get_db

    # Seed a user so the FK on the attempt row is satisfied.
    user_repo = UserRepository(db=db_session)
    seeded = user_repo.create(
        UserCreate(
            email="alice-deps@example.com",
            display_name="Alice",
            age=25,
            category=Category.PROFESSIONAL.value,
            password="Strong1Pass!",
        ),
        password_hash="bcrypt$fake$hash",
    )

    # Seed an IN_PROGRESS mock attempt for that user.
    attempt = MockExamAttempt(
        user_id=seeded.id,
        category=Category.PROFESSIONAL.value,
        status=MockExamAttemptStatus.IN_PROGRESS.value,
        started_at=datetime.now(tz=timezone.utc),
        max_score=50,
        seed=12345,
        focus_loss_events=[],
        nav_policy="LINEAR_NO_REVISIT",
        time_limit_minutes=180,
    )
    db_session.add(attempt)
    db_session.commit()

    # Wire the auth service to return THIS user (matching id) so the dep
    # finds the IN_PROGRESS row.
    mock_auth_service.get_current_user_from_jti.return_value = seeded

    # Wire get_db to the test session.
    app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(app)

    response = client.get("/study", headers=_bearer())

    assert response.status_code == 409
    assert response.json() == {
        "error": {"message": "exam_in_progress", "code": "HTTP_409"}
    }


def test_require_no_active_mock_401_without_token(client: TestClient) -> None:
    """The dep depends on ``get_current_user`` first, so a missing token is
    a 401 (not a 409) regardless of the mock-exam check."""
    response = client.get("/study")

    assert response.status_code == 401
