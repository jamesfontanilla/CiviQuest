"""Router tests for the admin slice (Task 17.8).

Per testing-standards.md: TestClient + dependency_overrides, mocked service.
Coverage: happy path + 401 (no token) + 403 (non-admin) + 422 per route,
plus force-flag cascade test for delete.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI, HTTPException, status
from fastapi.testclient import TestClient

from app.common.deps import get_current_user, require_admin
from app.common.middlewares.error_handler import register_exception_handlers
from app.common.middlewares.logging import RequestLoggingMiddleware
from app.features.admin.router import get_admin_service, router as admin_router
from app.features.admin.schemas import AnalyticsResponse, WeakSubtopic
from app.features.admin.service import AdminService
from app.features.content.models import Module, Question, Subtopic, Topic, Lesson
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


def _make_learner(**overrides: object) -> User:
    defaults: dict[str, object] = {
        "id": 2,
        "email": "learner@example.com",
        "display_name": "Learner",
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


def _make_user_response(**overrides: object) -> User:
    defaults: dict[str, object] = {
        "id": 5,
        "email": "user5@example.com",
        "display_name": "User Five",
        "age": 22,
        "category": Category.PROFESSIONAL.value,
        "role": Role.LEARNER.value,
        "account_state": AccountState.VERIFIED.value,
        "is_banned": False,
        "tz_name": "UTC",
        "password_hash": "x",
        "cross_category_preview": False,
        "created_at": datetime(2025, 1, 1, tzinfo=timezone.utc),
        "updated_at": datetime(2025, 1, 1, tzinfo=timezone.utc),
    }
    return User(**{**defaults, **overrides})


# --- fixtures ---------------------------------------------------------------


@pytest.fixture
def mock_service() -> MagicMock:
    return MagicMock(spec=AdminService)


@pytest.fixture
def admin_user() -> User:
    return _make_admin()


@pytest.fixture
def learner_user() -> User:
    return _make_learner()


@pytest.fixture
def app(mock_service: MagicMock, admin_user: User) -> Iterator[FastAPI]:
    """Mount admin router with mocked service and admin user."""
    fastapi_app = FastAPI()
    fastapi_app.add_middleware(RequestLoggingMiddleware)
    register_exception_handlers(fastapi_app)
    fastapi_app.include_router(admin_router)

    fastapi_app.dependency_overrides[get_admin_service] = lambda: mock_service
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
    """App with no auth override — simulates missing token."""
    fastapi_app = FastAPI()
    fastapi_app.add_middleware(RequestLoggingMiddleware)
    register_exception_handlers(fastapi_app)
    fastapi_app.include_router(admin_router)

    fastapi_app.dependency_overrides[get_admin_service] = lambda: mock_service

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
def forbidden_app(mock_service: MagicMock, learner_user: User) -> Iterator[FastAPI]:
    """App with a non-admin user — simulates 403."""
    fastapi_app = FastAPI()
    fastapi_app.add_middleware(RequestLoggingMiddleware)
    register_exception_handlers(fastapi_app)
    fastapi_app.include_router(admin_router)

    fastapi_app.dependency_overrides[get_admin_service] = lambda: mock_service

    def _raise_403():
        raise HTTPException(status_code=403, detail="forbidden")

    fastapi_app.dependency_overrides[require_admin] = _raise_403
    fastapi_app.dependency_overrides[get_current_user] = lambda: learner_user

    try:
        yield fastapi_app
    finally:
        fastapi_app.dependency_overrides.clear()


@pytest.fixture
def forbidden_client(forbidden_app: FastAPI) -> TestClient:
    return TestClient(forbidden_app)


# ===========================================================================
# GET /v1/admin/users
# ===========================================================================


class TestListUsers:
    def test_200_happy_path(self, client: TestClient, mock_service: MagicMock) -> None:
        user = _make_user_response()
        mock_service.list_users.return_value = ([user], 1)

        response = client.get("/v1/admin/users?skip=0&limit=20")

        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 1
        assert body["items"][0]["email"] == "user5@example.com"

    def test_401_no_token(self, unauthenticated_client: TestClient) -> None:
        response = unauthenticated_client.get("/v1/admin/users")
        assert response.status_code == 401

    def test_403_non_admin(self, forbidden_client: TestClient) -> None:
        response = forbidden_client.get("/v1/admin/users")
        assert response.status_code == 403

    def test_422_invalid_skip(self, client: TestClient) -> None:
        response = client.get("/v1/admin/users?skip=-1")
        assert response.status_code == 422


# ===========================================================================
# PATCH /v1/admin/users/{id}
# ===========================================================================


class TestPatchUser:
    def test_200_ban_toggle(self, client: TestClient, mock_service: MagicMock) -> None:
        user = _make_user_response(is_banned=True)
        mock_service.patch_user.return_value = user

        response = client.patch("/v1/admin/users/5", json={"is_banned": True})

        assert response.status_code == 200
        assert response.json()["is_banned"] is True

    def test_200_role_change(self, client: TestClient, mock_service: MagicMock) -> None:
        user = _make_user_response(role=Role.ADMIN.value)
        mock_service.patch_user.return_value = user

        response = client.patch("/v1/admin/users/5", json={"role": "ADMIN"})

        assert response.status_code == 200
        assert response.json()["role"] == "ADMIN"

    def test_401_no_token(self, unauthenticated_client: TestClient) -> None:
        response = unauthenticated_client.patch("/v1/admin/users/5", json={"is_banned": True})
        assert response.status_code == 401

    def test_403_non_admin(self, forbidden_client: TestClient) -> None:
        response = forbidden_client.patch("/v1/admin/users/5", json={"is_banned": True})
        assert response.status_code == 403

    def test_422_invalid_role(self, client: TestClient) -> None:
        response = client.patch("/v1/admin/users/5", json={"role": "INVALID"})
        assert response.status_code == 422


# ===========================================================================
# DELETE /v1/admin/users/{id}
# ===========================================================================


class TestDeleteUser:
    def test_204_happy_path(self, client: TestClient, mock_service: MagicMock) -> None:
        mock_service.delete_user.return_value = None

        response = client.delete("/v1/admin/users/5")

        assert response.status_code == 204

    def test_401_no_token(self, unauthenticated_client: TestClient) -> None:
        response = unauthenticated_client.delete("/v1/admin/users/5")
        assert response.status_code == 401

    def test_403_non_admin(self, forbidden_client: TestClient) -> None:
        response = forbidden_client.delete("/v1/admin/users/5")
        assert response.status_code == 403

    def test_404_user_not_found(self, client: TestClient, mock_service: MagicMock) -> None:
        mock_service.delete_user.side_effect = HTTPException(
            status_code=404, detail="user_not_found"
        )
        response = client.delete("/v1/admin/users/999")
        assert response.status_code == 404


# ===========================================================================
# POST /v1/admin/modules
# ===========================================================================


class TestCreateModule:
    def test_201_happy_path(self, client: TestClient, mock_service: MagicMock) -> None:
        module = Module(
            id=1, category="PROFESSIONAL", slug="math", title="Math",
            order_index=0, is_published=True,
        )
        mock_service.create_module.return_value = module

        response = client.post("/v1/admin/modules", json={
            "category": "PROFESSIONAL", "slug": "math", "title": "Math"
        })

        assert response.status_code == 201
        assert response.json()["slug"] == "math"

    def test_401_no_token(self, unauthenticated_client: TestClient) -> None:
        response = unauthenticated_client.post("/v1/admin/modules", json={
            "category": "PROFESSIONAL", "slug": "math", "title": "Math"
        })
        assert response.status_code == 401

    def test_403_non_admin(self, forbidden_client: TestClient) -> None:
        response = forbidden_client.post("/v1/admin/modules", json={
            "category": "PROFESSIONAL", "slug": "math", "title": "Math"
        })
        assert response.status_code == 403

    def test_422_missing_title(self, client: TestClient) -> None:
        response = client.post("/v1/admin/modules", json={
            "category": "PROFESSIONAL", "slug": "math"
        })
        assert response.status_code == 422


# ===========================================================================
# DELETE /v1/admin/modules/{id} — force-flag cascade test
# ===========================================================================


class TestDeleteModule:
    def test_204_no_progress(self, client: TestClient, mock_service: MagicMock) -> None:
        mock_service.delete_module.return_value = None

        response = client.delete("/v1/admin/modules/1")

        assert response.status_code == 204

    def test_409_progress_exists_without_force(
        self, client: TestClient, mock_service: MagicMock
    ) -> None:
        mock_service.delete_module.side_effect = HTTPException(
            status_code=409, detail="progress_exists"
        )

        response = client.delete("/v1/admin/modules/1")

        assert response.status_code == 409
        assert "progress_exists" in response.json()["error"]["message"]

    def test_204_force_cascade(self, client: TestClient, mock_service: MagicMock) -> None:
        mock_service.delete_module.return_value = None

        response = client.delete("/v1/admin/modules/1?force=true")

        assert response.status_code == 204
        mock_service.delete_module.assert_called_once_with(1, force=True)

    def test_401_no_token(self, unauthenticated_client: TestClient) -> None:
        response = unauthenticated_client.delete("/v1/admin/modules/1")
        assert response.status_code == 401

    def test_403_non_admin(self, forbidden_client: TestClient) -> None:
        response = forbidden_client.delete("/v1/admin/modules/1")
        assert response.status_code == 403


# ===========================================================================
# DELETE /v1/admin/topics/{id} — force-flag cascade test
# ===========================================================================


class TestDeleteTopic:
    def test_204_no_progress(self, client: TestClient, mock_service: MagicMock) -> None:
        mock_service.delete_topic.return_value = None
        response = client.delete("/v1/admin/topics/1")
        assert response.status_code == 204

    def test_409_progress_exists_without_force(
        self, client: TestClient, mock_service: MagicMock
    ) -> None:
        mock_service.delete_topic.side_effect = HTTPException(
            status_code=409, detail="progress_exists"
        )
        response = client.delete("/v1/admin/topics/1")
        assert response.status_code == 409

    def test_204_force_cascade(self, client: TestClient, mock_service: MagicMock) -> None:
        mock_service.delete_topic.return_value = None
        response = client.delete("/v1/admin/topics/1?force=true")
        assert response.status_code == 204
        mock_service.delete_topic.assert_called_once_with(1, force=True)


# ===========================================================================
# DELETE /v1/admin/subtopics/{id} — force-flag cascade test
# ===========================================================================


class TestDeleteSubtopic:
    def test_204_no_progress(self, client: TestClient, mock_service: MagicMock) -> None:
        mock_service.delete_subtopic.return_value = None
        response = client.delete("/v1/admin/subtopics/1")
        assert response.status_code == 204

    def test_409_progress_exists_without_force(
        self, client: TestClient, mock_service: MagicMock
    ) -> None:
        mock_service.delete_subtopic.side_effect = HTTPException(
            status_code=409, detail="progress_exists"
        )
        response = client.delete("/v1/admin/subtopics/1")
        assert response.status_code == 409

    def test_204_force_cascade(self, client: TestClient, mock_service: MagicMock) -> None:
        mock_service.delete_subtopic.return_value = None
        response = client.delete("/v1/admin/subtopics/1?force=true")
        assert response.status_code == 204
        mock_service.delete_subtopic.assert_called_once_with(1, force=True)


# ===========================================================================
# POST /v1/admin/questions:bulk-import
# ===========================================================================


class TestBulkImport:
    def test_200_happy_path(self, client: TestClient, mock_service: MagicMock) -> None:
        mock_service.bulk_import_questions.return_value = {"accepted": 2, "rejected": []}

        response = client.post("/v1/admin/questions:bulk-import", json={
            "questions": [
                {
                    "subtopic_id": 1, "level_scope": "SUBTOPIC", "stem": "Q1?",
                    "options": ["A", "B"], "correct_answer": "A",
                    "explanation": "Because A", "difficulty": "EASY",
                    "qtype": "MULTIPLE_CHOICE",
                },
                {
                    "subtopic_id": 1, "level_scope": "SUBTOPIC", "stem": "Q2?",
                    "options": ["C", "D"], "correct_answer": "C",
                    "explanation": "Because C", "difficulty": "MEDIUM",
                    "qtype": "MULTIPLE_CHOICE",
                },
            ]
        })

        assert response.status_code == 200
        body = response.json()
        assert body["accepted"] == 2
        assert body["rejected"] == []

    def test_401_no_token(self, unauthenticated_client: TestClient) -> None:
        response = unauthenticated_client.post("/v1/admin/questions:bulk-import", json={
            "questions": []
        })
        assert response.status_code == 401

    def test_403_non_admin(self, forbidden_client: TestClient) -> None:
        response = forbidden_client.post("/v1/admin/questions:bulk-import", json={
            "questions": []
        })
        assert response.status_code == 403

    def test_422_invalid_question(self, client: TestClient) -> None:
        response = client.post("/v1/admin/questions:bulk-import", json={
            "questions": [{"subtopic_id": 1}]  # missing required fields
        })
        assert response.status_code == 422


# ===========================================================================
# DELETE /v1/admin/users/{id}/mock-exam-attempts
# ===========================================================================


class TestDeleteMockAttempts:
    def test_204_happy_path(self, client: TestClient, mock_service: MagicMock) -> None:
        mock_service.delete_mock_attempts.return_value = 3

        response = client.delete("/v1/admin/users/5/mock-exam-attempts")

        assert response.status_code == 204

    def test_401_no_token(self, unauthenticated_client: TestClient) -> None:
        response = unauthenticated_client.delete("/v1/admin/users/5/mock-exam-attempts")
        assert response.status_code == 401

    def test_403_non_admin(self, forbidden_client: TestClient) -> None:
        response = forbidden_client.delete("/v1/admin/users/5/mock-exam-attempts")
        assert response.status_code == 403

    def test_404_user_not_found(self, client: TestClient, mock_service: MagicMock) -> None:
        mock_service.delete_mock_attempts.side_effect = HTTPException(
            status_code=404, detail="user_not_found"
        )
        response = client.delete("/v1/admin/users/999/mock-exam-attempts")
        assert response.status_code == 404


# ===========================================================================
# GET /v1/admin/analytics
# ===========================================================================


class TestAnalytics:
    def test_200_happy_path(self, client: TestClient, mock_service: MagicMock) -> None:
        mock_service.get_analytics.return_value = AnalyticsResponse(
            total_users=100,
            verified_users=80,
            banned_users=5,
            total_lessons_completed=500,
            total_quiz_attempts=200,
            total_mock_attempts=50,
            mock_pass_rate=0.75,
            weakest_subtopics=[
                WeakSubtopic(subtopic_id=1, title="Algebra", avg_score=0.45),
            ],
        )

        response = client.get("/v1/admin/analytics")

        assert response.status_code == 200
        body = response.json()
        assert body["total_users"] == 100
        assert body["mock_pass_rate"] == 0.75
        assert len(body["weakest_subtopics"]) == 1

    def test_401_no_token(self, unauthenticated_client: TestClient) -> None:
        response = unauthenticated_client.get("/v1/admin/analytics")
        assert response.status_code == 401

    def test_403_non_admin(self, forbidden_client: TestClient) -> None:
        response = forbidden_client.get("/v1/admin/analytics")
        assert response.status_code == 403


# ===========================================================================
# POST /v1/admin/exports
# ===========================================================================


class TestExport:
    def test_201_happy_path(self, client: TestClient, mock_service: MagicMock) -> None:
        mock_service.export_data.return_value = {"users": [], "modules": []}

        response = client.post("/v1/admin/exports")

        assert response.status_code == 201
        body = response.json()
        assert "users" in body
        assert "modules" in body

    def test_401_no_token(self, unauthenticated_client: TestClient) -> None:
        response = unauthenticated_client.post("/v1/admin/exports")
        assert response.status_code == 401

    def test_403_non_admin(self, forbidden_client: TestClient) -> None:
        response = forbidden_client.post("/v1/admin/exports")
        assert response.status_code == 403


# ===========================================================================
# POST /v1/admin/imports
# ===========================================================================


class TestImport:
    def test_200_happy_path(self, client: TestClient, mock_service: MagicMock) -> None:
        mock_service.import_data.return_value = {"success": True, "errors": []}

        response = client.post("/v1/admin/imports", json={
            "data": {"modules": [], "topics": [], "subtopics": [], "questions": []}
        })

        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True

    def test_422_fk_violation(self, client: TestClient, mock_service: MagicMock) -> None:
        mock_service.import_data.side_effect = HTTPException(
            status_code=422,
            detail={"message": "import_referential_integrity", "errors": [
                {"type": "FK_VIOLATION", "detail": "Topic 1 references non-existent module 99"}
            ]},
        )

        response = client.post("/v1/admin/imports", json={
            "data": {"modules": [], "topics": [{"id": 1, "module_id": 99}]}
        })

        assert response.status_code == 422

    def test_401_no_token(self, unauthenticated_client: TestClient) -> None:
        response = unauthenticated_client.post("/v1/admin/imports", json={"data": {}})
        assert response.status_code == 401

    def test_403_non_admin(self, forbidden_client: TestClient) -> None:
        response = forbidden_client.post("/v1/admin/imports", json={"data": {}})
        assert response.status_code == 403


# ===========================================================================
# POST /v1/admin/announcements
# ===========================================================================


class TestCreateAnnouncement:
    def test_201_happy_path(self, client: TestClient, app: FastAPI) -> None:
        """Announcement creation uses the DB directly, so we mock at the repo level."""
        from app.features.announcements.models import Announcement
        from app.features.announcements.repository import AnnouncementRepository
        from app.infrastructure.database.session import get_db

        mock_announcement = MagicMock(spec=Announcement)
        mock_announcement.id = 1
        mock_announcement.title = "Test"
        mock_announcement.body = "Body"
        mock_announcement.audience_filter = None
        mock_announcement.expires_at = None
        mock_announcement.created_by = 1
        mock_announcement.created_at = datetime(2025, 1, 1, tzinfo=timezone.utc)

        with patch.object(
            AnnouncementRepository, "create_announcement", return_value=mock_announcement
        ):
            # Override get_db to return a mock session
            mock_db = MagicMock()
            app.dependency_overrides[get_db] = lambda: mock_db

            response = client.post("/v1/admin/announcements", json={
                "title": "Test", "body": "Body"
            })

        assert response.status_code == 201
        body = response.json()
        assert body["title"] == "Test"

    def test_401_no_token(self, unauthenticated_client: TestClient) -> None:
        response = unauthenticated_client.post("/v1/admin/announcements", json={
            "title": "Test", "body": "Body"
        })
        assert response.status_code == 401

    def test_403_non_admin(self, forbidden_client: TestClient) -> None:
        response = forbidden_client.post("/v1/admin/announcements", json={
            "title": "Test", "body": "Body"
        })
        assert response.status_code == 403

    def test_422_missing_title(self, client: TestClient) -> None:
        response = client.post("/v1/admin/announcements", json={"body": "Body"})
        assert response.status_code == 422
