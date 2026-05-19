"""Router tests for the audit log slice (Task 18.3).

Per testing-standards.md: TestClient + dependency_overrides, mocked service.
Coverage: 200 happy path + 401 (no token) + 403 (non-admin) + response shape.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.common.deps import get_current_user, require_admin
from app.common.middlewares.error_handler import register_exception_handlers
from app.common.middlewares.logging import RequestLoggingMiddleware
from app.features.audit.models import AuditLog
from app.features.audit.router import get_audit_logger, router as audit_router
from app.features.audit.service import AuditLogger
from app.features.users.models import AccountState, Category, Role, User


# --- factories --------------------------------------------------------------


def _make_admin(**overrides: object) -> User:
    defaults: dict[str, object] = {
        "id": 1,
        "email": "admin@example.com",
        "display_name": "Admin",
        "age": 30,
        "category": Category.PROFESSIONAL.value,
        "role": Role.ADMIN.value,
        "account_state": AccountState.VERIFIED.value,
        "is_banned": False,
        "tz_name": "UTC",
        "password_hash": "x",
        "cross_category_preview": False,
    }
    return User(**{**defaults, **overrides})


def _make_audit_log_entry(**overrides: object) -> AuditLog:
    defaults: dict[str, object] = {
        "id": 1,
        "actor_id": 1,
        "action": "user_ban",
        "target_kind": "user",
        "target_id": "5",
        "payload_json": {"reason": "spam"},
        "request_id": "abc-123",
        "occurred_at": datetime(2025, 6, 1, 12, 0, 0, tzinfo=timezone.utc),
        "created_at": datetime(2025, 6, 1, 12, 0, 0, tzinfo=timezone.utc),
        "updated_at": datetime(2025, 6, 1, 12, 0, 0, tzinfo=timezone.utc),
    }
    return AuditLog(**{**defaults, **overrides})


# --- fixtures ---------------------------------------------------------------


@pytest.fixture
def mock_service() -> MagicMock:
    return MagicMock(spec=AuditLogger)


@pytest.fixture
def admin_user() -> User:
    return _make_admin()


@pytest.fixture
def app(mock_service: MagicMock, admin_user: User) -> Iterator[FastAPI]:
    """Mount audit router with mocked service and admin user."""
    fastapi_app = FastAPI()
    fastapi_app.add_middleware(RequestLoggingMiddleware)
    register_exception_handlers(fastapi_app)
    fastapi_app.include_router(audit_router)

    fastapi_app.dependency_overrides[get_audit_logger] = lambda: mock_service
    fastapi_app.dependency_overrides[require_admin] = lambda: admin_user
    fastapi_app.dependency_overrides[get_current_user] = lambda: admin_user

    try:
        yield fastapi_app
    finally:
        fastapi_app.dependency_overrides.clear()


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


@pytest.fixture
def unauthenticated_app(mock_service: MagicMock) -> Iterator[FastAPI]:
    """App with no auth override — simulates missing token (401)."""
    fastapi_app = FastAPI()
    fastapi_app.add_middleware(RequestLoggingMiddleware)
    register_exception_handlers(fastapi_app)
    fastapi_app.include_router(audit_router)

    fastapi_app.dependency_overrides[get_audit_logger] = lambda: mock_service

    def _raise_401():
        raise HTTPException(status_code=401, detail="invalid_credentials")

    fastapi_app.dependency_overrides[require_admin] = _raise_401
    fastapi_app.dependency_overrides[get_current_user] = _raise_401

    try:
        yield fastapi_app
    finally:
        fastapi_app.dependency_overrides.clear()


@pytest.fixture
def unauthenticated_client(unauthenticated_app: FastAPI) -> TestClient:
    return TestClient(unauthenticated_app)


@pytest.fixture
def forbidden_app(mock_service: MagicMock) -> Iterator[FastAPI]:
    """App with a non-admin user — simulates 403."""
    fastapi_app = FastAPI()
    fastapi_app.add_middleware(RequestLoggingMiddleware)
    register_exception_handlers(fastapi_app)
    fastapi_app.include_router(audit_router)

    fastapi_app.dependency_overrides[get_audit_logger] = lambda: mock_service

    def _raise_403():
        raise HTTPException(status_code=403, detail="forbidden")

    fastapi_app.dependency_overrides[require_admin] = _raise_403
    fastapi_app.dependency_overrides[get_current_user] = _raise_403

    try:
        yield fastapi_app
    finally:
        fastapi_app.dependency_overrides.clear()


@pytest.fixture
def forbidden_client(forbidden_app: FastAPI) -> TestClient:
    return TestClient(forbidden_app)


# ===========================================================================
# GET /v1/admin/audit-log
# ===========================================================================


class TestListAuditLog:
    """Tests for GET /v1/admin/audit-log."""

    def test_200_happy_path(self, client: TestClient, mock_service: MagicMock) -> None:
        """Paginated response with audit log entries."""
        entry = _make_audit_log_entry()
        mock_service.list_paginated.return_value = ([entry], 1)

        response = client.get("/v1/admin/audit-log?skip=0&limit=20")

        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 1
        assert body["skip"] == 0
        assert body["limit"] == 20
        assert len(body["items"]) == 1

        item = body["items"][0]
        assert item["id"] == 1
        assert item["actor_id"] == 1
        assert item["action"] == "user_ban"
        assert item["target_kind"] == "user"
        assert item["target_id"] == "5"
        assert item["payload_json"] == {"reason": "spam"}
        assert item["request_id"] == "abc-123"
        assert "occurred_at" in item

    def test_200_empty_list(self, client: TestClient, mock_service: MagicMock) -> None:
        """Empty audit log returns empty items with total=0."""
        mock_service.list_paginated.return_value = ([], 0)

        response = client.get("/v1/admin/audit-log")

        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 0
        assert body["items"] == []

    def test_200_response_shape_matches_schema(
        self, client: TestClient, mock_service: MagicMock
    ) -> None:
        """Verify all AuditLogResponse fields are present."""
        entry = _make_audit_log_entry(
            actor_id=None,
            target_id=None,
            payload_json=None,
            request_id=None,
        )
        mock_service.list_paginated.return_value = ([entry], 1)

        response = client.get("/v1/admin/audit-log")

        assert response.status_code == 200
        item = response.json()["items"][0]
        expected_keys = {
            "id", "actor_id", "action", "target_kind",
            "target_id", "payload_json", "request_id", "occurred_at",
        }
        assert set(item.keys()) == expected_keys
        # Nullable fields should be None
        assert item["actor_id"] is None
        assert item["target_id"] is None
        assert item["payload_json"] is None
        assert item["request_id"] is None

    def test_401_without_token(self, unauthenticated_client: TestClient) -> None:
        """Missing auth token returns 401."""
        response = unauthenticated_client.get("/v1/admin/audit-log")
        assert response.status_code == 401

    def test_403_non_admin(self, forbidden_client: TestClient) -> None:
        """Non-admin user returns 403."""
        response = forbidden_client.get("/v1/admin/audit-log")
        assert response.status_code == 403

    def test_422_invalid_skip(self, client: TestClient) -> None:
        """Negative skip returns 422."""
        response = client.get("/v1/admin/audit-log?skip=-1")
        assert response.status_code == 422

    def test_pagination_params_forwarded(
        self, client: TestClient, mock_service: MagicMock
    ) -> None:
        """Verify skip/limit are forwarded to the service."""
        mock_service.list_paginated.return_value = ([], 0)

        client.get("/v1/admin/audit-log?skip=10&limit=5")

        mock_service.list_paginated.assert_called_once_with(skip=10, limit=5)
