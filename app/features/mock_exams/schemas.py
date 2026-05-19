"""Pydantic schemas for the mock-exam slice (Task 12.5).

Three response shapes per attempt lifecycle stage:

- :class:`MockExamStartResponse` — for the POST start surface. Carries
  the assembled questions in the in-progress shape (no correctness
  fields per Property 17 / Req 10.4) plus the server-authoritative
  timer state.
- :class:`MockExamAttemptResponse` — for the GET surface while
  ``status == IN_PROGRESS``. Same in-progress question shape; carries
  ``remaining_seconds`` for the live UI countdown.
- :class:`MockExamSubmittedResponse` — for the GET surface on submitted
  attempts and the POST ``:submit`` return. Carries score, percentage,
  passed flag, per-module breakdown, weakness summary, and the full
  graded question list (Req 10.5, Property 35).

The PATCH-answer / focus-loss request bodies are minimal one-or-two
field schemas with strict bounds; ``extra="forbid"`` keeps the wire
contract tight.

Reuses :class:`QuizAttemptInProgressQuestion` and
:class:`QuizGradedQuestion` from the quizzes slice — the per-question
shape is identical and there's no reason to maintain a parallel
hierarchy.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.features.quizzes.schemas import (
    QuizAnswerPatchRequest,
    QuizAttemptInProgressQuestion,
    QuizGradedQuestion,
)
from app.features.users.models import Category


# Re-export the answer PATCH schema so callers don't reach across slices.
# The mock-exam PATCH body is byte-identical to the quiz PATCH body
# (one ``selected_answer`` field bounded to 1..512 characters) so
# duplicating the class would be pure noise.
MockAnswerPatchRequest = QuizAnswerPatchRequest


class ModuleScoreBreakdown(BaseModel):
    """Per-module score record on a submitted mock attempt (Req 10.5).

    Used both inside :class:`MockExamSubmittedResponse.per_module_breakdown`
    and inside ``weakness_summary``. The field names mirror the
    design's catalog so leaderboard / UI consumers can address them
    without translation.
    """

    module_id: int
    title: str
    score: int
    max: int
    pct: float


class FocusLossReportRequest(BaseModel):
    """POST body for ``:report-focus-loss`` (Req 19.2).

    ``kind`` is a short string (UI-defined; e.g. ``"blur"``,
    ``"tab_switch"``) capped at 64 chars to keep an adversarial client
    from filling the JSON column. ``at`` is the client-recorded
    timestamp; the server records this verbatim alongside its own
    log line via the request-correlation middleware.

    The endpoint MUST NOT modify the timer (Req 19.2 / Property 30):
    an adversarial client cannot game the clock by spamming this
    route.
    """

    model_config = ConfigDict(extra="forbid")

    kind: str = Field(min_length=1, max_length=64)
    at: datetime


class MockExamStartResponse(BaseModel):
    """Response shape for ``POST /v1/mock-exams/attempts``.

    Property 17 / Req 10.4: the in-progress question shape carries no
    correctness fields. The schema below intentionally embeds the
    same :class:`QuizAttemptInProgressQuestion` used by the quizzes
    slice so that compliance can be enforced once.
    """

    attempt_id: int
    category: Category
    started_at: datetime
    time_limit_minutes: int
    remaining_seconds: int
    nav_policy: str
    questions: list[QuizAttemptInProgressQuestion]
    total_questions: int


class MockExamAttemptResponse(BaseModel):
    """Response shape for ``GET /v1/mock-exams/attempts/{id}`` while IN_PROGRESS.

    Mirror of :class:`MockExamStartResponse` plus an explicit ``status``
    field. The router's GET handler returns this when the attempt is
    still IN_PROGRESS; if the attempt is already submitted (or just
    auto-submitted by the timer check), it returns
    :class:`MockExamSubmittedResponse` instead — the GET is
    polymorphic, see ``router.py``.
    """

    attempt_id: int
    category: Category
    started_at: datetime
    time_limit_minutes: int
    remaining_seconds: int
    nav_policy: str
    status: str  # "IN_PROGRESS"
    questions: list[QuizAttemptInProgressQuestion]
    total_questions: int


class MockExamSubmittedResponse(BaseModel):
    """Response shape for submitted / auto-submitted attempts (Req 10.5).

    Property 35: every required field present, ``weakness_summary``
    ordered ascending by ``pct`` with deterministic tie-break by
    ``module_id``, length min(3, n_modules). The clamp is documented
    in :meth:`MockExamService._build_submitted_response` — Req 10.5
    says "three Modules with the lowest score percentages" but if the
    pool has only two modules we return what we have rather than
    fabricating a third.
    """

    attempt_id: int
    category: Category
    status: str  # "SUBMITTED" or "AUTO_SUBMITTED"
    submission_mode: str  # "MANUAL" or "AUTO_SUBMIT"
    started_at: datetime
    submitted_at: datetime
    score: int
    max_score: int
    percentage: float
    passed: bool
    awarded_xp: int
    per_module_breakdown: list[ModuleScoreBreakdown]
    weakness_summary: list[ModuleScoreBreakdown]
    questions: list[QuizGradedQuestion]
