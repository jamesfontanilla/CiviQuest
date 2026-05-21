"""SQLAlchemy ORM models for the quizzes slice (Task 11.1).

Two tables live here per design ``Progress and attempts``:

- :class:`QuizAttempt` — the lifecycle row for a single (subtopic|topic|
  module) quiz attempt by one user. Carries the assembly ``seed`` so
  reproductions and audits can rebuild the exact question set, and a
  nullable UNIQUE ``client_event_id`` for offline-sync idempotency
  (Req 20.3, Req 14.1).
- :class:`QuizAttemptAnswer` — one row per question on the attempt.
  ``ordinal`` pins the display position so a refresh / resume can
  redraw the same order without recomputing from the seed. The
  ``displayed_options`` JSON column stores the per-attempt shuffled
  option order for ``MULTIPLE_CHOICE`` questions; non-MC questions
  leave it ``NULL``. ``selected_answer`` and ``is_correct`` are both
  nullable: ``selected_answer`` until the learner answers,
  ``is_correct`` until the attempt is graded at submit.

Why store ``displayed_options`` instead of re-deriving from the seed:
- Storage is the source of truth for "what the learner saw". A future
  schema change to the per-question option set must not retroactively
  alter what answers a graded attempt was scored against.
- A resume read is a single indexed query, no Python re-shuffle on the
  hot path.
- The seed remains useful for audit (Req 21) — it lets an admin
  reproduce the assembly decision (which questions were drawn) but the
  per-attempt option order is durably attached to the attempt.

Indexes critical to the lookups in :class:`QuizRepository`:

- ``(user_id, status)`` — "find this user's in-progress attempts" lookup
  used by the resume snapshot (Req 14.2) and the prerequisite-gate
  query that walks "all subtopic-quizzes the user has passed".
- UNIQUE ``client_event_id`` — at-most-once retry semantics for offline
  sync.
- UNIQUE ``(attempt_id, question_id)`` — a question appears at most once
  per attempt; the assembler relies on this to tell duplicates apart
  from a legitimate retry.
- UNIQUE ``(attempt_id, ordinal)`` — display order is a permutation of
  ``1..N``; no two answers share a slot.

Foreign-key cascades match design — deleting a User cascades to every
attempt; deleting an attempt cascades to every answer row.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base


class QuizAttemptStatus(str, Enum):
    """Lifecycle state for a quiz attempt row."""

    IN_PROGRESS = "IN_PROGRESS"
    SUBMITTED = "SUBMITTED"


# Reusable CHECK fragments. Kept as constants so they line up exactly with
# the enum values above and don't drift if a new state is ever added.
_QUIZ_STATUS_VALUES = "('IN_PROGRESS', 'SUBMITTED')"
_LEVEL_SCOPE_VALUES = "('SUBTOPIC', 'TOPIC', 'MODULE')"


class QuizAttempt(Base):
    """One quiz attempt by a single user at a single scope.

    ``scope_level`` + ``scope_id`` together identify the quiz pool the
    attempt was assembled against (e.g. ``SUBTOPIC, 17``). The pair is
    not a foreign key because the target table varies by scope; the
    service layer is responsible for resolving the scope-specific row
    and applying the category-isolation policy.

    ``max_score`` is captured at start time so a subsequent change to
    the underlying question pool (e.g. an admin adds another question)
    does not retroactively change the denominator for an already-running
    attempt. ``score`` stays NULL until submit.
    """

    __tablename__ = "quiz_attempts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    scope_level: Mapped[str] = mapped_column(String(16), nullable=False)
    scope_id: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=QuizAttemptStatus.IN_PROGRESS.value,
        server_default=QuizAttemptStatus.IN_PROGRESS.value,
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    submitted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_score: Mapped[int] = mapped_column(Integer, nullable=False)
    # 64-bit seed captured at assembly time for audit / reproducibility
    # (Req 21). ``BigInteger`` because ``rng.randbits(64)`` returns
    # values up to 2**64 - 1.
    seed: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # Optional countdown timer in seconds chosen by the learner at
    # start time (practice=1200, exam=900, power=600). NULL means no
    # timer was selected (legacy attempts or topic/module quizzes).
    time_limit_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    client_event_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        CheckConstraint(
            f"status IN {_QUIZ_STATUS_VALUES}", name="ck_quiz_attempts_status"
        ),
        CheckConstraint(
            f"scope_level IN {_LEVEL_SCOPE_VALUES}",
            name="ck_quiz_attempts_scope_level",
        ),
        UniqueConstraint(
            "client_event_id", name="uq_quiz_attempts_client_event_id"
        ),
        # "Find user's in-progress attempts" — used by snapshot reads
        # (Req 14.2) and prerequisite-gate joins (Req 8.1, 9.1).
        Index("ix_quiz_attempts_user_status", "user_id", "status"),
    )


class QuizAttemptAnswer(Base):
    """One row per (attempt, question) pair.

    ``ordinal`` is 1-indexed so the UI can render "Question 7 of 20"
    without a translation step.

    ``displayed_options`` snapshots the per-attempt shuffled option
    order for ``MULTIPLE_CHOICE`` questions. ``NULL`` for non-MC types
    or when no options were captured. The shuffle happens once at
    start-quiz time and is the canonical "what the learner saw" record
    for the duration of the attempt.

    ``selected_answer`` is NULL until the learner submits an answer for
    this question. ``is_correct`` is NULL until ``submit_attempt`` runs
    grading; mid-attempt reads MUST NOT include it (Req 7.4 — non-
    disclosure). The schema mirror of this row in
    ``app/features/quizzes/schemas.py`` enforces that on the wire.
    """

    __tablename__ = "quiz_attempt_answers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    attempt_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("quiz_attempts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    question_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("questions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    displayed_options: Mapped[list | None] = mapped_column(JSON, nullable=True)
    selected_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    answered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint(
            "attempt_id",
            "question_id",
            name="uq_quiz_attempt_answers_attempt_question",
        ),
        UniqueConstraint(
            "attempt_id",
            "ordinal",
            name="uq_quiz_attempt_answers_attempt_ordinal",
        ),
    )
