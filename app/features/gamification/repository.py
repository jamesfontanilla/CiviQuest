"""Repository for the gamification slice.

Owns reads and writes for daily goals, streak freezes, XP multipliers,
and tournaments.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.features.gamification.models import (
    StreakFreeze,
    Tournament,
    TournamentParticipant,
    UserDailyGoal,
    XPMultiplier,
)
from app.infrastructure.repositories.base import BaseRepository


class DailyGoalRepository(BaseRepository[UserDailyGoal]):
    """Persistence for daily goal rows."""

    model = UserDailyGoal

    def __init__(self, db: Session) -> None:
        super().__init__(db=db)

    def get_for_date(self, user_id: int, goal_date: date) -> UserDailyGoal | None:
        """Return the goal for a specific date or None."""
        stmt = (
            select(UserDailyGoal)
            .where(UserDailyGoal.user_id == user_id)
            .where(UserDailyGoal.goal_date == goal_date)
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def create_goal(
        self, *, user_id: int, target_xp: int, goal_date: date
    ) -> UserDailyGoal:
        """Create a new daily goal row."""
        goal = UserDailyGoal(
            user_id=user_id,
            target_xp=target_xp,
            goal_date=goal_date,
        )
        self.db.add(goal)
        self.db.commit()
        self.db.refresh(goal)
        return goal

    def get_last_n_days(
        self, user_id: int, *, since: date, until: date
    ) -> list[UserDailyGoal]:
        """Return goals in the date range [since, until] inclusive."""
        stmt = (
            select(UserDailyGoal)
            .where(UserDailyGoal.user_id == user_id)
            .where(UserDailyGoal.goal_date >= since)
            .where(UserDailyGoal.goal_date <= until)
            .order_by(UserDailyGoal.goal_date.asc())
        )
        return list(self.db.execute(stmt).scalars().all())

    def get_latest_target(self, user_id: int) -> int | None:
        """Return the most recent target_xp for the user, or None if no goals exist."""
        stmt = (
            select(UserDailyGoal.target_xp)
            .where(UserDailyGoal.user_id == user_id)
            .order_by(UserDailyGoal.goal_date.desc())
            .limit(1)
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def save(self, goal: UserDailyGoal) -> UserDailyGoal:
        """Persist changes to an existing goal."""
        self.db.commit()
        self.db.refresh(goal)
        return goal


class StreakFreezeRepository(BaseRepository[StreakFreeze]):
    """Persistence for streak freeze rows."""

    model = StreakFreeze

    def __init__(self, db: Session) -> None:
        super().__init__(db=db)

    def get_available(self, user_id: int) -> list[StreakFreeze]:
        """Return all unused freezes for the user."""
        stmt = (
            select(StreakFreeze)
            .where(StreakFreeze.user_id == user_id)
            .where(StreakFreeze.used_on.is_(None))
            .order_by(StreakFreeze.granted_at.asc())
        )
        return list(self.db.execute(stmt).scalars().all())

    def count_available(self, user_id: int) -> int:
        """Return count of unused freezes."""
        stmt = (
            select(func.count())
            .select_from(StreakFreeze)
            .where(StreakFreeze.user_id == user_id)
            .where(StreakFreeze.used_on.is_(None))
        )
        return int(self.db.execute(stmt).scalar_one())

    def grant(self, *, user_id: int, granted_at: datetime) -> StreakFreeze:
        """Grant a new freeze to the user."""
        freeze = StreakFreeze(
            user_id=user_id,
            granted_at=granted_at,
        )
        self.db.add(freeze)
        self.db.commit()
        self.db.refresh(freeze)
        return freeze

    def use_oldest(self, user_id: int, *, used_on: date) -> StreakFreeze | None:
        """Consume the oldest available freeze. Returns None if none available."""
        available = self.get_available(user_id)
        if not available:
            return None
        freeze = available[0]
        freeze.available = 0
        freeze.used_on = used_on
        self.db.commit()
        self.db.refresh(freeze)
        return freeze


class XPMultiplierRepository(BaseRepository[XPMultiplier]):
    """Persistence for XP multiplier rows."""

    model = XPMultiplier

    def __init__(self, db: Session) -> None:
        super().__init__(db=db)

    def get_active(self, user_id: int, *, now: datetime) -> list[XPMultiplier]:
        """Return all active (non-expired) multipliers for the user."""
        stmt = (
            select(XPMultiplier)
            .where(XPMultiplier.user_id == user_id)
            .where(XPMultiplier.expires_at > now)
            .order_by(XPMultiplier.expires_at.asc())
        )
        return list(self.db.execute(stmt).scalars().all())

    def create_multiplier(
        self,
        *,
        user_id: int,
        multiplier: float,
        reason: str,
        expires_at: datetime,
    ) -> XPMultiplier:
        """Create a new XP multiplier."""
        m = XPMultiplier(
            user_id=user_id,
            multiplier=multiplier,
            reason=reason,
            expires_at=expires_at,
        )
        self.db.add(m)
        self.db.commit()
        self.db.refresh(m)
        return m


class TournamentRepository(BaseRepository[Tournament]):
    """Persistence for tournament and participant rows."""

    model = Tournament

    def __init__(self, db: Session) -> None:
        super().__init__(db=db)

    def list_active_and_upcoming(self, *, now: datetime) -> list[Tournament]:
        """Return tournaments that are ACTIVE or UPCOMING."""
        stmt = (
            select(Tournament)
            .where(Tournament.status.in_(["ACTIVE", "UPCOMING"]))
            .order_by(Tournament.starts_at.asc())
        )
        return list(self.db.execute(stmt).scalars().all())

    def get_participant(
        self, tournament_id: int, user_id: int
    ) -> TournamentParticipant | None:
        """Return the participant row or None."""
        stmt = (
            select(TournamentParticipant)
            .where(TournamentParticipant.tournament_id == tournament_id)
            .where(TournamentParticipant.user_id == user_id)
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def join(
        self, *, tournament_id: int, user_id: int, joined_at: datetime
    ) -> TournamentParticipant:
        """Add a participant to a tournament."""
        p = TournamentParticipant(
            tournament_id=tournament_id,
            user_id=user_id,
            joined_at=joined_at,
        )
        self.db.add(p)
        self.db.commit()
        self.db.refresh(p)
        return p

    def count_participants(self, tournament_id: int) -> int:
        """Return the number of participants in a tournament."""
        stmt = (
            select(func.count())
            .select_from(TournamentParticipant)
            .where(TournamentParticipant.tournament_id == tournament_id)
        )
        return int(self.db.execute(stmt).scalar_one())

    def get_leaderboard(self, tournament_id: int) -> list[TournamentParticipant]:
        """Return participants ordered by xp_earned DESC."""
        stmt = (
            select(TournamentParticipant)
            .where(TournamentParticipant.tournament_id == tournament_id)
            .order_by(TournamentParticipant.xp_earned.desc())
        )
        return list(self.db.execute(stmt).scalars().all())

    def get_active_tournaments_for_user(
        self, user_id: int, *, now: datetime
    ) -> list[TournamentParticipant]:
        """Return participant rows for active tournaments the user is in."""
        stmt = (
            select(TournamentParticipant)
            .join(Tournament, Tournament.id == TournamentParticipant.tournament_id)
            .where(TournamentParticipant.user_id == user_id)
            .where(Tournament.status == "ACTIVE")
        )
        return list(self.db.execute(stmt).scalars().all())

    def increment_xp(self, participant: TournamentParticipant, amount: int) -> None:
        """Add XP to a participant's tournament total."""
        participant.xp_earned += amount
        self.db.commit()
        self.db.refresh(participant)

    def create_tournament(self, tournament: Tournament) -> Tournament:
        """Persist a new tournament."""
        self.db.add(tournament)
        self.db.commit()
        self.db.refresh(tournament)
        return tournament
