"""Service tests for the planner feature — mocked repositories."""

from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.features.content.models import Subtopic
from app.features.content.repository import SubtopicRepository
from app.features.mastery.models import UserSubtopicMastery
from app.features.mastery.repository import MasteryRepository
from app.features.planner.models import StudyPlan, StudyPlanDay
from app.features.planner.repository import StudyPlanDayRepository, StudyPlanRepository
from app.features.planner.service import StudyPlannerService


@pytest.fixture
def mock_plan_repo() -> MagicMock:
    return MagicMock(spec=StudyPlanRepository)


@pytest.fixture
def mock_day_repo() -> MagicMock:
    return MagicMock(spec=StudyPlanDayRepository)


@pytest.fixture
def mock_mastery_repo() -> MagicMock:
    return MagicMock(spec=MasteryRepository)


@pytest.fixture
def mock_subtopic_repo() -> MagicMock:
    return MagicMock(spec=SubtopicRepository)


@pytest.fixture
def service(mock_plan_repo, mock_day_repo, mock_mastery_repo, mock_subtopic_repo):
    return StudyPlannerService(
        plan_repo=mock_plan_repo,
        day_repo=mock_day_repo,
        mastery_repo=mock_mastery_repo,
        subtopic_repo=mock_subtopic_repo,
    )


def test_create_plan_rejects_past_date(service, mock_plan_repo):
    with pytest.raises(HTTPException) as exc_info:
        service.create_plan(
            user_id=1,
            target_exam_date=date.today() - timedelta(days=1),
            available_hours_per_day=2.0,
            target_score=0.85,
        )
    assert exc_info.value.status_code == 422


def test_create_plan_abandons_existing(
    service, mock_plan_repo, mock_day_repo, mock_mastery_repo, mock_subtopic_repo
):
    existing_plan = MagicMock(spec=StudyPlan)
    mock_plan_repo.get_active_plan.return_value = existing_plan
    mock_mastery_repo.list_by_user.return_value = []
    mock_subtopic_repo.list.return_value = []

    new_plan = MagicMock(spec=StudyPlan)
    new_plan.id = 1
    new_plan.target_exam_date = date.today() + timedelta(days=30)
    new_plan.available_hours_per_day = 2.0
    new_plan.target_score = 0.85
    new_plan.status = "ACTIVE"
    mock_plan_repo.create.return_value = new_plan
    mock_day_repo.count_total.return_value = 0
    mock_day_repo.count_completed.return_value = 0

    service.create_plan(
        user_id=1,
        target_exam_date=date.today() + timedelta(days=30),
        available_hours_per_day=2.0,
        target_score=0.85,
    )

    mock_plan_repo.abandon_plan.assert_called_once_with(existing_plan)


def test_get_active_plan_returns_none_when_no_plan(service, mock_plan_repo):
    mock_plan_repo.get_active_plan.return_value = None
    result = service.get_active_plan(user_id=1)
    assert result is None


def test_mark_task_complete_raises_404_no_plan(service, mock_plan_repo):
    mock_plan_repo.get_active_plan.return_value = None
    with pytest.raises(HTTPException) as exc_info:
        service.mark_task_complete(user_id=1, task_id=1)
    assert exc_info.value.status_code == 404


def test_mark_task_complete_raises_404_wrong_task(service, mock_plan_repo, mock_day_repo):
    plan = MagicMock(spec=StudyPlan)
    plan.id = 1
    mock_plan_repo.get_active_plan.return_value = plan
    mock_day_repo.get.return_value = None

    with pytest.raises(HTTPException) as exc_info:
        service.mark_task_complete(user_id=1, task_id=999)
    assert exc_info.value.status_code == 404


def test_abandon_plan_raises_404_no_plan(service, mock_plan_repo):
    mock_plan_repo.get_active_plan.return_value = None
    with pytest.raises(HTTPException) as exc_info:
        service.abandon_plan(user_id=1)
    assert exc_info.value.status_code == 404
