"""Property-based tests for the content slice (Task 7.6).

Three properties from the design's correctness catalog land here:

- **Property 12 — Category isolation** (Req 5.1, 5.2, 5.3) — for any
  ``(user_category, resource_category, ccp_flag)`` combination,
  :meth:`ModuleService.get_for_user` succeeds iff the user's category
  matches the resource's *or* ``cross_category_preview`` is set; every
  mismatch raises **403** (never 404).
- **Property 13 — Lesson content schema completeness** (Req 6.3) — the
  ``LessonContent`` validator accepts a payload iff every required section
  is present and non-empty.
- **Property 28 — Question quality gate enforcement** (Req 18.1, 18.2,
  18.3) — :func:`is_question_quality_passing` returns ``(False, RULE_*)``
  for every Req 18.x violation and ``(True, None)`` only when all rules
  hold.

Shared hypothesis settings:

- ``max_examples=50`` matches the rest of this codebase's PBT density;
  none of these tests do real I/O so 50 is plenty without bloating CI.
- ``HealthCheck.too_slow`` / ``HealthCheck.function_scoped_fixture`` are
  suppressed because hypothesis sometimes flags the validator-only
  property as "too slow" when run alongside the slower auth PBT.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from hypothesis import HealthCheck, given, settings, strategies as st
from pydantic import ValidationError

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
from app.features.content.models import (
    Difficulty,
    LessonStatus,
    Module,
    Question,
    QuestionType,
)
from app.features.content.schemas import (
    LessonContent,
    LessonExplanation,
    LessonWorkedExample,
)
from app.features.content.service import ModuleService
from app.features.users.models import (
    AccountState,
    Category,
    Role,
    User,
)
from unittest.mock import MagicMock

from app.features.content.repository import ModuleRepository


_PBT_SETTINGS = dict(
    suppress_health_check=[
        HealthCheck.too_slow,
        HealthCheck.function_scoped_fixture,
    ],
    deadline=None,
)


# --- helpers ----------------------------------------------------------------


def _make_user(category: Category, *, ccp: bool = False) -> User:
    return User(
        id=1,
        email="alice@example.com",
        display_name="Alice",
        age=25,
        category=category.value,
        role=Role.LEARNER.value,
        account_state=AccountState.VERIFIED.value,
        is_banned=False,
        tz_name="UTC",
        password_hash="x",
        cross_category_preview=ccp,
    )


def _make_module(category: Category) -> Module:
    return Module(
        id=42,
        category=category.value,
        slug="m",
        title="M",
        order_index=0,
        is_published=True,
    )


def _make_question(**overrides: object) -> Question:
    """Build a transient ``Question`` instance for the gate predicate."""
    base: dict[str, object] = {
        "id": 1,
        "subtopic_id": 1,
        "topic_id": 1,
        "module_id": 1,
        "category": Category.PROFESSIONAL.value,
        "level_scope": "SUBTOPIC",
        "stem": "What is 2 + 2?",
        "options": ["3", "4", "5", "6"],
        "correct_answer": "4",
        "explanation": "Addition.",
        "difficulty": Difficulty.EASY.value,
        "qtype": QuestionType.MULTIPLE_CHOICE.value,
        "is_active": True,
    }
    base.update(overrides)
    return Question(**base)


# --- Property 12: Category isolation ----------------------------------------
#
# Validates: Requirements 5.1, 5.2, 5.3
#
# Strategy: enumerate every (user_cat, resource_cat, ccp_flag) triple via
# ``st.sampled_from`` and assert the equivalence between the boolean
# "should succeed" derived from the rule and the actual service behaviour.
# A failure raises 403 — never 404 — so we additionally assert the exact
# status code on every mismatch path.


@given(
    user_cat=st.sampled_from(list(Category)),
    resource_cat=st.sampled_from(list(Category)),
    ccp=st.booleans(),
)
@settings(max_examples=50, **_PBT_SETTINGS)
def test_property_12_category_isolation(
    user_cat: Category, resource_cat: Category, ccp: bool
) -> None:
    """ModuleService.get_for_user succeeds iff categories match or the
    Phase 2 ``cross_category_preview`` flag admits cross-category reads;
    otherwise 403 (never 404)."""
    repo = MagicMock(spec=ModuleRepository)
    module = _make_module(resource_cat)
    repo.get.return_value = module

    service = ModuleService(module_repo=repo)
    user = _make_user(user_cat, ccp=ccp)

    should_succeed = (user_cat == resource_cat) or ccp

    if should_succeed:
        result = service.get_for_user(user, module.id)
        assert result is module
    else:
        with pytest.raises(HTTPException) as exc_info:
            service.get_for_user(user, module.id)
        assert exc_info.value.status_code == 403
        # Never 404 — Property 12 explicitly forbids it.
        assert exc_info.value.status_code != 404


@given(user_cat=st.sampled_from(list(Category)))
@settings(max_examples=20, **_PBT_SETTINGS)
def test_property_12_unknown_id_is_403_not_404(user_cat: Category) -> None:
    """Property 12 forbids 404 even when the id genuinely does not exist."""
    repo = MagicMock(spec=ModuleRepository)
    repo.get.return_value = None
    service = ModuleService(module_repo=repo)

    with pytest.raises(HTTPException) as exc_info:
        service.get_for_user(_make_user(user_cat), 9999)

    assert exc_info.value.status_code == 403


# --- Property 13: Lesson content schema completeness ------------------------
#
# Validates: Requirement 6.3
#
# Strategy: build payloads where each of the four required sections is
# either present-and-non-empty (``present=True``) or absent/empty
# (``present=False``). The validator accepts iff *all four* are present.


_NONEMPTY_TEXT = st.text(min_size=1, max_size=20).filter(lambda s: s.strip() != "")


def _explanation_section(non_empty: bool) -> dict[str, str]:
    return {
        "heading": "Heading" if non_empty else "Heading",
        "body": "Body" if non_empty else "Body",
    }


@given(
    n_explanations=st.integers(min_value=0, max_value=3),
    n_examples=st.integers(min_value=0, max_value=3),
    takeaways=st.lists(_NONEMPTY_TEXT, min_size=0, max_size=3),
    summary=st.text(min_size=0, max_size=20),
)
@settings(max_examples=50, **_PBT_SETTINGS)
def test_property_13_lesson_content_completeness(
    n_explanations: int,
    n_examples: int,
    takeaways: list[str],
    summary: str,
) -> None:
    """LessonContent accepts iff every required section is present and
    non-empty (Req 6.3)."""
    payload = {
        "explanations": [
            LessonExplanation(heading=f"H{i}", body=f"B{i}")
            for i in range(n_explanations)
        ],
        "worked_examples": [
            LessonWorkedExample(title=f"T{i}", body=f"B{i}")
            for i in range(n_examples)
        ],
        "key_takeaways": takeaways,
        "summary": summary,
    }

    should_pass = (
        n_explanations >= 1
        and n_examples >= 1
        and len(takeaways) >= 1
        and bool(summary.strip())
    )

    if should_pass:
        content = LessonContent(**payload)
        assert len(content.explanations) == n_explanations
        assert len(content.worked_examples) == n_examples
        assert content.key_takeaways == takeaways
        assert content.summary == summary
    else:
        with pytest.raises(ValidationError):
            LessonContent(**payload)


# --- Property 28: Question quality gate enforcement -------------------------
#
# Validates: Requirements 18.1, 18.2, 18.3
#
# Two complementary properties:
#
# - Any well-formed question passes.
# - Mutating *exactly one* attribute to violate one Req 18.x rule causes
#   the gate to return ``(False, RULE_*)`` naming that rule.
#
# We can't reasonably guarantee the rule string for a multi-mutation
# question (some violations are checked before others — see the helper's
# rule order), so the property fixes one mutation at a time.


# Map the rule we want to hit -> a callable that produces the mutation kwargs.
def _mutation_for_rule(rule: str) -> dict[str, object]:
    if rule == RULE_STEM_EMPTY:
        return {"stem": "   "}
    if rule == RULE_NO_CORRECT_ANSWER:
        return {"correct_answer": "   "}
    if rule == RULE_EMPTY_EXPLANATION:
        return {"explanation": ""}
    if rule == RULE_INVALID_DIFFICULTY:
        return {"difficulty": "BANANAS"}
    if rule == RULE_INVALID_TYPE:
        return {"qtype": "DOODLE"}
    if rule == RULE_MC_OPTION_COUNT:
        # Make the option count fail without tripping the in-options rule
        # first by keeping correct_answer in the (single) option list.
        return {"options": ["only"], "correct_answer": "only"}
    if rule == RULE_CORRECT_NOT_IN_OPTIONS:
        return {"options": ["3", "4", "5", "6"], "correct_answer": "42"}
    raise AssertionError(f"unhandled rule: {rule}")


_RULE_STRATEGY = st.sampled_from(
    [
        RULE_STEM_EMPTY,
        RULE_NO_CORRECT_ANSWER,
        RULE_EMPTY_EXPLANATION,
        RULE_INVALID_DIFFICULTY,
        RULE_INVALID_TYPE,
        RULE_MC_OPTION_COUNT,
        RULE_CORRECT_NOT_IN_OPTIONS,
    ]
)


@given(rule=_RULE_STRATEGY)
@settings(max_examples=50, **_PBT_SETTINGS)
def test_property_28_each_violation_caught_with_correct_rule(rule: str) -> None:
    """For any Req 18.x rule, a question mutated to violate exactly that
    rule fails the gate with that rule string."""
    q = _make_question(**_mutation_for_rule(rule))
    passes, returned_rule = is_question_quality_passing(q)

    assert passes is False
    assert returned_rule == rule


@given(
    qtype=st.sampled_from(
        [
            QuestionType.MULTIPLE_CHOICE,
            QuestionType.IDENTIFICATION,
            QuestionType.LOGICAL_REASONING,
            QuestionType.READING_COMPREHENSION,
            QuestionType.PROBLEM_SOLVING,
        ]
    ),
    difficulty=st.sampled_from(list(Difficulty)),
    n_options=st.integers(min_value=2, max_value=6),
    stem=_NONEMPTY_TEXT,
    explanation=_NONEMPTY_TEXT,
)
@settings(max_examples=50, **_PBT_SETTINGS)
def test_property_28_well_formed_questions_pass(
    qtype: QuestionType,
    difficulty: Difficulty,
    n_options: int,
    stem: str,
    explanation: str,
) -> None:
    """Conversely: any question generated within the allowed shape passes
    the gate. This is the "iff" direction of Property 28."""
    options = [f"opt-{i}" for i in range(n_options)]
    correct = options[0]

    # Non-MC questions allow no-options form too. Cover both branches.
    use_options = qtype != QuestionType.MULTIPLE_CHOICE and (
        n_options % 2 == 0
    )
    if use_options:
        # Free-text identification / reasoning style.
        q = _make_question(
            qtype=qtype.value,
            difficulty=difficulty.value,
            options=None,
            correct_answer="any-answer",
            stem=stem,
            explanation=explanation,
        )
    else:
        q = _make_question(
            qtype=qtype.value,
            difficulty=difficulty.value,
            options=options,
            correct_answer=correct,
            stem=stem,
            explanation=explanation,
        )

    passes, rule = is_question_quality_passing(q)
    assert passes is True
    assert rule is None


# Double-check Property 13's interaction with the LessonStatus ``INCOMPLETE``
# branch by asserting the enum value exists; the actual exclusion behaviour
# is service-level (covered in test_service.py).
def test_lesson_status_incomplete_exists_for_property_13_excl_branch() -> None:
    assert LessonStatus.INCOMPLETE.value == "INCOMPLETE"
