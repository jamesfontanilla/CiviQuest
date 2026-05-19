"""Service tests for the mastery feature — mocked repositories."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from app.features.content.models import Subtopic
from app.features.content.repository import SubtopicRepository
from app.features.mastery.models import (
    MasteryLevel,
    ReviewSchedule,
    UserSubtopicMastery,
)
from app.features.mastery.repository import (
    MasteryRepository,
    ReviewScheduleRepository,
)
from app.features.mastery.service import MasteryService, SpacedRepetitionService


def _make_subtopic_mock(id: int = 1, title: str = "Test Subtopic") -> Subtopic:
    """Build a mock subtopic."""
    s = MagicMock(spec=Subtopic)
    s.id = id
    s.title = title
    return s


# ---------------------------------------------------------------------------
# MasteryService
# ---------------------------------------------------------------------------


class TestMasteryServiceRecordAttempt:
    def test_creates_new_mastery_on_first_attempt(self):
        mastery_repo = MagicMock(spec=MasteryRepository)
        subtopic_repo = MagicMock(spec=SubtopicRepository)
        mastery_repo.get_by_user_and_subtopic.return_value = None
        mastery_repo.upsert.side_effect = lambda m: m

        service = MasteryService(
            mastery_repo=mastery_repo,
            subtopic_repo=subtopic_repo,
        )

        result = service.record_attempt(
            user_id=1,
            subtopic_id=10,
            is_correct=True,
            response_time_ms=5000,
        )

        assert result.total_attempts == 1
        assert result.correct_attempts == 1
        assert result.mastery_score > 0.0
        mastery_repo.upsert.assert_called_once()

    def test_updates_existing_mastery(self):
        mastery_repo = MagicMock(spec=MasteryRepository)
        subtopic_repo = MagicMock(spec=SubtopicRepository)

        existing = UserSubtopicMastery(
            user_id=1,
            subtopic_id=10,
            mastery_score=0.3,
            mastery_level=MasteryLevel.FAMILIAR.value,
            total_attempts=5,
            correct_attempts=3,
            avg_response_time_ms=12000,
            confidence_score=0.25,
            retention_score=0.4,
        )
        mastery_repo.get_by_user_and_subtopic.return_value = existing
        mastery_repo.upsert.side_effect = lambda m: m

        service = MasteryService(
            mastery_repo=mastery_repo,
            subtopic_repo=subtopic_repo,
        )

        result = service.record_attempt(
            user_id=1,
            subtopic_id=10,
            is_correct=True,
            response_time_ms=8000,
        )

        assert result.total_attempts == 6
        assert result.correct_attempts == 4
        assert result.mastery_score > 0.0

    def test_incorrect_attempt_lowers_accuracy(self):
        mastery_repo = MagicMock(spec=MasteryRepository)
        subtopic_repo = MagicMock(spec=SubtopicRepository)

        existing = UserSubtopicMastery(
            user_id=1,
            subtopic_id=10,
            mastery_score=0.8,
            mastery_level=MasteryLevel.ADVANCED.value,
            total_attempts=10,
            correct_attempts=9,
            avg_response_time_ms=8000,
            confidence_score=0.5,
            retention_score=0.9,
        )
        mastery_repo.get_by_user_and_subtopic.return_value = existing
        mastery_repo.upsert.side_effect = lambda m: m

        service = MasteryService(
            mastery_repo=mastery_repo,
            subtopic_repo=subtopic_repo,
        )

        result = service.record_attempt(
            user_id=1,
            subtopic_id=10,
            is_correct=False,
            response_time_ms=45000,
        )

        # Score should decrease since accuracy dropped and response time is slow.
        assert result.total_attempts == 11
        assert result.correct_attempts == 9


class TestMasteryServiceGetUserMastery:
    def test_returns_empty_list_for_no_data(self):
        mastery_repo = MagicMock(spec=MasteryRepository)
        subtopic_repo = MagicMock(spec=SubtopicRepository)
        mastery_repo.list_by_user.return_value = []

        service = MasteryService(
            mastery_repo=mastery_repo,
            subtopic_repo=subtopic_repo,
        )

        result = service.get_user_mastery(user_id=1)
        assert result == []

    def test_returns_mastery_responses(self):
        mastery_repo = MagicMock(spec=MasteryRepository)
        subtopic_repo = MagicMock(spec=SubtopicRepository)

        mastery_row = UserSubtopicMastery(
            user_id=1,
            subtopic_id=10,
            mastery_score=0.6,
            mastery_level=MasteryLevel.PROFICIENT.value,
            total_attempts=15,
            correct_attempts=10,
            confidence_score=0.75,
            retention_score=0.7,
            last_practiced_at=None,
        )
        mastery_repo.list_by_user.return_value = [mastery_row]
        subtopic_repo.get.return_value = _make_subtopic_mock(id=10, title="Civil Law")

        service = MasteryService(
            mastery_repo=mastery_repo,
            subtopic_repo=subtopic_repo,
        )

        result = service.get_user_mastery(user_id=1)
        assert len(result) == 1
        assert result[0].subtopic_id == 10
        assert result[0].subtopic_title == "Civil Law"
        assert result[0].mastery_score == 0.6


class TestMasteryServiceGetWeakest:
    def test_returns_weakest_subtopics(self):
        mastery_repo = MagicMock(spec=MasteryRepository)
        subtopic_repo = MagicMock(spec=SubtopicRepository)

        weak = UserSubtopicMastery(
            user_id=1,
            subtopic_id=5,
            mastery_score=0.1,
            mastery_level=MasteryLevel.BEGINNER.value,
            total_attempts=3,
            correct_attempts=1,
            confidence_score=0.15,
            retention_score=0.2,
            last_practiced_at=None,
        )
        mastery_repo.list_weakest.return_value = [weak]
        subtopic_repo.get.return_value = _make_subtopic_mock(id=5, title="Weak Topic")

        service = MasteryService(
            mastery_repo=mastery_repo,
            subtopic_repo=subtopic_repo,
        )

        result = service.get_weakest_subtopics(user_id=1, limit=5)
        assert len(result) == 1
        assert result[0].subtopic_title == "Weak Topic"


# ---------------------------------------------------------------------------
# SpacedRepetitionService
# ---------------------------------------------------------------------------


class TestSpacedRepetitionServiceScheduleInitial:
    def test_creates_schedule_for_new_subtopic(self):
        review_repo = MagicMock(spec=ReviewScheduleRepository)
        subtopic_repo = MagicMock(spec=SubtopicRepository)
        review_repo.get_by_user_and_subtopic.return_value = None
        review_repo.upsert.side_effect = lambda s: s

        service = SpacedRepetitionService(
            review_repo=review_repo,
            subtopic_repo=subtopic_repo,
        )

        now = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
        result = service.schedule_initial_review(
            user_id=1, subtopic_id=10, now=now
        )

        assert result.interval_days == 1.0
        assert result.next_review_at == now + timedelta(days=1)
        review_repo.upsert.assert_called_once()

    def test_does_not_overwrite_existing_schedule(self):
        review_repo = MagicMock(spec=ReviewScheduleRepository)
        subtopic_repo = MagicMock(spec=SubtopicRepository)

        existing = ReviewSchedule(
            user_id=1,
            subtopic_id=10,
            next_review_at=datetime(2024, 1, 20, tzinfo=timezone.utc),
            interval_days=5.0,
            ease_factor=2.5,
            repetitions=3,
        )
        review_repo.get_by_user_and_subtopic.return_value = existing

        service = SpacedRepetitionService(
            review_repo=review_repo,
            subtopic_repo=subtopic_repo,
        )

        result = service.schedule_initial_review(
            user_id=1, subtopic_id=10
        )

        assert result is existing
        review_repo.upsert.assert_not_called()


class TestSpacedRepetitionServiceRecordReview:
    def test_updates_schedule_with_sm2(self):
        review_repo = MagicMock(spec=ReviewScheduleRepository)
        subtopic_repo = MagicMock(spec=SubtopicRepository)

        existing = ReviewSchedule(
            user_id=1,
            subtopic_id=10,
            next_review_at=datetime(2024, 1, 15, tzinfo=timezone.utc),
            interval_days=1.0,
            ease_factor=2.5,
            repetitions=0,
        )
        review_repo.get_by_user_and_subtopic.return_value = existing
        review_repo.upsert.side_effect = lambda s: s

        service = SpacedRepetitionService(
            review_repo=review_repo,
            subtopic_repo=subtopic_repo,
        )

        now = datetime(2024, 1, 16, 12, 0, 0, tzinfo=timezone.utc)
        result = service.record_review(
            user_id=1, subtopic_id=10, quality=4, now=now
        )

        assert result.repetitions == 1
        assert result.last_reviewed_at == now
        assert result.next_review_at == now + timedelta(days=result.interval_days)

    def test_failed_review_resets_repetitions(self):
        review_repo = MagicMock(spec=ReviewScheduleRepository)
        subtopic_repo = MagicMock(spec=SubtopicRepository)

        existing = ReviewSchedule(
            user_id=1,
            subtopic_id=10,
            next_review_at=datetime(2024, 1, 15, tzinfo=timezone.utc),
            interval_days=10.0,
            ease_factor=2.5,
            repetitions=5,
        )
        review_repo.get_by_user_and_subtopic.return_value = existing
        review_repo.upsert.side_effect = lambda s: s

        service = SpacedRepetitionService(
            review_repo=review_repo,
            subtopic_repo=subtopic_repo,
        )

        now = datetime(2024, 1, 16, 12, 0, 0, tzinfo=timezone.utc)
        result = service.record_review(
            user_id=1, subtopic_id=10, quality=1, now=now
        )

        assert result.repetitions == 0
        assert result.interval_days == 1.0


class TestSpacedRepetitionServiceGetDueReviews:
    def test_returns_due_items(self):
        review_repo = MagicMock(spec=ReviewScheduleRepository)
        subtopic_repo = MagicMock(spec=SubtopicRepository)

        now = datetime(2024, 1, 20, 12, 0, 0, tzinfo=timezone.utc)
        schedule = ReviewSchedule(
            user_id=1,
            subtopic_id=10,
            next_review_at=datetime(2024, 1, 18, tzinfo=timezone.utc),
            interval_days=3.0,
            ease_factor=2.5,
            repetitions=2,
        )
        review_repo.list_due.return_value = [schedule]
        subtopic_repo.get.return_value = _make_subtopic_mock(id=10, title="Due Topic")

        service = SpacedRepetitionService(
            review_repo=review_repo,
            subtopic_repo=subtopic_repo,
        )

        result = service.get_due_reviews(user_id=1, now=now)
        assert len(result) == 1
        assert result[0].subtopic_id == 10
        assert result[0].subtopic_title == "Due Topic"
        assert result[0].days_overdue > 0
