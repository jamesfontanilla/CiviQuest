"""Pydantic schemas for the quizzes slice (Task 11.4).

Two response shapes per attempt lifecycle stage:

- :class:`QuizAttemptInProgressResponse` — for ``status == IN_PROGRESS``.
  No correctness fields; satisfies Property 17 (mid-attempt
  non-disclosure, Req 7.4).
- :class:`QuizSubmittedResponse` — for ``status == SUBMITTED``. Carries
  per-question ``correct_answer`` / ``is_correct`` / ``explanation``
  plus aggregate stats and awarded XP (Req 7.5).

The PATCH-answer request body is a one-field schema with strict bounds
to keep injection / oversized-payload risk minimal.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.features.content.models import LevelScope, QuestionType


# --- mid-attempt question shape --------------------------------------------


class QuizAttemptInProgressQuestion(BaseModel):
    """A question as the learner sees it during an in-progress attempt.

    Property 17: this shape MUST NOT contain ``correct_answer``,
    ``is_correct``, or ``explanation``. The fields below are
    intentionally an exhaustive enumeration so any future addition has
    to consciously decide whether it's safe to disclose.
    """

    id: int
    ordinal: int
    stem: str
    qtype: QuestionType
    # Per-attempt shuffled options for MULTIPLE_CHOICE; ``None`` for
    # free-text qtypes.
    options: list[str] | None
    # The learner's last submitted choice for this question, or ``None``
    # if they haven't answered yet. Showing the selection back is safe
    # — the rule is "don't reveal correctness".
    selected_answer: str | None


class QuizAttemptInProgressResponse(BaseModel):
    """Response shape for in-progress GETs and start-quiz returns."""

    attempt_id: int
    scope_level: LevelScope
    scope_id: int
    status: str  # "IN_PROGRESS"
    started_at: datetime
    questions: list[QuizAttemptInProgressQuestion]
    total_questions: int


# --- answer PATCH request --------------------------------------------------


class QuizAnswerPatchRequest(BaseModel):
    """One-field PATCH body for ``/quiz-attempts/{id}/answers/{qid}``.

    ``min_length=1`` rejects the empty string (a deliberate "submit
    empty answer" should null out via a different route, not here).
    ``max_length=512`` is large enough for any sensible
    multiple-choice option label or short identification answer while
    bounding payload size.
    """

    model_config = ConfigDict(extra="forbid")

    selected_answer: str = Field(min_length=1, max_length=512)


# --- submitted-attempt question shape --------------------------------------


class QuizGradedQuestion(BaseModel):
    """A graded question record (Req 7.5).

    Mirrors :class:`~app.features.quizzes.algorithms.grading.GradedAnswer`
    on the wire; the service projects one to the other directly.
    """

    id: int
    ordinal: int
    stem: str
    selected_answer: str | None
    correct_answer: str
    is_correct: bool
    explanation: str


class QuizSubmittedResponse(BaseModel):
    """Response shape for submit + GET-on-already-submitted reads."""

    attempt_id: int
    scope_level: LevelScope
    scope_id: int
    status: str  # "SUBMITTED"
    started_at: datetime
    submitted_at: datetime
    score: int
    max_score: int
    percentage: float
    is_perfect: bool
    is_passing: bool
    awarded_xp: int
    questions: list[QuizGradedQuestion]
