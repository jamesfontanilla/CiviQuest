"""Pydantic request/response schemas for the study planner feature."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field


class CreatePlanRequest(BaseModel):
    """Request body for creating a study plan."""

    target_exam_date: date
    available_hours_per_day: float = Field(ge=0.5, le=12.0)
    target_score: float = Field(ge=0.5, le=1.0)


class StudyPlanResponse(BaseModel):
    """Response for a study plan."""

    id: int
    target_exam_date: date
    available_hours_per_day: float
    target_score: float
    status: str
    total_days: int
    days_remaining: int
    completion_percentage: float

    model_config = {"from_attributes": True}


class PlanDayResponse(BaseModel):
    """Response for a single day's task in the plan."""

    id: int
    plan_date: date
    subtopic_title: str
    activity_type: str
    estimated_minutes: int
    completed: bool

    model_config = {"from_attributes": True}


class ReadinessResponse(BaseModel):
    """Response for exam readiness prediction."""

    passing_probability: float
    predicted_score: float
    readiness_percentage: float
    recommended_hours_remaining: float
    strengths: list[str]
    weaknesses: list[str]
    confidence_level: str
