"""Repository for the mock-exam slice (Task 12.1).

A single :class:`MockExamRepository` owns reads and writes for all
three mock-exam tables. The class extends
``BaseRepository[MockExamAttempt]`` because the attempt row is the
busy table — most reads target it. :class:`MockExamConfig` and
:class:`MockExamAttemptAnswer` get dedicated helpers on the same
class rather than separate repositories; the slice convention is "one
``repository.py`` per feature" and these tables co-evolve
transactionally.

Key design choices:

- **Authorization at lookup.** :meth:`get_attempt_for_user` returns
  ``None`` when the attempt belongs to another user. The service
  layer treats ``None`` as 403 ``forbidden`` (Property 12) — never
  404, so an attacker cannot probe attempt-id existence by comparing
  status codes.
- **At-most-one-in-progress is DB-enforced.** The partial unique
  index on :class:`MockExamAttempt` makes the duplicate IN_PROGRESS
  case impossible at the storage layer (Req 10.8 / Property 36). The
  service-level check is defense at the boundary; under concurrent
  requests one could slip past, and the SQL constraint is the
  canonical guarantee.
- **Bulk insert at start.** :meth:`add_attempt_questions` builds
  N answer rows in one transaction. The assembler picks the question
  set; the service shuffles MC options per question and hands the
  resulting (question_id, ordinal, displayed_options) tuples here.
- **Submit is a single commit.** :meth:`submit_attempt` flips status,
  stamps ``submitted_at`` + ``submission_mode``, sets ``score``,
  and writes per-row ``is_correct`` corrections — all in one
  transaction. No partial-submit state exists.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.features.mock_exams.models import (
    MockExamAttempt,
    MockExamAttemptAnswer,
    MockExamAttemptStatus,
    MockExamConfig,
    MockExamNavPolicy,
    MockExamSubmissionMode,
)
from app.features.users.models import Category
from app.infrastructure.repositories.base import BaseRepository


class MockExamRepository(BaseRepository[MockExamAttempt]):
    """Persistence for mock-exam configs, attempts, and answer rows."""

    model = MockExamAttempt

    def __init__(self, db: Session) -> None:
        super().__init__(db=db)

    # ------------------------------------------------------------------
    # MockExamConfig
    # ------------------------------------------------------------------

    def get_config(self, category: Category) -> MockExamConfig | None:
        """Return the config row for ``category`` or ``None`` if absent."""
        return self.db.get(MockExamConfig, category.value)

    def upsert_config(
        self,
        *,
        category: Category,
        total_questions: int,
        weights_json: dict[str, int],
        time_limit_minutes: int = 180,
        nav_policy: MockExamNavPolicy = MockExamNavPolicy.LINEAR_NO_REVISIT,
        pass_threshold: float = 0.80,
    ) -> MockExamConfig:
        """Insert or update the config for ``category``.

        Used by admin/seed paths. The validation that
        ``sum(weights_json.values()) == total_questions`` and that every
        ``module_id`` references an existing module of the matching
        category lives in the service layer (Task 12.2).
        """
        existing = self.get_config(category)
        if existing is None:
            row = MockExamConfig(
                category=category.value,
                total_questions=total_questions,
                weights_json=weights_json,
                time_limit_minutes=time_limit_minutes,
                nav_policy=nav_policy.value,
                pass_threshold=pass_threshold,
            )
            self.db.add(row)
            self.db.commit()
            self.db.refresh(row)
            return row

        existing.total_questions = total_questions
        existing.weights_json = weights_json
        existing.time_limit_minutes = time_limit_minutes
        existing.nav_policy = nav_policy.value
        existing.pass_threshold = pass_threshold
        self.db.commit()
        self.db.refresh(existing)
        return existing

    # ------------------------------------------------------------------
    # MockExamAttempt
    # ------------------------------------------------------------------

    def create_attempt(
        self,
        *,
        user_id: int,
        category: Category,
        started_at: datetime,
        max_score: int,
        seed: int,
        nav_policy: MockExamNavPolicy,
        time_limit_minutes: int,
    ) -> MockExamAttempt:
        """Insert a fresh ``IN_PROGRESS`` mock-exam attempt.

        Caller is expected to follow up with
        :meth:`add_attempt_questions` to populate the answer rows in
        the same logical operation. The partial unique index will
        raise :class:`IntegrityError` if the user already has an
        IN_PROGRESS attempt; the service layer catches this and
        translates it to 409 ``mock_exam_in_progress``.
        """
        row = MockExamAttempt(
            user_id=user_id,
            category=category.value,
            status=MockExamAttemptStatus.IN_PROGRESS.value,
            started_at=started_at,
            max_score=max_score,
            seed=seed,
            focus_loss_events=[],
            nav_policy=nav_policy.value,
            time_limit_minutes=time_limit_minutes,
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def get_attempt(self, attempt_id: int) -> MockExamAttempt | None:
        """Single-row lookup by primary key."""
        return self.db.get(MockExamAttempt, attempt_id)

    def get_attempt_for_user(
        self, attempt_id: int, user_id: int
    ) -> MockExamAttempt | None:
        """Return the attempt iff it belongs to ``user_id``.

        Returning ``None`` for "exists but wrong owner" lets the
        service raise a uniform 403 without leaking existence through
        a 404-vs-403 distinction.
        """
        attempt = self.db.get(MockExamAttempt, attempt_id)
        if attempt is None or attempt.user_id != user_id:
            return None
        return attempt

    def get_in_progress_for_user(
        self, user_id: int
    ) -> MockExamAttempt | None:
        """Return the at-most-one IN_PROGRESS attempt for ``user_id``.

        The partial unique index guarantees at most one row matches;
        the helper returns it for snapshot reads (Req 14.2) and for
        the service-side pre-check that complements the
        ``require_no_active_mock`` dependency.
        """
        stmt = (
            select(MockExamAttempt)
            .where(MockExamAttempt.user_id == user_id)
            .where(
                MockExamAttempt.status
                == MockExamAttemptStatus.IN_PROGRESS.value
            )
        )
        return self.db.execute(stmt).scalar_one_or_none()

    # ------------------------------------------------------------------
    # MockExamAttemptAnswer
    # ------------------------------------------------------------------

    def add_attempt_questions(
        self,
        attempt_id: int,
        *,
        rows: list[dict[str, Any]],
    ) -> list[MockExamAttemptAnswer]:
        """Bulk-insert answer rows for a fresh attempt.

        ``rows`` is a list of dicts with keys
        ``{question_id, ordinal, displayed_options}``. The UNIQUE
        constraints on ``(attempt_id, ordinal)`` and
        ``(attempt_id, question_id)`` keep ordinals a permutation of
        1..N and prevent question duplicates.
        """
        instances = [
            MockExamAttemptAnswer(
                attempt_id=attempt_id,
                question_id=row["question_id"],
                ordinal=row["ordinal"],
                displayed_options=row.get("displayed_options"),
            )
            for row in rows
        ]
        for inst in instances:
            self.db.add(inst)
        self.db.commit()
        for inst in instances:
            self.db.refresh(inst)
        return instances

    def get_answer(
        self, attempt_id: int, question_id: int
    ) -> MockExamAttemptAnswer | None:
        """Look up a single (attempt, question) row."""
        stmt = select(MockExamAttemptAnswer).where(
            MockExamAttemptAnswer.attempt_id == attempt_id,
            MockExamAttemptAnswer.question_id == question_id,
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def list_attempt_answers(
        self, attempt_id: int
    ) -> list[MockExamAttemptAnswer]:
        """Return every answer row for ``attempt_id`` ordered by ordinal."""
        stmt = (
            select(MockExamAttemptAnswer)
            .where(MockExamAttemptAnswer.attempt_id == attempt_id)
            .order_by(MockExamAttemptAnswer.ordinal)
        )
        return list(self.db.execute(stmt).scalars().all())

    def set_answer(
        self,
        *,
        attempt_id: int,
        question_id: int,
        selected_answer: str,
        answered_at: datetime,
        finalized_at: datetime | None = None,
    ) -> MockExamAttemptAnswer:
        """Update the learner's selected answer for a question.

        Looks up the existing row (created at start time by
        :meth:`add_attempt_questions`) and overwrites
        ``selected_answer`` / ``answered_at``. When ``finalized_at``
        is provided (LINEAR_NO_REVISIT path), it is stamped in the
        same write — but only if the row is not already finalized.
        Re-finalizing a row would let a careless caller bypass the
        Property 31 lock; the service layer is responsible for the
        409 ``question_finalized`` check before calling this. Raises
        :class:`LookupError` if the row is missing.
        """
        row = self.get_answer(attempt_id, question_id)
        if row is None:
            raise LookupError(
                f"No answer row for attempt={attempt_id} question={question_id}"
            )
        row.selected_answer = selected_answer
        row.answered_at = answered_at
        if finalized_at is not None and row.finalized_at is None:
            row.finalized_at = finalized_at
        self.db.commit()
        self.db.refresh(row)
        return row

    def mark_finalized(
        self, *, attempt_id: int, ordinal: int, finalized_at: datetime
    ) -> MockExamAttemptAnswer | None:
        """Stamp ``finalized_at`` on the answer row at ``ordinal``.

        Returns the updated row, or ``None`` if no such row exists.
        Used by the LINEAR_NO_REVISIT progression (one-shot per
        question — when the learner moves on, the prior row is
        locked).
        """
        stmt = select(MockExamAttemptAnswer).where(
            MockExamAttemptAnswer.attempt_id == attempt_id,
            MockExamAttemptAnswer.ordinal == ordinal,
        )
        row = self.db.execute(stmt).scalar_one_or_none()
        if row is None:
            return None
        if row.finalized_at is None:
            row.finalized_at = finalized_at
            self.db.commit()
            self.db.refresh(row)
        return row

    # ------------------------------------------------------------------
    # submit_attempt
    # ------------------------------------------------------------------

    def submit_attempt(
        self,
        attempt_id: int,
        *,
        score: int,
        submitted_at: datetime,
        submission_mode: MockExamSubmissionMode,
        answer_corrections: list[dict[str, Any]],
    ) -> MockExamAttempt:
        """Transition an attempt out of IN_PROGRESS with grading results.

        ``submission_mode`` selects between ``MANUAL`` (learner-driven
        ``:submit``) and ``AUTO_SUBMIT`` (timer expiry).
        ``answer_corrections`` is a list of
        ``{"question_id": int, "is_correct": bool}`` entries, one per
        graded question. Each is applied via the natural-key UNIQUE
        so the order of ``answer_corrections`` is irrelevant. The
        whole thing commits in a single transaction so an attempt
        never ends up in a half-graded state.

        The new ``status`` is ``AUTO_SUBMITTED`` for the timer-expiry
        path and ``SUBMITTED`` for the manual path — the design
        distinguishes them so analytics can separate "learner ran out
        of time" from "learner finished".
        """
        attempt = self.get_attempt(attempt_id)
        if attempt is None:
            raise LookupError(f"No mock-exam attempt with id={attempt_id}")

        for correction in answer_corrections:
            answer = self.get_answer(attempt_id, correction["question_id"])
            if answer is None:
                raise LookupError(
                    f"No answer row to grade for attempt={attempt_id} "
                    f"question={correction['question_id']}"
                )
            answer.is_correct = bool(correction["is_correct"])

        if submission_mode == MockExamSubmissionMode.AUTO_SUBMIT:
            attempt.status = MockExamAttemptStatus.AUTO_SUBMITTED.value
        else:
            attempt.status = MockExamAttemptStatus.SUBMITTED.value
        attempt.submission_mode = submission_mode.value
        attempt.score = score
        attempt.submitted_at = submitted_at

        self.db.commit()
        self.db.refresh(attempt)
        return attempt

    # ------------------------------------------------------------------
    # Focus-loss events
    # ------------------------------------------------------------------

    def append_focus_loss(
        self,
        attempt_id: int,
        *,
        kind: str,
        at: datetime,
    ) -> MockExamAttempt:
        """Append a ``{kind, at}`` entry to the attempt's focus-loss list.

        Read-modify-write on the JSON column. SQLAlchemy detects the
        attribute reassignment via mutation tracking; we explicitly
        reassign the list rather than mutating in place so the change
        is observable across SQLAlchemy versions.
        """
        attempt = self.get_attempt(attempt_id)
        if attempt is None:
            raise LookupError(f"No mock-exam attempt with id={attempt_id}")

        events = list(attempt.focus_loss_events or [])
        events.append({"kind": kind, "at": at.isoformat()})
        attempt.focus_loss_events = events
        self.db.commit()
        self.db.refresh(attempt)
        return attempt

    # Alias kept so the design-doc-named method exists. Some callers
    # may prefer ``update_focus_loss`` for symmetry with other "update"
    # verbs in the slice; both delegate to the same logic.
    update_focus_loss = append_focus_loss
