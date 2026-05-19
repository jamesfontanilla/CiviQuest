"""Router tests for the content slice (Task 7.8).

Per ``testing-standards.md`` router tests use ``TestClient`` with mocked
services injected via ``app.dependency_overrides``. The DB is never hit
here; service-layer behaviour is exercised in ``test_service.py``.

The test app stacks the production middleware set so the canonical
``ErrorResponse`` envelope (Task 1.5) is what assertions see, not
FastAPI's default ``{"detail": "..."}``.

Coverage shape (per Task 7.8 acceptance bullets):

* Each route: happy path + at least one validation failure + 401 + 403.
* The 409 ``exam_in_progress`` case is owned by Task 12.8 — until Task 12.1
  lands the dependency is a no-op pass-through (see ``app/common/deps.py``).
* The mock-exam guard is overridden to a pass-through so authenticated
  routes don't have to mint a real ``MockExamAttempt`` row.
"""

from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI, HTTPException, status
from fastapi.testclient import TestClient

from app.common.deps import get_current_user, require_no_active_mock
from app.common.middlewares.auth import AuthMiddleware
from app.common.middlewares.error_handler import register_exception_handlers
from app.common.middlewares.logging import RequestLoggingMiddleware
from app.features.content.models import (
    LessonStatus,
    Lesson,
    Module,
    Subtopic,
    Topic,
)
from app.features.content.router import (
    get_lesson_service,
    get_module_service,
    get_subtopic_service,
    get_topic_service,
    router as content_router,
)
from app.features.content.service import (
    LessonService,
    ModuleService,
    SubtopicService,
    TopicService,
)
from app.features.users.models import AccountState, Category, Role, User


# --- factories --------------------------------------------------------------


def _make_user(**overrides: object) -> User:
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


def _make_module(**overrides: object) -> Module:
    defaults: dict[str, object] = {
        "id": 10,
        "category": Category.PROFESSIONAL.value,
        "slug": "math",
        "title": "Math",
        "order_index": 0,
        "is_published": True,
    }
    return Module(**{**defaults, **overrides})


def _make_topic(**overrides: object) -> Topic:
    defaults: dict[str, object] = {
        "id": 20,
        "module_id": 10,
        "slug": "algebra",
        "title": "Algebra",
        "order_index": 0,
    }
    return Topic(**{**defaults, **overrides})


def _make_subtopic(**overrides: object) -> Subtopic:
    defaults: dict[str, object] = {
        "id": 30,
        "topic_id": 20,
        "slug": "linear",
        "title": "Linear",
        "order_index": 0,
    }
    return Subtopic(**{**defaults, **overrides})


def _make_lesson(**overrides: object) -> Lesson:
    defaults: dict[str, object] = {
        "id": 40,
        "subtopic_id": 30,
        "content_json": {
            "explanations": [{"heading": "I", "body": "b"}],
            "worked_examples": [{"title": "T", "body": "b"}],
            "key_takeaways": ["k"],
            "summary": "s",
        },
        "status": LessonStatus.PUBLISHED.value,
    }
    return Lesson(**{**defaults, **overrides})


# --- fixtures ---------------------------------------------------------------


@pytest.fixture
def mock_module_service() -> MagicMock:
    return MagicMock(spec=ModuleService)


@pytest.fixture
def mock_topic_service() -> MagicMock:
    return MagicMock(spec=TopicService)


@pytest.fixture
def mock_subtopic_service() -> MagicMock:
    return MagicMock(spec=SubtopicService)


@pytest.fixture
def mock_lesson_service() -> MagicMock:
    return MagicMock(spec=LessonService)


@pytest.fixture
def authed_user() -> User:
    return _make_user()


@pytest.fixture
def app(
    mock_module_service: MagicMock,
    mock_topic_service: MagicMock,
    mock_subtopic_service: MagicMock,
    mock_lesson_service: MagicMock,
    authed_user: User,
) -> Iterator[FastAPI]:
    """Mount the content router with the production middleware stack.

    ``get_current_user`` and ``require_no_active_mock`` are overridden to
    return the fixture user directly so router tests don't have to mint a
    real JWT or a ``MockExamAttempt`` row. The 401 path is exercised by
    *removing* the override per-test (see ``unauthenticated_client``).
    """
    fastapi_app = FastAPI()
    fastapi_app.add_middleware(AuthMiddleware)
    fastapi_app.add_middleware(RequestLoggingMiddleware)
    register_exception_handlers(fastapi_app)
    fastapi_app.include_router(content_router)

    fastapi_app.dependency_overrides[get_module_service] = (
        lambda: mock_module_service
    )
    fastapi_app.dependency_overrides[get_topic_service] = (
        lambda: mock_topic_service
    )
    fastapi_app.dependency_overrides[get_subtopic_service] = (
        lambda: mock_subtopic_service
    )
    fastapi_app.dependency_overrides[get_lesson_service] = (
        lambda: mock_lesson_service
    )

    # Both dependencies return the user directly; authentication is exercised
    # at ``test_deps.py`` and ``test_router.py`` for the auth slice. Here we
    # treat the user as already-loaded.
    fastapi_app.dependency_overrides[get_current_user] = lambda: authed_user
    fastapi_app.dependency_overrides[require_no_active_mock] = (
        lambda: authed_user
    )

    try:
        yield fastapi_app
    finally:
        fastapi_app.dependency_overrides.clear()


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


@pytest.fixture
def unauthenticated_client(app: FastAPI) -> TestClient:
    """A client whose auth-dependency override raises 401, mimicking a
    request with no/invalid bearer token."""
    app.dependency_overrides[require_no_active_mock] = _raise_401
    app.dependency_overrides[get_current_user] = _raise_401
    return TestClient(app)


def _raise_401() -> None:
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="invalid_credentials",
    )


# ===========================================================================
# GET /v1/modules
# ===========================================================================


def test_list_modules_200(
    client: TestClient, mock_module_service: MagicMock
) -> None:
    mock_module_service.list_for_user.return_value = (
        [_make_module(id=1, slug="m1"), _make_module(id=2, slug="m2")],
        2,
    )

    response = client.get("/v1/modules?skip=0&limit=20")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert body["skip"] == 0
    assert body["limit"] == 20
    assert {item["slug"] for item in body["items"]} == {"m1", "m2"}


def test_list_modules_422_on_negative_skip(client: TestClient) -> None:
    response = client.get("/v1/modules?skip=-1")
    assert response.status_code == 422


def test_list_modules_422_on_limit_over_max(client: TestClient) -> None:
    response = client.get("/v1/modules?limit=1000")
    assert response.status_code == 422


def test_list_modules_401_without_token(
    unauthenticated_client: TestClient,
) -> None:
    response = unauthenticated_client.get("/v1/modules")
    assert response.status_code == 401
    assert response.json() == {
        "error": {"message": "invalid_credentials", "code": "HTTP_401"}
    }


# ===========================================================================
# GET /v1/modules/{id}
# ===========================================================================


def test_get_module_200(
    client: TestClient, mock_module_service: MagicMock
) -> None:
    mock_module_service.get_for_user.return_value = _make_module(id=10)

    response = client.get("/v1/modules/10")

    assert response.status_code == 200
    assert response.json()["id"] == 10


def test_get_module_403_for_wrong_category(
    client: TestClient, mock_module_service: MagicMock
) -> None:
    mock_module_service.get_for_user.side_effect = HTTPException(
        status_code=status.HTTP_403_FORBIDDEN, detail="forbidden"
    )

    response = client.get("/v1/modules/99")

    assert response.status_code == 403
    assert response.json() == {
        "error": {"message": "forbidden", "code": "HTTP_403"}
    }


def test_get_module_422_for_non_int_id(client: TestClient) -> None:
    response = client.get("/v1/modules/not-a-number")
    assert response.status_code == 422


def test_get_module_401_without_token(
    unauthenticated_client: TestClient,
) -> None:
    response = unauthenticated_client.get("/v1/modules/10")
    assert response.status_code == 401


# ===========================================================================
# GET /v1/modules/{id}/topics
# ===========================================================================


def test_list_topics_200(
    client: TestClient, mock_topic_service: MagicMock
) -> None:
    mock_topic_service.list_for_user.return_value = [
        _make_topic(id=21, slug="a"),
        _make_topic(id=22, slug="b"),
    ]

    response = client.get("/v1/modules/10/topics")

    assert response.status_code == 200
    body = response.json()
    assert [t["slug"] for t in body] == ["a", "b"]


def test_list_topics_403_for_wrong_category(
    client: TestClient, mock_topic_service: MagicMock
) -> None:
    mock_topic_service.list_for_user.side_effect = HTTPException(
        status_code=status.HTTP_403_FORBIDDEN, detail="forbidden"
    )

    response = client.get("/v1/modules/99/topics")

    assert response.status_code == 403


def test_list_topics_422_for_non_int_module_id(client: TestClient) -> None:
    response = client.get("/v1/modules/abc/topics")
    assert response.status_code == 422


def test_list_topics_401_without_token(
    unauthenticated_client: TestClient,
) -> None:
    response = unauthenticated_client.get("/v1/modules/10/topics")
    assert response.status_code == 401


# ===========================================================================
# GET /v1/topics/{id}/subtopics
# ===========================================================================


def test_list_subtopics_200(
    client: TestClient, mock_subtopic_service: MagicMock
) -> None:
    mock_subtopic_service.list_for_user.return_value = [
        _make_subtopic(id=31, slug="a"),
        _make_subtopic(id=32, slug="b"),
    ]

    response = client.get("/v1/topics/20/subtopics")

    assert response.status_code == 200
    body = response.json()
    assert [s["slug"] for s in body] == ["a", "b"]


def test_list_subtopics_403_for_wrong_category(
    client: TestClient, mock_subtopic_service: MagicMock
) -> None:
    mock_subtopic_service.list_for_user.side_effect = HTTPException(
        status_code=status.HTTP_403_FORBIDDEN, detail="forbidden"
    )

    response = client.get("/v1/topics/9999/subtopics")

    assert response.status_code == 403


def test_list_subtopics_422_for_non_int_topic_id(client: TestClient) -> None:
    response = client.get("/v1/topics/zzz/subtopics")
    assert response.status_code == 422


def test_list_subtopics_401_without_token(
    unauthenticated_client: TestClient,
) -> None:
    response = unauthenticated_client.get("/v1/topics/20/subtopics")
    assert response.status_code == 401


# ===========================================================================
# GET /v1/subtopics/{id}/lesson
# ===========================================================================


def test_get_lesson_200(
    client: TestClient, mock_lesson_service: MagicMock
) -> None:
    mock_lesson_service.get_for_user.return_value = _make_lesson()

    response = client.get("/v1/subtopics/30/lesson")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == 40
    assert body["status"] == LessonStatus.PUBLISHED.value
    assert "explanations" in body["content_json"]


def test_get_lesson_403_for_incomplete(
    client: TestClient, mock_lesson_service: MagicMock
) -> None:
    """Req 6.4: INCOMPLETE lessons are hidden behind 403, not 404."""
    mock_lesson_service.get_for_user.side_effect = HTTPException(
        status_code=status.HTTP_403_FORBIDDEN, detail="forbidden"
    )

    response = client.get("/v1/subtopics/30/lesson")

    assert response.status_code == 403


def test_get_lesson_422_for_non_int_subtopic_id(client: TestClient) -> None:
    response = client.get("/v1/subtopics/zzz/lesson")
    assert response.status_code == 422


def test_get_lesson_401_without_token(
    unauthenticated_client: TestClient,
) -> None:
    response = unauthenticated_client.get("/v1/subtopics/30/lesson")
    assert response.status_code == 401
