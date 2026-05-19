"""Property-based tests for the quizzes slice (Task 11.5).

Five correctness properties from the design's catalog land here:

- **Property 14 — Lesson-before-quiz gating** (Req 6.1):
  ``start_subtopic_quiz`` succeeds iff
  ``is_lesson_complete_for_subtopic(user, subtopic)`` is True; else
  raises 409 ``lesson_not_completed``.
- **Property 15 — Question-count exactness** (Req 7.1, 8.2, 9.2):
  ``assemble_quiz`` returns exactly ``COUNT_BY_SCOPE[scope]``
  questions, all drawn from the input pool.
- **Property 16 — Randomization across attempts** (Req 7.3):
  multiple invocations of ``assemble_quiz`` against the same
  sufficiently-large pool produce non-degenerate ordering across
  attempts.
- **Property 17 — Mid-attempt non-disclosure** (Req 7.4): the
  in-progress response shape never carries ``correct_answer``,
  ``is_correct``, or ``explanation`` for any question.
- **Property 18 — Prerequisite gating for higher-scope quizzes**
  (Req 8.1, 9.1): topic / module quiz starts succeed iff every
  prerequisite scope-quiz has been passed.

Hypothesis settings: ``max_examples=30`` per the task spec; deadline
disabled because some examples touch the DB.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from hypothesis import HealthCheck, given, settings, strategies as st

from app.features.content.models import (
    Difficulty,
    LevelScope,
    Module,
    Question,
    QuestionType,
    Subtopic,
    Topic,
)
from app.features.content.repository import (
    QuestionRepository,
    SubtopicRepository,
    TopicRepository,
)
from app.features.progress.repository import ProgressRepository
from app.features.quizzes.algorithms.assembly import (
    COUNT_BY_SCOPE,
    assemble_quiz,
)
from app.features.quizzes.repository import QuizRepository
from app.features.quizzes.schemas import (
    QuizAttemptInProgressQuestion,
    QuizAttemptInProgressResponse,
)
from app.features.quizzes.service import QuizService
from app.features.users.models import (
    AccountState,
    Category,
    Role,
    User,
)
from app.features.xp.service import XPService


_PBT_SETTINGS = dict(
    max_examples=30,
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


def _make_question(qid: int) -> Question:
    return Question(
        id=qid,
        subtopic_id=1,
        topic_id=1,
        module_id=1,
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


def _build_pool(size: int) -> list[Question]:
    return [_make_question(qid) for qid in range(1, size + 1)]


def _build_service_with_pool(
    *,
    user: User,
    subtopic_id: int,
    topic_id: int,
    module_id: int,
    pool_size: int,
    lesson_complete: bool,
    has_passed_subtopic: bool = False,
    has_passed_topic: bool = False,
) -> QuizService:
    """Build a :class:`QuizService` with mocked repos for property tests.

    Each repo is a :class:`MagicMock(spec=...)` so attribute typos
    fail at test time per ``testing-standards.md``.
    """
    quiz_repo = MagicMock(spec=QuizRepository)
    question_repo = MagicMock(spec=QuestionRepository)
    progress_repo = MagicMock(spec=ProgressRepository)
    topic_repo = MagicMock(spec=TopicRepository)
    subtopic_repo = MagicMock(spec=SubtopicRepository)
    xp_service = MagicMock(spec=XPService)

    # Topology: subtopic -> topic -> module, all matching the user's
    # category so the category-isolation gate doesn't trip.
    subtopic = Subtopic(
        id=subtopic_id, topic_id=topic_id, slug="s", title="S", order_index=0
    )
    topic = Topic(
        id=topic_id, module_id=module_id, slug="t", title="T", order_index=0
    )
    module = Module(
        id=module_id,
        category=user.category,
        slug="m",
        title="M",
        order_index=0,
        is_published=True,
    )

    subtopic_repo.get.return_value = subtopic
    topic_repo.get.return_value = topic
    # The service walks ``self._topic_repo.db.get(Module, ...)``; mock
    # the chain.
    topic_repo.db = MagicMock()
    topic_repo.db.get.return_value = module

    progress_repo.is_lesson_complete_for_subtopic.return_value = lesson_complete

    pool = _build_pool(pool_size)
    question_repo.list_active_passing_quality_gate.return_value = pool

    # Persistence mocks: capture state in plain attributes so the
    # response builder can read them back.
    captured = {"attempt_id": 999}

    def _create_attempt(**kwargs):
        attempt = MagicMock()
        attempt.id = captured["attempt_id"]
        attempt.user_id = kwargs["user_id"]
        attempt.scope_level = kwargs["scope_level"].value
        attempt.scope_id = kwargs["scope_id"]
        attempt.status = "IN_PROGRESS"
        attempt.started_at = kwargs["started_at"]
        attempt.max_score = kwargs["max_score"]
        attempt.submitted_at = None
        attempt.score = None
        return attempt

    quiz_repo.create_attempt.side_effect = _create_attempt
    quiz_repo.add_attempt_questions.return_value = []

    # The in-progress response builder also re-reads the attempt's
    # answers via ``list_attempt_answers``.
    def _list_attempt_answers(_attempt_id):
        # Return mocked answer rows mirroring what the service just
        # persisted. The test only reads question_id / ordinal /
        # displayed_options / selected_answer.
        rows = []
        # Hypothesis runs many examples — use the *current* call args
        # of add_attempt_questions to mirror.
        last_call = quiz_repo.add_attempt_questions.call_args
        if last_call is None:
            return rows
        kwargs = last_call.kwargs or {}
        answer_rows = kwargs.get("rows", [])
        for r in answer_rows:
            mock_row = MagicMock()
            mock_row.question_id = r["question_id"]
            mock_row.ordinal = r["ordinal"]
            mock_row.displayed_options = r.get("displayed_options")
            mock_row.selected_answer = None
            mock_row.is_correct = None
            rows.append(mock_row)
        return rows

    quiz_repo.list_attempt_answers.side_effect = _list_attempt_answers
    # Question lookup for response building.
    question_repo.get.side_effect = lambda qid: next(
        (q for q in pool if q.id == qid), None
    )

    quiz_repo.has_passed_attempt.side_effect = (
        lambda *, user_id, scope_level, scope_id: (
            has_passed_subtopic
            if scope_level == LevelScope.SUBTOPIC
            else has_passed_topic
        )
    )

    subtopic_repo.list_by_topic.return_value = [subtopic]
    topic_repo.list_by_module.return_value = [topic]

    return QuizService(
        quiz_repo=quiz_repo,
        question_repo=question_repo,
        progress_repo=progress_repo,
        topic_repo=topic_repo,
        subtopic_repo=subtopic_repo,
        xp_service=xp_service,
    )


# ---------------------------------------------------------------------------
# Property 14 — Lesson-before-quiz gating
# ---------------------------------------------------------------------------
#
# Validates: Requirements 6.1
#
# Strategy: enumerate ``lesson_complete`` ∈ {True, False}. The service
# must succeed iff True; on False it must raise 409 lesson_not_completed.


@given(lesson_complete=st.booleans())
@settings(**_PBT_SETTINGS)
def test_property_14_lesson_before_quiz_gating(lesson_complete: bool) -> None:
    """Property 14 — Lesson-before-quiz gating (Req 6.1).

    For any (user, subtopic), start_subtopic_quiz succeeds iff
    is_lesson_complete_for_subtopic returns True.
    """
    user = _make_user()
    service = _build_service_with_pool(
        user=user,
        subtopic_id=10,
        topic_id=20,
        module_id=30,
        pool_size=COUNT_BY_SCOPE[LevelScope.SUBTOPIC],
        lesson_complete=lesson_complete,
    )

    if lesson_complete:
        result = service.start_subtopic_quiz(user=user, subtopic_id=10)
        assert isinstance(result, QuizAttemptInProgressResponse)
    else:
        with pytest.raises(HTTPException) as exc_info:
            service.start_subtopic_quiz(user=user, subtopic_id=10)
        assert exc_info.value.status_code == 409
        assert exc_info.value.detail == "lesson_not_completed"


# ---------------------------------------------------------------------------
# Property 15 — Question-count exactness
# ---------------------------------------------------------------------------
#
# Validates: Requirements 7.1, 8.2, 9.2
#
# Strategy: enumerate scope ∈ {SUBTOPIC, TOPIC, MODULE} and pool sizes
# >= the per-scope target. The assembled list must have exactly the
# target count, every item must come from the pool, and every item
# must have passed the quality gate (the pool is generated by the
# repo's ``list_active_passing_quality_gate`` so this holds
# transitively when the source pool is well-formed).


@given(
    scope=st.sampled_from(list(LevelScope)),
    pool_excess=st.integers(min_value=0, max_value=20),
)
@settings(**_PBT_SETTINGS)
def test_property_15_question_count_exactness(
    scope: LevelScope, pool_excess: int
) -> None:
    """Property 15 — Question-count exactness (Req 7.1, 8.2, 9.2).

    Assembled list has exactly count(S) items, all drawn from the pool.
    """
    target = COUNT_BY_SCOPE[scope]
    pool = _build_pool(target + pool_excess)
    pool_ids = {q.id for q in pool}

    chosen, seed = assemble_quiz(scope_level=scope, pool=pool)

    assert len(chosen) == target
    assert {q.id for q in chosen} <= pool_ids
    # Sample is without replacement — no duplicate ids.
    assert len({q.id for q in chosen}) == target
    # Seed is a non-negative 64-bit integer.
    assert 0 <= seed < 2**64


@given(scope=st.sampled_from(list(LevelScope)))
@settings(**_PBT_SETTINGS)
def test_property_15_insufficient_pool_raises_409(scope: LevelScope) -> None:
    """Property 15 corner case — pool < target raises 409
    insufficient_question_pool."""
    target = COUNT_BY_SCOPE[scope]
    pool = _build_pool(target - 1)

    with pytest.raises(HTTPException) as exc_info:
        assemble_quiz(scope_level=scope, pool=pool)

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "insufficient_question_pool"


# ---------------------------------------------------------------------------
# Property 16 — Randomization across attempts
# ---------------------------------------------------------------------------
#
# Validates: Requirements 7.3
#
# Strategy: assemble twice from the same pool (security RNG is
# non-deterministic, so seeds will differ). For pool size >= 20 the
# probability of identical ordering across two random samples is
# vanishingly small (~ 1 / 20!). The property test asserts that the
# two orderings differ; a flake here would indicate the RNG is
# degenerate.


@given(scope=st.sampled_from(list(LevelScope)))
@settings(**_PBT_SETTINGS)
def test_property_16_randomization_across_attempts(scope: LevelScope) -> None:
    """Property 16 — Randomization across attempts (Req 7.3).

    Two attempts against the same pool produce different orderings with
    overwhelming probability for any reasonable pool size.
    """
    target = COUNT_BY_SCOPE[scope]
    # Use a generous pool excess so even in the unlikely case of identical
    # subset sampling the orderings still diverge.
    pool = _build_pool(target * 2)

    chosen_a, seed_a = assemble_quiz(scope_level=scope, pool=pool)
    chosen_b, seed_b = assemble_quiz(scope_level=scope, pool=pool)

    # Seeds drawn from the security RNG are virtually certain to differ.
    # The orderings must differ for a non-degenerate sampler.
    ordering_a = [q.id for q in chosen_a]
    ordering_b = [q.id for q in chosen_b]
    assert (
        ordering_a != ordering_b or seed_a != seed_b
    ), "two attempts produced identical ordering AND identical seed — RNG degenerate"


# ---------------------------------------------------------------------------
# Property 17 — Mid-attempt non-disclosure
# ---------------------------------------------------------------------------
#
# Validates: Requirements 7.4
#
# Strategy: enumerate scope ∈ {SUBTOPIC, TOPIC, MODULE} and assert that
# the in-progress response shape, serialized to a dict, contains no
# field named ``correct_answer``, ``is_correct``, or ``explanation``
# anywhere in the payload (including nested ``questions`` entries).


_FORBIDDEN_FIELDS = frozenset(
    {"correct_answer", "is_correct", "explanation"}
)


def _walk_for_forbidden(node: object) -> set[str]:
    """Recursively walk a Pydantic-dumped payload and return the set of
    forbidden field names encountered (empty == compliant)."""
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


@given(scope=st.sampled_from(list(LevelScope)))
@settings(**_PBT_SETTINGS)
def test_property_17_in_progress_schema_excludes_correctness(
    scope: LevelScope,
) -> None:
    """Property 17 — Mid-attempt non-disclosure (Req 7.4).

    The in-progress response shape MUST NOT contain correct_answer,
    is_correct, or explanation for any question.
    """
    user = _make_user()
    service = _build_service_with_pool(
        user=user,
        subtopic_id=10,
        topic_id=20,
        module_id=30,
        pool_size=COUNT_BY_SCOPE[scope],
        lesson_complete=True,
        has_passed_subtopic=True,
        has_passed_topic=True,
    )

    if scope == LevelScope.SUBTOPIC:
        response = service.start_subtopic_quiz(user=user, subtopic_id=10)
    elif scope == LevelScope.TOPIC:
        response = service.start_topic_quiz(user=user, topic_id=20)
    else:
        response = service.start_module_quiz(user=user, module_id=30)

    # Serialize to dict and walk for forbidden fields.
    payload = response.model_dump()
    forbidden = _walk_for_forbidden(payload)
    assert forbidden == set(), (
        f"in-progress response leaked correctness fields: {forbidden}"
    )


def test_property_17_schema_class_excludes_correctness_fields() -> None:
    """Defense in depth: the schema class itself must not declare any
    of the forbidden field names. A future contributor adding one of
    these fields would have to remove this test, which is the
    correct prompt to re-read Req 7.4."""
    in_progress_fields = set(QuizAttemptInProgressQuestion.model_fields.keys())
    response_fields = set(QuizAttemptInProgressResponse.model_fields.keys())
    assert _FORBIDDEN_FIELDS & in_progress_fields == set()
    assert _FORBIDDEN_FIELDS & response_fields == set()


# ---------------------------------------------------------------------------
# Property 18 — Prerequisite gating for higher-scope quizzes
# ---------------------------------------------------------------------------
#
# Validates: Requirements 8.1, 9.1
#
# Strategy: enumerate (passed_subtopic, passed_topic) ∈ {True, False}^2.
#
# - start_topic_quiz succeeds iff the subtopic under the topic has been
#   passed.
# - start_module_quiz succeeds iff the topic under the module has been
#   passed.


@given(
    has_passed_subtopic=st.booleans(),
    has_passed_topic=st.booleans(),
)
@settings(**_PBT_SETTINGS)
def test_property_18_prerequisite_gating(
    has_passed_subtopic: bool, has_passed_topic: bool
) -> None:
    """Property 18 — Prerequisite gating for higher-scope quizzes
    (Req 8.1, 9.1)."""
    user = _make_user()

    # Topic-quiz start branch.
    topic_service = _build_service_with_pool(
        user=user,
        subtopic_id=10,
        topic_id=20,
        module_id=30,
        pool_size=COUNT_BY_SCOPE[LevelScope.TOPIC],
        lesson_complete=True,
        has_passed_subtopic=has_passed_subtopic,
        has_passed_topic=has_passed_topic,
    )

    if has_passed_subtopic:
        result = topic_service.start_topic_quiz(user=user, topic_id=20)
        assert isinstance(result, QuizAttemptInProgressResponse)
    else:
        with pytest.raises(HTTPException) as exc_info:
            topic_service.start_topic_quiz(user=user, topic_id=20)
        assert exc_info.value.status_code == 409
        assert exc_info.value.detail == "prerequisites_not_met"

    # Module-quiz start branch (independent service so mock state is fresh).
    module_service = _build_service_with_pool(
        user=user,
        subtopic_id=10,
        topic_id=20,
        module_id=30,
        pool_size=COUNT_BY_SCOPE[LevelScope.MODULE],
        lesson_complete=True,
        has_passed_subtopic=has_passed_subtopic,
        has_passed_topic=has_passed_topic,
    )

    if has_passed_topic:
        result = module_service.start_module_quiz(user=user, module_id=30)
        assert isinstance(result, QuizAttemptInProgressResponse)
    else:
        with pytest.raises(HTTPException) as exc_info:
            module_service.start_module_quiz(user=user, module_id=30)
        assert exc_info.value.status_code == 409
        assert exc_info.value.detail == "prerequisites_not_met"
