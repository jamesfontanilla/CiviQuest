"""Repository tests for the focus feature — real DB, no mocks."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.features.focus.models import FocusSession
from app.features.focus.repository import FocusSessionRepository
from app.features.users.models import User


def _seed_user(db: Session) -> User:
    user = User(
        email="focus@test.com",
        display_name="Focus Tester",
        age=25,
        category="PROFESSIONAL",
        role="LEARNER",
        account_state="VERIFIED",
        password_hash="$2b$10$fakehash",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _make_session(user_id: int, **kwargs) -> FocusSession:
    defaults = {
        "user_id": user_id,
        "mode": "25_5",
        "work_minutes": 25,
        "break_minutes": 5,
        "started_at": datetime.now(tz=timezone.utc),
    }
    defaults.update(kwargs)
    return FocusSession(**defaults)


def test_create_and_get_user_session(db_session: Session) -> None:
    user = _seed_user(db_session)
    repo = FocusSessionRepository(db=db_session)

    session = _make_session(user.id)
    session = repo.create(session)

    found = repo.get_user_session(user.id, session.id)
    assert found is not None
    assert found.id == session.id
    assert found.mode == "25_5"


def test_get_user_session_wrong_user(db_session: Session) -> None:
    user = _seed_user(db_session)
    repo = FocusSessionRepository(db=db_session)

    session = _make_session(user.id)
    session = repo.create(session)

    # Different user_id should not find it
    found = repo.get_user_session(user.id + 999, session.id)
    assert found is None


def test_count_user_sessions(db_session: Session) -> None:
    user = _seed_user(db_session)
    repo = FocusSessionRepository(db=db_session)

    # Create 2 completed, 1 not completed
    for _ in range(2):
        s = _make_session(user.id, completed=True, total_focus_minutes=25)
        repo.create(s)
    s = _make_session(user.id, completed=False)
    repo.create(s)

    assert repo.count_user_sessions(user.id) == 2


def test_total_focus_minutes(db_session: Session) -> None:
    user = _seed_user(db_session)
    repo = FocusSessionRepository(db=db_session)

    repo.create(_make_session(user.id, completed=True, total_focus_minutes=25))
    repo.create(_make_session(user.id, completed=True, total_focus_minutes=50))
    repo.create(_make_session(user.id, completed=False, total_focus_minutes=10))

    assert repo.total_focus_minutes(user.id) == 75


def test_avg_session_minutes(db_session: Session) -> None:
    user = _seed_user(db_session)
    repo = FocusSessionRepository(db=db_session)

    repo.create(_make_session(user.id, completed=True, total_focus_minutes=20))
    repo.create(_make_session(user.id, completed=True, total_focus_minutes=40))

    assert repo.avg_session_minutes(user.id) == 30.0


def test_sessions_today(db_session: Session) -> None:
    user = _seed_user(db_session)
    repo = FocusSessionRepository(db=db_session)

    repo.create(_make_session(user.id))
    repo.create(_make_session(user.id))

    assert repo.sessions_today(user.id) == 2


def test_focus_minutes_today(db_session: Session) -> None:
    user = _seed_user(db_session)
    repo = FocusSessionRepository(db=db_session)

    repo.create(_make_session(user.id, completed=True, total_focus_minutes=15))
    repo.create(_make_session(user.id, completed=True, total_focus_minutes=25))

    assert repo.focus_minutes_today(user.id) == 40
