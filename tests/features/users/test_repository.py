"""Repository tests for ``UserRepository`` against in-memory SQLite.

Per ``testing-standards.md``, repository tests use the ``db_session`` fixture
with no mocks. ``_make_payload`` keeps the per-test setup short.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.features.users.models import AccountState, Category, Role, User
from app.features.users.repository import UserRepository
from app.features.users.schemas import UserCreate


def _make_payload(**overrides: object) -> UserCreate:
    """Build a ``UserCreate`` payload with safe defaults for tests."""
    defaults: dict[str, object] = {
        "email": "alice@example.com",
        "display_name": "Alice",
        "age": 25,
        "category": "PROFESSIONAL",
        "password": "Strong1Pass!",
    }
    return UserCreate(**{**defaults, **overrides})


def _create_user(repo: UserRepository, **overrides: object) -> User:
    payload = _make_payload(**overrides)
    return repo.create(payload, password_hash="bcrypt$fake$hash")


def test_get_by_email_lowercases_input(db_session: Session) -> None:
    repo = UserRepository(db=db_session)
    _create_user(repo, email="alice@example.com")

    found = repo.get_by_email("ALICE@Example.COM")

    assert found is not None
    assert found.email == "alice@example.com"


def test_get_by_email_returns_none_when_absent(db_session: Session) -> None:
    repo = UserRepository(db=db_session)
    assert repo.get_by_email("nobody@example.com") is None


def test_create_persists_with_default_state_and_role(db_session: Session) -> None:
    repo = UserRepository(db=db_session)
    user = _create_user(repo)

    assert user.id is not None
    assert user.account_state == AccountState.UNVERIFIED.value
    assert user.role == Role.LEARNER.value
    assert user.is_banned is False
    assert user.tz_name == "UTC"
    assert user.password_hash == "bcrypt$fake$hash"


def test_set_account_state_transitions_to_verified(db_session: Session) -> None:
    repo = UserRepository(db=db_session)
    user = _create_user(repo)

    repo.set_account_state(user, AccountState.VERIFIED)

    refetched = repo.get(user.id)
    assert refetched is not None
    assert refetched.account_state == AccountState.VERIFIED.value


def test_set_banned_toggle(db_session: Session) -> None:
    repo = UserRepository(db=db_session)
    user = _create_user(repo)

    repo.set_banned(user, True)
    assert repo.get(user.id).is_banned is True  # type: ignore[union-attr]

    repo.set_banned(user, False)
    assert repo.get(user.id).is_banned is False  # type: ignore[union-attr]


def test_paginated_admin_list_filters_by_category(db_session: Session) -> None:
    repo = UserRepository(db=db_session)
    _create_user(repo, email="prof1@example.com", category="PROFESSIONAL")
    _create_user(repo, email="prof2@example.com", category="PROFESSIONAL")
    _create_user(repo, email="sub1@example.com", category="SUB_PROFESSIONAL")

    rows, total = repo.paginated_admin_list(
        skip=0, limit=20, category=Category.PROFESSIONAL
    )

    assert total == 2
    assert {u.email for u in rows} == {"prof1@example.com", "prof2@example.com"}


def test_paginated_admin_list_returns_total_count(db_session: Session) -> None:
    repo = UserRepository(db=db_session)
    for n in range(5):
        _create_user(repo, email=f"user{n}@example.com")

    rows, total = repo.paginated_admin_list(skip=2, limit=2)

    assert total == 5
    assert len(rows) == 2


def test_paginated_admin_list_filters_by_is_banned(db_session: Session) -> None:
    repo = UserRepository(db=db_session)
    u1 = _create_user(repo, email="banned@example.com")
    _create_user(repo, email="ok@example.com")
    repo.set_banned(u1, True)

    rows, total = repo.paginated_admin_list(skip=0, limit=20, is_banned=True)

    assert total == 1
    assert rows[0].email == "banned@example.com"


def test_delete_with_progress_cascade_removes_user(db_session: Session) -> None:
    repo = UserRepository(db=db_session)
    user = _create_user(repo)
    user_id = user.id

    repo.delete_with_progress_cascade(user)

    assert repo.get(user_id) is None
