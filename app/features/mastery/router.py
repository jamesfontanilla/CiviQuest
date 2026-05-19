"""FastAPI router for the mastery slice.

Mounts under ``/v1`` and exposes mastery tracking, spaced repetition
review scheduling, and personalized recommendations.

All routes require authentication via ``get_current_user``.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.common.deps import get_current_user
from app.features.content.repository import SubtopicRepository
from app.features.mastery.algorithms.recommendations import (
    generate_recommendations,
)
from app.features.mastery.repository import (
    MasteryRepository,
    ReviewScheduleRepository,
)
from app.features.mastery.schemas import (
    RecommendationResponse,
    ReviewCompleteRequest,
    ReviewDueResponse,
    SubtopicMasteryResponse,
)
from app.features.mastery.service import MasteryService, SpacedRepetitionService
from app.features.users.models import User
from app.infrastructure.database.session import get_db

router = APIRouter(prefix="/v1", tags=["mastery"])


def _get_mastery_service(db: Session = Depends(get_db)) -> MasteryService:
    """Construct MasteryService for the request."""
    return MasteryService(
        mastery_repo=MasteryRepository(db=db),
        subtopic_repo=SubtopicRepository(db=db),
    )


def _get_sr_service(db: Session = Depends(get_db)) -> SpacedRepetitionService:
    """Construct SpacedRepetitionService for the request."""
    return SpacedRepetitionService(
        review_repo=ReviewScheduleRepository(db=db),
        subtopic_repo=SubtopicRepository(db=db),
    )


@router.get("/mastery/me", response_model=list[SubtopicMasteryResponse])
def get_my_mastery(
    user: User = Depends(get_current_user),
    service: MasteryService = Depends(_get_mastery_service),
) -> list[SubtopicMasteryResponse]:
    """All subtopic mastery for current user."""
    return service.get_user_mastery(user.id)


@router.get("/mastery/me/weakest", response_model=list[SubtopicMasteryResponse])
def get_my_weakest(
    user: User = Depends(get_current_user),
    service: MasteryService = Depends(_get_mastery_service),
) -> list[SubtopicMasteryResponse]:
    """Top 5 weakest subtopics."""
    return service.get_weakest_subtopics(user.id)


@router.get("/mastery/me/recommendations", response_model=list[RecommendationResponse])
def get_my_recommendations(
    user: User = Depends(get_current_user),
    service: MasteryService = Depends(_get_mastery_service),
    sr_service: SpacedRepetitionService = Depends(_get_sr_service),
    db: Session = Depends(get_db),
) -> list[RecommendationResponse]:
    """Personalized recommendations combining mastery + review schedules."""
    now = datetime.now(tz=timezone.utc)
    mastery_repo = MasteryRepository(db=db)
    review_repo = ReviewScheduleRepository(db=db)
    subtopic_repo = SubtopicRepository(db=db)

    mastery_data = list(mastery_repo.list_by_user(user.id))
    review_schedules = list(review_repo.list_by_user(user.id))

    # Build subtopic title lookup.
    subtopic_ids = {m.subtopic_id for m in mastery_data}
    subtopic_ids.update(rs.subtopic_id for rs in review_schedules)
    titles: dict[int, str] = {}
    for sid in subtopic_ids:
        st = subtopic_repo.get(sid)
        if st is not None:
            titles[sid] = st.title

    recs = generate_recommendations(
        mastery_data=mastery_data,
        review_schedules=review_schedules,
        now=now,
        subtopic_titles=titles,
    )
    return [
        RecommendationResponse(
            subtopic_id=r.subtopic_id,
            subtopic_title=r.subtopic_title,
            reason=r.reason,
            priority=r.priority,
            recommended_difficulty=r.recommended_difficulty.value,
        )
        for r in recs
    ]


@router.get("/mastery/me/reviews/due", response_model=list[ReviewDueResponse])
def get_due_reviews(
    user: User = Depends(get_current_user),
    service: SpacedRepetitionService = Depends(_get_sr_service),
) -> list[ReviewDueResponse]:
    """Due spaced repetition reviews."""
    return service.get_due_reviews(user.id)


@router.post("/mastery/me/reviews/{subtopic_id}:complete")
def complete_review(
    subtopic_id: int,
    payload: ReviewCompleteRequest,
    user: User = Depends(get_current_user),
    service: SpacedRepetitionService = Depends(_get_sr_service),
) -> dict[str, str]:
    """Record a review session result."""
    service.record_review(
        user_id=user.id,
        subtopic_id=subtopic_id,
        quality=payload.quality,
    )
    return {"status": "ok"}
