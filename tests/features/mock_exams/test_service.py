"""Service tests for the mock-exam slice (Task 12.5).

Per ``testing-standards.md`` the service layer is exercised against
mocked repositories. Property-level coverage of timer / nav / weakness
ranking lives in ``test_property.py``; this file focuses on:

- ``start_attempt`` happy / 409 ``mock_exam_in_progress`` / 404
  ``mock_config_not_found``.
- ``get_attempt`` polymorphic shape + Property 30 auto-submit
  (auto-submit BEFORE building the response).
- ``set_answer`` LINEAR_NO_REVISIT lock, FREE_NAV re-PATCH, expired
  timer behaviour.
- ``report_focus_loss`` appends the event without touching the timer.
- ``submit_attempt`` happy paths: passing → 500 XP, failing → 0 XP,
  per-module breakdown shape, weakness ordering.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.features.content.models import (
    Difficulty,
    LevelScope,
    Module,
    Question,
    QuestionType,
)
from app.features.content.repository import (
    ModuleRepository,
    QuestionRepository,
)
from app.features.mock_exams.models import (
    MockExamAttempt,
    MockExamAttemptStatus,
    MockExamConfig,
    MockExamNavPolicy,
    MockExamSubmissionMode,
)
from app.features.mock_exams.repository import MockExamRepository
from app.features.mock_exams.schemas import (
    FocusLossReportRequest,
    MockAnswerPatchRequest,
    MockExamAttemptResponse,
    MockExamStartResponse,
    MockExamSubmittedResponse,
)
from app.features.mock_exams.service import MockExamService
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


def _make_question(qid: int, *, module_id: int = 1, correct: str = "A") -> Question:
    return Question(
        id=qid,
        subtopic_id=1,
        topic_id=1,
        module_id=module_id,
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


def _make_config(
    *,
    total: int = 4,
    weights: dict[str, int] | None = None,
    nav_policy: MockExamNavPolicy = MockExamNavPolicy.LINEAR_NO_REVISIT,
    pass_threshold: float = 0.80,
) -> MockExamConfig:
    return MockExamConfig(
        category=Category.PROFESSIONAL.value,
        total_questions=total,
        weights_json=weights or {"1": total},
        time_limit_minutes=180,
        nav_policy=nav_policy.value,
        pass_threshold=pass_threshold,
    )


def _make_attempt(
    *,
    attempt_id: int = 99,
    user_id: int = 1,
    status_value: str = "IN_PROGRESS",
    max_score: int = 4,
    score: int | None = None,
    nav_policy: MockExamNavPolicy = MockExamNavPolicy.LINEAR_NO_REVISIT,
    started_at: datetime | None = None,
    submitted_at: datetime | None = None,
    submission_mode: str | None = None,
) -> MockExamAttempt:
    started_at = started_at or datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
    return MockExamAttempt(
        id=attempt_id,
        user_id=user_id,
        category=Category.PROFESSIONAL.value,
        status=status_value,
        started_at=started_at,
        submitted_at=submitted_at,
        submission_mode=submission_mode,
        score=score,
        max_score=max_score,
        seed=12345,
        focus_loss_events=[],
        nav_policy=nav_policy.value,
        time_limit_minutes=180,
    )


def _build_service(
    *,
    mock_repo: MagicMock | None = None,
    question_repo: MagicMock | None = None,
    module_repo: MagicMock | None = None,
    xp_service: MagicMock | None = None,
) -> tuple[MockExamService, dict[str, MagicMock]]:
    repos = {
        "mock_repo": mock_repo or MagicMock(spec=MockExamRepository),
        "question_repo": question_repo or MagicMock(spec=QuestionRepository),
        "module_repo": module_repo or MagicMock(spec=ModuleRepository),
        "xp_service": xp_service or MagicMock(spec=XPService),
    }
    service = MockExamService(**repos)
    return service, repos


def _seed_pool(repos: dict[str, MagicMock], count: int) -> list[Question]:
    pool = [_make_question(qid) for qid in range(1, count + 1)]
    repos["question_repo"].list_active_passing_quality_gate.return_value = pool
    return pool


def _seed_create_attempt(
    repos: dict[str, MagicMock], *, attempt_id: int = 99, max_score: int
) -> None:
    def _create_attempt(**kwargs):
        return _make_attempt(
            attempt_id=attempt_id,
            user_id=kwargs["user_id"],
            max_score=max_score,
            nav_policy=kwargs["nav_policy"],
            started_at=kwargs["started_at"],
        )

    repos["mock_repo"].create_attempt.side_effect = _create_attempt


def _seed_list_answers_for_attempt(
    repos: dict[str, MagicMock],
    *,
    selected_by_qid: dict[int, str | None],
    correct_by_qid: dict[int, str],
    is_correct_by_qid: dict[int, bool] | None = None,
    module_by_qid: dict[int, int] | None = None,
) -> list[Question]:
    """Wire the answers list + question lookup for response building."""
    answers = []
    for ordinal, (qid, selected) in enumerate(selected_by_qid.items(), start=1):
        row = MagicMock()
        row.question_id = qid
        row.ordinal = ordinal
        row.displayed_options = ["A", "B", "C", "D"]
        row.selected_answer = selected
        row.is_correct = (
            is_correct_by_qid.get(qid)
            if is_correct_by_qid is not None
            else None
        )
        row.finalized_at = None
        row.answered_at = None
        answers.append(row)
    repos["mock_repo"].list_attempt_answers.return_value = answers

    questions = {
        qid: _make_question(
            qid,
            module_id=(module_by_qid or {}).get(qid, 1),
            correct=correct_by_qid[qid],
        )
        for qid in selected_by_qid
    }
    repos["question_repo"].get.side_effect = lambda qid: questions.get(qid)
    return list(questions.values())


# ===========================================================================
# start_attempt
# ===========================================================================


def test_start_attempt_happy_path_returns_start_response() -> None:
    service, repos = _build_service()
    user = _make_user()

    repos["mock_repo"].get_in_progress_for_user.return_value = None
    repos["mock_repo"].get_config.return_value = _make_config(
        total=4, weights={"1": 4}
    )
    _seed_pool(repos, count=10)
    _seed_create_attempt(repos, max_score=4)
    repos["mock_repo"].add_attempt_questions.return_value = []
    repos["mock_repo"].list_attempt_answers.return_value = []

    result = service.start_attempt(user=user)

    assert isinstance(result, MockExamStartResponse)
    assert result.total_questions == 4
    assert result.time_limit_minutes == 180
    assert result.remaining_seconds == 180 * 60
    assert result.nav_policy == MockExamNavPolicy.LINEAR_NO_REVISIT.value


def test_start_attempt_409_when_in_progress_exists() -> None:
    service, repos = _build_service()
    user = _make_user()
    repos["mock_repo"].get_in_progress_for_user.return_value = _make_attempt()

    with pytest.raises(HTTPException) as exc_info:
        service.start_attempt(user=user)

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "mock_exam_in_progress"
    repos["mock_repo"].create_attempt.assert_not_called()


def test_start_attempt_404_when_no_config() -> None:
    service, repos = _build_service()
    user = _make_user()
    repos["mock_repo"].get_in_progress_for_user.return_value = None
    repos["mock_repo"].get_config.return_value = None

    with pytest.raises(HTTPException) as exc_info:
        service.start_attempt(user=user)

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "mock_config_not_found"


# ===========================================================================
# get_attempt
# ===========================================================================


def test_get_attempt_in_progress_returns_in_progress_response() -> None:
    service, repos = _build_service()
    user = _make_user()
    attempt = _make_attempt(max_score=1)
    repos["mock_repo"].get_attempt_for_user.return_value = attempt
    answer_row = MagicMock()
    answer_row.question_id = 1
    answer_row.ordinal = 1
    answer_row.displayed_options = ["A", "B", "C", "D"]
    answer_row.selected_answer = None
    repos["mock_repo"].list_attempt_answers.return_value = [answer_row]
    repos["question_repo"].get.return_value = _make_question(1)

    now = attempt.started_at + timedelta(minutes=10)
    result = service.get_attempt(attempt_id=99, user=user, now=now)

    assert isinstance(result, MockExamAttemptResponse)
    assert result.status == MockExamAttemptStatus.IN_PROGRESS.value
    assert result.remaining_seconds == 170 * 60


def test_get_attempt_403_for_other_user() -> None:
    service, repos = _build_service()
    repos["mock_repo"].get_attempt_for_user.return_value = None

    with pytest.raises(HTTPException) as exc_info:
        service.get_attempt(attempt_id=99, user=_make_user())

    assert exc_info.value.status_code == 403


def test_get_attempt_auto_submits_when_expired_property_30() -> None:
    """Property 30: timer authority — get_attempt auto-submits BEFORE
    building any other response when the timer has expired."""
    service, repos = _build_service()
    user = _make_user()
    attempt = _make_attempt(max_score=1)
    repos["mock_repo"].get_attempt_for_user.return_value = attempt

    # The grade pass reads list_attempt_answers and question lookups.
    _seed_list_answers_for_attempt(
        repos,
        selected_by_qid={1: None},
        correct_by_qid={1: "A"},
        is_correct_by_qid={1: False},
    )
    repos["mock_repo"].get_config.return_value = _make_config()
    repos["module_repo"].get.return_value = Module(
        id=1,
        category=Category.PROFESSIONAL.value,
        slug="m-1",
        title="Module 1",
        order_index=0,
        is_published=True,
    )

    # Expected attempt after auto-submit.
    submitted = _make_attempt(
        max_score=1,
        score=0,
        status_value=MockExamAttemptStatus.AUTO_SUBMITTED.value,
        submitted_at=attempt.started_at + timedelta(minutes=180),
        submission_mode=MockExamSubmissionMode.AUTO_SUBMIT.value,
    )
    repos["mock_repo"].submit_attempt.return_value = submitted

    now = attempt.started_at + timedelta(minutes=180)
    result = service.get_attempt(attempt_id=99, user=user, now=now)

    assert isinstance(result, MockExamSubmittedResponse)
    assert result.status == MockExamAttemptStatus.AUTO_SUBMITTED.value
    assert result.submission_mode == MockExamSubmissionMode.AUTO_SUBMIT.value
    repos["mock_repo"].submit_attempt.assert_called_once()
    submit_kwargs = repos["mock_repo"].submit_attempt.call_args.kwargs
    assert (
        submit_kwargs["submission_mode"]
        == MockExamSubmissionMode.AUTO_SUBMIT
    )


def test_get_attempt_already_submitted_returns_submitted_response() -> None:
    service, repos = _build_service()
    user = _make_user()
    attempt = _make_attempt(
        status_value=MockExamAttemptStatus.SUBMITTED.value,
        score=1,
        submitted_at=datetime(2025, 1, 1, 13, 0, tzinfo=timezone.utc),
        submission_mode=MockExamSubmissionMode.MANUAL.value,
    )
    repos["mock_repo"].get_attempt_for_user.return_value = attempt
    _seed_list_answers_for_attempt(
        repos,
        selected_by_qid={1: "A"},
        correct_by_qid={1: "A"},
        is_correct_by_qid={1: True},
    )
    repos["mock_repo"].get_config.return_value = _make_config()
    repos["module_repo"].get.return_value = Module(
        id=1,
        category=Category.PROFESSIONAL.value,
        slug="m",
        title="Module One",
        order_index=0,
        is_published=True,
    )

    result = service.get_attempt(attempt_id=99, user=user)

    assert isinstance(result, MockExamSubmittedResponse)
    assert result.status == MockExamAttemptStatus.SUBMITTED.value
    repos["mock_repo"].submit_attempt.assert_not_called()


# ===========================================================================
# set_answer
# ===========================================================================


def test_set_answer_happy_path_linear_no_revisit_stamps_finalized_at() -> None:
    service, repos = _build_service()
    user = _make_user()
    attempt = _make_attempt(nav_policy=MockExamNavPolicy.LINEAR_NO_REVISIT)
    repos["mock_repo"].get_attempt_for_user.return_value = attempt
    existing = MagicMock()
    existing.finalized_at = None
    repos["mock_repo"].get_answer.return_value = existing

    now = attempt.started_at + timedelta(minutes=10)
    service.set_answer(
        attempt_id=99,
        question_id=1,
        payload=MockAnswerPatchRequest(selected_answer="A"),
        user=user,
        now=now,
    )

    repos["mock_repo"].set_answer.assert_called_once()
    kwargs = repos["mock_repo"].set_answer.call_args.kwargs
    assert kwargs["finalized_at"] is not None


def test_set_answer_409_question_finalized_under_linear_no_revisit() -> None:
    """Property 31: second PATCH on same question under LINEAR_NO_REVISIT."""
    service, repos = _build_service()
    user = _make_user()
    attempt = _make_attempt(nav_policy=MockExamNavPolicy.LINEAR_NO_REVISIT)
    repos["mock_repo"].get_attempt_for_user.return_value = attempt
    locked = MagicMock()
    locked.finalized_at = datetime(2025, 1, 1, 12, 5, tzinfo=timezone.utc)
    repos["mock_repo"].get_answer.return_value = locked

    now = attempt.started_at + timedelta(minutes=10)
    with pytest.raises(HTTPException) as exc_info:
        service.set_answer(
            attempt_id=99,
            question_id=1,
            payload=MockAnswerPatchRequest(selected_answer="B"),
            user=user,
            now=now,
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "question_finalized"
    repos["mock_repo"].set_answer.assert_not_called()


def test_set_answer_free_nav_allows_re_patch() -> None:
    """Property 31: under FREE_NAV the same PATCH succeeds twice."""
    service, repos = _build_service()
    user = _make_user()
    attempt = _make_attempt(nav_policy=MockExamNavPolicy.FREE_NAV)
    repos["mock_repo"].get_attempt_for_user.return_value = attempt

    now = attempt.started_at + timedelta(minutes=10)
    service.set_answer(
        attempt_id=99,
        question_id=1,
        payload=MockAnswerPatchRequest(selected_answer="A"),
        user=user,
        now=now,
    )
    service.set_answer(
        attempt_id=99,
        question_id=1,
        payload=MockAnswerPatchRequest(selected_answer="B"),
        user=user,
        now=now,
    )

    assert repos["mock_repo"].set_answer.call_count == 2
    # FREE_NAV path doesn't read get_answer (no lock check).
    repos["mock_repo"].get_answer.assert_not_called()
    # Neither call stamped finalized_at.
    for call in repos["mock_repo"].set_answer.call_args_list:
        assert call.kwargs["finalized_at"] is None


def test_set_answer_auto_submits_when_expired_property_30() -> None:
    """Property 30: timer authority — set_answer auto-submits BEFORE
    accepting the answer when the timer has expired."""
    service, repos = _build_service()
    user = _make_user()
    attempt = _make_attempt(max_score=1)
    repos["mock_repo"].get_attempt_for_user.return_value = attempt
    _seed_list_answers_for_attempt(
        repos,
        selected_by_qid={1: None},
        correct_by_qid={1: "A"},
        is_correct_by_qid={1: False},
    )
    repos["mock_repo"].get_config.return_value = _make_config()
    repos["module_repo"].get.return_value = Module(
        id=1,
        category=Category.PROFESSIONAL.value,
        slug="m-1",
        title="Module 1",
        order_index=0,
        is_published=True,
    )
    submitted = _make_attempt(
        max_score=1,
        score=0,
        status_value=MockExamAttemptStatus.AUTO_SUBMITTED.value,
        submission_mode=MockExamSubmissionMode.AUTO_SUBMIT.value,
        submitted_at=attempt.started_at + timedelta(minutes=180),
    )
    repos["mock_repo"].submit_attempt.return_value = submitted

    now = attempt.started_at + timedelta(minutes=180)
    with pytest.raises(HTTPException) as exc_info:
        service.set_answer(
            attempt_id=99,
            question_id=1,
            payload=MockAnswerPatchRequest(selected_answer="A"),
            user=user,
            now=now,
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "attempt_already_submitted"
    repos["mock_repo"].submit_attempt.assert_called_once()
    submit_kwargs = repos["mock_repo"].submit_attempt.call_args.kwargs
    assert (
        submit_kwargs["submission_mode"]
        == MockExamSubmissionMode.AUTO_SUBMIT
    )
    repos["mock_repo"].set_answer.assert_not_called()


def test_set_answer_409_when_already_submitted() -> None:
    service, repos = _build_service()
    user = _make_user()
    repos["mock_repo"].get_attempt_for_user.return_value = _make_attempt(
        status_value=MockExamAttemptStatus.SUBMITTED.value
    )

    with pytest.raises(HTTPException) as exc_info:
        service.set_answer(
            attempt_id=99,
            question_id=1,
            payload=MockAnswerPatchRequest(selected_answer="A"),
            user=user,
        )

    assert exc_info.value.status_code == 409


def test_set_answer_403_for_other_user() -> None:
    service, repos = _build_service()
    repos["mock_repo"].get_attempt_for_user.return_value = None

    with pytest.raises(HTTPException) as exc_info:
        service.set_answer(
            attempt_id=99,
            question_id=1,
            payload=MockAnswerPatchRequest(selected_answer="A"),
            user=_make_user(),
        )

    assert exc_info.value.status_code == 403


# ===========================================================================
# report_focus_loss
# ===========================================================================


def test_report_focus_loss_appends_event_and_does_not_touch_timer() -> None:
    service, repos = _build_service()
    user = _make_user()
    attempt = _make_attempt()
    repos["mock_repo"].get_attempt_for_user.return_value = attempt

    payload = FocusLossReportRequest(
        kind="blur",
        at=datetime(2025, 1, 1, 12, 1, tzinfo=timezone.utc),
    )
    service.report_focus_loss(
        attempt_id=99, payload=payload, user=user
    )

    repos["mock_repo"].append_focus_loss.assert_called_once()
    # The repo's append_focus_loss is the only mutation; no
    # submit_attempt and no set_answer touched.
    repos["mock_repo"].submit_attempt.assert_not_called()
    repos["mock_repo"].set_answer.assert_not_called()


def test_report_focus_loss_409_when_already_submitted() -> None:
    service, repos = _build_service()
    user = _make_user()
    repos["mock_repo"].get_attempt_for_user.return_value = _make_attempt(
        status_value=MockExamAttemptStatus.SUBMITTED.value
    )

    payload = FocusLossReportRequest(
        kind="blur",
        at=datetime(2025, 1, 1, 12, 1, tzinfo=timezone.utc),
    )
    with pytest.raises(HTTPException) as exc_info:
        service.report_focus_loss(
            attempt_id=99, payload=payload, user=user
        )

    assert exc_info.value.status_code == 409


# ===========================================================================
# submit_attempt
# ===========================================================================


def _wire_submit(
    repos: dict[str, MagicMock],
    *,
    attempt: MockExamAttempt,
    selected_by_qid: dict[int, str | None],
    correct_by_qid: dict[int, str],
    module_by_qid: dict[int, int] | None = None,
) -> None:
    repos["mock_repo"].get_attempt_for_user.return_value = attempt
    answers = []
    for ordinal, (qid, selected) in enumerate(
        selected_by_qid.items(), start=1
    ):
        row = MagicMock()
        row.question_id = qid
        row.ordinal = ordinal
        row.displayed_options = ["A", "B", "C", "D"]
        row.selected_answer = selected
        row.is_correct = None
        row.finalized_at = None
        row.answered_at = None
        answers.append(row)
    repos["mock_repo"].list_attempt_answers.return_value = answers

    questions = {
        qid: _make_question(
            qid,
            module_id=(module_by_qid or {}).get(qid, 1),
            correct=correct_by_qid[qid],
        )
        for qid in selected_by_qid
    }
    repos["question_repo"].get.side_effect = lambda qid: questions.get(qid)

    repos["mock_repo"].get_config.return_value = _make_config()

    def _fake_submit(_attempt_id, *, score, submitted_at, submission_mode, answer_corrections):
        attempt.score = score
        attempt.submitted_at = submitted_at
        attempt.submission_mode = submission_mode.value
        attempt.status = (
            MockExamAttemptStatus.AUTO_SUBMITTED.value
            if submission_mode == MockExamSubmissionMode.AUTO_SUBMIT
            else MockExamAttemptStatus.SUBMITTED.value
        )
        # Mirror is_correct on the answer rows.
        by_qid = {row.question_id: row for row in answers}
        for c in answer_corrections:
            by_qid[c["question_id"]].is_correct = c["is_correct"]
        return attempt

    repos["mock_repo"].submit_attempt.side_effect = _fake_submit

    # Module repo: identity-keyed lookup with a unique title per module.
    module_ids = set((module_by_qid or {}).values()) | {1}
    modules = {
        mid: Module(
            id=mid,
            category=Category.PROFESSIONAL.value,
            slug=f"m-{mid}",
            title=f"Module {mid}",
            order_index=0,
            is_published=True,
        )
        for mid in module_ids
    }
    repos["module_repo"].get.side_effect = lambda mid: modules.get(mid)


def test_submit_passing_awards_500_xp() -> None:
    service, repos = _build_service()
    user = _make_user()
    attempt = _make_attempt(max_score=5)
    _wire_submit(
        repos,
        attempt=attempt,
        selected_by_qid={1: "A", 2: "A", 3: "A", 4: "A", 5: "A"},
        correct_by_qid={1: "A", 2: "A", 3: "A", 4: "A", 5: "A"},
    )

    result = service.submit_attempt(attempt_id=99, user=user)

    assert result.passed is True
    assert result.awarded_xp == 500
    repos["xp_service"].award.assert_called_once()
    award_kwargs = repos["xp_service"].award.call_args.kwargs
    assert award_kwargs["source"] == XPSource.MOCK_PASS
    assert award_kwargs["amount"] == 500


def test_submit_failing_awards_no_xp() -> None:
    service, repos = _build_service()
    user = _make_user()
    attempt = _make_attempt(max_score=5)
    _wire_submit(
        repos,
        attempt=attempt,
        selected_by_qid={1: "A", 2: "Z", 3: "Z", 4: "Z", 5: "Z"},
        correct_by_qid={1: "A", 2: "B", 3: "B", 4: "B", 5: "B"},
    )

    result = service.submit_attempt(attempt_id=99, user=user)

    assert result.passed is False
    assert result.awarded_xp == 0
    repos["xp_service"].award.assert_not_called()


def test_submit_builds_per_module_breakdown() -> None:
    service, repos = _build_service()
    user = _make_user()
    attempt = _make_attempt(max_score=4)
    _wire_submit(
        repos,
        attempt=attempt,
        selected_by_qid={1: "A", 2: "A", 3: "A", 4: "A"},
        correct_by_qid={1: "A", 2: "A", 3: "Z", 4: "Z"},
        module_by_qid={1: 1, 2: 1, 3: 2, 4: 2},
    )

    result = service.submit_attempt(attempt_id=99, user=user)

    by_module = {m.module_id: m for m in result.per_module_breakdown}
    assert by_module[1].score == 2 and by_module[1].max == 2
    assert by_module[2].score == 0 and by_module[2].max == 2
    assert by_module[1].title == "Module 1"
    assert by_module[2].title == "Module 2"


def test_submit_weakness_summary_three_lowest_with_tie_break() -> None:
    """Property 35: weakness_summary length min(3, n), ordered ascending
    by (pct, module_id)."""
    service, repos = _build_service()
    user = _make_user()
    attempt = _make_attempt(max_score=8)
    # Modules: 1 (50%), 2 (50%), 3 (100%), 4 (0%). Weakest 3 by (pct,
    # module_id) = [4 (0%), 1 (50%), 2 (50%)]. Module 3 is excluded.
    _wire_submit(
        repos,
        attempt=attempt,
        selected_by_qid={
            1: "A", 2: "Z",  # mod 1: 1/2
            3: "A", 4: "Z",  # mod 2: 1/2
            5: "A", 6: "A",  # mod 3: 2/2
            7: "Z", 8: "Z",  # mod 4: 0/2
        },
        correct_by_qid={
            1: "A", 2: "A",
            3: "A", 4: "A",
            5: "A", 6: "A",
            7: "A", 8: "A",
        },
        module_by_qid={
            1: 1, 2: 1,
            3: 2, 4: 2,
            5: 3, 6: 3,
            7: 4, 8: 4,
        },
    )

    result = service.submit_attempt(attempt_id=99, user=user)

    weakness_module_ids = [m.module_id for m in result.weakness_summary]
    assert weakness_module_ids == [4, 1, 2]
    # Ordered ascending by (pct, module_id)
    pcts = [m.pct for m in result.weakness_summary]
    assert pcts == sorted(pcts)


def test_submit_weakness_summary_clamps_to_min_three_n_modules() -> None:
    """Spec carve-out — fewer than 3 modules in pool returns what we have."""
    service, repos = _build_service()
    user = _make_user()
    attempt = _make_attempt(max_score=4)
    _wire_submit(
        repos,
        attempt=attempt,
        selected_by_qid={1: "A", 2: "A", 3: "Z", 4: "Z"},
        correct_by_qid={1: "A", 2: "A", 3: "A", 4: "A"},
        module_by_qid={1: 1, 2: 1, 3: 2, 4: 2},
    )

    result = service.submit_attempt(attempt_id=99, user=user)

    assert len(result.weakness_summary) == 2


def test_submit_409_when_already_submitted() -> None:
    service, repos = _build_service()
    user = _make_user()
    repos["mock_repo"].get_attempt_for_user.return_value = _make_attempt(
        status_value=MockExamAttemptStatus.SUBMITTED.value
    )

    with pytest.raises(HTTPException) as exc_info:
        service.submit_attempt(attempt_id=99, user=user)

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "attempt_already_submitted"


def test_submit_403_for_other_user() -> None:
    service, repos = _build_service()
    repos["mock_repo"].get_attempt_for_user.return_value = None

    with pytest.raises(HTTPException) as exc_info:
        service.submit_attempt(attempt_id=99, user=_make_user())

    assert exc_info.value.status_code == 403


# ===========================================================================
# validate_config (Task 12.2)
# ===========================================================================


def test_validate_config_weights_sum_mismatch_raises_400() -> None:
    service, repos = _build_service()

    with pytest.raises(HTTPException) as exc_info:
        service.validate_config(
            {
                "category": Category.PROFESSIONAL.value,
                "total_questions": 50,
                "weights_json": {"1": 25, "2": 20},
            }
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "invalid_mock_config:weights_sum_mismatch"


def test_validate_config_module_id_mismatch_raises_400() -> None:
    service, repos = _build_service()
    repos["module_repo"].get.return_value = None  # module missing

    with pytest.raises(HTTPException) as exc_info:
        service.validate_config(
            {
                "category": Category.PROFESSIONAL.value,
                "total_questions": 50,
                "weights_json": {"99": 50},
            }
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "invalid_mock_config:module_id_mismatch"


def test_validate_config_category_mismatch_raises_400() -> None:
    service, repos = _build_service()
    repos["module_repo"].get.return_value = Module(
        id=1,
        category=Category.SUB_PROFESSIONAL.value,  # mismatch
        slug="m",
        title="M",
        order_index=0,
        is_published=True,
    )

    with pytest.raises(HTTPException) as exc_info:
        service.validate_config(
            {
                "category": Category.PROFESSIONAL.value,
                "total_questions": 50,
                "weights_json": {"1": 50},
            }
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "invalid_mock_config:module_id_mismatch"


def test_validate_config_happy_path_does_not_raise() -> None:
    service, repos = _build_service()
    repos["module_repo"].get.return_value = Module(
        id=1,
        category=Category.PROFESSIONAL.value,
        slug="m",
        title="M",
        order_index=0,
        is_published=True,
    )

    # Should not raise.
    service.validate_config(
        {
            "category": Category.PROFESSIONAL.value,
            "total_questions": 50,
            "weights_json": {"1": 50},
        }
    )
