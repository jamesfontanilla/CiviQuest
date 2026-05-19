"""FastAPI router for the XP slice (Task 9.5).

One endpoint mounted under ``/v1``:

- ``GET /v1/xp/me`` — return the calling learner's cumulative XP, level,
  and current (decay-applied) streak (Req 11.4, 11.6).

The route depends on :func:`get_current_user` rather than
:func:`require_no_active_mock`. Like the progress snapshot, this is a
read-only surface that must keep working mid-mock-exam: the mock-exam UI
shows the learner's current XP / level / streak in the header chrome, and
blocking the read while a mock attempt is IN_PROGRESS would force the UI
to hide that chrome for a multi-hour window.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.common.deps import get_current_user
from app.features.achievements.repository import AchievementRepository
from app.features.achievements.service import AchievementService
from app.features.mock_exams.repository import MockExamRepository
from app.features.progress.repository import ProgressRepository
from app.features.quizzes.repository import QuizRepository
from app.features.users.models import User
from app.features.users.repository import UserRepository
from app.features.xp.repository import XPRepository
from app.features.xp.schemas import UserXPResponse
from app.features.xp.service import XPService
from app.infrastructure.database.session import get_db


router = APIRouter(prefix="/v1", tags=["xp"])


def get_xp_service(db: Session = Depends(get_db)) -> XPService:
    """Construct :class:`XPService` for the request.

    The achievement evaluator is wired in here so every production
    XP award triggers the criterion check (Req 13.1). The achievement
    service is held by the XP service for the duration of the request
    only; both share the same DB session so the evaluator's writes are
    transactionally consistent with the XP event that triggered them.
    """
    achievement_service = AchievementService(
        ach_repo=AchievementRepository(db=db),
        xp_repo=XPRepository(db=db),
        quiz_repo=QuizRepository(db=db),
        mock_repo=MockExamRepository(db=db),
        progress_repo=ProgressRepository(db=db),
    )
    return XPService(
        xp_repo=XPRepository(db=db),
        user_repo=UserRepository(db=db),
        achievement_service=achievement_service,
    )


@router.get("/xp/me", response_model=UserXPResponse)
def get_my_xp(
    user: User = Depends(get_current_user),
    service: XPService = Depends(get_xp_service),
) -> UserXPResponse:
    """Return the caller's XP / level / streak view (Req 11.4, 11.6).

    ``streak`` reflects the 36-hour decay rule applied at read time, so
    a learner who has been away for 40 hours sees ``streak: 0`` without
    the server having to write the cache back on the read.
    """
    return service.get_user_xp_view(user)
