"""Unit tests for ``is_question_quality_passing``.

The Python helper is the read-side and write-side enforcement point for
Req 18.1, 18.2, 18.3. These tests exercise each failure rule in isolation
so a regression names the specific rule that broke. The SQL predicate
itself is exercised end-to-end by the repository tests (which run against
in-memory SQLite).
"""

from __future__ import annotations

import pytest

from app.features.content.algorithms.quality_gate import (
    RULE_CORRECT_NOT_IN_OPTIONS,
    RULE_EMPTY_EXPLANATION,
    RULE_INVALID_DIFFICULTY,
    RULE_INVALID_TYPE,
    RULE_MC_OPTION_COUNT,
    RULE_NO_CORRECT_ANSWER,
    RULE_STEM_EMPTY,
    is_question_quality_passing,
)
from app.features.content.models import Question


def _make_question(**overrides) -> Question:
    """Build a transient ``Question`` ORM instance with sane MC defaults.

    The instance is unattached to a session — the helper checks attributes
    directly so we don't need the row to be persistable for these tests.
    """
    base = {
        "id": 1,
        "subtopic_id": 1,
        "topic_id": 1,
        "module_id": 1,
        "category": "PROFESSIONAL",
        "level_scope": "SUBTOPIC",
        "stem": "What is 2 + 2?",
        "options": ["3", "4", "5", "6"],
        "correct_answer": "4",
        "explanation": "Addition.",
        "difficulty": "EASY",
        "qtype": "MULTIPLE_CHOICE",
        "is_active": True,
    }
    base.update(overrides)
    return Question(**base)


def test_is_question_quality_passing_returns_true_for_valid_mc() -> None:
    q = _make_question()
    passes, rule = is_question_quality_passing(q)

    assert passes is True
    assert rule is None


def test_passes_for_identification_without_options() -> None:
    q = _make_question(qtype="IDENTIFICATION", options=None, correct_answer="Manila")
    passes, rule = is_question_quality_passing(q)

    assert passes is True
    assert rule is None


def test_passes_for_identification_with_correct_in_options() -> None:
    q = _make_question(
        qtype="IDENTIFICATION",
        options=["Manila", "Cebu"],
        correct_answer="Manila",
    )
    passes, rule = is_question_quality_passing(q)

    assert passes is True
    assert rule is None


@pytest.mark.parametrize(
    ("overrides", "expected_rule"),
    [
        ({"stem": ""}, RULE_STEM_EMPTY),
        ({"stem": "   "}, RULE_STEM_EMPTY),
        ({"correct_answer": ""}, RULE_NO_CORRECT_ANSWER),
        ({"correct_answer": "   "}, RULE_NO_CORRECT_ANSWER),
        ({"explanation": ""}, RULE_EMPTY_EXPLANATION),
        ({"explanation": "  \t"}, RULE_EMPTY_EXPLANATION),
        ({"difficulty": "BANANAS"}, RULE_INVALID_DIFFICULTY),
        ({"qtype": "DOODLE"}, RULE_INVALID_TYPE),
        # Req 18.2 — MC option count.
        # Single option but make it match correct_answer so we don't trip
        # the in-options rule first.
        ({"options": ["only"], "correct_answer": "only"}, RULE_MC_OPTION_COUNT),
        (
            {
                "options": ["a", "b", "c", "d", "e", "f", "g"],
                "correct_answer": "a",
            },
            RULE_MC_OPTION_COUNT,
        ),
        # Req 18.3 — MC correct must match an option.
        (
            {"options": ["3", "4", "5", "6"], "correct_answer": "42"},
            RULE_CORRECT_NOT_IN_OPTIONS,
        ),
    ],
)
def test_is_question_quality_passing_rejects_each_failure_mode(
    overrides: dict, expected_rule: str
) -> None:
    q = _make_question(**overrides)
    passes, rule = is_question_quality_passing(q)

    assert passes is False
    assert rule == expected_rule


def test_mc_with_no_options_fails_option_count_rule() -> None:
    """A MULTIPLE_CHOICE row missing options entirely is treated as bad
    option count (Req 18.2). This catches NULL options on legacy rows.
    """
    q = _make_question(options=None)
    passes, rule = is_question_quality_passing(q)

    assert passes is False
    assert rule == RULE_MC_OPTION_COUNT


def test_identification_with_options_correct_not_in_options_rejected() -> None:
    q = _make_question(
        qtype="IDENTIFICATION",
        options=["Manila", "Cebu"],
        correct_answer="Davao",
    )
    passes, rule = is_question_quality_passing(q)

    assert passes is False
    assert rule == RULE_CORRECT_NOT_IN_OPTIONS
