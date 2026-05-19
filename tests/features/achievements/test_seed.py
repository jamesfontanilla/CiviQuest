"""Seed tests for the achievements slice (Task 15.1, 15.5)."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.features.achievements.models import Achievement
from app.features.achievements.repository import AchievementRepository
from app.features.achievements.seed import (
    MVP_ACHIEVEMENTS,
    PHASE2_ACHIEVEMENTS,
    seed_all_achievements,
    seed_mvp_achievements,
    seed_phase2_achievements,
)


# --- catalog --------------------------------------------------------------


def test_mvp_achievements_contains_three_named_entries() -> None:
    """Task 15.1 — the MVP set is exactly FIRST_LESSON, STREAK_7_DAYS, LEVEL_10."""
    ids = {a.id for a in MVP_ACHIEVEMENTS}

    assert ids == {"FIRST_LESSON", "STREAK_7_DAYS", "LEVEL_10"}


def test_phase2_achievements_contains_six_named_entries() -> None:
    """Task 15.5 — Phase 2 adds the remaining six from Req 13.4."""
    ids = {a.id for a in PHASE2_ACHIEVEMENTS}

    assert ids == {
        "FIRST_PERFECT_SUBTOPIC_QUIZ",
        "FIRST_TOPIC_PASSED",
        "FIRST_MODULE_PASSED",
        "FIRST_MOCK_PASSED",
        "STREAK_30_DAYS",
        "LEVEL_25",
    }


def test_streak_7_days_seed_carries_days_criterion_value() -> None:
    """STREAK_7_DAYS must declare ``criterion_value == {"days": 7}``."""
    streak = next(a for a in MVP_ACHIEVEMENTS if a.id == "STREAK_7_DAYS")

    assert streak.criterion_kind == "STREAK_N_DAYS"
    assert streak.criterion_value == {"days": 7}


def test_level_10_seed_carries_level_criterion_value() -> None:
    level = next(a for a in MVP_ACHIEVEMENTS if a.id == "LEVEL_10")

    assert level.criterion_kind == "LEVEL_N"
    assert level.criterion_value == {"level": 10}


def test_first_lesson_seed_carries_first_lesson_criterion_kind() -> None:
    first = next(a for a in MVP_ACHIEVEMENTS if a.id == "FIRST_LESSON")

    assert first.criterion_kind == "FIRST_LESSON"
    assert first.criterion_value == {}


# --- seeding -------------------------------------------------------------


def test_seed_mvp_achievements_writes_three_rows(db_session: Session) -> None:
    repo = AchievementRepository(db=db_session)

    seed_mvp_achievements(repo)

    rows = repo.list_all()
    assert {r.id for r in rows} == {
        "FIRST_LESSON",
        "STREAK_7_DAYS",
        "LEVEL_10",
    }


def test_seed_mvp_achievements_is_idempotent(db_session: Session) -> None:
    """Running the seeder twice must not duplicate rows or fail."""
    repo = AchievementRepository(db=db_session)

    seed_mvp_achievements(repo)
    seed_mvp_achievements(repo)

    assert db_session.query(Achievement).count() == 3


def test_seed_phase2_achievements_writes_six_rows(db_session: Session) -> None:
    repo = AchievementRepository(db=db_session)

    seed_phase2_achievements(repo)

    rows = repo.list_all()
    assert {r.id for r in rows} == {
        "FIRST_PERFECT_SUBTOPIC_QUIZ",
        "FIRST_TOPIC_PASSED",
        "FIRST_MODULE_PASSED",
        "FIRST_MOCK_PASSED",
        "STREAK_30_DAYS",
        "LEVEL_25",
    }


def test_seed_all_achievements_writes_full_set(db_session: Session) -> None:
    repo = AchievementRepository(db=db_session)

    seed_all_achievements(repo)

    rows = repo.list_all()
    assert len(rows) == 12
    assert {r.id for r in rows} == {
        "FIRST_LESSON",
        "STREAK_7_DAYS",
        "LEVEL_10",
        "FIRST_PERFECT_SUBTOPIC_QUIZ",
        "FIRST_TOPIC_PASSED",
        "FIRST_MODULE_PASSED",
        "FIRST_MOCK_PASSED",
        "STREAK_30_DAYS",
        "LEVEL_25",
        "DAILY_GOAL_7",
        "DAILY_GOAL_30",
        "TOURNAMENT_WINNER",
    }


def test_seed_all_achievements_is_idempotent(db_session: Session) -> None:
    repo = AchievementRepository(db=db_session)

    seed_all_achievements(repo)
    seed_all_achievements(repo)

    assert db_session.query(Achievement).count() == 12
