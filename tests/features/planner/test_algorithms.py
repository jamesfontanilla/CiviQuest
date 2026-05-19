"""Unit tests for planner algorithms."""

from __future__ import annotations

from datetime import date, timedelta

from app.features.planner.algorithms.plan_generator import (
    SubtopicMasteryInput,
    generate_study_plan,
)
from app.features.planner.algorithms.readiness_predictor import (
    MasteryInput,
    predict_readiness,
)


def test_generate_plan_empty_when_past_date():
    result = generate_study_plan(
        target_exam_date=date.today() - timedelta(days=1),
        available_hours_per_day=2.0,
        target_score=0.85,
        mastery_data=[],
        all_subtopic_ids=[1, 2, 3],
        now=date.today(),
    )
    assert result == []


def test_generate_plan_produces_days():
    now = date.today()
    result = generate_study_plan(
        target_exam_date=now + timedelta(days=10),
        available_hours_per_day=2.0,
        target_score=0.85,
        mastery_data=[
            SubtopicMasteryInput(subtopic_id=1, mastery_score=0.2),
            SubtopicMasteryInput(subtopic_id=2, mastery_score=0.8),
        ],
        all_subtopic_ids=[1, 2, 3],
        now=now,
    )
    assert len(result) > 0
    # All days should be between now+1 and target
    for day in result:
        assert now < day.plan_date <= now + timedelta(days=10)
        assert day.activity_type in ("lesson", "quiz", "review", "mock_exam")
        assert day.estimated_minutes > 0


def test_readiness_all_zeros():
    report = predict_readiness(
        mastery_data=[],
        recent_quiz_scores=[],
        mock_exam_scores=[],
        streak_count=0,
        total_study_sessions=0,
    )
    assert report.passing_probability >= 0.0
    assert report.passing_probability <= 1.0
    assert report.readiness_percentage == 0.0
    assert report.confidence_level == "low"
    assert report.recommended_hours_remaining == 40.0


def test_readiness_perfect_scores():
    mastery = [
        MasteryInput(subtopic_id=i, subtopic_title=f"Sub {i}", mastery_score=1.0)
        for i in range(10)
    ]
    report = predict_readiness(
        mastery_data=mastery,
        recent_quiz_scores=[1.0] * 10,
        mock_exam_scores=[1.0] * 5,
        streak_count=30,
        total_study_sessions=100,
    )
    assert report.passing_probability > 0.9
    assert report.readiness_percentage == 100.0
    assert report.confidence_level == "very_high"
    assert report.recommended_hours_remaining == 0.0
    assert len(report.weaknesses) == 0


def test_readiness_mixed_scores():
    mastery = [
        MasteryInput(subtopic_id=1, subtopic_title="Strong", mastery_score=0.9),
        MasteryInput(subtopic_id=2, subtopic_title="Weak", mastery_score=0.2),
        MasteryInput(subtopic_id=3, subtopic_title="Medium", mastery_score=0.5),
    ]
    report = predict_readiness(
        mastery_data=mastery,
        recent_quiz_scores=[0.7, 0.8, 0.6],
        mock_exam_scores=[0.65],
        streak_count=5,
        total_study_sessions=20,
    )
    assert 0.0 <= report.passing_probability <= 1.0
    assert 0.0 <= report.readiness_percentage <= 100.0
    assert "Weak" in report.weaknesses
    assert report.confidence_level in ("low", "moderate", "high", "very_high")
