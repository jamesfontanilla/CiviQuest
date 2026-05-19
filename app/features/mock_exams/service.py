"""Mock-exam business logic (Task 12.5).

The :class:`MockExamService` orchestrates start → answer → submit for
the mock-exam slice (MVP: 50 questions, 180 minute limit, 80% pass
threshold). It composes:

- :class:`MockExamRepository` for attempt + config + answer
  persistence and the focus-loss append.
- :class:`QuestionRepository` for the per-module quality-gated
  question pools used by
  :func:`assemble_mock_exam`.
- :class:`ModuleRepository` for resolving module titles when building
  the per-module score breakdown (Req 10.5).
- :class:`XPService` for awarding ``MOCK_PASS`` 500 XP on a passing
  submission (Req 10.6).

Cross-cutting policies:

1. **At-most-one IN_PROGRESS per user (Req 10.8 / Property 36).** The
   partial unique index on ``mock_exam_attempts(user_id) WHERE
   status='IN_PROGRESS'`` is the canonical guarantee. The service-side
   check in :meth:`start_attempt` raises 409 ``mock_exam_in_progress``
   *before* the insert under contention; the SQL constraint catches
   any concurrent slip-through and we translate the IntegrityError
   to the same 409 for a clean wire shape.

2. **Server-authoritative timer (Req 10.3, 14.3, 19.3 / Property 30).**
   Every read or write on an IN_PROGRESS attempt runs
   :func:`is_expired`. If the timer has expired, the service
   auto-submits *before* any other side effect — so a mid-attempt
   ``set_answer`` against an expired timer turns into a 409
   ``attempt_already_submitted`` instead of accepting the answer.

3. **Mid-attempt non-disclosure (Req 10.4, 7.4 / Property 17).** The
   in-progress / start responses use the
   :class:`QuizAttemptInProgressQuestion` shape with no
   ``correct_answer`` / ``is_correct`` / ``explanation`` fields.

4. **LINEAR_NO_REVISIT one-shot answers (Req 19.4 / Property 31).**
   When ``nav_policy == LINEAR_NO_REVISIT``, ``set_answer`` rejects
   PATCHes against an already-finalized row with 409
   ``question_finalized``. The same answer is stamped
   ``finalized_at`` on the *first* PATCH so the second PATCH (if
   any) finds the lock. Under FREE_NAV, ``finalized_at`` stays NULL
   and PATCHes succeed indefinitely while the attempt is
   IN_PROGRESS.

5. **Persist-before-respond (Req 14.1 / Property 24).** Every state
   transition (insert attempt, set answer, submit) commits before
   the response builder runs. The repository's helpers commit
   internally; the service only adds policy.

6. **Weakness summary clamp (Req 10.5 / Property 35).** Strict
   reading of Req 10.5 says "three Modules with the lowest score
   percentages". If the assembled pool spans fewer than three
   modules, returning three would require fabrication; we clamp to
   ``min(3, n_modules)`` instead. Property 35's "length 3" reads as
   "length 3 when there are >= 3 modules", which is the common case
   for a 50q exam spanning a real category.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError

from app.features.content.models import LevelScope, Question, QuestionType
from app.features.content.repository import (
    ModuleRepository,
    QuestionRepository,
)
from app.features.mock_exams.algorithms.category_weighted_assembly import (
    assemble_mock_exam,
)
from app.features.mock_exams.algorithms.timer import (
    is_expired,
    remaining_seconds,
)
from app.features.mock_exams.models import (
    MockExamAttempt,
    MockExamAttemptStatus,
    MockExamConfig,
    MockExamNavPolicy,
    MockExamSubmissionMode,
)
from app.features.mock_exams.repository import MockExamRepository
from app.features.mock_exams.schemas import (
    FocusLossReportRequest,
    MockAnswerPatchRequest,
    MockExamAttemptResponse,
    MockExamStartResponse,
    MockExamSubmittedResponse,
    ModuleScoreBreakdown,
)
from app.features.quizzes.algorithms.grading import grade_attempt
from app.features.quizzes.schemas import (
    QuizAttemptInProgressQuestion,
    QuizGradedQuestion,
)
from app.features.users.models import Category, User
from app.features.xp.models import XPSource
from app.features.xp.service import XPService
from app.infrastructure.security import rng


_MOCK_PASS_XP = 500  # Req 10.6


def _utcnow() -> datetime:
    """Aware UTC ``now`` so callers can pin time during tests."""
    return datetime.now(tz=timezone.utc)


class MockExamService:
    """Mock-exam start / get / answer / focus-loss / submit orchestration."""

    def __init__(
        self,
        *,
        mock_repo: MockExamRepository,
        question_repo: QuestionRepository,
        module_repo: ModuleRepository,
        xp_service: XPService,
    ) -> None:
        self._mock_repo = mock_repo
        self._question_repo = question_repo
        self._module_repo = module_repo
        self._xp_service = xp_service

    # ------------------------------------------------------------------
    # validate_config (Task 12.2)
    # ------------------------------------------------------------------

    def validate_config(self, payload: dict) -> None:
        """Check ``payload`` against Req 10.1, 10.2, 16.1.

        Two invariants:

        - ``sum(weights.values()) == total_questions``
          (``invalid_mock_config:weights_sum_mismatch``).
        - Every ``module_id`` in ``weights`` references an existing
          module of the matching category
          (``invalid_mock_config:module_id_mismatch``).

        Used by admin write paths. The MVP slice only seeds the config
        once; this method exists so the admin slice (Task 17.x) has a
        single place to re-validate without re-deriving the rules.
        """
        weights = payload.get("weights_json") or {}
        total = payload.get("total_questions")
        category = payload.get("category")

        if total is None or sum(int(v) for v in weights.values()) != int(total):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="invalid_mock_config:weights_sum_mismatch",
            )

        for module_id_str in weights:
            module = self._module_repo.get(int(module_id_str))
            if module is None or (
                category is not None and module.category != category
            ):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="invalid_mock_config:module_id_mismatch",
                )

    # ------------------------------------------------------------------
    # start_attempt
    # ------------------------------------------------------------------

    def start_attempt(
        self,
        *,
        user: User,
        now: datetime | None = None,
    ) -> MockExamStartResponse:
        """Assemble + persist a fresh mock-exam attempt (Req 10.1, 10.2).

        Order of operations:

        1. Service-side IN_PROGRESS guard. The DB partial unique index
           is the canonical enforcement; the early raise gives a clean
           409 in the common (single-request) path.
        2. Resolve the config for the user's category. 404
           ``mock_config_not_found`` if missing.
        3. Build per-module pools via
           :meth:`QuestionRepository.list_active_passing_quality_gate`
           (no ``level_scope`` filter — the mock spans every scope per
           A1).
        4. Call :func:`assemble_mock_exam`, which raises 409
           ``insufficient_question_pool`` if any module's pool is short.
        5. Persist the attempt + per-question answer rows. MC option
           order is shuffled per attempt and snapshotted in
           ``displayed_options`` (Req 7.3 applied to mock).
        6. Build the start response.
        """
        when = now or _utcnow()

        # 1. Service-side guard.
        active = self._mock_repo.get_in_progress_for_user(user.id)
        if active is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="mock_exam_in_progress",
            )

        # 2. Resolve config.
        category = Category(user.category)
        config = self._mock_repo.get_config(category)
        if config is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="mock_config_not_found",
            )

        # 3. Build pools_by_module.
        pools_by_module: dict[int, list[Question]] = {}
        for module_id_str in config.weights_json:
            mid = int(module_id_str)
            pools_by_module[mid] = (
                self._question_repo.list_active_passing_quality_gate(
                    module_id=mid,
                    category=category,
                )
            )

        # 4. Assemble.
        chosen, seed = assemble_mock_exam(
            weights=dict(config.weights_json),
            pools_by_module=pools_by_module,
        )

        # 5. Persist attempt + answer rows. The DB partial unique index
        # may still raise on a concurrent insert; translate the
        # IntegrityError to the same 409 the service-side check uses.
        try:
            attempt = self._mock_repo.create_attempt(
                user_id=user.id,
                category=category,
                started_at=when,
                max_score=len(chosen),
                seed=seed,
                nav_policy=MockExamNavPolicy(config.nav_policy),
                time_limit_minutes=config.time_limit_minutes,
            )
        except IntegrityError:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="mock_exam_in_progress",
            )

        rows = []
        for ordinal, question in enumerate(chosen, start=1):
            displayed_options: list[str] | None = None
            if (
                question.qtype == QuestionType.MULTIPLE_CHOICE.value
                and question.options is not None
            ):
                displayed_options = list(question.options)
                rng.shuffle(displayed_options)
            rows.append(
                {
                    "question_id": question.id,
                    "ordinal": ordinal,
                    "displayed_options": displayed_options,
                }
            )
        self._mock_repo.add_attempt_questions(attempt.id, rows=rows)

        # 6. Build response.
        return MockExamStartResponse(
            attempt_id=attempt.id,
            category=category,
            started_at=attempt.started_at,
            time_limit_minutes=attempt.time_limit_minutes,
            remaining_seconds=remaining_seconds(
                started_at=attempt.started_at,
                time_limit_minutes=attempt.time_limit_minutes,
                now=when,
            ),
            nav_policy=attempt.nav_policy,
            questions=self._build_in_progress_questions(attempt.id),
            total_questions=attempt.max_score,
        )

    # ------------------------------------------------------------------
    # get_attempt
    # ------------------------------------------------------------------

    def get_attempt(
        self,
        *,
        attempt_id: int,
        user: User,
        now: datetime | None = None,
    ) -> MockExamAttemptResponse | MockExamSubmittedResponse:
        """Polymorphic read: in-progress vs submitted shape.

        Property 30: if the timer has expired and the attempt is still
        IN_PROGRESS, auto-submit *before* building any other response.
        The result reads as the submitted shape with
        ``submission_mode == AUTO_SUBMIT``.
        """
        when = now or _utcnow()

        attempt = self._mock_repo.get_attempt_for_user(attempt_id, user.id)
        if attempt is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="forbidden"
            )

        if attempt.status == MockExamAttemptStatus.IN_PROGRESS.value:
            if is_expired(
                started_at=attempt.started_at,
                time_limit_minutes=attempt.time_limit_minutes,
                now=when,
            ):
                attempt = self._auto_submit(attempt, now=when)
                return self._build_submitted_response(
                    attempt, awarded_xp=0
                )

            return MockExamAttemptResponse(
                attempt_id=attempt.id,
                category=Category(attempt.category),
                started_at=attempt.started_at,
                time_limit_minutes=attempt.time_limit_minutes,
                remaining_seconds=remaining_seconds(
                    started_at=attempt.started_at,
                    time_limit_minutes=attempt.time_limit_minutes,
                    now=when,
                ),
                nav_policy=attempt.nav_policy,
                status=attempt.status,
                questions=self._build_in_progress_questions(attempt.id),
                total_questions=attempt.max_score,
            )

        return self._build_submitted_response(attempt, awarded_xp=0)

    # ------------------------------------------------------------------
    # set_answer
    # ------------------------------------------------------------------

    def set_answer(
        self,
        *,
        attempt_id: int,
        question_id: int,
        payload: MockAnswerPatchRequest,
        user: User,
        now: datetime | None = None,
    ) -> None:
        """Persist the learner's selection (Req 14.1, 19.4).

        Property 30: the expiry check runs *first*. If the timer has
        expired, the attempt auto-submits (mode AUTO_SUBMIT) and the
        request returns 409 ``attempt_already_submitted``.

        Property 31: under LINEAR_NO_REVISIT, a PATCH against an
        already-finalized row returns 409 ``question_finalized``. The
        first PATCH in this nav mode stamps ``finalized_at`` so the
        next PATCH on the same question hits the lock.
        """
        when = now or _utcnow()

        attempt = self._mock_repo.get_attempt_for_user(attempt_id, user.id)
        if attempt is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="forbidden"
            )

        # Already-submitted attempts: 409, no other side effect.
        if attempt.status != MockExamAttemptStatus.IN_PROGRESS.value:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="attempt_already_submitted",
            )

        # Property 30: timer authority — auto-submit before anything else.
        if is_expired(
            started_at=attempt.started_at,
            time_limit_minutes=attempt.time_limit_minutes,
            now=when,
        ):
            self._auto_submit(attempt, now=when)
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="attempt_already_submitted",
            )

        # Property 31: LINEAR_NO_REVISIT lock check.
        finalized_at: datetime | None = None
        if attempt.nav_policy == MockExamNavPolicy.LINEAR_NO_REVISIT.value:
            existing = self._mock_repo.get_answer(attempt.id, question_id)
            if existing is None:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="forbidden",
                )
            if existing.finalized_at is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="question_finalized",
                )
            # Stamp the lock with the answer write.
            finalized_at = when

        try:
            self._mock_repo.set_answer(
                attempt_id=attempt.id,
                question_id=question_id,
                selected_answer=payload.selected_answer,
                answered_at=when,
                finalized_at=finalized_at,
            )
        except LookupError:
            # The question isn't on this attempt. 403 instead of 404
            # — same shape as the quizzes-slice precedent.
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="forbidden"
            )

    # ------------------------------------------------------------------
    # report_focus_loss
    # ------------------------------------------------------------------

    def report_focus_loss(
        self,
        *,
        attempt_id: int,
        payload: FocusLossReportRequest,
        user: User,
    ) -> None:
        """Append a focus-loss event to the attempt (Req 19.2).

        Property 30: this MUST NOT modify ``started_at`` or
        ``time_limit_minutes`` — an adversarial client cannot extend
        the timer by spamming this route.

        Returns ``None`` so the router responds 204.
        """
        attempt = self._mock_repo.get_attempt_for_user(attempt_id, user.id)
        if attempt is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="forbidden"
            )
        if attempt.status != MockExamAttemptStatus.IN_PROGRESS.value:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="attempt_already_submitted",
            )
        self._mock_repo.append_focus_loss(
            attempt.id, kind=payload.kind, at=payload.at
        )

    # ------------------------------------------------------------------
    # submit_attempt
    # ------------------------------------------------------------------

    def submit_attempt(
        self,
        *,
        attempt_id: int,
        user: User,
        now: datetime | None = None,
        mode: MockExamSubmissionMode = MockExamSubmissionMode.MANUAL,
    ) -> MockExamSubmittedResponse:
        """Grade + persist + fan out XP (Req 10.5, 10.6).

        Auth check first; 409 if already submitted; otherwise grade
        via :func:`grade_attempt`, persist via
        :meth:`MockExamRepository.submit_attempt`, then award
        ``MOCK_PASS`` 500 XP if the percentage clears the configured
        pass threshold (default 0.80).
        """
        when = now or _utcnow()

        attempt = self._mock_repo.get_attempt_for_user(attempt_id, user.id)
        if attempt is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="forbidden"
            )
        if attempt.status != MockExamAttemptStatus.IN_PROGRESS.value:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="attempt_already_submitted",
            )

        attempt = self._grade_and_submit(attempt, mode=mode, now=when)
        awarded_xp = self._award_pass_xp_if_passing(
            user=user, attempt=attempt, occurred_at=when
        )
        return self._build_submitted_response(attempt, awarded_xp=awarded_xp)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _auto_submit(
        self,
        attempt: MockExamAttempt,
        *,
        now: datetime,
    ) -> MockExamAttempt:
        """Auto-submit an expired IN_PROGRESS attempt.

        Used by Property 30: the GET / PATCH branches funnel here when
        ``is_expired`` returns True. The status flips to AUTO_SUBMITTED
        with submission_mode AUTO_SUBMIT.

        Auto-submit does **not** award MOCK_PASS XP here. The user
        object isn't on this code path (only the attempt + repos),
        and Req 10.6 ties the award to a passing submission. A
        learner whose timer expired with passing partial answers is
        a rare-but-real case; the current contract is "auto-submit
        scores the partial answers but doesn't award XP". Surfacing
        XP would require plumbing the user through every read path —
        out of scope for this slice.
        """
        return self._grade_and_submit(
            attempt, mode=MockExamSubmissionMode.AUTO_SUBMIT, now=now
        )

    def _grade_and_submit(
        self,
        attempt: MockExamAttempt,
        *,
        mode: MockExamSubmissionMode,
        now: datetime,
    ) -> MockExamAttempt:
        """Grade + persist transition. Shared by submit and auto-submit."""
        answers = self._mock_repo.list_attempt_answers(attempt.id)
        question_lookup: dict[int, Question] = {}
        for a in answers:
            q = self._question_repo.get(a.question_id)
            if q is not None:
                question_lookup[a.question_id] = q

        result = grade_attempt(
            attempt_answers=answers,
            question_lookup=question_lookup,
        )

        return self._mock_repo.submit_attempt(
            attempt.id,
            score=result.score,
            submitted_at=now,
            submission_mode=mode,
            answer_corrections=[
                {"question_id": g.question_id, "is_correct": g.is_correct}
                for g in result.answers
            ],
        )

    def _award_pass_xp_if_passing(
        self,
        *,
        user: User,
        attempt: MockExamAttempt,
        occurred_at: datetime,
    ) -> int:
        """Award 500 XP if the attempt's percentage clears the threshold.

        Uses the attempt's category-config ``pass_threshold`` rather
        than a hard-coded 0.80 so an admin re-tuning the threshold is
        respected.
        """
        max_score = attempt.max_score
        if max_score <= 0 or attempt.score is None:
            return 0
        config = self._mock_repo.get_config(Category(attempt.category))
        threshold = config.pass_threshold if config else 0.80
        percentage = attempt.score / max_score
        if percentage < threshold:
            return 0
        self._xp_service.award(
            user=user,
            source=XPSource.MOCK_PASS,
            amount=_MOCK_PASS_XP,
            occurred_at=occurred_at,
            source_ref_id=attempt.id,
        )
        return _MOCK_PASS_XP

    def _build_in_progress_questions(
        self, attempt_id: int
    ) -> list[QuizAttemptInProgressQuestion]:
        """Project answer rows into the in-progress question shape.

        Property 17: this builder MUST NOT include
        ``correct_answer`` / ``is_correct`` / ``explanation``. The
        :class:`QuizAttemptInProgressQuestion` schema doesn't carry
        those fields, so the guarantee is enforced at the type level.
        """
        answers = self._mock_repo.list_attempt_answers(attempt_id)
        questions: list[QuizAttemptInProgressQuestion] = []
        for a in answers:
            q = self._question_repo.get(a.question_id)
            if q is None:
                continue
            options = a.displayed_options
            if options is None and q.options is not None:
                options = list(q.options)
            questions.append(
                QuizAttemptInProgressQuestion(
                    id=q.id,
                    ordinal=a.ordinal,
                    stem=q.stem,
                    qtype=QuestionType(q.qtype),
                    options=options,
                    selected_answer=a.selected_answer,
                )
            )
        return questions

    def _build_submitted_response(
        self,
        attempt: MockExamAttempt,
        *,
        awarded_xp: int,
    ) -> MockExamSubmittedResponse:
        """Project a submitted attempt into the graded response shape.

        Builds the per-module breakdown by grouping graded answers by
        ``question.module_id``, looking up titles via
        :meth:`ModuleRepository.get`. ``weakness_summary`` is
        ``sorted(per_module, key=(pct, module_id))[:min(3,
        n_modules)]``.
        """
        answers = self._mock_repo.list_attempt_answers(attempt.id)
        score = attempt.score or 0
        max_score = attempt.max_score
        percentage = score / max_score if max_score > 0 else 0.0

        config = self._mock_repo.get_config(Category(attempt.category))
        threshold = config.pass_threshold if config else 0.80
        passed = max_score > 0 and percentage >= threshold

        graded: list[QuizGradedQuestion] = []
        # Per-module aggregates: ``module_id -> [score, max]``.
        per_module: dict[int, list[int]] = {}
        for a in answers:
            q = self._question_repo.get(a.question_id)
            if q is None:
                continue
            graded.append(
                QuizGradedQuestion(
                    id=q.id,
                    ordinal=a.ordinal,
                    stem=q.stem,
                    selected_answer=a.selected_answer,
                    correct_answer=q.correct_answer,
                    is_correct=bool(a.is_correct)
                    if a.is_correct is not None
                    else False,
                    explanation=q.explanation,
                )
            )
            bucket = per_module.setdefault(q.module_id, [0, 0])
            bucket[1] += 1
            if a.is_correct:
                bucket[0] += 1

        # Build ModuleScoreBreakdown rows.
        breakdown: list[ModuleScoreBreakdown] = []
        for module_id, (m_score, m_max) in sorted(per_module.items()):
            module = self._module_repo.get(module_id)
            title = module.title if module is not None else f"Module {module_id}"
            pct = m_score / m_max if m_max > 0 else 0.0
            breakdown.append(
                ModuleScoreBreakdown(
                    module_id=module_id,
                    title=title,
                    score=m_score,
                    max=m_max,
                    pct=pct,
                )
            )

        # Property 35 — sort ascending by (pct, module_id), clamp to
        # min(3, n_modules).
        weakness_size = min(3, len(breakdown))
        weakness = sorted(
            breakdown, key=lambda m: (m.pct, m.module_id)
        )[:weakness_size]

        return MockExamSubmittedResponse(
            attempt_id=attempt.id,
            category=Category(attempt.category),
            status=attempt.status,
            submission_mode=attempt.submission_mode or "MANUAL",
            started_at=attempt.started_at,
            submitted_at=attempt.submitted_at or attempt.started_at,
            score=score,
            max_score=max_score,
            percentage=percentage,
            passed=passed,
            awarded_xp=awarded_xp,
            per_module_breakdown=breakdown,
            weakness_summary=weakness,
            questions=graded,
        )
