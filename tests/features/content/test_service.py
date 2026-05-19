"""Service tests for the content slice.

Per ``testing-standards.md`` the service layer is exercised with mocked
repositories, except :class:`QuestionService` whose contract spans an actual
DB write + a rejection log row. That branch uses the real ``db_session``
fixture so the ``question_rejection_log`` FK is honoured.

Coverage shape (per Task 7.5 acceptance bullets):

* ``ModuleService``: list, happy-path get, 403-on-mismatch, 403-on-unknown,
  Phase 2 ``cross_category_preview`` admits cross-category reads.
* ``TopicService``: 403 when the parent module is wrong category.
* ``SubtopicService``: walks topic -> module for the check; 403 on unknown
  topic id.
* ``LessonService``: 403 for INCOMPLETE / DRAFT / unknown / cross-category;
  happy path for PUBLISHED.
* ``QuestionService.create``: happy path persists active row, MC-with-one-
  option persists inactive + logs rejection + 400, unknown subtopic 400.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.features.content.algorithms.quality_gate import (
    RULE_MC_OPTION_COUNT,
)
from app.features.content.models import (
    Difficulty,
    LessonStatus,
    LevelScope,
    Lesson,
    Module,
    Question,
    QuestionRejectionLog,
    QuestionType,
    Subtopic,
    Topic,
)
from app.features.content.repository import (
    LessonRepository,
    ModuleRepository,
    QuestionRepository,
    SubtopicRepository,
    TopicRepository,
)
from app.features.content.schemas import QuestionCreate
from app.features.content.service import (
    LessonService,
    ModuleService,
    QuestionService,
    SubtopicService,
    TopicService,
)
from app.features.users.models import AccountState, Category, Role, User


# ----- Test data factories --------------------------------------------------


def _make_user(**overrides: object) -> User:
    """Build a detached ``User`` for service-layer tests."""
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
    """Build a detached ``Module``."""
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
        "title": "Linear Equations",
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


# ----- ModuleService --------------------------------------------------------


def test_module_service_list_for_user_passes_category_filter() -> None:
    repo = MagicMock(spec=ModuleRepository)
    expected = ([_make_module()], 1)
    repo.list_by_category.return_value = expected

    service = ModuleService(module_repo=repo)
    result = service.list_for_user(_make_user(), skip=0, limit=20)

    assert result == expected
    repo.list_by_category.assert_called_once_with(
        Category.PROFESSIONAL, skip=0, limit=20
    )


def test_module_service_get_for_user_happy_path() -> None:
    module = _make_module(category=Category.PROFESSIONAL.value)
    repo = MagicMock(spec=ModuleRepository)
    repo.get.return_value = module

    service = ModuleService(module_repo=repo)
    result = service.get_for_user(_make_user(), module.id)

    assert result is module


def test_module_service_get_for_user_raises_403_on_unknown_id() -> None:
    """Unknown id surfaces as 403, not 404 — Property 12."""
    repo = MagicMock(spec=ModuleRepository)
    repo.get.return_value = None

    service = ModuleService(module_repo=repo)
    with pytest.raises(HTTPException) as exc_info:
        service.get_for_user(_make_user(), 9999)

    assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
    assert exc_info.value.detail == "forbidden"


def test_module_service_get_for_user_raises_403_on_category_mismatch() -> None:
    module = _make_module(category=Category.SUB_PROFESSIONAL.value)
    repo = MagicMock(spec=ModuleRepository)
    repo.get.return_value = module

    service = ModuleService(module_repo=repo)
    with pytest.raises(HTTPException) as exc_info:
        service.get_for_user(
            _make_user(category=Category.PROFESSIONAL.value), module.id
        )

    assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
    assert exc_info.value.detail == "forbidden"


def test_module_service_cross_category_preview_admits_mismatch() -> None:
    """Phase 2 hook: ``cross_category_preview=True`` skips the category gate."""
    module = _make_module(category=Category.SUB_PROFESSIONAL.value)
    repo = MagicMock(spec=ModuleRepository)
    repo.get.return_value = module

    service = ModuleService(module_repo=repo)
    result = service.get_for_user(
        _make_user(
            category=Category.PROFESSIONAL.value,
            cross_category_preview=True,
        ),
        module.id,
    )

    assert result is module


# ----- TopicService ---------------------------------------------------------


def test_topic_service_list_for_user_happy_path() -> None:
    module = _make_module()
    topics = [_make_topic(id=21), _make_topic(id=22, slug="b")]
    module_repo = MagicMock(spec=ModuleRepository)
    module_repo.get.return_value = module
    topic_repo = MagicMock(spec=TopicRepository)
    topic_repo.list_by_module.return_value = topics

    service = TopicService(
        topic_repo=topic_repo,
        module_service=ModuleService(module_repo=module_repo),
    )
    result = service.list_for_user(_make_user(), module.id)

    assert result == topics
    topic_repo.list_by_module.assert_called_once_with(module.id)


def test_topic_service_raises_403_when_module_wrong_category() -> None:
    module = _make_module(category=Category.SUB_PROFESSIONAL.value)
    module_repo = MagicMock(spec=ModuleRepository)
    module_repo.get.return_value = module
    topic_repo = MagicMock(spec=TopicRepository)

    service = TopicService(
        topic_repo=topic_repo,
        module_service=ModuleService(module_repo=module_repo),
    )
    with pytest.raises(HTTPException) as exc_info:
        service.list_for_user(
            _make_user(category=Category.PROFESSIONAL.value), module.id
        )

    assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
    # The topic listing must never run when the module check fails.
    topic_repo.list_by_module.assert_not_called()


# ----- SubtopicService ------------------------------------------------------


def test_subtopic_service_walks_topic_to_module_for_check() -> None:
    module = _make_module()
    topic = _make_topic(module_id=module.id)
    subtopics = [_make_subtopic(id=31), _make_subtopic(id=32, slug="b")]

    module_repo = MagicMock(spec=ModuleRepository)
    module_repo.get.return_value = module
    topic_repo = MagicMock(spec=TopicRepository)
    topic_repo.get.return_value = topic
    subtopic_repo = MagicMock(spec=SubtopicRepository)
    subtopic_repo.list_by_topic.return_value = subtopics

    service = SubtopicService(
        subtopic_repo=subtopic_repo,
        topic_repo=topic_repo,
        module_service=ModuleService(module_repo=module_repo),
    )
    result = service.list_for_user(_make_user(), topic.id)

    assert result == subtopics
    topic_repo.get.assert_called_once_with(topic.id)
    module_repo.get.assert_called_once_with(module.id)
    subtopic_repo.list_by_topic.assert_called_once_with(topic.id)


def test_subtopic_service_raises_403_for_unknown_topic() -> None:
    module_repo = MagicMock(spec=ModuleRepository)
    topic_repo = MagicMock(spec=TopicRepository)
    topic_repo.get.return_value = None
    subtopic_repo = MagicMock(spec=SubtopicRepository)

    service = SubtopicService(
        subtopic_repo=subtopic_repo,
        topic_repo=topic_repo,
        module_service=ModuleService(module_repo=module_repo),
    )
    with pytest.raises(HTTPException) as exc_info:
        service.list_for_user(_make_user(), 9999)

    assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
    subtopic_repo.list_by_topic.assert_not_called()


def test_subtopic_service_raises_403_when_module_wrong_category() -> None:
    module = _make_module(category=Category.SUB_PROFESSIONAL.value)
    topic = _make_topic(module_id=module.id)

    module_repo = MagicMock(spec=ModuleRepository)
    module_repo.get.return_value = module
    topic_repo = MagicMock(spec=TopicRepository)
    topic_repo.get.return_value = topic
    subtopic_repo = MagicMock(spec=SubtopicRepository)

    service = SubtopicService(
        subtopic_repo=subtopic_repo,
        topic_repo=topic_repo,
        module_service=ModuleService(module_repo=module_repo),
    )
    with pytest.raises(HTTPException) as exc_info:
        service.list_for_user(
            _make_user(category=Category.PROFESSIONAL.value), topic.id
        )

    assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN


# ----- LessonService --------------------------------------------------------


def _build_lesson_service(
    *,
    module: Module,
    topic: Topic,
    subtopic: Subtopic | None,
    lesson: Lesson | None,
) -> LessonService:
    module_repo = MagicMock(spec=ModuleRepository)
    module_repo.get.return_value = module
    topic_repo = MagicMock(spec=TopicRepository)
    topic_repo.get.return_value = topic
    subtopic_repo = MagicMock(spec=SubtopicRepository)
    subtopic_repo.get.return_value = subtopic
    lesson_repo = MagicMock(spec=LessonRepository)
    lesson_repo.get_by_subtopic_id.return_value = lesson

    return LessonService(
        lesson_repo=lesson_repo,
        subtopic_repo=subtopic_repo,
        topic_repo=topic_repo,
        module_service=ModuleService(module_repo=module_repo),
    )


def test_lesson_service_returns_published_lesson() -> None:
    module = _make_module()
    topic = _make_topic(module_id=module.id)
    subtopic = _make_subtopic(topic_id=topic.id)
    lesson = _make_lesson(
        subtopic_id=subtopic.id, status=LessonStatus.PUBLISHED.value
    )

    service = _build_lesson_service(
        module=module, topic=topic, subtopic=subtopic, lesson=lesson
    )
    result = service.get_for_user(_make_user(), subtopic.id)

    assert result is lesson


def test_lesson_service_403_for_incomplete_lesson() -> None:
    """Req 6.4 — INCOMPLETE lessons are hidden from learners."""
    module = _make_module()
    topic = _make_topic(module_id=module.id)
    subtopic = _make_subtopic(topic_id=topic.id)
    lesson = _make_lesson(
        subtopic_id=subtopic.id, status=LessonStatus.INCOMPLETE.value
    )

    service = _build_lesson_service(
        module=module, topic=topic, subtopic=subtopic, lesson=lesson
    )
    with pytest.raises(HTTPException) as exc_info:
        service.get_for_user(_make_user(), subtopic.id)

    assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN


def test_lesson_service_403_for_draft_lesson() -> None:
    """DRAFT lessons are pre-publication and must not reach learners either."""
    module = _make_module()
    topic = _make_topic(module_id=module.id)
    subtopic = _make_subtopic(topic_id=topic.id)
    lesson = _make_lesson(
        subtopic_id=subtopic.id, status=LessonStatus.DRAFT.value
    )

    service = _build_lesson_service(
        module=module, topic=topic, subtopic=subtopic, lesson=lesson
    )
    with pytest.raises(HTTPException) as exc_info:
        service.get_for_user(_make_user(), subtopic.id)

    assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN


def test_lesson_service_403_for_unknown_subtopic() -> None:
    module = _make_module()
    topic = _make_topic(module_id=module.id)

    service = _build_lesson_service(
        module=module, topic=topic, subtopic=None, lesson=None
    )
    with pytest.raises(HTTPException) as exc_info:
        service.get_for_user(_make_user(), 9999)

    assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN


def test_lesson_service_403_when_module_wrong_category() -> None:
    module = _make_module(category=Category.SUB_PROFESSIONAL.value)
    topic = _make_topic(module_id=module.id)
    subtopic = _make_subtopic(topic_id=topic.id)
    lesson = _make_lesson(subtopic_id=subtopic.id)

    service = _build_lesson_service(
        module=module, topic=topic, subtopic=subtopic, lesson=lesson
    )
    with pytest.raises(HTTPException) as exc_info:
        service.get_for_user(
            _make_user(category=Category.PROFESSIONAL.value), subtopic.id
        )

    assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN


def test_lesson_service_403_when_lesson_missing() -> None:
    """A subtopic that has no lesson row at all surfaces as 403."""
    module = _make_module()
    topic = _make_topic(module_id=module.id)
    subtopic = _make_subtopic(topic_id=topic.id)

    service = _build_lesson_service(
        module=module, topic=topic, subtopic=subtopic, lesson=None
    )
    with pytest.raises(HTTPException) as exc_info:
        service.get_for_user(_make_user(), subtopic.id)

    assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN


# ----- QuestionService ------------------------------------------------------
#
# Uses the real ``db_session`` fixture because the rejection-path branches
# touch ``question_rejection_log`` via FK and the rejection logging is part
# of the contract (Req 18.4).


def _seed_module_topic_subtopic(
    db: Session,
    *,
    category: Category = Category.PROFESSIONAL,
) -> tuple[Module, Topic, Subtopic]:
    module = Module(
        category=category.value, slug="m1", title="M", order_index=0
    )
    db.add(module)
    db.commit()
    db.refresh(module)
    topic = Topic(module_id=module.id, slug="t1", title="T", order_index=0)
    db.add(topic)
    db.commit()
    db.refresh(topic)
    subtopic = Subtopic(
        topic_id=topic.id, slug="s1", title="S", order_index=0
    )
    db.add(subtopic)
    db.commit()
    db.refresh(subtopic)
    return module, topic, subtopic


def _question_create(**overrides: object) -> QuestionCreate:
    defaults: dict[str, object] = {
        "subtopic_id": 1,
        "level_scope": LevelScope.SUBTOPIC,
        "stem": "What is 2 + 2?",
        "options": ["3", "4", "5", "6"],
        "correct_answer": "4",
        "explanation": "Addition.",
        "difficulty": Difficulty.EASY,
        "qtype": QuestionType.MULTIPLE_CHOICE,
    }
    return QuestionCreate(**{**defaults, **overrides})


def _build_question_service(db: Session) -> QuestionService:
    return QuestionService(
        question_repo=QuestionRepository(db=db),
        subtopic_repo=SubtopicRepository(db=db),
        topic_repo=TopicRepository(db=db),
        module_repo=ModuleRepository(db=db),
    )


def test_question_service_create_happy_path_persists_active(
    db_session: Session,
) -> None:
    module, topic, subtopic = _seed_module_topic_subtopic(db_session)
    service = _build_question_service(db_session)

    payload = _question_create(subtopic_id=subtopic.id)
    question = service.create(payload)

    assert question.id is not None
    assert question.is_active is True
    assert question.topic_id == topic.id
    assert question.module_id == module.id
    assert question.category == module.category
    # No rejection log row should exist for this happy-path call.
    assert (
        db_session.query(QuestionRejectionLog)
        .filter_by(question_id=question.id)
        .count()
        == 0
    )


def test_question_service_create_400_for_unknown_subtopic(
    db_session: Session,
) -> None:
    service = _build_question_service(db_session)

    with pytest.raises(HTTPException) as exc_info:
        service.create(_question_create(subtopic_id=999))

    assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
    assert exc_info.value.detail == "invalid_subtopic_id"


def test_question_service_rejection_path_persists_inactive_and_logs(
    db_session: Session,
) -> None:
    """A question that fails the gate is persisted with ``is_active=False``,
    a row is written to ``question_rejection_log``, and the service raises
    400 ``question_rejected:RULE``.

    We can't construct an MC-with-one-option ``QuestionCreate`` (the
    Pydantic validator rejects it), so we go through the service's lower-
    rung path: an ``IDENTIFICATION`` question with options where the
    correct answer is missing — this passes Pydantic but trips the
    quality-gate's ``RULE_CORRECT_NOT_IN_OPTIONS``... wait, the schema
    blocks that too. Use a different angle: monkeypatch the gate helper
    so it returns False for this specific call, simulating the future
    drift the defense-in-depth is guarding against.
    """
    from app.features.content import service as service_module

    module, topic, subtopic = _seed_module_topic_subtopic(db_session)
    service = _build_question_service(db_session)
    payload = _question_create(subtopic_id=subtopic.id)

    # Force the gate to reject so we can exercise the rejection branch
    # without having to defeat the Pydantic schema first.
    original = service_module.is_question_quality_passing
    service_module.is_question_quality_passing = (  # type: ignore[assignment]
        lambda q: (False, RULE_MC_OPTION_COUNT)
    )
    try:
        with pytest.raises(HTTPException) as exc_info:
            service.create(payload)
    finally:
        service_module.is_question_quality_passing = original  # type: ignore[assignment]

    assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
    assert exc_info.value.detail == f"question_rejected:{RULE_MC_OPTION_COUNT}"

    # The question row exists, but is inactive.
    persisted = (
        db_session.query(Question)
        .filter_by(subtopic_id=subtopic.id)
        .one()
    )
    assert persisted.is_active is False
    # Topic/module/category still fanned out from the parent.
    assert persisted.topic_id == topic.id
    assert persisted.module_id == module.id
    assert persisted.category == module.category

    # The rejection was logged with the rule string.
    log = (
        db_session.query(QuestionRejectionLog)
        .filter_by(question_id=persisted.id)
        .one()
    )
    assert log.rule == RULE_MC_OPTION_COUNT
