"""Service tests for the tutor feature — mocked repository."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.features.content.models import Question
from app.features.content.repository import QuestionRepository, SubtopicRepository
from app.features.tutor.models import TutorInteraction
from app.features.tutor.repository import TutorRepository
from app.features.tutor.service import TutorService


def _make_question(**kwargs) -> Question:
    defaults = {
        "id": 1,
        "subtopic_id": 10,
        "topic_id": 5,
        "module_id": 2,
        "category": "PROFESSIONAL",
        "level_scope": "SUBTOPIC",
        "stem": "What is the capital of the Philippines?",
        "options": ["Manila", "Cebu", "Davao", "Quezon City"],
        "correct_answer": "Manila",
        "explanation": "Manila is the capital city of the Philippines.",
        "difficulty": "EASY",
        "qtype": "MULTIPLE_CHOICE",
        "is_active": True,
    }
    defaults.update(kwargs)
    q = MagicMock(spec=Question)
    for k, v in defaults.items():
        setattr(q, k, v)
    return q


def _make_interaction(**kwargs) -> TutorInteraction:
    defaults = {
        "id": 1,
        "user_id": 1,
        "question_id": 1,
        "subtopic_id": 10,
        "interaction_type": "explain_answer",
        "request_context": None,
        "response_text": "test response",
        "helpful": None,
    }
    defaults.update(kwargs)
    obj = MagicMock(spec=TutorInteraction)
    for k, v in defaults.items():
        setattr(obj, k, v)
    return obj


@pytest.fixture
def mock_tutor_repo() -> MagicMock:
    return MagicMock(spec=TutorRepository)


@pytest.fixture
def mock_question_repo() -> MagicMock:
    return MagicMock(spec=QuestionRepository)


@pytest.fixture
def mock_subtopic_repo() -> MagicMock:
    return MagicMock(spec=SubtopicRepository)


@pytest.fixture
def service(mock_tutor_repo, mock_question_repo, mock_subtopic_repo) -> TutorService:
    return TutorService(
        tutor_repo=mock_tutor_repo,
        question_repo=mock_question_repo,
        subtopic_repo=mock_subtopic_repo,
    )


def test_explain_returns_response(service, mock_question_repo, mock_tutor_repo):
    question = _make_question()
    mock_question_repo.get.return_value = question
    mock_tutor_repo.create_interaction.return_value = _make_interaction(
        interaction_type="explain_answer"
    )

    result = service.explain(user_id=1, question_id=1, selected_answer="Cebu")

    assert result.interaction_type == "explain_answer"
    assert result.interaction_id == 1
    mock_question_repo.get.assert_called_once_with(1)


def test_explain_raises_404_when_question_missing(service, mock_question_repo):
    mock_question_repo.get.return_value = None

    with pytest.raises(HTTPException) as exc_info:
        service.explain(user_id=1, question_id=999)
    assert exc_info.value.status_code == 404


def test_hint_returns_response(service, mock_question_repo, mock_tutor_repo):
    question = _make_question()
    mock_question_repo.get.return_value = question
    mock_tutor_repo.create_interaction.return_value = _make_interaction(
        interaction_type="hint"
    )

    result = service.hint(user_id=1, question_id=1)
    assert result.interaction_type == "hint"


def test_step_by_step_returns_steps(service, mock_question_repo, mock_tutor_repo):
    question = _make_question()
    mock_question_repo.get.return_value = question
    mock_tutor_repo.create_interaction.return_value = _make_interaction(
        interaction_type="step_by_step"
    )

    result = service.step_by_step_explain(user_id=1, question_id=1)
    assert result.interaction_id == 1
    assert isinstance(result.steps, list)
    assert len(result.steps) > 0


def test_similar_question_returns_data(service, mock_question_repo, mock_tutor_repo):
    question = _make_question()
    mock_question_repo.get.return_value = question
    mock_tutor_repo.create_interaction.return_value = _make_interaction(
        interaction_type="similar_question"
    )

    result = service.similar_question(user_id=1, question_id=1)
    assert result.interaction_id == 1
    assert result.correct_answer == "Manila"


def test_rate_interaction_raises_404_when_missing(service, mock_tutor_repo):
    mock_tutor_repo.rate_interaction.return_value = None

    with pytest.raises(HTTPException) as exc_info:
        service.rate_interaction(999, True)
    assert exc_info.value.status_code == 404


def test_rate_interaction_success(service, mock_tutor_repo):
    mock_tutor_repo.rate_interaction.return_value = _make_interaction(helpful=True)
    # Should not raise
    service.rate_interaction(1, True)
    mock_tutor_repo.rate_interaction.assert_called_once_with(1, True)
