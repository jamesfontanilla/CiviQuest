"""Pydantic schema tests for the content slice.

The two interesting validators here are ``LessonContent`` (Req 6.3) and
``QuestionCreate`` (Req 16.2, 18.1, 18.2, 18.3). Module/Topic/Subtopic
schemas are pure ``BaseModel`` shapes with field-level constraints — those
are covered indirectly via the FastAPI 422 path in router tests, so we
don't re-test trivial passthroughs here.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.features.content.schemas import (
    LessonContent,
    LessonExplanation,
    LessonWorkedExample,
    QuestionCreate,
)


# ----- LessonContent --------------------------------------------------------


def _make_lesson_content(**overrides):
    """Build a valid LessonContent kwargs dict, override fields per test."""
    base = {
        "explanations": [
            LessonExplanation(heading="Intro", body="The basics."),
        ],
        "worked_examples": [
            LessonWorkedExample(title="Example 1", body="Step by step."),
        ],
        "key_takeaways": ["Remember the rule of three."],
        "summary": "A short summary.",
    }
    base.update(overrides)
    return base


def test_lesson_content_accepts_minimal_valid_payload() -> None:
    content = LessonContent(**_make_lesson_content())

    assert len(content.explanations) == 1
    assert len(content.worked_examples) == 1
    assert content.key_takeaways == ["Remember the rule of three."]


def test_lesson_content_rejects_empty_explanations() -> None:
    with pytest.raises(ValidationError):
        LessonContent(**_make_lesson_content(explanations=[]))


def test_lesson_content_rejects_empty_worked_examples() -> None:
    with pytest.raises(ValidationError):
        LessonContent(**_make_lesson_content(worked_examples=[]))


def test_lesson_content_rejects_empty_key_takeaways_list() -> None:
    with pytest.raises(ValidationError):
        LessonContent(**_make_lesson_content(key_takeaways=[]))


def test_lesson_content_rejects_blank_string_takeaways() -> None:
    with pytest.raises(ValidationError):
        LessonContent(**_make_lesson_content(key_takeaways=["valid", "   "]))


def test_lesson_content_rejects_empty_summary() -> None:
    with pytest.raises(ValidationError):
        LessonContent(**_make_lesson_content(summary=""))


def test_lesson_content_rejects_whitespace_only_summary() -> None:
    with pytest.raises(ValidationError):
        LessonContent(**_make_lesson_content(summary="   \t\n"))


# ----- QuestionCreate -------------------------------------------------------


def _make_question_create(**overrides):
    """Build kwargs for a valid MC ``QuestionCreate``; override per test."""
    base = {
        "subtopic_id": 1,
        "level_scope": "SUBTOPIC",
        "stem": "What is 2 + 2?",
        "options": ["3", "4", "5", "6"],
        "correct_answer": "4",
        "explanation": "Addition.",
        "difficulty": "EASY",
        "qtype": "MULTIPLE_CHOICE",
    }
    base.update(overrides)
    return base


def test_question_create_accepts_valid_multiple_choice() -> None:
    q = QuestionCreate(**_make_question_create())

    assert q.options == ["3", "4", "5", "6"]
    assert q.correct_answer == "4"


def test_question_create_accepts_valid_identification_without_options() -> None:
    q = QuestionCreate(
        **_make_question_create(
            qtype="IDENTIFICATION",
            options=None,
            correct_answer="Manila",
            stem="Capital of the Philippines?",
        )
    )

    assert q.options is None
    assert q.correct_answer == "Manila"


def test_question_create_accepts_valid_identification_with_options() -> None:
    q = QuestionCreate(
        **_make_question_create(
            qtype="IDENTIFICATION",
            options=["Manila", "Cebu"],
            correct_answer="Manila",
        )
    )

    assert q.correct_answer in q.options


def test_question_create_rejects_mc_with_one_option() -> None:
    with pytest.raises(ValidationError):
        QuestionCreate(
            **_make_question_create(options=["only"], correct_answer="only")
        )


def test_question_create_rejects_mc_with_seven_options() -> None:
    seven = ["a", "b", "c", "d", "e", "f", "g"]
    with pytest.raises(ValidationError):
        QuestionCreate(**_make_question_create(options=seven, correct_answer="a"))


def test_question_create_rejects_mc_correct_answer_not_in_options() -> None:
    with pytest.raises(ValidationError):
        QuestionCreate(
            **_make_question_create(
                options=["3", "4", "5", "6"], correct_answer="42"
            )
        )


def test_question_create_rejects_mc_without_options() -> None:
    with pytest.raises(ValidationError):
        QuestionCreate(**_make_question_create(options=None))


def test_question_create_rejects_identification_with_options_correct_not_in_options() -> None:
    with pytest.raises(ValidationError):
        QuestionCreate(
            **_make_question_create(
                qtype="IDENTIFICATION",
                options=["Manila", "Cebu"],
                correct_answer="Davao",
            )
        )


def test_question_create_rejects_empty_stem() -> None:
    with pytest.raises(ValidationError):
        QuestionCreate(**_make_question_create(stem=""))


def test_question_create_rejects_empty_explanation() -> None:
    with pytest.raises(ValidationError):
        QuestionCreate(**_make_question_create(explanation=""))


def test_question_create_rejects_blank_option_string() -> None:
    with pytest.raises(ValidationError):
        QuestionCreate(
            **_make_question_create(
                options=["3", "  ", "5", "6"], correct_answer="5"
            )
        )
