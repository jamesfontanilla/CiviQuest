"""Router tests for the mastery feature — mocked service, HTTP client."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.common.deps import get_current_user
from app.features.mastery.models import MasteryLevel, ReviewSchedule
from app.features.mastery.router import _get_mastery_service, _get_sr_service
from app.features.mastery.schemas import (
    RecommendationResponse,
    ReviewDueResponse,
    SubtopicMasteryResponse,
)
from app.features.mastery.service import MasteryService, SpacedRepetitionService
from app.features.users.models import AccountState, Category, Role, User
from app.main import app


def _make_user(**overrides) -> User:
    defaults = {
        "id": 1,
        "email": "test@example.com",
        "display_name": "Test",
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


@pytest.fixture
def mock_user():
    return _make_user()


@pytest.fixture
def mock_mastery_service():
    return MagicMock(spec=MasteryService)


@pytest.fixture
def mock_sr_service():
    return MagicMock(spec=SpacedRepetitionService)


@pytest.fixture
def client(mock_user, mock_mastery_service, mock_sr_service):
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[_get_mastery_service] = lambda: mock_mastery_service
    app.dependency_overrides[_get_sr_service] = lambda: mock_sr_service
    yield TestClient(app)
    app.dependency_overrides.clear()


class TestGetMyMastery:
    def test_returns_200_with_mastery_list(self, client, mock_mastery_service):
        mock_mastery_service.get_user_mastery.return_value = [
            SubtopicMasteryResponse(
                subtopic_id=1,
                subtopic_title="Civil Law Basics",
                mastery_level=MasteryLevel.FAMILIAR,
                mastery_score=0.35,
                confidence_score=0.4,
                retention_score=0.5,
                total_attempts=8,
                correct_attempts=5,
                last_practiced_at=None,
            )
        ]

        response = client.get("/v1/mastery/me")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["subtopic_id"] == 1
        assert data[0]["mastery_level"] == "FAMILIAR"

    def test_returns_empty_list_when_no_data(self, client, mock_mastery_service):
        mock_mastery_service.get_user_mastery.return_value = []

        response = client.get("/v1/mastery/me")
        assert response.status_code == 200
        assert response.json() == []


class TestGetMyWeakest:
    def test_returns_200_with_weakest(self, client, mock_mastery_service):
        mock_mastery_service.get_weakest_subtopics.return_value = [
            SubtopicMasteryResponse(
                subtopic_id=5,
                subtopic_title="Weak Area",
                mastery_level=MasteryLevel.BEGINNER,
                mastery_score=0.1,
                confidence_score=0.1,
                retention_score=0.2,
                total_attempts=3,
                correct_attempts=1,
                last_practiced_at=None,
            )
        ]

        response = client.get("/v1/mastery/me/weakest")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["mastery_score"] == 0.1


class TestGetDueReviews:
    def test_returns_200_with_due_reviews(self, client, mock_sr_service):
        mock_sr_service.get_due_reviews.return_value = [
            ReviewDueResponse(
                subtopic_id=10,
                subtopic_title="Review Topic",
                next_review_at=datetime(2024, 1, 15, tzinfo=timezone.utc),
                days_overdue=2.5,
                interval_days=3.0,
            )
        ]

        response = client.get("/v1/mastery/me/reviews/due")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["subtopic_id"] == 10
        assert data[0]["days_overdue"] == 2.5


class TestCompleteReview:
    def test_returns_200_on_valid_quality(self, client, mock_sr_service):
        mock_sr_service.record_review.return_value = MagicMock(spec=ReviewSchedule)

        response = client.post(
            "/v1/mastery/me/reviews/10:complete",
            json={"quality": 4},
        )
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
        mock_sr_service.record_review.assert_called_once()

    def test_returns_422_on_invalid_quality(self, client, mock_sr_service):
        response = client.post(
            "/v1/mastery/me/reviews/10:complete",
            json={"quality": 6},
        )
        assert response.status_code == 422

    def test_returns_422_on_missing_quality(self, client, mock_sr_service):
        response = client.post(
            "/v1/mastery/me/reviews/10:complete",
            json={},
        )
        assert response.status_code == 422


class TestGetRecommendations:
    def test_returns_200_with_db(self, mock_user, mock_mastery_service, mock_sr_service):
        """The recommendations endpoint accesses DB directly for full data.
        We override get_db to provide a working session."""
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from sqlalchemy.pool import StaticPool

        from app.infrastructure.database.base import Base
        from app.infrastructure.database.session import get_db

        engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)

        def override_db():
            session = TestSession()
            try:
                yield session
            finally:
                session.close()

        app.dependency_overrides[get_current_user] = lambda: mock_user
        app.dependency_overrides[get_db] = override_db
        try:
            c = TestClient(app)
            response = c.get("/v1/mastery/me/recommendations")
            assert response.status_code == 200
            assert response.json() == []
        finally:
            app.dependency_overrides.clear()


class TestUnauthenticated:
    def test_mastery_me_requires_auth(self):
        """Without auth override, should get 401."""
        app.dependency_overrides.clear()
        c = TestClient(app)
        response = c.get("/v1/mastery/me")
        assert response.status_code == 401
