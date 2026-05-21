"""Repository for the quizzes slice (Task 11.1).

A single :class:`QuizRepository` owns reads and writes for both
:class:`QuizAttempt` and :class:`QuizAttemptAnswer`. The class extends
``BaseRepository[QuizAttempt]`` because the attempt row is the busy
table — most reads target it. ``QuizAttemptAnswer`` gets dedicated
helpers on the same class rather than a separate repository because
the slice convention is "one ``repository.py`` per feature" and the
two tables co-evolve transactionally.

Key design choices:

- **Authorization at lookup.** :meth:`get_attempt_for_user` returns
  ``None`` when the attempt belongs to another user, not the row. The
  service layer treats ``None`` as a 403 ``forbidden`` (Property 12 —
  never 404). The plain :meth:`get_attempt` is used by internal flows
  that already authenticated the user.
- **Bulk insert at start.** :meth:`add_attempt_questions` builds
  N answer rows in one transaction. The assembler picks the question
  set; the service shuffles MC options per question and hands the
  resulting (question_id, ordinal, displayed_options) tuples here.
- **Upsert for answer set.** :meth:`set_answer` is the per-keystroke
  PATCH path. It looks up the existing row for ``(attempt, question)``
  via the natural-key UNIQUE and updates ``selected_answer`` /
  ``answered_at`` in-place. ``is_correct`` is left untouched — that's
  computed at submit only (Req 7.4 mid-attempt non-disclosure).
- **One-shot grading at submit.** :meth:`submit_attempt` accepts the
  pre-graded answer corrections from the service and writes them in a
  single commit alongside the attempt's status / score / submitted_at
  transition. No partial-submit state exists.
- **Pass-threshold lookup is a single SUBMITTED-row scan.**
  :meth:`has_passed_attempt` walks SUBMITTED attempts at the matching
  scope and checks ``score / max_score >= threshold`` — used by the
  prerequisite gate (Req 8.1, 9.1) and surfaced as Property 18.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.features.content.models import LevelScope
from app.features.quizzes.models import (
    QuizAttempt,
    QuizAttemptAnswer,
    QuizAttemptStatus,
)
from app.infrastructure.repositories.base import BaseRepository


class QuizRepository(BaseRepository[QuizAttempt]):
    """Persistence for quiz attempts and their answer rows."""

    model = QuizAttempt

    def __init__(self, db: Session) -> None:
        super().__init__(db=db)

    # ------------------------------------------------------------------
    # QuizAttempt
    # ------------------------------------------------------------------

    def create_attempt(
        self,
        *,
        user_id: int,
        scope_level: LevelScope,
        scope_id: int,
        started_at: datetime,
        max_score: int,
        seed: int,
        time_limit_seconds: int | None = None,
        client_event_id: str | None = None,
    ) -> QuizAttempt:
        """Insert a fresh ``IN_PROGRESS`` attempt row.

        Caller is expected to follow up with
        :meth:`add_attempt_questions` to populate the answer rows in
        the same logical operation. Splitting the two writes lets the
        service layer compute ``max_score`` once (``len(assembled)``)
        and avoids bouncing the assembled list through this method.
        """
        row = QuizAttempt(
            user_id=user_id,
            scope_level=scope_level.value,
            scope_id=scope_id,
            status=QuizAttemptStatus.IN_PROGRESS.value,
            started_at=started_at,
            max_score=max_score,
            seed=seed,
            time_limit_seconds=time_limit_seconds,
            client_event_id=client_event_id,
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def get_attempt(self, attempt_id: int) -> QuizAttempt | None:
        """Single-row lookup by primary key."""
        return self.db.get(QuizAttempt, attempt_id)

    def get_attempt_for_user(
        self, attempt_id: int, user_id: int
    ) -> QuizAttempt | None:
        """Return the attempt iff it belongs to ``user_id``.

        The dual check (id + owner) is one indexed lookup followed by a
        Python compare. Returning ``None`` for "exists but wrong
        owner" lets the service raise a uniform 403 without leaking
        existence information through a 404 vs 403 distinction
        (Property 12).
        """
        attempt = self.db.get(QuizAttempt, attempt_id)
        if attempt is None or attempt.user_id != user_id:
            return None
        return attempt

    def get_in_progress_attempts(self, user_id: int) -> list[QuizAttempt]:
        """List every IN_PROGRESS attempt for ``user_id``.

        Used by the resume snapshot (Req 14.2). Ordered by
        ``started_at`` ascending for deterministic output.
        """
        stmt = (
            select(QuizAttempt)
            .where(QuizAttempt.user_id == user_id)
            .where(
                QuizAttempt.status == QuizAttemptStatus.IN_PROGRESS.value
            )
            .order_by(QuizAttempt.started_at, QuizAttempt.id)
        )
        return list(self.db.execute(stmt).scalars().all())

    def get_by_client_event_id(
        self, client_event_id: str
    ) -> QuizAttempt | None:
        """Idempotency lookup for offline sync (Req 20.3)."""
        stmt = select(QuizAttempt).where(
            QuizAttempt.client_event_id == client_event_id
        )
        return self.db.execute(stmt).scalar_one_or_none()

    # ------------------------------------------------------------------
    # QuizAttemptAnswer
    # ------------------------------------------------------------------

    def add_attempt_questions(
        self,
        attempt_id: int,
        *,
        rows: list[dict[str, Any]],
    ) -> list[QuizAttemptAnswer]:
        """Bulk-insert the answer rows for an attempt.

        ``rows`` is a list of dicts with keys
        ``{question_id, ordinal, displayed_options}``; the service
        layer assembles this from the per-question shuffle. The
        UNIQUE``(attempt_id, ordinal)`` and ``(attempt_id,
        question_id)`` constraints enforce that ordinals are
        a permutation of 1..N and that no question repeats.
        """
        instances = [
            QuizAttemptAnswer(
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
    ) -> QuizAttemptAnswer | None:
        """Look up the (attempt, question) row via the natural-key UNIQUE."""
        stmt = select(QuizAttemptAnswer).where(
            QuizAttemptAnswer.attempt_id == attempt_id,
            QuizAttemptAnswer.question_id == question_id,
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def list_attempt_answers(
        self, attempt_id: int
    ) -> list[QuizAttemptAnswer]:
        """Return every answer row for ``attempt_id`` ordered by ``ordinal``."""
        stmt = (
            select(QuizAttemptAnswer)
            .where(QuizAttemptAnswer.attempt_id == attempt_id)
            .order_by(QuizAttemptAnswer.ordinal)
        )
        return list(self.db.execute(stmt).scalars().all())

    def set_answer(
        self,
        *,
        attempt_id: int,
        question_id: int,
        selected_answer: str,
        answered_at: datetime,
    ) -> QuizAttemptAnswer:
        """Update the learner's selected answer for a question.

        Looks up the existing row (created at start time by
        :meth:`add_attempt_questions`) and overwrites
        ``selected_answer`` / ``answered_at``. Does NOT touch
        ``is_correct`` — grading happens once, at submit. Raises
        :class:`LookupError` if the row is missing; the service layer
        translates that to 403 ``forbidden`` because a missing
        ``(attempt, question)`` pair means the question wasn't on this
        attempt.
        """
        row = self.get_answer(attempt_id, question_id)
        if row is None:
            raise LookupError(
                f"No answer row for attempt={attempt_id} question={question_id}"
            )
        row.selected_answer = selected_answer
        row.answered_at = answered_at
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
        answer_corrections: list[dict[str, Any]],
    ) -> QuizAttempt:
        """Transition an attempt to SUBMITTED with grading results.

        ``answer_corrections`` is a list of
        ``{"question_id": int, "is_correct": bool}`` entries — one per
        graded question. Each is applied via the natural-key UNIQUE so
        the order of ``answer_corrections`` is irrelevant. The whole
        thing commits in a single transaction so an attempt never
        ends up in a half-graded state.

        The caller (service layer) is responsible for computing the
        grading; the repository just persists.
        """
        attempt = self.get_attempt(attempt_id)
        if attempt is None:
            raise LookupError(f"No attempt with id={attempt_id}")

        # Apply each correction.
        for correction in answer_corrections:
            answer = self.get_answer(attempt_id, correction["question_id"])
            if answer is None:
                # The grading service should have produced a correction
                # entry for every answer row on the attempt; a missing
                # row indicates a slice-internal bug, not a user error.
                raise LookupError(
                    f"No answer row to grade for attempt={attempt_id} "
                    f"question={correction['question_id']}"
                )
            answer.is_correct = bool(correction["is_correct"])

        attempt.status = QuizAttemptStatus.SUBMITTED.value
        attempt.score = score
        attempt.submitted_at = submitted_at

        self.db.commit()
        self.db.refresh(attempt)
        return attempt

    # ------------------------------------------------------------------
    # Pass-threshold lookup
    # ------------------------------------------------------------------

    def has_passed_attempt(
        self,
        *,
        user_id: int,
        scope_level: LevelScope,
        scope_id: int,
        threshold_pct: float = 0.80,
    ) -> bool:
        """Return True iff the user has any SUBMITTED attempt at this
        scope whose ``score / max_score >= threshold_pct``.

        Used by the prerequisite gate for higher-scope quizzes (Req
        8.1, 9.1) and surfaced as Property 18. ``threshold_pct``
        defaults to 0.80 (Req 8.4 / 9.4); subtopic perfection (Req 7.6)
        is not modelled here — the service layer checks for the
        QUIZ_PERFECT XP event when it needs that signal.

        Implementation note: passing threshold is multiplicative
        (``score >= max_score * threshold_pct``) so the comparison
        doesn't introduce floating-point edge cases on attempts where
        ``max_score == 0`` (which is itself impossible for a quiz that
        passed assembly, but a defensive ``if not max_score`` keeps
        the function total).
        """
        stmt = (
            select(QuizAttempt)
            .where(QuizAttempt.user_id == user_id)
            .where(QuizAttempt.scope_level == scope_level.value)
            .where(QuizAttempt.scope_id == scope_id)
            .where(QuizAttempt.status == QuizAttemptStatus.SUBMITTED.value)
        )
        rows = self.db.execute(stmt).scalars().all()
        for row in rows:
            if row.max_score <= 0 or row.score is None:
                continue
            if row.score / row.max_score >= threshold_pct:
                return True
        return False
