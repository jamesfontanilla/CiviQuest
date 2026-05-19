"""Repository tests for the gamification slice.

Per testing-standards.md: real DB, no mocks.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.features.gamification.models import Tournament, TournamentParticipant
from app.features.gamification.repository import (
    DailyGoalRepository,
    StreakFreezeRepository,
    TournamentRepository,
    XPMultiplierRepository,
)
from app.features.users.models import Category, User
from app.features.users.repository import UserRepository
from app.features.users.schemas import UserCreate


# --- factories --------------------------------------------------------------


def _make_user(db: Session, *, email: str = "alice@example.com") -> User:
    repo = UserRepository(db=db)
    return repo.create(
        UserCreate(
            email=email,
            display_name="Alice",
            age=25,
            category=Category.PROFESSIONAL.value,
            password="Strong1Pass!",
        ),
        password_hash="bcrypt$fake$hash",
    )


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


# --- DailyGoalRepository ---------------------------------------------------


def test_create_and_get_goal(db_session: Session) -> None:
    user = _make_user(db_session)
    repo = DailyGoalRepository(db=db_session)
    today = date(2025, 6, 15)

    goal = repo.create_goal(user_id=user.id, target_xp=50, goal_date=today)

    assert goal.id is not None
    assert goal.user_id == user.id
    assert goal.target_xp == 50
    assert goal.current_xp == 0
    assert goal.completed is False

    fetched = repo.get_for_date(user.id, today)
    assert fetched is not None
    assert fetched.id == goal.id


def test_get_for_date_returns_none_when_absent(db_session: Session) -> None:
    user = _make_user(db_session)
    repo = DailyGoalRepository(db=db_session)

    assert repo.get_for_date(user.id, date(2025, 1, 1)) is None


def test_get_last_n_days(db_session: Session) -> None:
    user = _make_user(db_session)
    repo = DailyGoalRepository(db=db_session)

    for i in range(5):
        repo.create_goal(
            user_id=user.id,
            target_xp=50,
            goal_date=date(2025, 6, 10 + i),
        )

    goals = repo.get_last_n_days(
        user.id, since=date(2025, 6, 11), until=date(2025, 6, 13)
    )
    assert len(goals) == 3


def test_get_latest_target(db_session: Session) -> None:
    user = _make_user(db_session)
    repo = DailyGoalRepository(db=db_session)

    assert repo.get_latest_target(user.id) is None

    repo.create_goal(user_id=user.id, target_xp=25, goal_date=date(2025, 6, 1))
    repo.create_goal(user_id=user.id, target_xp=100, goal_date=date(2025, 6, 2))

    assert repo.get_latest_target(user.id) == 100


# --- StreakFreezeRepository -------------------------------------------------


def test_grant_and_count_freezes(db_session: Session) -> None:
    user = _make_user(db_session)
    repo = StreakFreezeRepository(db=db_session)
    now = _now()

    assert repo.count_available(user.id) == 0

    repo.grant(user_id=user.id, granted_at=now)
    repo.grant(user_id=user.id, granted_at=now)

    assert repo.count_available(user.id) == 2


def test_use_oldest_freeze(db_session: Session) -> None:
    user = _make_user(db_session)
    repo = StreakFreezeRepository(db=db_session)
    now = _now()

    repo.grant(user_id=user.id, granted_at=now)
    repo.grant(user_id=user.id, granted_at=now + timedelta(hours=1))

    result = repo.use_oldest(user.id, used_on=date(2025, 6, 15))
    assert result is not None
    assert result.used_on == date(2025, 6, 15)
    assert repo.count_available(user.id) == 1


def test_use_oldest_returns_none_when_empty(db_session: Session) -> None:
    user = _make_user(db_session)
    repo = StreakFreezeRepository(db=db_session)

    assert repo.use_oldest(user.id, used_on=date(2025, 6, 15)) is None


# --- XPMultiplierRepository -------------------------------------------------


def test_create_and_get_active_multipliers(db_session: Session) -> None:
    user = _make_user(db_session)
    repo = XPMultiplierRepository(db=db_session)
    now = _now()

    repo.create_multiplier(
        user_id=user.id,
        multiplier=1.5,
        reason="streak_7",
        expires_at=now + timedelta(hours=24),
    )
    repo.create_multiplier(
        user_id=user.id,
        multiplier=2.0,
        reason="expired_one",
        expires_at=now - timedelta(hours=1),
    )

    active = repo.get_active(user.id, now=now)
    assert len(active) == 1
    assert active[0].multiplier == 1.5


# --- TournamentRepository --------------------------------------------------


def test_create_tournament_and_join(db_session: Session) -> None:
    user = _make_user(db_session)
    repo = TournamentRepository(db=db_session)
    now = _now()

    tournament = Tournament(
        title="Weekly Sprint",
        starts_at=now,
        ends_at=now + timedelta(days=7),
        status="ACTIVE",
    )
    tournament = repo.create_tournament(tournament)
    assert tournament.id is not None

    participant = repo.join(
        tournament_id=tournament.id, user_id=user.id, joined_at=now
    )
    assert participant.tournament_id == tournament.id
    assert participant.xp_earned == 0


def test_list_active_and_upcoming(db_session: Session) -> None:
    user = _make_user(db_session)
    repo = TournamentRepository(db=db_session)
    now = _now()

    repo.create_tournament(
        Tournament(title="Active", starts_at=now, ends_at=now + timedelta(days=7), status="ACTIVE")
    )
    repo.create_tournament(
        Tournament(title="Upcoming", starts_at=now + timedelta(days=1), ends_at=now + timedelta(days=8), status="UPCOMING")
    )
    repo.create_tournament(
        Tournament(title="Done", starts_at=now - timedelta(days=14), ends_at=now - timedelta(days=7), status="COMPLETED")
    )

    results = repo.list_active_and_upcoming(now=now)
    assert len(results) == 2
    titles = {t.title for t in results}
    assert "Active" in titles
    assert "Upcoming" in titles


def test_get_leaderboard_ordered_by_xp(db_session: Session) -> None:
    alice = _make_user(db_session)
    bob = _make_user(db_session, email="bob@example.com")
    repo = TournamentRepository(db=db_session)
    now = _now()

    tournament = repo.create_tournament(
        Tournament(title="T1", starts_at=now, ends_at=now + timedelta(days=7), status="ACTIVE")
    )
    p_alice = repo.join(tournament_id=tournament.id, user_id=alice.id, joined_at=now)
    p_bob = repo.join(tournament_id=tournament.id, user_id=bob.id, joined_at=now)

    repo.increment_xp(p_alice, 100)
    repo.increment_xp(p_bob, 200)

    leaderboard = repo.get_leaderboard(tournament.id)
    assert leaderboard[0].user_id == bob.id
    assert leaderboard[1].user_id == alice.id


def test_count_participants(db_session: Session) -> None:
    alice = _make_user(db_session)
    bob = _make_user(db_session, email="bob@example.com")
    repo = TournamentRepository(db=db_session)
    now = _now()

    tournament = repo.create_tournament(
        Tournament(title="T1", starts_at=now, ends_at=now + timedelta(days=7), status="ACTIVE")
    )
    assert repo.count_participants(tournament.id) == 0

    repo.join(tournament_id=tournament.id, user_id=alice.id, joined_at=now)
    repo.join(tournament_id=tournament.id, user_id=bob.id, joined_at=now)

    assert repo.count_participants(tournament.id) == 2


def test_get_active_tournaments_for_user(db_session: Session) -> None:
    user = _make_user(db_session)
    repo = TournamentRepository(db=db_session)
    now = _now()

    active = repo.create_tournament(
        Tournament(title="Active", starts_at=now, ends_at=now + timedelta(days=7), status="ACTIVE")
    )
    completed = repo.create_tournament(
        Tournament(title="Done", starts_at=now - timedelta(days=14), ends_at=now - timedelta(days=7), status="COMPLETED")
    )

    repo.join(tournament_id=active.id, user_id=user.id, joined_at=now)
    repo.join(tournament_id=completed.id, user_id=user.id, joined_at=now)

    active_participations = repo.get_active_tournaments_for_user(user.id, now=now)
    assert len(active_participations) == 1
    assert active_participations[0].tournament_id == active.id
