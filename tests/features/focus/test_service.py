"""Service tests for the focus feature — mocked repository."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.features.focus.models import FocusSession
from app.features.focus.repository import FocusSessionRepository
from app.features.focus.service import FocusService


def _mock_repo() -> MagicMock:
    return MagicMock(spec=FocusSessionRepository)


def _make_session(**kwargs) -> FocusSession:
    defaults = {
        "id": 1,
        "user_id": 10,
        "mode": "25_5",
        "work_minutes": 25,
        "break_minutes": 5,
        "started_at": datetime.now(tz=timezone.utc),
        "ended_at": None,
        "completed": False,
        "total_focus_minutes": 0,
        "distractions": 0,
    }
    defaults.update(kwargs)
    s = FocusSession(**defaults)
    return s


def test_start_session_creates_and_returns() -> None:
    repo = _mock_repo()

    def _fake_create(s: FocusSession) -> FocusSession:
        s.id = 1
        s.completed = False
        s.total_focus_minutes = 0
        s.distractions = 0
        return s

    repo.create.side_effect = _fake_create
    service = FocusService(repository=repo)

    result = service.start_session(10, mode="25_5", work_minutes=25, break_minutes=5)
    assert result.mode == "25_5"
    assert result.work_minutes == 25
    repo.create.assert_called_once()


def test_complete_session_success() -> None:
    repo = _mock_repo()
    session = _make_session(id=5, user_id=10, completed=False)
    repo.get_user_session.return_value = session
    repo.update.side_effect = lambda s, **kw: (
        [setattr(s, k, v) for k, v in kw.items()] and None
    ) or s

    service = FocusService(repository=repo)
    result = service.complete_session(10, 5, total_focus_minutes=22, distractions=1)

    repo.get_user_session.assert_called_once_with(10, 5)
    repo.update.assert_called_once()


def test_complete_session_not_found() -> None:
    repo = _mock_repo()
    repo.get_user_session.return_value = None

    service = FocusService(repository=repo)
    with pytest.raises(HTTPException) as exc_info:
        service.complete_session(10, 999, total_focus_minutes=20, distractions=0)
    assert exc_info.value.status_code == 404


def test_complete_session_already_completed() -> None:
    repo = _mock_repo()
    session = _make_session(id=5, user_id=10, completed=True)
    repo.get_user_session.return_value = session

    service = FocusService(repository=repo)
    with pytest.raises(HTTPException) as exc_info:
        service.complete_session(10, 5, total_focus_minutes=20, distractions=0)
    assert exc_info.value.status_code == 409


def test_abandon_session_success() -> None:
    repo = _mock_repo()
    session = _make_session(id=5, user_id=10, completed=False)
    repo.get_user_session.return_value = session
    repo.update.return_value = session

    service = FocusService(repository=repo)
    service.abandon_session(10, 5)

    repo.update.assert_called_once()


def test_abandon_session_not_found() -> None:
    repo = _mock_repo()
    repo.get_user_session.return_value = None

    service = FocusService(repository=repo)
    with pytest.raises(HTTPException) as exc_info:
        service.abandon_session(10, 999)
    assert exc_info.value.status_code == 404


def test_get_stats() -> None:
    repo = _mock_repo()
    repo.count_user_sessions.return_value = 10
    repo.total_focus_minutes.return_value = 300
    repo.avg_session_minutes.return_value = 30.0
    repo.sessions_today.return_value = 2
    repo.focus_minutes_today.return_value = 50

    service = FocusService(repository=repo)
    stats = service.get_stats(10)

    assert stats.total_sessions == 10
    assert stats.total_focus_hours == 5.0
    assert stats.avg_session_minutes == 30.0
    assert stats.sessions_today == 2
    assert stats.focus_minutes_today == 50


def test_get_wellness_no_fatigue() -> None:
    repo = _mock_repo()
    repo.focus_minutes_today.return_value = 30

    service = FocusService(repository=repo)
    result = service.get_wellness(10)

    assert result.is_fatigued is False
    assert result.fatigue_level == "none"
    assert result.suggestion == "keep_going"


def test_get_wellness_high_fatigue() -> None:
    repo = _mock_repo()
    repo.focus_minutes_today.return_value = 200

    service = FocusService(repository=repo)
    result = service.get_wellness(10)

    assert result.is_fatigued is True
    assert result.fatigue_level == "high"
    assert result.suggestion == "stop_for_today"
