"""Quiz business logic (Task 11.4).

The :class:`QuizService` orchestrates start → answer → submit for the
three quiz scopes (subtopic 20q, topic 50q, module 100q). It composes:

- :class:`QuizRepository` for attempt persistence.
- :class:`QuestionRepository` for the quality-gated question pool.
- :class:`ProgressRepository` for the lesson-completion gate (Req 6.1)
  and for marking topic / module completion on a passing submit
  (Req 8.5, 9.4).
- :class:`TopicRepository` / :class:`SubtopicRepository` for resolving
  the prerequisite hierarchy when starting topic / module quizzes.
- :class:`XPService` for awarding ``QUIZ_PASS`` / ``QUIZ_PERFECT`` on
  submit (Req 7.6, 7.7, 8.4, 9.4).

Cross-cutting policies:

1. **Lesson-before-quiz gating (Property 14, Req 6.1).**
   ``start_subtopic_quiz`` requires
   :meth:`ProgressRepository.is_lesson_complete_for_subtopic` to be
   ``True``; otherwise raises 409 ``lesson_not_completed``.

2. **Prerequisite gating (Property 18, Req 8.1, 9.1).**
   ``start_topic_quiz`` requires every subtopic under the topic to
   have a SUBMITTED quiz attempt with ``score / max_score >= 0.80``.
   ``start_module_quiz`` requires the same for every topic under the
   module. Failure raises 409 ``prerequisites_not_met``.

3. **Mid-attempt non-disclosure (Property 17, Req 7.4).** The
   :meth:`get_attempt` method returns
   :class:`QuizAttemptInProgressResponse` while the attempt is
   IN_PROGRESS — that schema has no ``correct_answer`` /
   ``is_correct`` / ``explanation`` fields. ``set_answer`` returns
   ``None`` (the router responds 200 with an empty body / minimal
   payload).

4. **Persist-before-respond (Property 24, Req 14.1).**
   ``set_answer`` commits the row before returning. The repository's
   ``set_answer`` already does this; the service only adds the
   authorization wrapper.

5. **XP fan-out on submit (Req 7.6, 7.7, 8.4, 9.4).**
   - SUBTOPIC + perfect: ``QUIZ_PERFECT`` 50 XP.
   - SUBTOPIC + non-perfect passing: ``QUIZ_PASS`` 20 XP.
   - TOPIC passing: ``QUIZ_PASS`` 100 XP + ``mark_topic_complete``.
   - MODULE passing: ``QUIZ_PASS`` 250 XP + ``mark_module_complete``.

The XP slice's ``XPService.award`` validates the source enum and the
amount sign — bad combinations surface as 400 from there.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException, status

from app.features.content.models import LevelScope, Question, QuestionType
from app.features.content.repository import (
    QuestionRepository,
    SubtopicRepository,
    TopicRepository,
)
from app.features.progress.repository import ProgressRepository
from app.features.quizzes.algorithms.assembly import (
    COUNT_BY_SCOPE,
    assemble_quiz,
)
from app.features.quizzes.algorithms.grading import grade_attempt
from app.features.quizzes.models import QuizAttempt, QuizAttemptStatus
from app.features.quizzes.repository import QuizRepository
from app.features.quizzes.schemas import (
    QuizAnswerPatchRequest,
    QuizAttemptInProgressQuestion,
    QuizAttemptInProgressResponse,
    QuizGradedQuestion,
    QuizSubmittedResponse,
)
from app.features.users.models import Category, User
from app.features.xp.models import XPSource
from app.features.xp.service import XPService
from app.infrastructure.security import rng

# Optional mastery integration — imported lazily to avoid hard coupling.
try:
    from app.features.mastery.service import MasteryService, SpacedRepetitionService
    from app.features.mastery.repository import MasteryRepository, ReviewScheduleRepository

    _MASTERY_AVAILABLE = True
except ImportError:
    _MASTERY_AVAILABLE = False


# Per-source amounts at submit time (Req 7.6, 7.7, 8.4, 9.4). Subtopic
# defaults are baked into ``XPService.DEFAULT_AMOUNT_BY_SOURCE`` already;
# topic and module passes override with explicit amounts.
_SUBTOPIC_PASS_XP = 20
_SUBTOPIC_PERFECT_XP = 50
_TOPIC_PASS_XP = 100
_MODULE_PASS_XP = 250


def _utcnow() -> datetime:
    """Aware UTC ``now`` so callers can pin time during tests."""
    return datetime.now(tz=timezone.utc)


class QuizService:
    """Subtopic / topic / module quiz orchestration."""

    def __init__(
        self,
        *,
        quiz_repo: QuizRepository,
        question_repo: QuestionRepository,
        progress_repo: ProgressRepository,
        topic_repo: TopicRepository,
        subtopic_repo: SubtopicRepository,
        xp_service: XPService,
    ) -> None:
        self._quiz_repo = quiz_repo
        self._question_repo = question_repo
        self._progress_repo = progress_repo
        self._topic_repo = topic_repo
        self._subtopic_repo = subtopic_repo
        self._xp_service = xp_service

    # ------------------------------------------------------------------
    # start_*_quiz
    # ------------------------------------------------------------------

    def start_subtopic_quiz(
        self,
        *,
        user: User,
        subtopic_id: int,
        time_limit_seconds: int | None = None,
        now: datetime | None = None,
    ) -> QuizAttemptInProgressResponse:
        """Assemble + persist a 20-question subtopic quiz (Req 7.1, 6.1).

        Order of operations:

        1. Resolve the subtopic + walk to module for the category check.
           Mismatched / missing rows → 403 ``forbidden`` (Property 12).
        2. Lesson-completion gate (Property 14). Missing → 409
           ``lesson_not_completed``.
        3. Pull the quality-gated subtopic pool. Assembly raises 409
           ``insufficient_question_pool`` if too small.
        4. Persist the attempt + answer rows in one logical operation.
        """
        when = now or _utcnow()

        # 1. Category isolation.
        subtopic = self._resolve_subtopic_for_user(user, subtopic_id)

        # 2. Lesson-before-quiz gating (Req 6.1).
        if not self._progress_repo.is_lesson_complete_for_subtopic(
            user.id, subtopic.id
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="lesson_not_completed",
            )

        # 3. Pull pool + assemble.
        pool = self._question_repo.list_active_passing_quality_gate(
            subtopic_id=subtopic.id,
            category=Category(user.category),
            level_scope=LevelScope.SUBTOPIC,
        )
        chosen, seed = assemble_quiz(
            scope_level=LevelScope.SUBTOPIC, pool=pool
        )

        # 4. Persist.
        return self._persist_assembled_attempt(
            user=user,
            scope_level=LevelScope.SUBTOPIC,
            scope_id=subtopic.id,
            chosen=chosen,
            seed=seed,
            started_at=when,
            time_limit_seconds=time_limit_seconds,
        )

    def start_topic_quiz(
        self,
        *,
        user: User,
        topic_id: int,
        time_limit_seconds: int | None = None,
        now: datetime | None = None,
    ) -> QuizAttemptInProgressResponse:
        """Assemble + persist a 50-question topic quiz (Req 8.1, 8.2).

        Prerequisite gate: every subtopic under ``topic_id`` must have a
        SUBMITTED quiz attempt with score >= 80%. Missing → 409
        ``prerequisites_not_met``.
        """
        when = now or _utcnow()

        topic = self._resolve_topic_for_user(user, topic_id)

        # Prerequisite gate.
        subtopics = self._subtopic_repo.list_by_topic(topic.id)
        if not subtopics or not all(
            self._quiz_repo.has_passed_attempt(
                user_id=user.id,
                scope_level=LevelScope.SUBTOPIC,
                scope_id=s.id,
            )
            for s in subtopics
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="prerequisites_not_met",
            )

        pool = self._question_repo.list_active_passing_quality_gate(
            topic_id=topic.id,
            category=Category(user.category),
            level_scope=LevelScope.TOPIC,
        )
        chosen, seed = assemble_quiz(
            scope_level=LevelScope.TOPIC, pool=pool
        )

        return self._persist_assembled_attempt(
            user=user,
            scope_level=LevelScope.TOPIC,
            scope_id=topic.id,
            chosen=chosen,
            seed=seed,
            started_at=when,
        )

    def start_module_quiz(
        self,
        *,
        user: User,
        module_id: int,
        now: datetime | None = None,
    ) -> QuizAttemptInProgressResponse:
        """Assemble + persist a 100-question module quiz (Req 9.1, 9.2).

        Prerequisite gate: every topic under ``module_id`` must have a
        SUBMITTED topic-quiz with score >= 80%. Missing → 409
        ``prerequisites_not_met``.
        """
        when = now or _utcnow()

        # Module category check is already in the chain via
        # _resolve_module_for_user (raises 403 on mismatch).
        module = self._resolve_module_for_user(user, module_id)

        topics = self._topic_repo.list_by_module(module.id)
        if not topics or not all(
            self._quiz_repo.has_passed_attempt(
                user_id=user.id,
                scope_level=LevelScope.TOPIC,
                scope_id=t.id,
            )
            for t in topics
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="prerequisites_not_met",
            )

        pool = self._question_repo.list_active_passing_quality_gate(
            module_id=module.id,
            category=Category(user.category),
            level_scope=LevelScope.MODULE,
        )
        chosen, seed = assemble_quiz(
            scope_level=LevelScope.MODULE, pool=pool
        )

        return self._persist_assembled_attempt(
            user=user,
            scope_level=LevelScope.MODULE,
            scope_id=module.id,
            chosen=chosen,
            seed=seed,
            started_at=when,
        )

    # ------------------------------------------------------------------
    # get_attempt / set_answer / submit_attempt
    # ------------------------------------------------------------------

    def get_attempt(
        self, *, attempt_id: int, user: User
    ) -> QuizAttemptInProgressResponse | QuizSubmittedResponse:
        """Return the in-progress or submitted view of an attempt.

        Polymorphic by ``status``: IN_PROGRESS → no correctness fields
        (Property 17); SUBMITTED → full graded payload.
        """
        attempt = self._quiz_repo.get_attempt_for_user(attempt_id, user.id)
        if attempt is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="forbidden"
            )

        if attempt.status == QuizAttemptStatus.IN_PROGRESS.value:
            return self._build_in_progress_response(attempt)
        return self._build_submitted_response(attempt, awarded_xp=0)

    def set_answer(
        self,
        *,
        attempt_id: int,
        question_id: int,
        payload: QuizAnswerPatchRequest,
        user: User,
        now: datetime | None = None,
    ) -> None:
        """Persist the learner's selection. Returns ``None``.

        - 403 if the attempt isn't theirs.
        - 409 ``attempt_already_submitted`` if SUBMITTED.
        - 403 if the question isn't on this attempt.
        - The repository commits before returning, satisfying Req 14.1
          (Property 24).
        """
        when = now or _utcnow()

        attempt = self._quiz_repo.get_attempt_for_user(attempt_id, user.id)
        if attempt is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="forbidden"
            )
        if attempt.status != QuizAttemptStatus.IN_PROGRESS.value:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="attempt_already_submitted",
            )

        try:
            self._quiz_repo.set_answer(
                attempt_id=attempt.id,
                question_id=question_id,
                selected_answer=payload.selected_answer,
                answered_at=when,
            )
        except LookupError:
            # The question isn't on this attempt. 403 instead of 404 so
            # the response shape stays consistent with category isolation.
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="forbidden"
            )

    def submit_attempt(
        self,
        *,
        attempt_id: int,
        user: User,
        now: datetime | None = None,
    ) -> QuizSubmittedResponse:
        """Grade + persist + fan out XP / completion (Req 7.5–7.7,
        8.4, 8.5, 9.4)."""
        when = now or _utcnow()

        attempt = self._quiz_repo.get_attempt_for_user(attempt_id, user.id)
        if attempt is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="forbidden"
            )
        if attempt.status != QuizAttemptStatus.IN_PROGRESS.value:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="attempt_already_submitted",
            )

        # Build the question lookup the grader needs.
        answers = self._quiz_repo.list_attempt_answers(attempt.id)
        question_lookup: dict[int, Question] = {}
        for a in answers:
            q = self._question_repo.get(a.question_id)
            if q is not None:
                question_lookup[a.question_id] = q

        result = grade_attempt(
            attempt_answers=answers,
            question_lookup=question_lookup,
        )

        # Persist the submit transition + per-row corrections.
        attempt = self._quiz_repo.submit_attempt(
            attempt.id,
            score=result.score,
            submitted_at=when,
            answer_corrections=[
                {"question_id": g.question_id, "is_correct": g.is_correct}
                for g in result.answers
            ],
        )

        # XP + completion fan-out.
        awarded_xp = self._fan_out_xp_and_completion(
            user=user,
            attempt=attempt,
            is_perfect=result.is_perfect,
            is_passing=result.is_passing,
            occurred_at=when,
        )

        # Mastery recording: update per-subtopic mastery for each graded answer.
        if _MASTERY_AVAILABLE and LevelScope(attempt.scope_level) == LevelScope.SUBTOPIC:
            self._record_mastery_after_submit(
                user=user,
                attempt=attempt,
                answers=answers,
                result=result,
                is_passing=result.is_passing,
                now=when,
            )

        return self._build_submitted_response(
            attempt, awarded_xp=awarded_xp
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _record_mastery_after_submit(
        self,
        *,
        user: User,
        attempt: QuizAttempt,
        answers: list,
        result,
        is_passing: bool,
        now: datetime,
    ) -> None:
        """Record mastery data after a subtopic quiz submit.

        Iterates over graded answers and calls MasteryService.record_attempt
        for each. Also schedules initial spaced repetition review if passing.
        """
        try:
            db = self._quiz_repo.db
            mastery_service = MasteryService(
                mastery_repo=MasteryRepository(db=db),
                subtopic_repo=self._subtopic_repo,
            )
            sr_service = SpacedRepetitionService(
                review_repo=ReviewScheduleRepository(db=db),
                subtopic_repo=self._subtopic_repo,
            )

            subtopic_id = attempt.scope_id

            # Record each answer as a mastery attempt.
            for graded_answer in result.answers:
                # Estimate response time from answered_at timestamps.
                # Default to 15s if no timing data available.
                response_time_ms = 15000
                for a in answers:
                    if a.question_id == graded_answer.question_id and a.answered_at:
                        # Use a rough estimate; we don't have per-question start time.
                        response_time_ms = 15000
                        break

                mastery_service.record_attempt(
                    user_id=user.id,
                    subtopic_id=subtopic_id,
                    is_correct=graded_answer.is_correct,
                    response_time_ms=response_time_ms,
                    now=now,
                )

            # Schedule initial review if this is a passing attempt.
            if is_passing:
                sr_service.schedule_initial_review(
                    user_id=user.id,
                    subtopic_id=subtopic_id,
                    now=now,
                )
        except Exception:
            # Mastery recording is non-critical; don't fail the quiz submit.
            pass

    def _resolve_subtopic_for_user(self, user: User, subtopic_id: int):
        """Walk subtopic → topic → module and enforce category isolation.

        Mirrors :meth:`LessonService.get_for_user`'s pattern from the
        content slice. Any mismatch surfaces as 403 ``forbidden``
        (Property 12).
        """
        subtopic = self._subtopic_repo.get(subtopic_id)
        if subtopic is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="forbidden"
            )
        topic = self._topic_repo.get(subtopic.topic_id)
        if topic is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="forbidden"
            )
        self._resolve_module_for_user(user, topic.module_id)
        return subtopic

    def _resolve_topic_for_user(self, user: User, topic_id: int):
        """Walk topic → module and enforce category isolation."""
        topic = self._topic_repo.get(topic_id)
        if topic is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="forbidden"
            )
        self._resolve_module_for_user(user, topic.module_id)
        return topic

    def _resolve_module_for_user(self, user: User, module_id: int):
        """Direct module category check.

        We don't import :class:`ModuleService` here to avoid the cycle
        with the content slice's service factory. The check is small
        enough to inline and the policy is identical.
        """
        # The TopicRepository / SubtopicRepository don't expose a
        # module getter; pull it via session directly.
        from app.features.content.models import Module

        module = self._topic_repo.db.get(Module, module_id)
        if module is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="forbidden"
            )
        if module.category != user.category and not getattr(
            user, "cross_category_preview", False
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="forbidden"
            )
        return module

    def _persist_assembled_attempt(
        self,
        *,
        user: User,
        scope_level: LevelScope,
        scope_id: int,
        chosen: list[Question],
        seed: int,
        started_at: datetime,
        time_limit_seconds: int | None = None,
    ) -> QuizAttemptInProgressResponse:
        """Persist attempt + answer rows; return the in-progress shape.

        Handles per-question option shuffling for ``MULTIPLE_CHOICE``
        questions. The shuffle uses the same security RNG so each
        attempt gets independently-random option order
        (Property 16). Non-MC questions store ``displayed_options =
        None``.
        """
        attempt = self._quiz_repo.create_attempt(
            user_id=user.id,
            scope_level=scope_level,
            scope_id=scope_id,
            started_at=started_at,
            max_score=len(chosen),
            seed=seed,
            time_limit_seconds=time_limit_seconds,
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
        self._quiz_repo.add_attempt_questions(attempt.id, rows=rows)

        # Reload the attempt + answers for the response so refresh is
        # observable across the session.
        return self._build_in_progress_response(attempt)

    def _build_in_progress_response(
        self, attempt: QuizAttempt
    ) -> QuizAttemptInProgressResponse:
        """Project an attempt + answer rows into the in-progress shape.

        Property 17: this builder MUST NOT include
        ``correct_answer`` / ``is_correct`` / ``explanation``.
        """
        answers = self._quiz_repo.list_attempt_answers(attempt.id)
        questions: list[QuizAttemptInProgressQuestion] = []
        for a in answers:
            q = self._question_repo.get(a.question_id)
            if q is None:
                continue
            options = a.displayed_options
            # Fallback to the canonical option list when ``displayed_options``
            # is null (non-MC questions or legacy rows).
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
                    difficulty=q.difficulty,
                )
            )
        return QuizAttemptInProgressResponse(
            attempt_id=attempt.id,
            scope_level=LevelScope(attempt.scope_level),
            scope_id=attempt.scope_id,
            status=attempt.status,
            started_at=attempt.started_at,
            time_limit_seconds=attempt.time_limit_seconds,
            questions=questions,
            total_questions=attempt.max_score,
        )

    def _build_submitted_response(
        self, attempt: QuizAttempt, *, awarded_xp: int
    ) -> QuizSubmittedResponse:
        """Project a submitted attempt into the graded response shape.

        Re-grades from the persisted ``is_correct`` flags rather than
        running ``grade_attempt`` again — the persisted truth is what
        the wire payload should reflect.
        """
        answers = self._quiz_repo.list_attempt_answers(attempt.id)
        score = attempt.score or 0
        max_score = attempt.max_score
        percentage = score / max_score if max_score > 0 else 0.0
        is_perfect = max_score > 0 and score == max_score
        from app.features.quizzes.algorithms.grading import (
            PASS_THRESHOLD_PCT,
        )

        is_passing = max_score > 0 and percentage >= PASS_THRESHOLD_PCT

        graded: list[QuizGradedQuestion] = []
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
                    is_correct=bool(a.is_correct) if a.is_correct is not None else False,
                    explanation=q.explanation,
                )
            )

        return QuizSubmittedResponse(
            attempt_id=attempt.id,
            scope_level=LevelScope(attempt.scope_level),
            scope_id=attempt.scope_id,
            status=attempt.status,
            started_at=attempt.started_at,
            submitted_at=attempt.submitted_at,
            score=score,
            max_score=max_score,
            percentage=percentage,
            is_perfect=is_perfect,
            is_passing=is_passing,
            awarded_xp=awarded_xp,
            questions=graded,
        )

    def _fan_out_xp_and_completion(
        self,
        *,
        user: User,
        attempt: QuizAttempt,
        is_perfect: bool,
        is_passing: bool,
        occurred_at: datetime,
    ) -> int:
        """Award XP and mark topic / module completion when applicable.

        Returns the awarded XP for the response payload. ``0`` when
        the attempt failed.
        """
        scope = LevelScope(attempt.scope_level)

        # SUBTOPIC: perfect → 50 XP QUIZ_PERFECT, otherwise pass → 20 XP
        # QUIZ_PASS. Failure → no XP.
        if scope == LevelScope.SUBTOPIC:
            if is_perfect:
                self._xp_service.award(
                    user=user,
                    source=XPSource.QUIZ_PERFECT,
                    amount=_SUBTOPIC_PERFECT_XP,
                    occurred_at=occurred_at,
                    source_ref_id=attempt.id,
                )
                return _SUBTOPIC_PERFECT_XP
            if is_passing:
                self._xp_service.award(
                    user=user,
                    source=XPSource.QUIZ_PASS,
                    amount=_SUBTOPIC_PASS_XP,
                    occurred_at=occurred_at,
                    source_ref_id=attempt.id,
                )
                return _SUBTOPIC_PASS_XP
            return 0

        # TOPIC: passing → 100 XP QUIZ_PASS + mark_topic_complete (Req 8.5).
        if scope == LevelScope.TOPIC:
            if is_passing:
                self._xp_service.award(
                    user=user,
                    source=XPSource.QUIZ_PASS,
                    amount=_TOPIC_PASS_XP,
                    occurred_at=occurred_at,
                    source_ref_id=attempt.id,
                )
                self._progress_repo.mark_topic_complete(
                    user.id, attempt.scope_id, occurred_at
                )
                return _TOPIC_PASS_XP
            return 0

        # MODULE: passing → 250 XP QUIZ_PASS + mark_module_complete (Req 9.4).
        if scope == LevelScope.MODULE:
            if is_passing:
                self._xp_service.award(
                    user=user,
                    source=XPSource.QUIZ_PASS,
                    amount=_MODULE_PASS_XP,
                    occurred_at=occurred_at,
                    source_ref_id=attempt.id,
                )
                self._progress_repo.mark_module_complete(
                    user.id, attempt.scope_id, occurred_at
                )
                return _MODULE_PASS_XP
            return 0

        return 0
