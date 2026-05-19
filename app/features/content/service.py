"""Content services for learner-facing reads and admin writes.

Five services ship in this module — one per content table — because the
slice convention is "one ``service.py`` per feature" and the responsibilities
form a tight cluster. Each is constructed with explicit repository
dependencies (no ``Depends`` inside the service) per ``code-conventions.md``.

Two cross-cutting policies live here, called out so a future reader can find
the rule by reading the service rather than tracing through every read path:

1. **Category isolation** (Req 5.1, 5.2, 5.3) — every read walks back up to
   the parent ``Module`` and compares ``module.category`` against the
   caller's ``user.category``. A mismatch raises **403** rather than 404 per
   ``security-policy.md`` ("Never return 404 to hide resource existence
   from unauthenticated users; return 401/403 first") and design Property 12
   ("the response is 403 — never 404"). Unknown ids on those endpoints also
   surface as 403 — distinguishing "wrong category" from "no such id" leaks
   the existence of resources outside the caller's category.

   Phase 2 carve-out: ``user.cross_category_preview == True`` admits cross-
   category reads. The column is already on the ORM (Req 5.4 Phase 2 hook);
   this slice honours the flag so flipping the toggle in admin tooling does
   not require re-shaping content reads.

2. **Quality-gate validation on admin writes** (Req 18.1, 18.2, 18.3, 18.4)
   — admin question writes pass through ``QuestionCreate`` first (so 422 is
   surfaced at the FastAPI boundary), then are re-checked at the ORM layer
   via :func:`is_question_quality_passing`. The re-check is defense in
   depth: it survives a future schema refactor that decouples validation
   from the wire shape, and it also catches drift between the schema's MC-
   only emphasis and the SQL gate. When the helper rejects, the row is
   persisted with ``is_active=False`` and a row is written to
   ``question_rejection_log`` (Req 18.4) before the request returns 400.

   Why persist a rejected row at all? Because Req 18.4 mandates logging
   "with the Question id". The only way to get an id is via INSERT, so we
   take the hit, mark the row inactive (the read-side gate hides
   ``is_active=False`` rows anyway), and log. No transient-question
   rejection is silently dropped.
"""

from __future__ import annotations

from fastapi import HTTPException, status

from app.features.content.algorithms.quality_gate import (
    is_question_quality_passing,
)
from app.features.content.models import (
    LessonStatus,
    Lesson,
    Module,
    Question,
    Subtopic,
    Topic,
)
from app.features.content.repository import (
    LessonRepository,
    ModuleRepository,
    QuestionRepository,
    SubtopicRepository,
    TopicRepository,
)
from app.features.content.schemas import QuestionCreate
from app.features.users.models import Category, User


# --- ModuleService ----------------------------------------------------------


class ModuleService:
    """Reads modules with category isolation enforced."""

    def __init__(self, *, module_repo: ModuleRepository) -> None:
        self._module_repo = module_repo

    def list_for_user(
        self, user: User, *, skip: int = 0, limit: int = 20
    ) -> tuple[list[Module], int]:
        """Return paginated modules in ``user.category`` (Req 5.1, 5.2).

        Pagination bounds are enforced upstream by ``PaginationParams``. The
        repository returns ``(rows, total)`` with the same filter so the
        router can render the standard envelope without a second query.
        """
        category = Category(user.category)
        return self._module_repo.list_by_category(
            category, skip=skip, limit=limit
        )

    def get_for_user(self, user: User, module_id: int) -> Module:
        """Resolve a module for the caller; raise 403 on any mismatch.

        "Mismatch" covers both unknown ids and category boundaries. Both
        surface as the same 403 ``forbidden`` so the caller cannot probe
        for the existence of ids outside their category by comparing
        404-vs-403 (Property 12). Phase 2 ``cross_category_preview`` admits
        cross-category reads.
        """
        module = self._module_repo.get(module_id)
        if module is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="forbidden"
            )
        if module.category != user.category:
            if not getattr(user, "cross_category_preview", False):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN, detail="forbidden"
                )
        return module


# --- TopicService -----------------------------------------------------------


class TopicService:
    """Lists topics under a module, gated by category isolation."""

    def __init__(
        self,
        *,
        topic_repo: TopicRepository,
        module_service: ModuleService,
    ) -> None:
        self._topic_repo = topic_repo
        self._module_service = module_service

    def list_for_user(self, user: User, module_id: int) -> list[Topic]:
        """Return topics under ``module_id`` after the parent passes the
        category check via :meth:`ModuleService.get_for_user`.

        ``ModuleService.get_for_user`` raises 403 on any mismatch, so
        unknown module ids surface as 403 (not an empty topic list).
        """
        self._module_service.get_for_user(user, module_id)
        return self._topic_repo.list_by_module(module_id)


# --- SubtopicService --------------------------------------------------------


class SubtopicService:
    """Lists subtopics under a topic, gated by topic -> module isolation."""

    def __init__(
        self,
        *,
        subtopic_repo: SubtopicRepository,
        topic_repo: TopicRepository,
        module_service: ModuleService,
    ) -> None:
        self._subtopic_repo = subtopic_repo
        self._topic_repo = topic_repo
        self._module_service = module_service

    def list_for_user(self, user: User, topic_id: int) -> list[Subtopic]:
        """Walk topic -> module to enforce category isolation, then list.

        An unknown ``topic_id`` raises 403, matching the rule that absence-
        vs-mismatch must not be distinguishable through HTTP.
        """
        topic = self._topic_repo.get(topic_id)
        if topic is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="forbidden"
            )
        # Delegates the category check + Phase 2 cross-category logic.
        self._module_service.get_for_user(user, topic.module_id)
        return self._subtopic_repo.list_by_topic(topic_id)


# --- LessonService ----------------------------------------------------------


class LessonService:
    """Returns the published lesson under a subtopic, gated for the caller."""

    def __init__(
        self,
        *,
        lesson_repo: LessonRepository,
        subtopic_repo: SubtopicRepository,
        topic_repo: TopicRepository,
        module_service: ModuleService,
    ) -> None:
        self._lesson_repo = lesson_repo
        self._subtopic_repo = subtopic_repo
        self._topic_repo = topic_repo
        self._module_service = module_service

    def get_for_user(self, user: User, subtopic_id: int) -> Lesson:
        """Walk subtopic -> topic -> module for category isolation.

        Per Req 6.4, ``INCOMPLETE`` lessons are hidden from learners — they
        surface as 403, not 404, for the same existence-hiding reason as
        category isolation. ``DRAFT`` lessons are also hidden; only
        ``PUBLISHED`` rows reach learners.
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
        # Category check + Phase 2 cross-category preview.
        self._module_service.get_for_user(user, topic.module_id)

        lesson = self._lesson_repo.get_by_subtopic_id(subtopic_id)
        if lesson is None or lesson.status != LessonStatus.PUBLISHED.value:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="forbidden"
            )
        return lesson


# --- QuestionService --------------------------------------------------------


class QuestionService:
    """Admin-side write surface for ``Question`` rows.

    The read side (assembly) is owned by ``QuestionRepository`` directly;
    quiz/mock services compose those reads with the SQL quality gate. This
    service exposes only the write path so the rejection-log + denormalized-
    column logic lives in one place.
    """

    def __init__(
        self,
        *,
        question_repo: QuestionRepository,
        subtopic_repo: SubtopicRepository,
        topic_repo: TopicRepository,
        module_repo: ModuleRepository,
    ) -> None:
        self._question_repo = question_repo
        self._subtopic_repo = subtopic_repo
        self._topic_repo = topic_repo
        self._module_repo = module_repo

    def create(self, payload: QuestionCreate) -> Question:
        """Persist a new question, fan out denormalized columns, gate-check.

        The flow is:

        1. Resolve subtopic -> topic -> module so we can copy ``topic_id``,
           ``module_id``, and ``category`` into the question row. Unknown
           parent rows surface as **400 invalid_subtopic_id** because this
           is admin-write input validation, not a read-side category check.
        2. Build the ORM instance.
        3. Run :func:`is_question_quality_passing` against the transient
           instance to get a deterministic ``(passes, rule)`` result.
        4. Persist with ``is_active = passes``. Either way the row exists
           in the DB; failed rows live as ``is_active=False`` so the read
           side's quality gate filters them out.
        5. On failure, write a ``question_rejection_log`` row with the rule
           string (Req 18.4) and raise 400 with ``question_rejected:RULE``.

        Why the persist-then-log pattern instead of "validate then persist":
        Req 18.4 requires logging "with the Question id". A transient
        instance has no id; logging without an id breaks the FK constraint
        on ``question_rejection_log.question_id``. We accept the cost of
        an inactive row to keep the audit trail honest.
        """
        # 1. Parent fan-out.
        subtopic = self._subtopic_repo.get(payload.subtopic_id)
        if subtopic is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="invalid_subtopic_id",
            )
        topic = self._topic_repo.get(subtopic.topic_id)
        if topic is None:
            # Defensive: subtopic shouldn't exist without a topic, but if a
            # legacy migration left a dangling FK we'd rather fail loudly.
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="invalid_topic",
            )
        module = self._module_repo.get(topic.module_id)
        if module is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="invalid_module",
            )

        # 2. Build the ORM instance with denormalized columns set.
        question = Question(
            subtopic_id=payload.subtopic_id,
            topic_id=topic.id,
            module_id=module.id,
            category=module.category,
            level_scope=payload.level_scope.value,
            stem=payload.stem,
            options=payload.options,
            correct_answer=payload.correct_answer,
            explanation=payload.explanation,
            difficulty=payload.difficulty.value,
            qtype=payload.qtype.value,
            is_active=True,  # provisional; flipped below if gate fails
        )

        # 3. Quality gate against the transient instance.
        passes, rule = is_question_quality_passing(question)
        question.is_active = passes

        # 4. Persist (commit + refresh assigns the PK).
        self._question_repo.create(question)

        # 5. On gate failure, log + raise.
        if not passes:
            assert rule is not None  # invariant: rejection always names a rule
            self._question_repo.log_rejection(question.id, rule)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"question_rejected:{rule}",
            )
        return question
