"""Service tests for the tournament service.

Per testing-standards.md: mocked repositories, test business logic.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.features.gamification.models import Tournament, TournamentParticipant
from app.features.gamification.repository import TournamentRepository
from app.features.gamification.tournament_service import TournamentService


def _now() -> datetime:
    return datetime(2025, 6, 15, 12, 0, 0, tzinfo=timezone.utc)


class TestTournamentService:
    def _make_service(self) -> tuple[TournamentService, MagicMock]:
        mock_repo = MagicMock(spec=TournamentRepository)
        service = TournamentService(tournament_repo=mock_repo)
        return service, mock_repo

    def test_list_active_returns_tournaments(self) -> None:
        service, mock_repo = self._make_service()
        t = MagicMock(spec=Tournament)
        t.id = 1
        t.title = "Sprint"
        t.description = None
        t.category = None
        t.starts_at = _now()
        t.ends_at = _now() + timedelta(days=7)
        t.status = "ACTIVE"
        t.max_participants = None
        t.prize_description = None
        mock_repo.list_active_and_upcoming.return_value = [t]

        result = service.list_active(now=_now())
        assert len(result) == 1
        assert result[0].title == "Sprint"

    def test_join_raises_404_when_not_found(self) -> None:
        service, mock_repo = self._make_service()
        mock_repo.get.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            service.join(1, 999, now=_now())
        assert exc_info.value.status_code == 404

    def test_join_raises_409_when_already_joined(self) -> None:
        service, mock_repo = self._make_service()
        t = MagicMock(spec=Tournament)
        t.status = "ACTIVE"
        t.max_participants = None
        mock_repo.get.return_value = t
        mock_repo.get_participant.return_value = MagicMock(spec=TournamentParticipant)

        with pytest.raises(HTTPException) as exc_info:
            service.join(1, 1, now=_now())
        assert exc_info.value.status_code == 409

    def test_join_raises_409_when_full(self) -> None:
        service, mock_repo = self._make_service()
        t = MagicMock(spec=Tournament)
        t.status = "ACTIVE"
        t.max_participants = 10
        mock_repo.get.return_value = t
        mock_repo.get_participant.return_value = None
        mock_repo.count_participants.return_value = 10

        with pytest.raises(HTTPException) as exc_info:
            service.join(1, 1, now=_now())
        assert exc_info.value.status_code == 409

    def test_join_raises_409_when_completed(self) -> None:
        service, mock_repo = self._make_service()
        t = MagicMock(spec=Tournament)
        t.status = "COMPLETED"
        mock_repo.get.return_value = t

        with pytest.raises(HTTPException) as exc_info:
            service.join(1, 1, now=_now())
        assert exc_info.value.status_code == 409

    def test_join_success(self) -> None:
        service, mock_repo = self._make_service()
        t = MagicMock(spec=Tournament)
        t.status = "ACTIVE"
        t.max_participants = None
        mock_repo.get.return_value = t
        mock_repo.get_participant.return_value = None
        p = MagicMock(spec=TournamentParticipant)
        p.tournament_id = 1
        p.user_id = 42
        p.joined_at = _now()
        mock_repo.join.return_value = p

        result = service.join(42, 1, now=_now())
        assert result.tournament_id == 1
        assert result.user_id == 42

    def test_get_leaderboard_raises_404_when_not_found(self) -> None:
        service, mock_repo = self._make_service()
        mock_repo.get.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            service.get_leaderboard(999)
        assert exc_info.value.status_code == 404

    def test_get_leaderboard_returns_ranked_entries(self) -> None:
        service, mock_repo = self._make_service()
        t = MagicMock(spec=Tournament)
        mock_repo.get.return_value = t

        p1 = MagicMock(spec=TournamentParticipant)
        p1.user_id = 1
        p1.xp_earned = 200
        p2 = MagicMock(spec=TournamentParticipant)
        p2.user_id = 2
        p2.xp_earned = 100
        mock_repo.get_leaderboard.return_value = [p1, p2]

        result = service.get_leaderboard(1)
        assert len(result) == 2
        assert result[0].rank == 1
        assert result[0].user_id == 1
        assert result[1].rank == 2

    def test_record_xp_increments_active_participations(self) -> None:
        service, mock_repo = self._make_service()
        p = MagicMock(spec=TournamentParticipant)
        mock_repo.get_active_tournaments_for_user.return_value = [p]

        service.record_xp(1, 50, now=_now())

        mock_repo.increment_xp.assert_called_once_with(p, 50)

    def test_record_xp_no_active_tournaments(self) -> None:
        service, mock_repo = self._make_service()
        mock_repo.get_active_tournaments_for_user.return_value = []

        service.record_xp(1, 50, now=_now())

        mock_repo.increment_xp.assert_not_called()
