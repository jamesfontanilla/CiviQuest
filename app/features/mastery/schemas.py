"""Pydantic schemas for the mastery feature."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.features.mastery.models import MasteryLevel


class SubtopicMasteryResponse(BaseModel):
    """Response schema for a single subtopic's mastery data."""

    subtopic_id: int
    subtopic_title: str
    mastery_level: MasteryLevel
    mastery_score: float
    confidence_score: float
    retention_score: float
    total_attempts: int
    correct_attempts: int
    last_practiced_at: datetime | None

    model_config = {"from_attributes": True}


class RecommendationResponse(BaseModel):
    """Response schema for a study recommendation."""

    subtopic_id: int
    subtopic_title: str
    reason: str
    priority: float
    recommended_difficulty: str


class ReviewDueResponse(BaseModel):
    """Response schema for a due review item."""

    subtopic_id: int
    subtopic_title: str
    next_review_at: datetime
    days_overdue: float
    interval_days: float


class ReviewCompleteRequest(BaseModel):
    """Request body for completing a review session."""

    quality: int = Field(ge=0, le=5, description="SM-2 quality rating 0-5")
