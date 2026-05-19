"""Tests for the Phase 2 mock-exam seed (Task 13.1).

Two layers:

- Pure-math tests against :func:`compute_phase2_weights` covering the
  even split, the remainder placement, the single-module degenerate,
  and the empty-list error path. These don't need a DB — the function
  is a stateless helper.
- DB-backed tests against :func:`seed_phase2_configs` to confirm the
  seed calls into :class:`MockExamRepository.upsert_config`
  idempotently and writes the documented defaults
  (``total_questions=165``, ``time_limit_minutes=180``,
  ``nav_policy=LINEAR_NO_REVISIT``, ``pass_threshold=0.80``).
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.features.mock_exams.models import MockExamNavPolicy
from app.features.mock_exams.repository import MockExamRepository
from app.features.mock_exams.seed import (
    PHASE2_TOTAL_QUESTIONS,
    compute_phase2_weights,
    seed_phase2_configs,
)
from app.features.users.models import Category


# ---------------------------------------------------------------------------
# compute_phase2_weights — pure helper
# ---------------------------------------------------------------------------


def test_compute_weights_even_split_five_modules() -> None:
    """5 modules: 165 / 5 = 33 each, no remainder."""
    weights = compute_phase2_weights([1, 2, 3, 4, 5])

    assert weights == {"1": 33, "2": 33, "3": 33, "4": 33, "5": 33}
    assert sum(weights.values()) == PHASE2_TOTAL_QUESTIONS


def test_compute_weights_uneven_split_seven_modules() -> None:
    """7 modules: floor(165/7)=23, remainder 4 → first 4 modules get +1."""
    weights = compute_phase2_weights([1, 2, 3, 4, 5, 6, 7])

    # First 4 modules get the bonus, remaining 3 stay at the base.
    assert weights == {
        "1": 24,
        "2": 24,
        "3": 24,
        "4": 24,
        "5": 23,
        "6": 23,
        "7": 23,
    }
    # Sorted distribution descending matches the spec's example.
    assert sorted(weights.values(), reverse=True) == [24, 24, 24, 24, 23, 23, 23]
    assert sum(weights.values()) == PHASE2_TOTAL_QUESTIONS


def test_compute_weights_single_module_takes_all() -> None:
    """1 module: gets all 165 slots."""
    weights = compute_phase2_weights([42])

    assert weights == {"42": 165}
    assert sum(weights.values()) == PHASE2_TOTAL_QUESTIONS


def test_compute_weights_empty_list_raises() -> None:
    """Empty module list is a programmer error, not a silent no-op."""
    with pytest.raises(ValueError, match="at least one module required"):
        compute_phase2_weights([])


def test_compute_weights_remainder_lands_on_lowest_index_modules() -> None:
    """Remainder placement is deterministic and order-sensitive."""
    # 165 / 4 = 41 base, remainder 1. The first module gets the +1.
    weights = compute_phase2_weights([7, 8, 9, 10])
    assert weights == {"7": 42, "8": 41, "9": 41, "10": 41}

    # Reordering the input changes which module gets the bonus.
    weights_reordered = compute_phase2_weights([10, 9, 8, 7])
    assert weights_reordered == {"10": 42, "9": 41, "8": 41, "7": 41}


def test_compute_weights_keys_are_string_typed() -> None:
    """JSON dicts can't have integer keys; persistence layer needs strings."""
    weights = compute_phase2_weights([1, 2, 3])
    assert all(isinstance(k, str) for k in weights.keys())
    assert all(isinstance(v, int) for v in weights.values())


# ---------------------------------------------------------------------------
# seed_phase2_configs — DB-backed
# ---------------------------------------------------------------------------


def test_seed_writes_config_for_each_category(db_session: Session) -> None:
    """Seed inserts one row per category with the documented defaults."""
    repo = MockExamRepository(db=db_session)

    seed_phase2_configs(
        repo,
        module_ids_by_category={
            Category.PROFESSIONAL: [1, 2, 3, 4, 5],
            Category.SUB_PROFESSIONAL: [10, 20, 30, 40, 50, 60, 70],
        },
    )

    pro_cfg = repo.get_config(Category.PROFESSIONAL)
    assert pro_cfg is not None
    assert pro_cfg.total_questions == PHASE2_TOTAL_QUESTIONS
    assert pro_cfg.weights_json == {
        "1": 33,
        "2": 33,
        "3": 33,
        "4": 33,
        "5": 33,
    }
    assert sum(pro_cfg.weights_json.values()) == PHASE2_TOTAL_QUESTIONS
    assert pro_cfg.time_limit_minutes == 180
    assert pro_cfg.nav_policy == MockExamNavPolicy.LINEAR_NO_REVISIT.value
    assert pro_cfg.pass_threshold == 0.80

    sub_cfg = repo.get_config(Category.SUB_PROFESSIONAL)
    assert sub_cfg is not None
    assert sub_cfg.total_questions == PHASE2_TOTAL_QUESTIONS
    assert sum(sub_cfg.weights_json.values()) == PHASE2_TOTAL_QUESTIONS
    # First 4 modules get the bonus, remaining 3 stay at base 23.
    assert sub_cfg.weights_json == {
        "10": 24,
        "20": 24,
        "30": 24,
        "40": 24,
        "50": 23,
        "60": 23,
        "70": 23,
    }


def test_seed_is_idempotent(db_session: Session) -> None:
    """Calling the seeder twice produces the same row state."""
    repo = MockExamRepository(db=db_session)
    payload = {
        Category.PROFESSIONAL: [1, 2, 3, 4, 5],
        Category.SUB_PROFESSIONAL: [10, 11, 12],
    }

    seed_phase2_configs(repo, module_ids_by_category=payload)
    first_pro = repo.get_config(Category.PROFESSIONAL)
    first_sub = repo.get_config(Category.SUB_PROFESSIONAL)
    assert first_pro is not None
    assert first_sub is not None
    first_pro_weights = dict(first_pro.weights_json)
    first_sub_weights = dict(first_sub.weights_json)

    seed_phase2_configs(repo, module_ids_by_category=payload)
    second_pro = repo.get_config(Category.PROFESSIONAL)
    second_sub = repo.get_config(Category.SUB_PROFESSIONAL)
    assert second_pro is not None
    assert second_sub is not None

    assert second_pro.weights_json == first_pro_weights
    assert second_pro.total_questions == PHASE2_TOTAL_QUESTIONS
    assert second_sub.weights_json == first_sub_weights
    assert second_sub.total_questions == PHASE2_TOTAL_QUESTIONS


def test_seed_overwrites_pre_existing_mvp_config(db_session: Session) -> None:
    """A pre-seeded MVP 50q config gets overwritten with the Phase 2 165q row."""
    repo = MockExamRepository(db=db_session)
    repo.upsert_config(
        category=Category.PROFESSIONAL,
        total_questions=50,
        weights_json={"1": 50},
        nav_policy=MockExamNavPolicy.FREE_NAV,
        pass_threshold=0.75,
    )

    seed_phase2_configs(
        repo,
        module_ids_by_category={Category.PROFESSIONAL: [1, 2, 3]},
    )

    cfg = repo.get_config(Category.PROFESSIONAL)
    assert cfg is not None
    assert cfg.total_questions == PHASE2_TOTAL_QUESTIONS
    assert sum(cfg.weights_json.values()) == PHASE2_TOTAL_QUESTIONS
    assert cfg.nav_policy == MockExamNavPolicy.LINEAR_NO_REVISIT.value
    assert cfg.pass_threshold == 0.80


def test_seed_rejects_empty_module_list_for_a_category(
    db_session: Session,
) -> None:
    """An empty module list for any category raises ValueError."""
    repo = MockExamRepository(db=db_session)

    with pytest.raises(ValueError, match="at least one module required"):
        seed_phase2_configs(
            repo,
            module_ids_by_category={
                Category.PROFESSIONAL: [1, 2, 3],
                Category.SUB_PROFESSIONAL: [],
            },
        )
