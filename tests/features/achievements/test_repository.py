"""Repository tests for the achievements slice (Task 15.1).

Per ``testing-standards.md`` repository tests run against in-memory
SQLite with no mocks. Each test seeds a real :class:`User` for the FK
target and exercises :class:`AchievementRepository` directly.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.features.achievements.models import Achievement, UserAchievement
from app.features.achievements.repository import AchievementRepository
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


def _make_ach(
    *,
    id: str = "FIRST_LESSON",
    title: str = "First Lesson",
    description: str = "Complete your first lesson.",
    criterion_kind: str = "FIRST_LESSON",
    criterion_value: dict | None = None,
) -> Achievement:
    return Achievement(
        id=id,
        title=title,
        description=description,
        criterion_kind=criterion_kind,
        criterion_value=criterion_value if criterion_value is not None else {},
    )


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


# --- upsert_achievement ----------------------------------------------------


def test_upsert_achievement_inserts_when_absent(db_session: Session) -> None:
    repo = AchievementRepository(db=db_session)

    written = repo.upsert_achievement(_make_ach())

    assert written.id == "FIRST_LESSON"
    assert written.title == "First Lesson"
    # Round-trip via PK lookup picks up server defaults.
    fetched = repo.get("FIRST_LESSON")
    assert fetched is not None
    assert fetched.criterion_kind == "FIRST_LESSON"


def test_upsert_achievement_is_idempotent_on_second_call(
    db_session: Session,
) -> None:
    """A second upsert with the same id updates fields in place."""
    repo = AchievementRepository(db=db_session)

    repo.upsert_achievement(_make_ach(title="v1"))
    repo.upsert_achievement(_make_ach(title="v2"))

    assert db_session.query(Achievement).count() == 1
    fetched = repo.get("FIRST_LESSON")
    assert fetched is not None
    assert fetched.title == "v2"


def test_get_returns_achievement_by_string_pk(db_session: Session) -> None:
    repo = AchievementRepository(db=db_session)
    repo.upsert_achievement(_make_ach())

    fetched = repo.get("FIRST_LESSON")

    assert fetched is not None
    assert fetched.id == "FIRST_LESSON"


def test_get_returns_none_for_missing_achievement(db_session: Session) -> None:
    repo = AchievementRepository(db=db_session)

    assert repo.get("NEVER_SEEDED") is None


# --- list_all + list_by_criterion_kind -------------------------------------


def test_list_all_returns_every_achievement_definition(
    db_session: Session,
) -> None:
    repo = AchievementRepository(db=db_session)
    repo.upsert_achievement(_make_ach(id="A"))
    repo.upsert_achievement(_make_ach(id="B"))
    repo.upsert_achievement(_make_ach(id="C"))

    rows = repo.list_all()

    assert [r.id for r in rows] == ["A", "B", "C"]


def test_list_by_criterion_kind_filters_to_matching_rows(
    db_session: Session,
) -> None:
    repo = AchievementRepository(db=db_session)
    repo.upsert_achievement(
        _make_ach(id="STREAK_7", criterion_kind="STREAK_N_DAYS",
                  criterion_value={"days": 7})
    )
    repo.upsert_achievement(
        _make_ach(id="STREAK_30", criterion_kind="STREAK_N_DAYS",
                  criterion_value={"days": 30})
    )
    repo.upsert_achievement(
        _make_ach(id="LEVEL_10", criterion_kind="LEVEL_N",
                  criterion_value={"level": 10})
    )

    streaks = repo.list_by_criterion_kind("STREAK_N_DAYS")
    levels = repo.list_by_criterion_kind("LEVEL_N")

    assert {r.id for r in streaks} == {"STREAK_7", "STREAK_30"}
    assert [r.id for r in levels] == ["LEVEL_10"]


def test_list_by_criterion_kind_returns_empty_for_unknown_kind(
    db_session: Session,
) -> None:
    repo = AchievementRepository(db=db_session)
    repo.upsert_achievement(_make_ach())

    assert repo.list_by_criterion_kind("UNKNOWN_KIND") == []


# --- grant ----------------------------------------------------------------


def test_grant_inserts_new_user_achievement(db_session: Session) -> None:
    user = _make_user(db_session)
    repo = AchievementRepository(db=db_session)
    repo.upsert_achievement(_make_ach())
    when = _now()

    grant = repo.grant(
        user_id=user.id,
        achievement_id="FIRST_LESSON",
        granted_at=when,
    )

    assert grant.id is not None
    assert grant.user_id == user.id
    assert grant.achievement_id == "FIRST_LESSON"
    # SQLite drops tz on round-trip; compare naive components.
    assert grant.granted_at.replace(tzinfo=None) == when.replace(tzinfo=None)


def test_grant_is_idempotent_returns_existing_row(db_session: Session) -> None:
    """Property 23 — second grant returns the original row, not a duplicate."""
    user = _make_user(db_session)
    repo = AchievementRepository(db=db_session)
    repo.upsert_achievement(_make_ach())
    first_when = _now()
    second_when = first_when + timedelta(hours=1)

    first = repo.grant(
        user_id=user.id, achievement_id="FIRST_LESSON", granted_at=first_when
    )
    second = repo.grant(
        user_id=user.id, achievement_id="FIRST_LESSON", granted_at=second_when
    )

    assert first.id == second.id
    # ``granted_at`` is preserved from the first call.
    assert second.granted_at.replace(tzinfo=None) == first_when.replace(
        tzinfo=None
    )
    assert (
        db_session.query(UserAchievement)
        .filter_by(user_id=user.id, achievement_id="FIRST_LESSON")
        .count()
        == 1
    )


def test_grant_records_source_xp_event_id(db_session: Session) -> None:
    """``source_xp_event_id`` is preserved when supplied."""
    from app.features.xp.models import XPSource
    from app.features.xp.repository import XPRepository

    user = _make_user(db_session)
    repo = AchievementRepository(db=db_session)
    repo.upsert_achievement(_make_ach())

    # Seed an XP event so the FK target exists.
    xp_repo = XPRepository(db=db_session)
    event, _ = xp_repo.insert_event_and_recompute(
        user_id=user.id,
        source=XPSource.LESSON_FIRST_COMPLETE,
        amount=20,
        occurred_at=_now(),
    )

    grant = repo.grant(
        user_id=user.id,
        achievement_id="FIRST_LESSON",
        granted_at=_now(),
        source_xp_event_id=event.id,
    )

    assert grant.source_xp_event_id == event.id


# --- list_for_user --------------------------------------------------------


def test_list_for_user_returns_only_that_users_grants(
    db_session: Session,
) -> None:
    alice = _make_user(db_session)
    bob = _make_user(db_session, email="bob@example.com")
    repo = AchievementRepository(db=db_session)
    repo.upsert_achievement(_make_ach(id="A1"))
    repo.upsert_achievement(_make_ach(id="A2"))
    when = _now()

    repo.grant(user_id=alice.id, achievement_id="A1", granted_at=when)
    repo.grant(user_id=alice.id, achievement_id="A2", granted_at=when)
    repo.grant(user_id=bob.id, achievement_id="A1", granted_at=when)

    alice_grants = repo.list_for_user(alice.id)

    assert {g.achievement_id for g in alice_grants} == {"A1", "A2"}


def test_list_for_user_orders_by_granted_at_ascending(
    db_session: Session,
) -> None:
    user = _make_user(db_session)
    repo = AchievementRepository(db=db_session)
    repo.upsert_achievement(_make_ach(id="EARLY"))
    repo.upsert_achievement(_make_ach(id="MIDDLE"))
    repo.upsert_achievement(_make_ach(id="LATE"))

    base = datetime(2025, 6, 1, 12, 0, tzinfo=timezone.utc)
    repo.grant(
        user_id=user.id,
        achievement_id="LATE",
        granted_at=base + timedelta(days=2),
    )
    repo.grant(
        user_id=user.id, achievement_id="EARLY", granted_at=base
    )
    repo.grant(
        user_id=user.id,
        achievement_id="MIDDLE",
        granted_at=base + timedelta(days=1),
    )

    rows = repo.list_for_user(user.id)

    assert [r.achievement_id for r in rows] == ["EARLY", "MIDDLE", "LATE"]


def test_list_for_user_returns_empty_when_no_grants(
    db_session: Session,
) -> None:
    user = _make_user(db_session)
    repo = AchievementRepository(db=db_session)

    assert repo.list_for_user(user.id) == []


# --- list_user_achievement_ids -------------------------------------------


def test_list_user_achievement_ids_returns_set_of_granted_ids(
    db_session: Session,
) -> None:
    user = _make_user(db_session)
    repo = AchievementRepository(db=db_session)
    repo.upsert_achievement(_make_ach(id="A"))
    repo.upsert_achievement(_make_ach(id="B"))
    repo.upsert_achievement(_make_ach(id="C"))
    when = _now()
    repo.grant(user_id=user.id, achievement_id="A", granted_at=when)
    repo.grant(user_id=user.id, achievement_id="C", granted_at=when)

    ids = repo.list_user_achievement_ids(user.id)

    assert ids == {"A", "C"}
    assert isinstance(ids, set)


def test_list_user_achievement_ids_empty_for_new_user(
    db_session: Session,
) -> None:
    user = _make_user(db_session)
    repo = AchievementRepository(db=db_session)

    assert repo.list_user_achievement_ids(user.id) == set()
