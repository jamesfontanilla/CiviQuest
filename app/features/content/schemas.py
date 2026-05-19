"""Pydantic schemas for the content feature.

Three shapes per ``code-conventions.md``: ``Create`` for write-side payloads,
``Update`` for partial PATCH semantics, and ``Response`` for ORM read-out.
The interesting part of this module is the validators on ``LessonContent``
and ``QuestionCreate`` — they re-state Req 6.3 and Req 18.1/18.2/18.3 at
the schema layer so the service can rely on either entry path:

- Admin writes go through the schema, so a malformed payload is rejected at
  the FastAPI boundary (422) before the service sees it.
- Read-side assembly relies on the SQL quality gate (``algorithms/quality_gate``)
  plus its Python helper to reject anything that slipped past the schema
  (e.g. legacy data imported before this slice landed).

The two paths are deliberately redundant. Defense in depth is cheap when the
rules are simple closed-set checks.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.features.content.models import (
    Difficulty,
    LessonStatus,
    LevelScope,
    QuestionType,
)
from app.features.users.models import Category


# ----- Lesson content (drives ``lessons.content_json``) ---------------------


class LessonExplanation(BaseModel):
    """One explanation section in a lesson (Req 6.3)."""

    heading: str = Field(min_length=1, max_length=255)
    body: str = Field(min_length=1)


class LessonWorkedExample(BaseModel):
    """One worked example in a lesson (Req 6.3)."""

    title: str = Field(min_length=1, max_length=255)
    body: str = Field(min_length=1)


class LessonContent(BaseModel):
    """The validated shape of a published lesson's ``content_json``.

    Per Req 6.3, a lesson must include:

    - At least one explanation section.
    - At least one worked example.
    - A non-empty ``key_takeaways`` list (no blank-string entries).
    - A non-empty ``summary`` string.

    Req 6.4 says a lesson lacking any of these is flagged ``INCOMPLETE`` and
    hidden from learners. This schema is strict — admin writes that fail
    validation surface as 422 from the service. The ``INCOMPLETE`` status is
    intended for *migrated* legacy data: an admin tool that ingests pre-spec
    lessons may bypass the strict schema and stamp them ``INCOMPLETE`` so
    learners never see them. New admin writes go through ``LessonCreate``
    and are validated.
    """

    explanations: list[LessonExplanation] = Field(min_length=1)
    worked_examples: list[LessonWorkedExample] = Field(min_length=1)
    key_takeaways: list[str] = Field(min_length=1)
    summary: str = Field(min_length=1)

    @field_validator("key_takeaways")
    @classmethod
    def _no_empty_takeaways(cls, v: list[str]) -> list[str]:
        for item in v:
            if not item or not item.strip():
                raise ValueError("key_takeaways entries must be non-empty")
        return v

    @field_validator("summary")
    @classmethod
    def _summary_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("summary must be non-empty")
        return v


# ----- Module schemas -------------------------------------------------------


class ModuleCreate(BaseModel):
    """Admin-write payload for creating a module (Req 16.1)."""

    category: Category
    slug: str = Field(min_length=1, max_length=255)
    title: str = Field(min_length=1, max_length=255)
    order_index: int = Field(default=0, ge=0)
    is_published: bool = True


class ModuleUpdate(BaseModel):
    """Partial-update payload for a module."""

    category: Category | None = None
    slug: str | None = Field(default=None, min_length=1, max_length=255)
    title: str | None = Field(default=None, min_length=1, max_length=255)
    order_index: int | None = Field(default=None, ge=0)
    is_published: bool | None = None


class ModuleResponse(BaseModel):
    """Read-side projection of a module (Req 5.1, 5.2)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    category: Category
    slug: str
    title: str
    order_index: int
    is_published: bool


# ----- Topic schemas --------------------------------------------------------


class TopicCreate(BaseModel):
    module_id: int
    slug: str = Field(min_length=1, max_length=255)
    title: str = Field(min_length=1, max_length=255)
    order_index: int = Field(default=0, ge=0)


class TopicUpdate(BaseModel):
    slug: str | None = Field(default=None, min_length=1, max_length=255)
    title: str | None = Field(default=None, min_length=1, max_length=255)
    order_index: int | None = Field(default=None, ge=0)


class TopicResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    module_id: int
    slug: str
    title: str
    order_index: int


# ----- Subtopic schemas -----------------------------------------------------


class SubtopicCreate(BaseModel):
    topic_id: int
    slug: str = Field(min_length=1, max_length=255)
    title: str = Field(min_length=1, max_length=255)
    order_index: int = Field(default=0, ge=0)


class SubtopicUpdate(BaseModel):
    slug: str | None = Field(default=None, min_length=1, max_length=255)
    title: str | None = Field(default=None, min_length=1, max_length=255)
    order_index: int | None = Field(default=None, ge=0)


class SubtopicResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    topic_id: int
    slug: str
    title: str
    order_index: int


# ----- Lesson schemas -------------------------------------------------------


class LessonCreate(BaseModel):
    """Create payload for a lesson.

    Strict validation on ``content``: a malformed payload raises
    ``ValidationError`` and never reaches the service. The service layer
    handles the ``INCOMPLETE``-on-migration case via a separate ingest path
    (see ``LessonContent`` docstring).
    """

    subtopic_id: int
    content: LessonContent
    status: LessonStatus = LessonStatus.DRAFT


class LessonUpdate(BaseModel):
    content: LessonContent | None = None
    status: LessonStatus | None = None


class LessonResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    subtopic_id: int
    content_json: dict[str, Any]
    status: LessonStatus


# ----- Question schemas -----------------------------------------------------


def _validate_question_payload(
    *,
    qtype: QuestionType,
    options: list[str] | None,
    correct_answer: str,
) -> None:
    """Apply Req 18.2 / 18.3 cross-field rules.

    Shared by ``QuestionCreate.model_validator`` and ``QuestionUpdate``'s
    after-validator. ``stem`` and ``explanation`` non-emptiness is enforced
    by ``Field(min_length=1)`` on the field declarations.
    """
    if qtype == QuestionType.MULTIPLE_CHOICE:
        if options is None:
            raise ValueError("MULTIPLE_CHOICE questions require options")
        if not (2 <= len(options) <= 6):
            raise ValueError(
                "MULTIPLE_CHOICE questions must have between 2 and 6 options"
            )
        for opt in options:
            if not isinstance(opt, str) or not opt.strip():
                raise ValueError("every option must be a non-empty string")
        if correct_answer not in options:
            raise ValueError("correct_answer must match one of the options")
        return

    if qtype == QuestionType.IDENTIFICATION:
        # Identification can be free-text or have a small option list. If
        # options are provided, the correct answer must still be among them
        # (Req 18.3).
        if options is not None:
            if not (2 <= len(options) <= 6):
                raise ValueError(
                    "IDENTIFICATION questions with options must have 2..6 entries"
                )
            for opt in options:
                if not isinstance(opt, str) or not opt.strip():
                    raise ValueError("every option must be a non-empty string")
            if correct_answer not in options:
                raise ValueError("correct_answer must match one of the options")
        return

    # LOGICAL_REASONING / READING_COMPREHENSION / PROBLEM_SOLVING.
    # The spec is silent on these in Req 18.2 / 18.3; we treat them like
    # IDENTIFICATION — options optional, but if present the same shape rules
    # apply.
    if options is not None:
        if not (2 <= len(options) <= 6):
            raise ValueError(
                "questions with options must have between 2 and 6 entries"
            )
        for opt in options:
            if not isinstance(opt, str) or not opt.strip():
                raise ValueError("every option must be a non-empty string")
        if correct_answer not in options:
            raise ValueError("correct_answer must match one of the options")


class QuestionCreate(BaseModel):
    """Admin-write payload for a question (Req 16.2, 18.1, 18.2, 18.3)."""

    subtopic_id: int
    level_scope: LevelScope
    stem: str = Field(min_length=1)
    options: list[str] | None = None
    correct_answer: str = Field(min_length=1)
    explanation: str = Field(min_length=1)
    difficulty: Difficulty
    qtype: QuestionType

    @model_validator(mode="after")
    def _enforce_quality_rules(self) -> "QuestionCreate":
        _validate_question_payload(
            qtype=self.qtype,
            options=self.options,
            correct_answer=self.correct_answer,
        )
        return self


class QuestionUpdate(BaseModel):
    """Partial update payload. Cross-field rules run only when the relevant
    fields are present together; partial PATCHes that don't touch
    ``qtype``/``options``/``correct_answer`` skip the cross-field check.
    """

    level_scope: LevelScope | None = None
    stem: str | None = Field(default=None, min_length=1)
    options: list[str] | None = None
    correct_answer: str | None = Field(default=None, min_length=1)
    explanation: str | None = Field(default=None, min_length=1)
    difficulty: Difficulty | None = None
    qtype: QuestionType | None = None
    is_active: bool | None = None

    @model_validator(mode="after")
    def _enforce_quality_rules(self) -> "QuestionUpdate":
        # Only run cross-field validation when all three of the relevant
        # fields are present in the patch — otherwise the caller is asking
        # for a metadata-only edit and the service will combine with stored
        # values before re-validating.
        if (
            self.qtype is not None
            and self.correct_answer is not None
            and "options" in self.model_fields_set
        ):
            _validate_question_payload(
                qtype=self.qtype,
                options=self.options,
                correct_answer=self.correct_answer,
            )
        return self


class QuestionResponse(BaseModel):
    """Admin / submitted-quiz read shape — includes correct_answer + explanation.

    The quiz / mock-exam slice projects this down to ``QuestionInProgressResponse``
    for any in-progress attempt so mid-attempt requests cannot leak the
    answer (Req 7.4).
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    subtopic_id: int
    topic_id: int
    module_id: int
    category: Category
    level_scope: LevelScope
    stem: str
    options: list[str] | None
    correct_answer: str
    explanation: str
    difficulty: Difficulty
    qtype: QuestionType
    is_active: bool


class QuestionInProgressResponse(BaseModel):
    """Slim read shape used during an active quiz/mock attempt (Req 7.4).

    Lives in the content slice because the content layer owns "what a
    question looks like on the wire". The quiz/mock services build this
    projection from a full ``Question`` row.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    stem: str
    options: list[str] | None
    qtype: QuestionType
