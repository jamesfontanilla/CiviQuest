"""Service tests for the quizzes slice (Task 11.4).

Per ``testing-standards.md`` the service layer is exercised against
mocked repositories. Property-level coverage of start-quiz gating
lives in ``test_property.py``; this file focuses on:

- ``set_answer`` happy path + 409 (already submitted) + 403 (wrong
  question on attempt).
- ``submit_attempt`` happy paths for SUBTOPIC perfect / SUBTOPIC pass
  / SUBTOPIC fail, TOPIC pass + ``mark_topic_complete`` fan-out, and
  MODULE pass + ``mark_module_complete`` fan-out.
- ``get_attempt`` returns the in-progress shape on IN_PROGRESS and
  the submitted shape on SUBMITTED.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException, status

from app.features.content.models import (
    Difficulty,
    LevelScope,
    Question,
    QuestionType,
)
from app.features.content.repository import (
    QuestionRepository,
    SubtopicRepository,
    TopicRepository,
)
from app.features.progress.repository import ProgressRepository
from app.features.quizzes.models import QuizAttempt, QuizAttemptStatus
from app.features.quizzes.repository import QuizRepository
from app.features.quizzes.schemas import (
    QuizAnswerPatchRequest,
    QuizAttemptInProgressResponse,
    QuizSubmittedResponse,
)
from app.features.quizzes.service import QuizService
from app.features.users.models import AccountState, Category, Role, User
from app.features.xp.models import XPSource
from app.features.xp.service import XPService


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


def _make_question(qid: int, *, correct: str = "A") -> Question:
    return Question(
        id=qid,
        subtopic_id=10,
        topic_id=20,
        module_id=30,
        category=Category.PROFESSIONAL.value,
        level_scope=LevelScope.SUBTOPIC.value,
        stem=f"Q{qid}?",
        options=["A", "B", "C", "D"],
        correct_answer=correct,
        explanation=f"exp{qid}",
        difficulty=Difficulty.EASY.value,
        qtype=QuestionType.MULTIPLE_CHOICE.value,
        is_active=True,
    )


def _make_attempt(
    *,
    attempt_id: int = 99,
    user_id: int = 1,
    scope_level: LevelScope = LevelScope.SUBTOPIC,
    scope_id: int = 10,
    status_value: str = "IN_PROGRESS",
    max_score: int = 2,
    score: int | None = None,
) -> QuizAttempt:
    return QuizAttempt(
        id=attempt_id,
        user_id=user_id,
        scope_level=scope_level.value,
        scope_id=scope_id,
        status=status_value,
        started_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        submitted_at=None
        if status_value == "IN_PROGRESS"
        else datetime(2025, 1, 1, 0, 30, tzinfo=timezone.utc),
        max_score=max_score,
        seed=12345,
        score=score,
    )


def _build_service(
    *,
    quiz_repo: MagicMock | None = None,
    question_repo: MagicMock | None = None,
    progress_repo: MagicMock | None = None,
    topic_repo: MagicMock | None = None,
    subtopic_repo: MagicMock | None = None,
    xp_service: MagicMock | None = None,
) -> tuple[QuizService, dict[str, MagicMock]]:
    repos = {
        "quiz_repo": quiz_repo or MagicMock(spec=QuizRepository),
        "question_repo": question_repo or MagicMock(spec=QuestionRepository),
        "progress_repo": progress_repo or MagicMock(spec=ProgressRepository),
        "topic_repo": topic_repo or MagicMock(spec=TopicRepository),
        "subtopic_repo": subtopic_repo or MagicMock(spec=SubtopicRepository),
        "xp_service": xp_service or MagicMock(spec=XPService),
    }
    service = QuizService(**repos)
    return service, repos


# --- set_answer ------------------------------------------------------------


def test_set_answer_happy_path() -> None:
    service, repos = _build_service()
    user = _make_user()
    repos["quiz_repo"].get_attempt_for_user.return_value = _make_attempt()

    service.set_answer(
        attempt_id=99,
        question_id=1,
        payload=QuizAnswerPatchRequest(selected_answer="A"),
        user=user,
    )

    repos["quiz_repo"].set_answer.assert_called_once()
    kwargs = repos["quiz_repo"].set_answer.call_args.kwargs
    assert kwargs["attempt_id"] == 99
    assert kwargs["question_id"] == 1
    assert kwargs["selected_answer"] == "A"


def test_set_answer_403_when_attempt_belongs_to_other_user() -> None:
    service, repos = _build_service()
    user = _make_user()
    repos["quiz_repo"].get_attempt_for_user.return_value = None

    with pytest.raises(HTTPException) as exc_info:
        service.set_answer(
            attempt_id=99,
            question_id=1,
            payload=QuizAnswerPatchRequest(selected_answer="A"),
            user=user,
        )

    assert exc_info.value.status_code == 403


def test_set_answer_409_when_attempt_submitted() -> None:
    service, repos = _build_service()
    user = _make_user()
    repos["quiz_repo"].get_attempt_for_user.return_value = _make_attempt(
        status_value="SUBMITTED"
    )

    with pytest.raises(HTTPException) as exc_info:
        service.set_answer(
            attempt_id=99,
            question_id=1,
            payload=QuizAnswerPatchRequest(selected_answer="A"),
            user=user,
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "attempt_already_submitted"


def test_set_answer_403_when_question_not_on_attempt() -> None:
    service, repos = _build_service()
    user = _make_user()
    repos["quiz_repo"].get_attempt_for_user.return_value = _make_attempt()
    repos["quiz_repo"].set_answer.side_effect = LookupError("missing")

    with pytest.raises(HTTPException) as exc_info:
        service.set_answer(
            attempt_id=99,
            question_id=9999,
            payload=QuizAnswerPatchRequest(selected_answer="A"),
            user=user,
        )

    assert exc_info.value.status_code == 403


# --- submit_attempt --------------------------------------------------------


def _seed_submit_mocks(
    repos: dict[str, MagicMock],
    *,
    attempt: QuizAttempt,
    selected_by_qid: dict[int, str],
    correct_by_qid: dict[int, str],
) -> None:
    """Wire ``submit_attempt``'s reads + writes to a deterministic state."""
    repos["quiz_repo"].get_attempt_for_user.return_value = attempt

    # Pre-grade answer rows: selected_answer per qid, ordinal 1..N.
    answers = []
    for ordinal, (qid, selected) in enumerate(selected_by_qid.items(), start=1):
        row = MagicMock()
        row.question_id = qid
        row.ordinal = ordinal
        row.selected_answer = selected
        row.is_correct = None
        answers.append(row)
    repos["quiz_repo"].list_attempt_answers.return_value = answers

    # Question lookup.
    questions = {
        qid: _make_question(qid, correct=correct_by_qid[qid])
        for qid in selected_by_qid
    }
    repos["question_repo"].get.side_effect = lambda qid: questions.get(qid)

    # ``submit_attempt`` returns the same attempt with status flipped.
    def _submit(_attempt_id, *, score, submitted_at, answer_corrections):
        attempt.status = QuizAttemptStatus.SUBMITTED.value
        attempt.score = score
        attempt.submitted_at = submitted_at
        # Reflect corrections back into the answer rows for the
        # response builder.
        by_qid = {row.question_id: row for row in answers}
        for c in answer_corrections:
            by_qid[c["question_id"]].is_correct = c["is_correct"]
        return attempt

    repos["quiz_repo"].submit_attempt.side_effect = _submit


def test_submit_subtopic_perfect_awards_quiz_perfect_50_xp() -> None:
    service, repos = _build_service()
    user = _make_user()
    attempt = _make_attempt(max_score=2)
    _seed_submit_mocks(
        repos,
        attempt=attempt,
        selected_by_qid={1: "A", 2: "B"},
        correct_by_qid={1: "A", 2: "B"},
    )

    result = service.submit_attempt(attempt_id=99, user=user)

    assert isinstance(result, QuizSubmittedResponse)
    assert result.is_perfect is True
    assert result.awarded_xp == 50
    award_call = repos["xp_service"].award.call_args
    assert award_call.kwargs["source"] == XPSource.QUIZ_PERFECT
    assert award_call.kwargs["amount"] == 50


def test_submit_subtopic_passing_non_perfect_awards_quiz_pass_20_xp() -> None:
    service, repos = _build_service()
    user = _make_user()
    # 5 questions, 4 correct → 80% (passing) but not perfect.
    attempt = _make_attempt(max_score=5)
    _seed_submit_mocks(
        repos,
        attempt=attempt,
        selected_by_qid={1: "A", 2: "A", 3: "A", 4: "A", 5: "B"},
        correct_by_qid={1: "A", 2: "A", 3: "A", 4: "A", 5: "Z"},
    )

    result = service.submit_attempt(attempt_id=99, user=user)

    assert result.is_passing is True
    assert result.is_perfect is False
    assert result.awarded_xp == 20
    award_call = repos["xp_service"].award.call_args
    assert award_call.kwargs["source"] == XPSource.QUIZ_PASS
    assert award_call.kwargs["amount"] == 20


def test_submit_subtopic_failing_awards_no_xp() -> None:
    service, repos = _build_service()
    user = _make_user()
    # 5 questions, 1 correct → 20% — fails.
    attempt = _make_attempt(max_score=5)
    _seed_submit_mocks(
        repos,
        attempt=attempt,
        selected_by_qid={1: "A", 2: "Z", 3: "Z", 4: "Z", 5: "Z"},
        correct_by_qid={1: "A", 2: "Y", 3: "Y", 4: "Y", 5: "Y"},
    )

    result = service.submit_attempt(attempt_id=99, user=user)

    assert result.is_passing is False
    assert result.awarded_xp == 0
    repos["xp_service"].award.assert_not_called()


def test_submit_topic_passing_awards_100_xp_and_marks_topic_complete() -> None:
    service, repos = _build_service()
    user = _make_user()
    attempt = _make_attempt(
        scope_level=LevelScope.TOPIC, scope_id=20, max_score=5
    )
    _seed_submit_mocks(
        repos,
        attempt=attempt,
        selected_by_qid={1: "A", 2: "A", 3: "A", 4: "A", 5: "A"},
        correct_by_qid={1: "A", 2: "A", 3: "A", 4: "A", 5: "A"},
    )

    result = service.submit_attempt(attempt_id=99, user=user)

    assert result.awarded_xp == 100
    award_call = repos["xp_service"].award.call_args
    assert award_call.kwargs["source"] == XPSource.QUIZ_PASS
    assert award_call.kwargs["amount"] == 100
    repos["progress_repo"].mark_topic_complete.assert_called_once()
    args = repos["progress_repo"].mark_topic_complete.call_args.args
    assert args[0] == user.id
    assert args[1] == 20


def test_submit_module_passing_awards_250_xp_and_marks_module_complete() -> None:
    service, repos = _build_service()
    user = _make_user()
    attempt = _make_attempt(
        scope_level=LevelScope.MODULE, scope_id=30, max_score=5
    )
    _seed_submit_mocks(
        repos,
        attempt=attempt,
        selected_by_qid={1: "A", 2: "A", 3: "A", 4: "A", 5: "A"},
        correct_by_qid={1: "A", 2: "A", 3: "A", 4: "A", 5: "A"},
    )

    result = service.submit_attempt(attempt_id=99, user=user)

    assert result.awarded_xp == 250
    award_call = repos["xp_service"].award.call_args
    assert award_call.kwargs["source"] == XPSource.QUIZ_PASS
    assert award_call.kwargs["amount"] == 250
    repos["progress_repo"].mark_module_complete.assert_called_once()


def test_submit_attempt_403_for_other_user() -> None:
    service, repos = _build_service()
    repos["quiz_repo"].get_attempt_for_user.return_value = None

    with pytest.raises(HTTPException) as exc_info:
        service.submit_attempt(attempt_id=99, user=_make_user())

    assert exc_info.value.status_code == 403


def test_submit_attempt_409_when_already_submitted() -> None:
    service, repos = _build_service()
    repos["quiz_repo"].get_attempt_for_user.return_value = _make_attempt(
        status_value="SUBMITTED"
    )

    with pytest.raises(HTTPException) as exc_info:
        service.submit_attempt(attempt_id=99, user=_make_user())

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "attempt_already_submitted"


# --- get_attempt -----------------------------------------------------------


def test_get_attempt_in_progress_returns_in_progress_shape() -> None:
    service, repos = _build_service()
    user = _make_user()
    attempt = _make_attempt(max_score=1)
    repos["quiz_repo"].get_attempt_for_user.return_value = attempt
    answer = MagicMock()
    answer.question_id = 1
    answer.ordinal = 1
    answer.displayed_options = ["A", "B", "C", "D"]
    answer.selected_answer = None
    repos["quiz_repo"].list_attempt_answers.return_value = [answer]
    repos["question_repo"].get.return_value = _make_question(1)

    result = service.get_attempt(attempt_id=99, user=user)

    assert isinstance(result, QuizAttemptInProgressResponse)
    assert result.status == "IN_PROGRESS"
    # Property 17 — schema-level guarantee.
    payload = result.model_dump()
    for q in payload["questions"]:
        assert "correct_answer" not in q
        assert "is_correct" not in q
        assert "explanation" not in q


def test_get_attempt_submitted_returns_submitted_shape() -> None:
    service, repos = _build_service()
    user = _make_user()
    attempt = _make_attempt(
        max_score=1, status_value="SUBMITTED", score=1
    )
    repos["quiz_repo"].get_attempt_for_user.return_value = attempt
    answer = MagicMock()
    answer.question_id = 1
    answer.ordinal = 1
    answer.selected_answer = "A"
    answer.is_correct = True
    repos["quiz_repo"].list_attempt_answers.return_value = [answer]
    repos["question_repo"].get.return_value = _make_question(1)

    result = service.get_attempt(attempt_id=99, user=user)

    assert isinstance(result, QuizSubmittedResponse)
    assert result.status == "SUBMITTED"
    assert result.questions[0].correct_answer == "A"
    assert result.questions[0].is_correct is True


def test_get_attempt_403_for_other_user() -> None:
    service, repos = _build_service()
    repos["quiz_repo"].get_attempt_for_user.return_value = None

    with pytest.raises(HTTPException) as exc_info:
        service.get_attempt(attempt_id=99, user=_make_user())

    assert exc_info.value.status_code == 403
