"""FastAPI router for the progress slice (Task 8.4).

Three endpoints mounted under ``/v1``:

- ``POST /v1/subtopics/{subtopic_id}/lesson:complete`` — record a
  lesson-completion event for the calling user. Gated by
  :func:`require_no_active_mock` per Req 19.1: a learner with an
  in-progress mock attempt cannot record progress through the normal
  endpoints (the mock attempt has its own scoring path).
- ``GET /v1/progress/snapshot`` — resume payload (Req 14.2). Uses
  :func:`get_current_user` rather than :func:`require_no_active_mock`
  because the snapshot is the canonical "resume mid-mock" surface;
  blocking it would prevent clients from re-entering an in-progress
  mock attempt after a restart.
- ``POST /v1/progress:sync`` — offline-sync ingestion (Task 16.2,
  Req 14.1, 20.3). Uses :func:`get_current_user` rather than
  :func:`require_no_active_mock` because sync needs to keep working
  mid-mock — a learner who started a mock attempt may still be
  flushing pre-mock pending events from the offline queue.

Per ``code-conventions.md`` the route handlers are thin: each delegates
to :class:`ProgressService` (or :class:`SyncService`) via
``Depends(...)`` and returns the result. The factory function
constructs the service per-request, sharing a single :class:`Session`
across the dependency graph.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.common.deps import get_current_user, require_no_active_mock
from app.features.achievements.repository import AchievementRepository
from app.features.achievements.service import AchievementService
from app.features.content.repository import (
    LessonRepository,
    SubtopicRepository,
)
from app.features.mock_exams.repository import MockExamRepository
from app.features.progress.repository import ProgressRepository
from app.features.progress.schemas import (
    LessonCompleteRequest,
    LessonCompleteResponse,
    ProgressSnapshotResponse,
    SyncRequest,
    SyncResponse,
    SyncResultOut,
)
from app.features.progress.service import ProgressService
from app.features.progress.sync_service import SyncService
from app.features.quizzes.repository import QuizRepository
from app.features.users.models import User
from app.features.users.repository import UserRepository
from app.features.xp.repository import XPRepository
from app.features.xp.service import XPService
from app.infrastructure.database.session import get_db


router = APIRouter(prefix="/v1", tags=["progress"])


def get_progress_service(db: Session = Depends(get_db)) -> ProgressService:
    """Construct :class:`ProgressService` for the request."""
    return ProgressService(
        progress_repo=ProgressRepository(db=db),
        lesson_repo=LessonRepository(db=db),
        subtopic_repo=SubtopicRepository(db=db),
        mock_repo=MockExamRepository(db=db),
    )


def get_sync_service(db: Session = Depends(get_db)) -> SyncService:
    """Construct :class:`SyncService` for the request.

    Wires both the underlying :class:`ProgressService` and
    :class:`XPService` so each event kind has its existing dispatch
    target. The XP service is constructed with its full achievement
    evaluator (matches :func:`app.features.xp.router.get_xp_service`)
    so an XP event synced offline still triggers the same achievement
    fan-out an online XP award would.

    The persistence-layer repositories
    (:class:`ProgressRepository`, :class:`XPRepository`,
    :class:`SubtopicRepository`, :class:`LessonRepository`) are
    passed through as well so the service can perform the
    early-exit idempotency lookup on ``client_event_id`` without
    re-running the full service codepath on a replay.
    """
    progress_repo = ProgressRepository(db=db)
    lesson_repo = LessonRepository(db=db)
    subtopic_repo = SubtopicRepository(db=db)
    mock_repo = MockExamRepository(db=db)
    xp_repo = XPRepository(db=db)
    progress_service = ProgressService(
        progress_repo=progress_repo,
        lesson_repo=lesson_repo,
        subtopic_repo=subtopic_repo,
        mock_repo=mock_repo,
    )
    achievement_service = AchievementService(
        ach_repo=AchievementRepository(db=db),
        xp_repo=xp_repo,
        quiz_repo=QuizRepository(db=db),
        mock_repo=mock_repo,
        progress_repo=progress_repo,
    )
    xp_service = XPService(
        xp_repo=xp_repo,
        user_repo=UserRepository(db=db),
        achievement_service=achievement_service,
    )
    return SyncService(
        progress_service=progress_service,
        progress_repo=progress_repo,
        xp_repo=xp_repo,
        xp_service=xp_service,
        subtopic_repo=subtopic_repo,
        lesson_repo=lesson_repo,
    )


@router.post(
    "/subtopics/{subtopic_id}/lesson:complete",
    status_code=status.HTTP_201_CREATED,
    response_model=LessonCompleteResponse,
)
def complete_lesson(
    subtopic_id: int,
    payload: LessonCompleteRequest,
    user: User = Depends(require_no_active_mock),
    service: ProgressService = Depends(get_progress_service),
) -> LessonCompleteResponse:
    """Record a lesson-completion event for the caller (Req 6.2, 14.1).

    Returns 201 on a fresh completion (with ``awarded_xp=20``) and 201
    + ``awarded_xp=0`` on an idempotent retry. The status code is the
    same on both paths because the persisted record is the canonical
    state — clients don't need to distinguish "created now" from
    "created on a previous request" to render the UI.
    """
    return service.complete_lesson(
        user=user, subtopic_id=subtopic_id, payload=payload
    )


@router.get("/progress/snapshot", response_model=ProgressSnapshotResponse)
def progress_snapshot(
    user: User = Depends(get_current_user),
    service: ProgressService = Depends(get_progress_service),
) -> ProgressSnapshotResponse:
    """Return the resume snapshot for the caller (Req 14.2).

    Note the dependency on :func:`get_current_user` rather than
    :func:`require_no_active_mock`: this endpoint is the one route in
    the system that MUST work mid-mock-exam. Clients that crash or
    close the app during a mock attempt rely on this snapshot to
    surface the in-progress attempt and re-enter it.
    """
    return service.get_snapshot(user)



@router.post("/progress:sync", response_model=SyncResponse)
def sync_progress(
    payload: SyncRequest,
    user: User = Depends(get_current_user),
    service: SyncService = Depends(get_sync_service),
) -> SyncResponse:
    """Drain an offline-sync batch (Task 16.2, Req 14.1, 20.3).

    The PWA's Background Sync flow POSTs every queued offline event
    here in a single request; the server returns a partition of
    accepted ids and rejection rows so the client can prune
    IndexedDB accordingly.

    ``Depends(get_current_user)`` (not ``require_no_active_mock``):
    sync needs to keep working mid-mock-exam so a learner who started
    a mock can still flush pre-mock pending events that are still
    sitting in their offline queue.
    """
    accepted, rejected = service.sync_events(
        user=user, events=payload.events
    )
    return SyncResponse(
        accepted=accepted,
        rejected=[
            SyncResultOut(
                client_event_id=r.client_event_id,
                accepted=r.accepted,
                reason=r.reason,
            )
            for r in rejected
        ],
    )
