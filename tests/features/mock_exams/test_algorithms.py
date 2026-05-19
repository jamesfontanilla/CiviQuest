"""Algorithm tests for the mock-exam slice (Task 12.4 verification surface).

Two pure modules under test:

- :mod:`category_weighted_assembly` — A1 sample-and-shuffle.
- :mod:`timer` — server-authoritative remaining-time math.

Per ``testing-standards.md`` algorithm tests run pure functions with
plain Python state; no DB fixtures.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from app.features.content.models import (
    Difficulty,
    LevelScope,
    Question,
    QuestionType,
)
from app.features.users.models import Category
from app.features.mock_exams.algorithms.category_weighted_assembly import (
    assemble_mock_exam,
)
from app.features.mock_exams.algorithms.timer import (
    is_expired,
    remaining_seconds,
)


# --- factories --------------------------------------------------------------


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


def _pool_for_module(module_id: int, size: int) -> list[Question]:
    return [
        _make_question(module_id * 1000 + i, module_id=module_id)
        for i in range(1, size + 1)
    ]


# ---------------------------------------------------------------------------
# assemble_mock_exam
# ---------------------------------------------------------------------------


def test_assemble_returns_total_equal_to_sum_of_weights() -> None:
    weights = {"1": 25, "2": 25}
    pools = {1: _pool_for_module(1, 30), 2: _pool_for_module(2, 30)}

    chosen, seed = assemble_mock_exam(
        weights=weights, pools_by_module=pools
    )

    assert len(chosen) == 50
    assert 0 <= seed < 2**64


def test_assemble_per_module_count_matches_weights() -> None:
    weights = {"1": 10, "2": 20, "3": 5}
    pools = {
        1: _pool_for_module(1, 30),
        2: _pool_for_module(2, 30),
        3: _pool_for_module(3, 30),
    }

    chosen, _ = assemble_mock_exam(weights=weights, pools_by_module=pools)

    by_module: dict[int, int] = {}
    for q in chosen:
        by_module[q.module_id] = by_module.get(q.module_id, 0) + 1
    assert by_module == {1: 10, 2: 20, 3: 5}


def test_assemble_exact_fit_pools_returns_all_questions() -> None:
    weights = {"1": 5, "2": 5}
    pools = {1: _pool_for_module(1, 5), 2: _pool_for_module(2, 5)}

    chosen, _ = assemble_mock_exam(weights=weights, pools_by_module=pools)

    assert len(chosen) == 10
    assert {q.id for q in chosen} == {q.id for p in pools.values() for q in p}


def test_assemble_insufficient_pool_raises_409() -> None:
    weights = {"1": 30}
    pools = {1: _pool_for_module(1, 5)}

    with pytest.raises(HTTPException) as exc_info:
        assemble_mock_exam(weights=weights, pools_by_module=pools)

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "insufficient_question_pool"


def test_assemble_missing_pool_for_module_raises_409() -> None:
    """A weight referencing a module with no pool entry treats that
    pool as empty — i.e. insufficient."""
    weights = {"1": 5}
    pools: dict[int, list[Question]] = {}

    with pytest.raises(HTTPException) as exc_info:
        assemble_mock_exam(weights=weights, pools_by_module=pools)

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "insufficient_question_pool"


def test_assemble_final_shuffle_is_non_degenerate() -> None:
    """Two assemblies against the same pools should rarely produce
    identical orderings — the cross-module shuffle is what guarantees
    Property 16 for the mock branch."""
    weights = {"1": 5, "2": 5}
    pools = {1: _pool_for_module(1, 30), 2: _pool_for_module(2, 30)}

    chosen_a, seed_a = assemble_mock_exam(
        weights=weights, pools_by_module=pools
    )
    chosen_b, seed_b = assemble_mock_exam(
        weights=weights, pools_by_module=pools
    )

    ordering_a = [q.id for q in chosen_a]
    ordering_b = [q.id for q in chosen_b]
    assert ordering_a != ordering_b or seed_a != seed_b, (
        "two assemblies produced identical ordering AND identical seed — "
        "RNG degenerate"
    )


# ---------------------------------------------------------------------------
# remaining_seconds / is_expired
# ---------------------------------------------------------------------------


def test_remaining_zero_elapsed_equals_full_limit() -> None:
    started = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
    assert (
        remaining_seconds(
            started_at=started,
            time_limit_minutes=180,
            now=started,
        )
        == 180 * 60
    )


def test_remaining_at_exactly_time_limit_is_zero() -> None:
    """Boundary case — at exactly the limit, ``remaining`` is 0."""
    started = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
    now = started + timedelta(minutes=180)

    assert (
        remaining_seconds(
            started_at=started, time_limit_minutes=180, now=now
        )
        == 0
    )
    assert is_expired(
        started_at=started, time_limit_minutes=180, now=now
    )


def test_remaining_past_time_limit_is_zero() -> None:
    started = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
    now = started + timedelta(minutes=200)

    assert (
        remaining_seconds(
            started_at=started, time_limit_minutes=180, now=now
        )
        == 0
    )
    assert is_expired(
        started_at=started, time_limit_minutes=180, now=now
    )


def test_remaining_naive_started_at_is_assumed_utc() -> None:
    started_naive = datetime(2025, 1, 1, 12, 0)  # tzinfo=None
    now = datetime(2025, 1, 1, 12, 30, tzinfo=timezone.utc)

    # 30 minutes in → remaining = 180*60 - 30*60 = 9000 (= 150 min).
    assert (
        remaining_seconds(
            started_at=started_naive,
            time_limit_minutes=180,
            now=now,
        )
        == 150 * 60
    )


def test_is_expired_negative_remaining_still_zero() -> None:
    started = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
    now = started + timedelta(hours=10)

    # 10h elapsed against a 180min limit — clamped at 0, expired.
    assert (
        remaining_seconds(
            started_at=started, time_limit_minutes=180, now=now
        )
        == 0
    )
    assert is_expired(
        started_at=started, time_limit_minutes=180, now=now
    )
