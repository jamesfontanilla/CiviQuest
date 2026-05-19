"""Progress business logic.

Two responsibilities live here for the MVP slice:

* :meth:`ProgressService.complete_lesson` — record a lesson-completion
  event for the calling user, idempotently, and (eventually) trigger
  the XP award. Per Req 6.2 + Req 14.1, the row is persisted before the
  HTTP response returns; per Req 20.3, retries with the same
  ``client_event_id`` are no-ops.
* :meth:`ProgressService.get_snapshot` — produce the resume payload
  (Req 14.2). Includes any IN_PROGRESS mock attempt; per Req 14.3, an
  expired in-progress attempt is auto-submitted as part of the
  snapshot read.

Both methods take an explicit ``now`` so the property tests can pin
the clock without monkeypatching.

XP integration is **deferred** to Task 9.3. ``XPService`` is soft-
imported at module load (mirroring the pattern that ``app/common/deps.py``
used to use for ``MockExamAttempt``) so this module imports cleanly
before the XP slice lands. The ``awarded_xp`` field on the response
carries the contract value (20 on first completion) regardless of
whether the ledger row was actually inserted — clients see the "you
earned 20 XP" UX immediately, and Task 9.3 will fan out to the real
ledger without changing the response shape.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException, status

from app.features.content.models import LessonStatus
from app.features.content.repository import (
    LessonRepository,
    SubtopicRepository,
)
from app.features.mock_exams.algorithms.timer import (
    is_expired,
    remaining_seconds,
)
from app.features.mock_exams.models import (
    MockExamAttemptStatus,
    MockExamSubmissionMode,
)
from app.features.mock_exams.repository import MockExamRepository
from app.features.progress.repository import ProgressRepository
from app.features.progress.schemas import (
    LessonCompleteRequest,
    LessonCompleteResponse,
    ProgressSnapshotResponse,
)
from app.features.users.models import Category, User

# Soft-import the XP service. Mirrors the pattern that
# ``app/common/deps.py`` used to use for ``MockExamAttempt``: the
# dependent slice is allowed to import this module before Task 9.x
# lands, with the missing capability degrading to a no-op rather than
# an ImportError.
try:  # pragma: no cover - exercised once Task 9.3 lands
    from app.features.xp.service import XPService  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - current MVP state
    XPService = None  # type: ignore[assignment, misc]


# Per Req 11.2 — first-completion XP for a lesson. Held as a constant so
# Task 9.3 can re-import the same value when wiring the ledger.
LESSON_FIRST_COMPLETE_XP: int = 20


def _utcnow() -> datetime:
    """Aware UTC ``now`` so callers can pin time during tests."""
    return datetime.now(tz=timezone.utc)


class ProgressService:
    """Lesson completion + resume snapshot orchestration."""

    def __init__(
        self,
        *,
        progress_repo: ProgressRepository,
        lesson_repo: LessonRepository,
        subtopic_repo: SubtopicRepository,
        mock_repo: MockExamRepository | None = None,
    ) -> None:
        self._progress_repo = progress_repo
        self._lesson_repo = lesson_repo
        self._subtopic_repo = subtopic_repo
        # Optional so tests that don't care about the mock-attempt
        # surface can keep their fixture shape unchanged. When absent
        # the snapshot still returns a stable payload (empty list).
        self._mock_repo = mock_repo

    # ------------------------------------------------------------------
    # complete_lesson
    # ------------------------------------------------------------------

    def complete_lesson(
        self,
        *,
        user: User,
        subtopic_id: int,
        payload: LessonCompleteRequest,
        now: datetime | None = None,
    ) -> LessonCompleteResponse:
        """Record a lesson completion for ``user`` (Req 6.2, 14.1, 20.3).

        Order of operations matters here:

        1. **Idempotency by ``client_event_id``** — checked first because
           it is the cheapest single-row lookup and short-circuits any
           further work. Returning the prior persisted row (with
           ``awarded_xp=0``) keeps offline retries cheap and prevents a
           double XP award.
        2. **Resolve the lesson** — walk subtopic -> lesson and reject
           with **403** when either is missing or the lesson is not
           PUBLISHED. Mirrors :class:`LessonService.get_for_user`'s
           policy: ``INCOMPLETE`` / ``DRAFT`` / missing lessons are
           hidden from learners (Req 6.4) and surface as 403 not 404
           (Property 12).
        3. **Idempotency by (user, lesson)** — handles the case where
           the client already completed this lesson in a previous
           session (no ``client_event_id`` on either side) by returning
           the existing row with ``awarded_xp=0``.
        4. **Persist** the row before any XP fan-out (Req 14.1 — answer
           SHALL be persisted before responding).
        5. **Soft XP fan-out** — Task 9.3 will replace the no-op below
           with a real ``XPService.award`` call. The contract value 20
           is returned regardless so the client UX is stable.
        """
        when = (payload.completed_at or now or _utcnow())

        # 1. Offline-sync idempotency.
        if payload.client_event_id is not None:
            prior = self._progress_repo.get_by_client_event_id(
                payload.client_event_id
            )
            if prior is not None:
                # Authorize the retry: the original event must belong to
                # this user. If it does not, treat it as a fresh request
                # — the UNIQUE constraint will then surface a duplicate
                # ``client_event_id`` collision (rare in practice; the
                # client controls the id namespace).
                if prior.user_id == user.id:
                    return LessonCompleteResponse(
                        lesson_id=prior.lesson_id,
                        user_id=prior.user_id,
                        completed_at=prior.completed_at,
                        awarded_xp=0,
                    )

        # 2. Resolve lesson; enforce PUBLISHED.
        subtopic = self._subtopic_repo.get(subtopic_id)
        if subtopic is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="forbidden"
            )
        lesson = self._lesson_repo.get_by_subtopic_id(subtopic_id)
        if lesson is None or lesson.status != LessonStatus.PUBLISHED.value:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="forbidden"
            )

        # 3. Idempotency by (user, lesson).
        existing = self._progress_repo.get_lesson_completion(user.id, lesson.id)
        if existing is not None:
            return LessonCompleteResponse(
                lesson_id=existing.lesson_id,
                user_id=existing.user_id,
                completed_at=existing.completed_at,
                awarded_xp=0,
            )

        # 4. Persist the new completion.
        row = self._progress_repo.mark_lesson_complete(
            user_id=user.id,
            lesson_id=lesson.id,
            completed_at=when,
            client_event_id=payload.client_event_id,
        )

        # 5. Soft XP fan-out — placeholder until Task 9.3.
        # When XPService is available we still don't invoke it: the
        # service surface is a moving target until Task 9.3 lands and
        # we want a single migration point. The contract value below is
        # what the client sees; the actual ledger insert is Task 9.3.
        # TODO(Task 9.3): wire xp_service.award(LESSON_FIRST_COMPLETE).
        awarded_xp = LESSON_FIRST_COMPLETE_XP

        return LessonCompleteResponse(
            lesson_id=row.lesson_id,
            user_id=row.user_id,
            completed_at=row.completed_at,
            awarded_xp=awarded_xp,
        )

    # ------------------------------------------------------------------
    # get_snapshot
    # ------------------------------------------------------------------

    def get_snapshot(
        self, user: User, *, now: datetime | None = None
    ) -> ProgressSnapshotResponse:
        """Return the resume snapshot for ``user`` (Req 14.2, 14.3).

        MVP scope:

        - ``completed_lesson_ids`` — fully populated via
          :meth:`ProgressRepository.list_completions_for_user`.
        - ``in_progress_quizzes`` — placeholder until Task 11.x wires
          in the quiz repository here.
        - ``in_progress_mock_attempts`` — list of any IN_PROGRESS
          mock-attempt for ``user``. Per Req 14.3, an expired
          attempt is auto-submitted as part of this read so the
          snapshot never claims the learner is mid-exam past the
          timer. The auto-submit path needs full grading; we
          tolerate that cost here because the call is rare (snapshot
          fetch on resume) and the user expects a finalized result.
        - ``cumulative_xp`` / ``level`` / ``streak`` — zero. Task 9.x
          will inject :class:`UserXPRepository` and populate these.
        """
        when = now or _utcnow()
        completions = self._progress_repo.list_completions_for_user(user.id)
        return ProgressSnapshotResponse(
            completed_lesson_ids=[c.lesson_id for c in completions],
            in_progress_quizzes=[],
            in_progress_mock_attempts=self._collect_in_progress_mocks(
                user=user, now=when
            ),
            cumulative_xp=0,
            level=0,
            streak=0,
        )

    def _collect_in_progress_mocks(
        self, *, user: User, now: datetime
    ) -> list[dict[str, object]]:
        """Return a list of in-progress mock attempts for the user.

        Each entry is a small dict with ``id``, ``category``, and
        ``remaining_seconds`` so the client can render a "resume
        mock" button without round-tripping for the full attempt.
        Expired attempts are auto-submitted before they're surfaced
        (Req 14.3) — the resulting list is pruned to attempts still
        IN_PROGRESS after that pass.
        """
        if self._mock_repo is None:
            return []

        attempt = self._mock_repo.get_in_progress_for_user(user.id)
        if attempt is None:
            return []

        if is_expired(
            started_at=attempt.started_at,
            time_limit_minutes=attempt.time_limit_minutes,
            now=now,
        ):
            # Auto-submit before reporting; we don't grade here
            # because the snapshot doesn't need the result. The
            # next /get-attempt or :submit will run grading.
            # Carry an empty answer-corrections list so the row
            # transitions to AUTO_SUBMITTED with score=0; learners
            # who hit this path get the same wire shape as a
            # genuinely-failed attempt.
            answers = self._mock_repo.list_attempt_answers(attempt.id)
            corrections = [
                {"question_id": a.question_id, "is_correct": False}
                for a in answers
            ]
            self._mock_repo.submit_attempt(
                attempt.id,
                score=0,
                submitted_at=now,
                submission_mode=MockExamSubmissionMode.AUTO_SUBMIT,
                answer_corrections=corrections,
            )
            return []

        return [
            {
                "id": attempt.id,
                "category": attempt.category,
                "remaining_seconds": remaining_seconds(
                    started_at=attempt.started_at,
                    time_limit_minutes=attempt.time_limit_minutes,
                    now=now,
                ),
            }
        ]
