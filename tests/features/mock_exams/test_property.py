"""Property-based tests for the mock-exam slice (Task 12.6).

Seven correctness properties from the design's catalog land here:

- **Property 15 (mock branch)** (Req 10.1, 10.2): per-module count
  exactly equals ``weights_json[module_id]``; total equals
  ``total_questions``.
- **Property 17** (Req 10.4): in-progress response shape never
  carries ``correct_answer`` / ``is_correct`` / ``explanation``.
- **Property 29** (Req 19.1): with an IN_PROGRESS mock attempt,
  ``/v1/subtopics/{id}/quiz-attempts`` returns 409 ``exam_in_progress``.
- **Property 30** (Req 10.3, 14.3, 19.3): timer authority — set_answer
  on an expired attempt auto-submits BEFORE any other side effect;
  attempt status is AUTO_SUBMITTED with submission_mode=AUTO_SUBMIT.
- **Property 31** (Req 19.4): under LINEAR_NO_REVISIT a second PATCH
  on the same question returns 409; under FREE_NAV the same PATCH
  succeeds.
- **Property 35** (Req 10.5): weakness_summary length min(3,
  n_modules), ordered ascending by (pct, module_id).
- **Property 36** (Req 10.8): at-most-one IN_PROGRESS — a second
  attempt creation for the same user surfaces 409.

Hypothesis settings: ``max_examples=20`` per the task spec; deadline
disabled because some examples touch the DB.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from hypothesis import HealthCheck, given, settings, strategies as st
from sqlalchemy.exc import IntegrityError

from app.common.deps import get_current_user, require_no_active_mock
from app.common.middlewares.auth import AuthMiddleware
from app.common.middlewares.error_handler import register_exception_handlers
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
from app.features.mock_exams.algorithms.category_weighted_assembly import (
    assemble_mock_exam,
)
from app.features.mock_exams.models import (
    MockExamAttempt,
    MockExamAttemptStatus,
    MockExamNavPolicy,
    MockExamSubmissionMode,
)
from app.features.mock_exams.repository import MockExamRepository
from app.features.mock_exams.schemas import (
    MockAnswerPatchRequest,
    MockExamAttemptResponse,
    MockExamStartResponse,
    MockExamSubmittedResponse,
    ModuleScoreBreakdown,
    QuizAttemptInProgressQuestion,
)
from app.features.mock_exams.service import MockExamService
from app.features.quizzes.router import router as quiz_router
from app.features.users.models import (
    AccountState,
    Category,
    Role,
    User,
)
from app.features.xp.service import XPService
from app.infrastructure.database.session import get_db


_PBT_SETTINGS = dict(
    max_examples=20,
    deadline=None,
    suppress_health_check=[
        HealthCheck.too_slow,
        HealthCheck.function_scoped_fixture,
    ],
)


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


def _make_question(qid: int, *, module_id: int = 1) -> Question:
    return Question(
        id=qid,
        subtopic_id=1,
        topic_id=1,
        module_id=module_id,
        category=Category.PROFESSIONAL.value,
        level_scope=LevelScope.SUBTOPIC.value,
        stem=f"Q{qid}?",
        options=["A", "B", "C", "D"],
        correct_answer="A",
        explanation=f"exp{qid}",
        difficulty=Difficulty.EASY.value,
        qtype=QuestionType.MULTIPLE_CHOICE.value,
        is_active=True,
    )


def _make_attempt(
    *,
    attempt_id: int = 99,
    user_id: int = 1,
    nav_policy: MockExamNavPolicy = MockExamNavPolicy.LINEAR_NO_REVISIT,
    status_value: str = "IN_PROGRESS",
    started_at: datetime | None = None,
    score: int | None = None,
    submitted_at: datetime | None = None,
    submission_mode: str | None = None,
    max_score: int = 4,
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


# ---------------------------------------------------------------------------
# Property 15 (mock branch) — Question-count exactness
# ---------------------------------------------------------------------------
#
# Validates: Requirements 10.1, 10.2


@given(
    weights=st.lists(
        st.tuples(
            st.integers(min_value=1, max_value=10),  # module_id
            st.integers(min_value=1, max_value=10),  # count
        ),
        min_size=1,
        max_size=5,
        unique_by=lambda t: t[0],
    ),
    pool_excess=st.integers(min_value=0, max_value=10),
)
@settings(**_PBT_SETTINGS)
def test_property_15_mock_branch_question_count_exactness(
    weights: list[tuple[int, int]], pool_excess: int
) -> None:
    """Property 15 (mock branch) — total = sum(weights), per-module
    counts = weights[module_id]."""
    weights_dict = {str(mid): count for mid, count in weights}
    pools_by_module: dict[int, list[Question]] = {
        mid: [
            _make_question(mid * 1000 + i, module_id=mid)
            for i in range(1, count + pool_excess + 1)
        ]
        for mid, count in weights
    }

    chosen, seed = assemble_mock_exam(
        weights=weights_dict, pools_by_module=pools_by_module
    )

    # Total count matches sum(weights).
    assert len(chosen) == sum(count for _, count in weights)
    # Per-module count matches weights[module_id].
    by_module: dict[int, int] = {}
    for q in chosen:
        by_module[q.module_id] = by_module.get(q.module_id, 0) + 1
    expected = {mid: count for mid, count in weights}
    assert by_module == expected
    # Seed within range.
    assert 0 <= seed < 2**64


# ---------------------------------------------------------------------------
# Property 17 — Mid-attempt non-disclosure
# ---------------------------------------------------------------------------
#
# Validates: Requirements 10.4


_FORBIDDEN_FIELDS = frozenset(
    {"correct_answer", "is_correct", "explanation"}
)


def _walk_for_forbidden(node: object) -> set[str]:
    """Recursively walk a Pydantic-dumped payload and return forbidden fields."""
    found: set[str] = set()
    if isinstance(node, dict):
        for key, value in node.items():
            if key in _FORBIDDEN_FIELDS:
                found.add(key)
            found |= _walk_for_forbidden(value)
    elif isinstance(node, list):
        for item in node:
            found |= _walk_for_forbidden(item)
    return found


def test_property_17_in_progress_question_schema_excludes_correctness() -> None:
    """Schema-level guarantee — :class:`QuizAttemptInProgressQuestion`
    has no correctness fields. The mock-exam in-progress / start
    responses use this same shape, so the wire payload cannot leak
    correctness regardless of how the service is called."""
    fields = set(QuizAttemptInProgressQuestion.model_fields.keys())
    assert _FORBIDDEN_FIELDS & fields == set()


def test_property_17_start_and_attempt_response_schemas_exclude_correctness() -> None:
    """Top-level mock-exam in-progress response shapes also clean."""
    start_fields = set(MockExamStartResponse.model_fields.keys())
    in_progress_fields = set(MockExamAttemptResponse.model_fields.keys())
    assert _FORBIDDEN_FIELDS & start_fields == set()
    assert _FORBIDDEN_FIELDS & in_progress_fields == set()


# ---------------------------------------------------------------------------
# Property 29 — Mock-exam in-progress guard
# ---------------------------------------------------------------------------
#
# Validates: Requirements 19.1
#
# Strategy: Mount the quizzes router with a real ``db_session`` and
# seed an IN_PROGRESS mock attempt. POST to the subtopic-quiz route
# should return 409 ``exam_in_progress`` from
# :func:`require_no_active_mock`. Without an attempt, the same call
# proceeds (hits the dependency stack normally).


@given(has_in_progress_mock=st.booleans())
@settings(**_PBT_SETTINGS)
def test_property_29_mock_exam_in_progress_guard(
    has_in_progress_mock: bool, db_session
) -> None:
    """Property 29: with an IN_PROGRESS mock, the quiz-start route
    returns 409 ``exam_in_progress``; without it, the route proceeds
    (no IntegrityError)."""
    from app.features.users.models import Category as Cat
    from app.features.users.repository import UserRepository
    from app.features.users.schemas import UserCreate

    user_repo = UserRepository(db=db_session)
    user = user_repo.create(
        UserCreate(
            email=f"alice-prop29-{has_in_progress_mock}@example.com",
            display_name="Alice",
            age=25,
            category=Cat.PROFESSIONAL.value,
            password="Strong1Pass!",
        ),
        password_hash="bcrypt$fake$hash",
    )

    if has_in_progress_mock:
        attempt = MockExamAttempt(
            user_id=user.id,
            category=Cat.PROFESSIONAL.value,
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

    fastapi_app = FastAPI()
    fastapi_app.add_middleware(AuthMiddleware)
    register_exception_handlers(fastapi_app)
    fastapi_app.include_router(quiz_router)
    fastapi_app.dependency_overrides[get_db] = lambda: db_session
    fastapi_app.dependency_overrides[get_current_user] = lambda: user
    client = TestClient(fastapi_app)

    response = client.post("/v1/subtopics/9999/quiz-attempts")

    if has_in_progress_mock:
        assert response.status_code == 409
        assert response.json()["error"]["message"] == "exam_in_progress"
    else:
        # No mock attempt — the route proceeds. The 9999 subtopic
        # doesn't exist so the service raises something else (403 or
        # 409 on insufficient pool); either way the response is NOT
        # 409 exam_in_progress.
        body = response.json()
        if response.status_code == 409:
            assert body["error"]["message"] != "exam_in_progress"


# ---------------------------------------------------------------------------
# Property 30 — Mock-exam timer authority
# ---------------------------------------------------------------------------
#
# Validates: Requirements 10.3, 14.3, 19.3
#
# Strategy: drive the service directly with mocked repos, manipulate
# ``started_at`` so the attempt has effectively expired, then call
# ``set_answer``. The result must be 409 ``attempt_already_submitted``,
# the persisted row must transition to AUTO_SUBMITTED with
# submission_mode=AUTO_SUBMIT, and no answer write happens.


@given(elapsed_minutes_past_limit=st.integers(min_value=0, max_value=120))
@settings(**_PBT_SETTINGS)
def test_property_30_timer_authority_auto_submits_before_side_effects(
    elapsed_minutes_past_limit: int,
) -> None:
    """Property 30: set_answer on an expired attempt auto-submits before
    any other side effect, and the attempt becomes AUTO_SUBMITTED with
    submission_mode=AUTO_SUBMIT."""
    mock_repo = MagicMock(spec=MockExamRepository)
    question_repo = MagicMock(spec=QuestionRepository)
    module_repo = MagicMock(spec=ModuleRepository)
    xp_service = MagicMock(spec=XPService)
    service = MockExamService(
        mock_repo=mock_repo,
        question_repo=question_repo,
        module_repo=module_repo,
        xp_service=xp_service,
    )

    started_at = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
    attempt = _make_attempt(started_at=started_at, max_score=1)
    mock_repo.get_attempt_for_user.return_value = attempt

    # Wire the grader/response builder reads.
    answer_row = MagicMock()
    answer_row.question_id = 1
    answer_row.ordinal = 1
    answer_row.displayed_options = ["A", "B", "C", "D"]
    answer_row.selected_answer = None
    answer_row.is_correct = None
    answer_row.finalized_at = None
    answer_row.answered_at = None
    mock_repo.list_attempt_answers.return_value = [answer_row]
    question_repo.get.return_value = _make_question(1)
    mock_repo.get_config.return_value = None

    submitted = _make_attempt(
        max_score=1,
        score=0,
        status_value=MockExamAttemptStatus.AUTO_SUBMITTED.value,
        submission_mode=MockExamSubmissionMode.AUTO_SUBMIT.value,
        submitted_at=started_at + timedelta(minutes=180),
    )
    mock_repo.submit_attempt.return_value = submitted
    module_repo.get.return_value = Module(
        id=1,
        category=Category.PROFESSIONAL.value,
        slug="m-1",
        title="Module 1",
        order_index=0,
        is_published=True,
    )

    now = started_at + timedelta(minutes=180 + elapsed_minutes_past_limit)

    user = _make_user()
    with pytest.raises(HTTPException) as exc_info:
        service.set_answer(
            attempt_id=99,
            question_id=1,
            payload=MockAnswerPatchRequest(selected_answer="A"),
            user=user,
            now=now,
        )

    # 409 attempt_already_submitted on the wire.
    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "attempt_already_submitted"

    # submit_attempt was invoked with AUTO_SUBMIT before any answer write.
    mock_repo.submit_attempt.assert_called_once()
    submit_kwargs = mock_repo.submit_attempt.call_args.kwargs
    assert submit_kwargs["submission_mode"] == MockExamSubmissionMode.AUTO_SUBMIT
    mock_repo.set_answer.assert_not_called()


# ---------------------------------------------------------------------------
# Property 31 — Linear-no-revisit navigation
# ---------------------------------------------------------------------------
#
# Validates: Requirements 19.4
#
# Strategy: enumerate (nav_policy, second_patch_finalized). Under
# LINEAR_NO_REVISIT with the row already finalized, the second PATCH
# must 409 question_finalized. Under FREE_NAV the PATCH must succeed.


@given(nav_policy=st.sampled_from(list(MockExamNavPolicy)))
@settings(**_PBT_SETTINGS)
def test_property_31_linear_no_revisit_navigation(
    nav_policy: MockExamNavPolicy,
) -> None:
    """Property 31: LINEAR_NO_REVISIT 409s on second PATCH; FREE_NAV
    accepts."""
    mock_repo = MagicMock(spec=MockExamRepository)
    question_repo = MagicMock(spec=QuestionRepository)
    module_repo = MagicMock(spec=ModuleRepository)
    xp_service = MagicMock(spec=XPService)
    service = MockExamService(
        mock_repo=mock_repo,
        question_repo=question_repo,
        module_repo=module_repo,
        xp_service=xp_service,
    )

    started_at = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
    now = started_at + timedelta(minutes=10)
    attempt = _make_attempt(nav_policy=nav_policy, started_at=started_at)
    mock_repo.get_attempt_for_user.return_value = attempt

    if nav_policy == MockExamNavPolicy.LINEAR_NO_REVISIT:
        # Row already finalized — PATCH must 409.
        locked = MagicMock()
        locked.finalized_at = started_at + timedelta(minutes=5)
        mock_repo.get_answer.return_value = locked

        with pytest.raises(HTTPException) as exc_info:
            service.set_answer(
                attempt_id=99,
                question_id=1,
                payload=MockAnswerPatchRequest(selected_answer="B"),
                user=_make_user(),
                now=now,
            )
        assert exc_info.value.status_code == 409
        assert exc_info.value.detail == "question_finalized"
        mock_repo.set_answer.assert_not_called()
    else:
        # FREE_NAV — PATCH must succeed.
        service.set_answer(
            attempt_id=99,
            question_id=1,
            payload=MockAnswerPatchRequest(selected_answer="B"),
            user=_make_user(),
            now=now,
        )
        mock_repo.set_answer.assert_called_once()


# ---------------------------------------------------------------------------
# Property 35 — Mock-exam result completeness and weakness ranking
# ---------------------------------------------------------------------------
#
# Validates: Requirements 10.5, 10.7
#
# Strategy: build a synthetic submitted attempt with deterministic
# per-module is_correct flags, run ``_build_submitted_response``
# through ``submit_attempt``, and check (a) length of weakness_summary,
# (b) ordering, (c) all required fields populated.


@given(
    n_modules=st.integers(min_value=1, max_value=6),
)
@settings(**_PBT_SETTINGS)
def test_property_35_weakness_summary_length_and_ordering(
    n_modules: int,
) -> None:
    """Property 35: weakness_summary length min(3, n_modules), ordered
    ascending by (pct, module_id)."""
    mock_repo = MagicMock(spec=MockExamRepository)
    question_repo = MagicMock(spec=QuestionRepository)
    module_repo = MagicMock(spec=ModuleRepository)
    xp_service = MagicMock(spec=XPService)
    service = MockExamService(
        mock_repo=mock_repo,
        question_repo=question_repo,
        module_repo=module_repo,
        xp_service=xp_service,
    )

    # Synthetic: 2 questions per module, one correct, one wrong → 50%
    # for every module. Tie-break by module_id ascending wins.
    questions_per_module = 2
    total = n_modules * questions_per_module

    answers = []
    questions: dict[int, Question] = {}
    for i in range(total):
        qid = i + 1
        module_id = (i // questions_per_module) + 1
        correct = i % questions_per_module == 0
        row = MagicMock()
        row.question_id = qid
        row.ordinal = qid
        row.selected_answer = "A" if correct else "Z"
        row.is_correct = correct
        row.displayed_options = ["A", "B", "C", "D"]
        row.finalized_at = None
        row.answered_at = None
        answers.append(row)
        questions[qid] = _make_question(qid, module_id=module_id)

    attempt = _make_attempt(max_score=total)
    mock_repo.get_attempt_for_user.return_value = attempt
    mock_repo.list_attempt_answers.return_value = answers
    question_repo.get.side_effect = lambda qid: questions.get(qid)

    def _fake_submit(
        _attempt_id, *, score, submitted_at, submission_mode, answer_corrections
    ):
        attempt.score = score
        attempt.submitted_at = submitted_at
        attempt.submission_mode = submission_mode.value
        attempt.status = MockExamAttemptStatus.SUBMITTED.value
        return attempt

    mock_repo.submit_attempt.side_effect = _fake_submit
    mock_repo.get_config.return_value = None
    module_repo.get.side_effect = lambda mid: Module(
        id=mid,
        category=Category.PROFESSIONAL.value,
        slug=f"m-{mid}",
        title=f"Module {mid}",
        order_index=0,
        is_published=True,
    )

    result = service.submit_attempt(attempt_id=99, user=_make_user())

    assert isinstance(result, MockExamSubmittedResponse)
    # Length is min(3, n_modules).
    assert len(result.weakness_summary) == min(3, n_modules)
    # Ordering is ascending by (pct, module_id).
    keys = [(m.pct, m.module_id) for m in result.weakness_summary]
    assert keys == sorted(keys)
    # All required result fields present (Property 35 — completeness).
    assert isinstance(result.score, int)
    assert isinstance(result.max_score, int)
    assert isinstance(result.percentage, float)
    assert isinstance(result.passed, bool)
    assert all(
        isinstance(m, ModuleScoreBreakdown) for m in result.per_module_breakdown
    )


# ---------------------------------------------------------------------------
# Property 36 — At-most-one in-progress mock attempt per user
# ---------------------------------------------------------------------------
#
# Validates: Requirements 10.8
#
# Strategy: drive the service against a MockExamRepository that
# raises IntegrityError on the second create_attempt call (simulating
# the partial unique index). The service must surface 409
# ``mock_exam_in_progress`` either via the pre-check or via the
# IntegrityError translation path.


@given(
    pre_check_finds_existing=st.booleans(),
)
@settings(**_PBT_SETTINGS)
def test_property_36_at_most_one_in_progress(
    pre_check_finds_existing: bool,
) -> None:
    """Property 36: a second start (whether caught at the pre-check or
    via the partial unique index) surfaces 409 mock_exam_in_progress."""
    mock_repo = MagicMock(spec=MockExamRepository)
    question_repo = MagicMock(spec=QuestionRepository)
    module_repo = MagicMock(spec=ModuleRepository)
    xp_service = MagicMock(spec=XPService)
    service = MockExamService(
        mock_repo=mock_repo,
        question_repo=question_repo,
        module_repo=module_repo,
        xp_service=xp_service,
    )

    if pre_check_finds_existing:
        # Pre-check finds an existing IN_PROGRESS attempt.
        mock_repo.get_in_progress_for_user.return_value = _make_attempt()
    else:
        # Pre-check sees nothing; the DB index raises on insert
        # (simulating a concurrent insert that slipped past the check).
        mock_repo.get_in_progress_for_user.return_value = None
        from app.features.mock_exams.models import MockExamConfig

        mock_repo.get_config.return_value = MockExamConfig(
            category=Category.PROFESSIONAL.value,
            total_questions=1,
            weights_json={"1": 1},
            time_limit_minutes=180,
            nav_policy=MockExamNavPolicy.LINEAR_NO_REVISIT.value,
            pass_threshold=0.80,
        )
        question_repo.list_active_passing_quality_gate.return_value = [
            _make_question(1)
        ]
        mock_repo.create_attempt.side_effect = IntegrityError(
            "INSERT", {}, Exception("uq_mock_exam_in_progress")
        )

    user = _make_user()
    with pytest.raises(HTTPException) as exc_info:
        service.start_attempt(user=user)

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "mock_exam_in_progress"


# ---------------------------------------------------------------------------
# Property 15 (Phase 2 mock branch) — Question-count exactness at 165q (Task 13.3)
# ---------------------------------------------------------------------------
#
# Validates: Requirements 10.1, 10.2
#
# Same property family as the MVP branch above, parametrized at the
# Phase 2 mock-exam scale (count(MOCK)=165). The scale matters because
# the 165-question pool has to be assembled from per-module pools that
# each meet their weight, the cross-module shuffle has to land all 165
# items, and the total / per-module counts have to land exactly. The
# MVP test (max sum 50) doesn't exercise the 165 lower-bound from
# Req 10.1, 10.2 directly.
#
# ``max_examples=10`` keeps the test from blowing wall-clock budget
# (each example builds 165+ Question objects and runs the assembler
# end-to-end). The count is deliberately small for this branch only —
# the smaller-scale MVP property covers the corner-case search space.


@settings(max_examples=10, deadline=None)
@given(seed_offset=st.integers(min_value=0, max_value=999))
def test_property_15_mock_branch_question_count_exactness_phase2_165q(
    seed_offset: int,
) -> None:
    """Property 15 (Phase 2 mock branch) — at count=165, the assembled
    list has exactly 165 items, per-module counts equal the configured
    weights, and every chosen question is drawn from its module's pool."""
    # Deterministic Phase 2-shaped weights summing to 165.
    # ``seed_offset`` only varies the per-question ids so identical
    # generated examples don't share Hypothesis cache lines; the
    # weights themselves stay fixed because Property 15 is about
    # *exactness against* a config, not about the config's distribution.
    weights = {1: 50, 2: 60, 3: 55}
    weights_dict = {str(mid): count for mid, count in weights.items()}

    # Each pool is sized exactly to the weight (no excess) so the
    # assembler is forced to draw every available question from each
    # pool. The assembler must still respect per-module counts despite
    # the cross-module shuffle.
    pools_by_module: dict[int, list[Question]] = {
        mid: [
            _make_question(mid * 100_000 + seed_offset * 1000 + i, module_id=mid)
            for i in range(1, count + 1)
        ]
        for mid, count in weights.items()
    }
    # Build per-module id sets for membership checks below.
    pool_ids_by_module: dict[int, set[int]] = {
        mid: {q.id for q in pool}
        for mid, pool in pools_by_module.items()
    }

    chosen, audit_seed = assemble_mock_exam(
        weights=weights_dict, pools_by_module=pools_by_module
    )

    # Exact total of 165 (Req 10.1, 10.2).
    assert len(chosen) == 165
    assert sum(weights.values()) == 165

    # Per-module count equals the configured weight.
    by_module: dict[int, int] = {}
    for q in chosen:
        by_module[q.module_id] = by_module.get(q.module_id, 0) + 1
    assert by_module == weights

    # Every chosen question came from its module's pool (id membership).
    for q in chosen:
        assert q.id in pool_ids_by_module[q.module_id]

    # Audit seed within the 64-bit range.
    assert 0 <= audit_seed < 2**64
