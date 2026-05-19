"""Service layer for tournaments."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException, status

from app.features.gamification.models import Tournament, TournamentParticipant
from app.features.gamification.repository import TournamentRepository
from app.features.gamification.schemas import (
    TournamentJoinResponse,
    TournamentLeaderboardEntry,
    TournamentResponse,
)


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


class TournamentService:
    """Manage tournaments: listing, joining, leaderboards, XP recording."""

    def __init__(self, *, tournament_repo: TournamentRepository) -> None:
        self._tournament_repo = tournament_repo

    def list_active(
        self, *, now: datetime | None = None
    ) -> list[TournamentResponse]:
        """Return active + upcoming tournaments."""
        when = now or _utcnow()
        tournaments = self._tournament_repo.list_active_and_upcoming(now=when)
        return [
            TournamentResponse(
                id=t.id,
                title=t.title,
                description=t.description,
                category=t.category,
                starts_at=t.starts_at,
                ends_at=t.ends_at,
                status=t.status,
                max_participants=t.max_participants,
                prize_description=t.prize_description,
            )
            for t in tournaments
        ]

    def join(
        self, user_id: int, tournament_id: int, *, now: datetime | None = None
    ) -> TournamentJoinResponse:
        """Join a tournament. Raises 409 if already joined or full, 404 if not found."""
        when = now or _utcnow()

        tournament = self._tournament_repo.get(tournament_id)
        if tournament is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="tournament_not_found",
            )

        if tournament.status == "COMPLETED":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="tournament_completed",
            )

        # Check if already joined.
        existing = self._tournament_repo.get_participant(tournament_id, user_id)
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="already_joined",
            )

        # Check capacity.
        if tournament.max_participants is not None:
            count = self._tournament_repo.count_participants(tournament_id)
            if count >= tournament.max_participants:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="tournament_full",
                )

        participant = self._tournament_repo.join(
            tournament_id=tournament_id, user_id=user_id, joined_at=when
        )
        return TournamentJoinResponse(
            tournament_id=participant.tournament_id,
            user_id=participant.user_id,
            joined_at=participant.joined_at,
        )

    def get_leaderboard(
        self, tournament_id: int
    ) -> list[TournamentLeaderboardEntry]:
        """Return participants ranked by xp_earned DESC."""
        tournament = self._tournament_repo.get(tournament_id)
        if tournament is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="tournament_not_found",
            )

        participants = self._tournament_repo.get_leaderboard(tournament_id)
        return [
            TournamentLeaderboardEntry(
                user_id=p.user_id,
                xp_earned=p.xp_earned,
                rank=idx + 1,
            )
            for idx, p in enumerate(participants)
        ]

    def record_xp(
        self, user_id: int, amount: int, *, now: datetime | None = None
    ) -> None:
        """Called after every XP award. If user is in an active tournament, increment their xp_earned."""
        when = now or _utcnow()
        active_participations = self._tournament_repo.get_active_tournaments_for_user(
            user_id, now=when
        )
        for participant in active_participations:
            self._tournament_repo.increment_xp(participant, amount)
