"""SQLAlchemy ORM models for the AI tutor feature.

Owns the tutor interaction tracking table that records every tutor
request/response pair for analytics and user feedback.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base


_INTERACTION_TYPE_VALUES = (
    "('explain_answer', 'simplify', 'similar_question', 'step_by_step', 'hint')"
)


class TutorInteraction(Base):
    """Records a single tutor interaction (request + generated response).

    The tutor is rule-based (no external LLM API). Each interaction
    captures what the user asked for, the context, and the generated
    response text. The optional ``helpful`` field captures user feedback.
    """

    __tablename__ = "tutor_interactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    question_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("questions.id", ondelete="CASCADE"),
        nullable=True,
    )
    subtopic_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("subtopics.id", ondelete="CASCADE"),
        nullable=True,
    )
    interaction_type: Mapped[str] = mapped_column(String(32), nullable=False)
    request_context: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    response_text: Mapped[str] = mapped_column(Text, nullable=False)
    helpful: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        CheckConstraint(
            f"interaction_type IN {_INTERACTION_TYPE_VALUES}",
            name="ck_tutor_interactions_type",
        ),
    )
