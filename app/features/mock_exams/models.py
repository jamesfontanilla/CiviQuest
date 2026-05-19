"""SQLAlchemy ORM models for the mock-exam slice (Task 12.1).

Three tables live here per design ``Progress and attempts`` and the
mock-exam-config block:

- :class:`MockExamConfig` — one row per category (``PROFESSIONAL`` /
  ``SUB_PROFESSIONAL``) carrying the assembly weights, time limit, and
  navigation policy. Validated at admin write (Task 12.2).
- :class:`MockExamAttempt` — the lifecycle row for a single mock-exam
  attempt by one user. Carries the assembly seed (Req 21 audit), the
  ``focus_loss_events`` JSON list (Req 19.2), and snapshots
  ``nav_policy`` + ``time_limit_minutes`` from the config at start time
  so a config change mid-attempt does not retroactively alter timing
  or navigation rules.
- :class:`MockExamAttemptAnswer` — one row per question on the attempt.
  ``finalized_at`` is the LINEAR_NO_REVISIT lock (Req 19.4): once set,
  PATCHes against this answer return 409 ``question_finalized``.

Why ``focus_loss_events`` is a JSON list, not a separate table:
- The list is a per-attempt audit blob with no cross-attempt queries.
  A side table would add a join with no benefit.
- The events are tiny ``{kind, at}`` records and there's no expected
  read pattern beyond "fetch the attempt and look at the list".
- The mutation pattern is read-modify-write within the same attempt's
  transaction, which JSON columns handle correctly on SQLite.

Why a partial unique index on ``(user_id) WHERE status='IN_PROGRESS'``:
- Req 10.8 ("at most one in-progress mock attempt per user") and
  Property 36 demand storage-level enforcement under concurrency. A
  service-side check is racy; the partial unique index makes a
  duplicate IN_PROGRESS row impossible.
- SQLite supports partial unique indexes natively. The same syntax
  ports to Postgres without changes (the design's eventual-deployment
  story).

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
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base


class MockExamAttemptStatus(str, Enum):
    """Lifecycle state for a mock-exam attempt row."""

    IN_PROGRESS = "IN_PROGRESS"
    SUBMITTED = "SUBMITTED"
    AUTO_SUBMITTED = "AUTO_SUBMITTED"


class MockExamSubmissionMode(str, Enum):
    """How an attempt transitioned out of IN_PROGRESS."""

    MANUAL = "MANUAL"
    AUTO_SUBMIT = "AUTO_SUBMIT"


class MockExamNavPolicy(str, Enum):
    """Navigation policy snapshot on an attempt (Req 19.4)."""

    LINEAR_NO_REVISIT = "LINEAR_NO_REVISIT"
    FREE_NAV = "FREE_NAV"


# Reusable CHECK fragments. Inlining the SQL strings is fine but factoring
# them avoids drift if a new value is ever added.
_CATEGORY_VALUES = "('PROFESSIONAL', 'SUB_PROFESSIONAL')"
_MOCK_STATUS_VALUES = "('IN_PROGRESS', 'SUBMITTED', 'AUTO_SUBMITTED')"
_MOCK_SUBMISSION_MODE_VALUES = "('MANUAL', 'AUTO_SUBMIT')"
_MOCK_NAV_POLICY_VALUES = "('LINEAR_NO_REVISIT', 'FREE_NAV')"


class MockExamConfig(Base):
    """One row per CSE category with assembly + timing knobs.

    ``weights_json`` maps ``module_id`` (string-keyed because JSON
    dicts can't have integer keys on the wire) to the per-module
    sample count. The service-layer validator (:class:`MockExamService`
    Task 12.2) asserts ``sum(weights.values()) == total_questions`` and
    that every ``module_id`` references an existing module of the same
    ``category``. The CHECK constraints below cover the closed-set
    columns; the multi-column invariant is service-side because SQLite
    can't express it in DDL.
    """

    __tablename__ = "mock_exam_configs"

    category: Mapped[str] = mapped_column(String(32), primary_key=True)
    total_questions: Mapped[int] = mapped_column(Integer, nullable=False)
    # ``weights_json`` is ``{str(module_id): int(count)}``; the service
    # parses to ``int`` keys at use time.
    weights_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    time_limit_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False, default=180, server_default="180"
    )
    nav_policy: Mapped[str] = mapped_column(String(32), nullable=False)
    pass_threshold: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.80, server_default="0.80"
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
            f"category IN {_CATEGORY_VALUES}",
            name="ck_mock_exam_configs_category",
        ),
        CheckConstraint(
            f"nav_policy IN {_MOCK_NAV_POLICY_VALUES}",
            name="ck_mock_exam_configs_nav_policy",
        ),
    )


class MockExamAttempt(Base):
    """One mock-exam attempt by a single user (Req 10.1, 10.2, 10.7, 10.8).

    The denormalized ``category`` column matches the corresponding
    config row's category. Snapshotting ``nav_policy`` and
    ``time_limit_minutes`` here protects in-flight attempts from
    config edits.

    ``focus_loss_events`` is a JSON list of ``{"kind": str, "at": ISO}``
    entries appended by ``POST :report-focus-loss`` (Req 19.2). The
    column starts as ``[]`` so a freshly-created attempt's list is
    never ``None``.

    ``submitted_at`` and ``submission_mode`` are NULL while
    ``status == IN_PROGRESS`` and populated together at submit time.
    The ``CHECK`` allows ``NULL`` for ``submission_mode`` so the
    column doesn't fight the lifecycle.
    """

    __tablename__ = "mock_exam_attempts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=MockExamAttemptStatus.IN_PROGRESS.value,
        server_default=MockExamAttemptStatus.IN_PROGRESS.value,
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    submitted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    submission_mode: Mapped[str | None] = mapped_column(
        String(16), nullable=True
    )
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_score: Mapped[int] = mapped_column(Integer, nullable=False)
    # 64-bit seed captured at assembly time for audit / reproducibility
    # (Req 21). ``BigInteger`` matches the quizzes-slice precedent.
    seed: Mapped[int] = mapped_column(BigInteger, nullable=False)
    focus_loss_events: Mapped[list] = mapped_column(
        JSON, nullable=False, default=list, server_default="[]"
    )
    nav_policy: Mapped[str] = mapped_column(String(32), nullable=False)
    time_limit_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
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
            f"category IN {_CATEGORY_VALUES}",
            name="ck_mock_exam_attempts_category",
        ),
        CheckConstraint(
            f"status IN {_MOCK_STATUS_VALUES}",
            name="ck_mock_exam_attempts_status",
        ),
        CheckConstraint(
            f"submission_mode IS NULL OR submission_mode IN "
            f"{_MOCK_SUBMISSION_MODE_VALUES}",
            name="ck_mock_exam_attempts_submission_mode",
        ),
        CheckConstraint(
            f"nav_policy IN {_MOCK_NAV_POLICY_VALUES}",
            name="ck_mock_exam_attempts_nav_policy",
        ),
        # Property 36 / Req 10.8 — at most one IN_PROGRESS row per user.
        # SQLite supports partial unique indexes via ``sqlite_where``; the
        # same syntax ports to Postgres if/when the deployment story
        # changes.
        Index(
            "uq_mock_exam_in_progress",
            "user_id",
            unique=True,
            sqlite_where=text("status = 'IN_PROGRESS'"),
            postgresql_where=text("status = 'IN_PROGRESS'"),
        ),
    )


class MockExamAttemptAnswer(Base):
    """One row per (attempt, question) pair on a mock-exam attempt.

    ``ordinal`` is 1-indexed so the UI can render "Question 7 of 50"
    without translation. ``displayed_options`` snapshots the
    per-attempt shuffled option order for ``MULTIPLE_CHOICE``
    questions (Req 7.3 applied to mock per A1).

    ``selected_answer`` is NULL until the learner answers; ``is_correct``
    is NULL until the attempt is graded at submit (Req 10.4 / Req 7.4
    mid-attempt non-disclosure).

    ``finalized_at`` is the LINEAR_NO_REVISIT lock (Req 19.4): when
    nav_policy is LINEAR_NO_REVISIT, the service stamps this column
    on each set-answer (one-shot per question), and subsequent
    PATCHes return 409 ``question_finalized`` (Property 31). When
    nav_policy is FREE_NAV, ``finalized_at`` stays NULL and PATCHes
    succeed indefinitely while the attempt is IN_PROGRESS.
    """

    __tablename__ = "mock_exam_attempt_answers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    attempt_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("mock_exam_attempts.id", ondelete="CASCADE"),
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
    displayed_options: Mapped[list | None] = mapped_column(
        JSON, nullable=True
    )
    selected_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    answered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finalized_at: Mapped[datetime | None] = mapped_column(
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
            "ordinal",
            name="uq_mock_exam_attempt_answers_attempt_ordinal",
        ),
        UniqueConstraint(
            "attempt_id",
            "question_id",
            name="uq_mock_exam_attempt_answers_attempt_question",
        ),
    )
