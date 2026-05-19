"""Repository for tutor interactions."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.features.tutor.models import TutorInteraction
from app.infrastructure.repositories.base import BaseRepository


class TutorRepository(BaseRepository[TutorInteraction]):
    """Data access for tutor interactions."""

    model = TutorInteraction

    def __init__(self, db: Session) -> None:
        super().__init__(db)

    def create_interaction(
        self,
        *,
        user_id: int,
        question_id: int | None,
        subtopic_id: int | None,
        interaction_type: str,
        request_context: dict | None,
        response_text: str,
    ) -> TutorInteraction:
        """Create and persist a new tutor interaction."""
        interaction = TutorInteraction(
            user_id=user_id,
            question_id=question_id,
            subtopic_id=subtopic_id,
            interaction_type=interaction_type,
            request_context=request_context,
            response_text=response_text,
        )
        self.db.add(interaction)
        self.db.commit()
        self.db.refresh(interaction)
        return interaction

    def rate_interaction(
        self, interaction_id: int, helpful: bool
    ) -> TutorInteraction | None:
        """Set the helpful flag on an interaction."""
        interaction = self.get(interaction_id)
        if interaction is None:
            return None
        interaction.helpful = helpful
        self.db.commit()
        self.db.refresh(interaction)
        return interaction
