"""FastAPI router for the achievements slice (Task 15.4).

One endpoint mounted under ``/v1``:

- ``GET /v1/achievements/me`` — return the calling learner's earned
  achievements joined with metadata (Req 13.4).

Like ``GET /v1/xp/me`` and ``GET /v1/leaderboards/*``, this route does
**not** depend on :func:`require_no_active_mock`. The mock-exam UI
displays the learner's achievement count in the header chrome; gating
the read while a mock attempt is IN_PROGRESS would force the chrome to
hide for a multi-hour window.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.common.deps import get_current_user
from app.features.achievements.repository import AchievementRepository
from app.features.achievements.schemas import UserAchievementResponse
from app.features.achievements.service import AchievementService
from app.features.mock_exams.repository import MockExamRepository
from app.features.progress.repository import ProgressRepository
from app.features.quizzes.repository import QuizRepository
from app.features.users.models import User
from app.features.xp.repository import XPRepository
from app.infrastructure.database.session import get_db


router = APIRouter(prefix="/v1", tags=["achievements"])


def get_achievement_service(
    db: Session = Depends(get_db),
) -> AchievementService:
    """Construct :class:`AchievementService` for the request.

    Plumbs every repository the evaluator might consult so future
    criteria can land without touching the route wiring.
    """
    return AchievementService(
        ach_repo=AchievementRepository(db=db),
        xp_repo=XPRepository(db=db),
        quiz_repo=QuizRepository(db=db),
        mock_repo=MockExamRepository(db=db),
        progress_repo=ProgressRepository(db=db),
    )


@router.get(
    "/achievements/me",
    response_model=list[UserAchievementResponse],
)
def get_my_achievements(
    user: User = Depends(get_current_user),
    service: AchievementService = Depends(get_achievement_service),
) -> list[UserAchievementResponse]:
    """Return the caller's earned achievements (Req 13.4).

    Each entry carries the achievement's ``title`` and ``description``
    so the client can render the badge without a second round-trip.
    """
    return service.list_for_user(user.id)
