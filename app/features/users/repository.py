"""Repository for user persistence and admin queries.

Provides the user-write API (``create``, ``set_account_state``, ``set_banned``,
``delete_with_progress_cascade``) plus the read API used by auth (``get_by_email``)
and admin (``paginated_admin_list``). Inherited CRUD from ``BaseRepository``
covers ``get`` and the generic ``list``; we override ``create`` so callers can
hand us a Pydantic ``UserCreate`` plus the bcrypt hash and not have to build
the ORM instance themselves.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.features.users.models import AccountState, Category, Role, User
from app.features.users.schemas import UserCreate
from app.infrastructure.repositories.base import BaseRepository


class UserRepository(BaseRepository[User]):
    """Persistence for ``User`` rows.

    Emails are always compared lowercased; the schema layer normalises on the
    way in, but ``get_by_email`` still defensively lowercases its input so
    callers passing a mixed-case string (e.g. from a non-Pydantic code path)
    get the expected hit.
    """

    model = User

    def __init__(self, db: Session) -> None:
        super().__init__(db=db)

    def get_by_email(self, email: str) -> User | None:
        """Return the user with ``email`` (case-insensitive) or ``None``."""
        normalized = email.strip().lower()
        stmt = select(User).where(User.email == normalized)
        return self.db.execute(stmt).scalar_one_or_none()

    def get_by_google_id(self, google_id: str) -> User | None:
        """Return the user linked to ``google_id`` or ``None``."""
        stmt = select(User).where(User.google_id == google_id)
        return self.db.execute(stmt).scalar_one_or_none()

    def create(  # type: ignore[override]
        self,
        payload: UserCreate,
        *,
        password_hash: str,
        account_state: AccountState = AccountState.UNVERIFIED,
        role: Role = Role.LEARNER,
    ) -> User:
        """Build and persist a ``User`` from a validated ``UserCreate`` payload.

        The service layer hashes the password and passes the hash; the
        repository never sees plaintext (Req 1.6, ``security-policy.md``).
        """
        user = User(
            email=payload.email,
            display_name=payload.display_name,
            age=payload.age,
            category=payload.category.value,
            role=role.value,
            account_state=account_state.value,
            password_hash=password_hash,
        )
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        return user

    def create_from_google(
        self,
        *,
        email: str,
        display_name: str,
        google_id: str,
        category: str,
    ) -> User:
        """Create a user from Google OAuth data (no password, auto-verified).

        Google has already verified the email, so the account starts as
        VERIFIED. No password_hash is set — the user authenticates via
        Google only (unless they later add a password via a future flow).
        """
        user = User(
            email=email.strip().lower(),
            display_name=display_name,
            age=18,  # Default age for Google OAuth users; can be updated later
            category=category,
            google_id=google_id,
            role=Role.LEARNER.value,
            account_state=AccountState.VERIFIED.value,
            password_hash=None,
        )
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        return user

    def link_google_id(self, user: User, google_id: str) -> User:
        """Link a Google account to an existing user."""
        user.google_id = google_id
        self.db.commit()
        self.db.refresh(user)
        return user

    def set_account_state(self, user: User, state: AccountState) -> User:
        """Transition the account state and persist (Req 2.2, 2.4)."""
        user.account_state = state.value
        self.db.commit()
        self.db.refresh(user)
        return user

    def set_banned(self, user: User, banned: bool) -> User:
        """Toggle the ban flag and persist (Req 15.3)."""
        user.is_banned = banned
        self.db.commit()
        self.db.refresh(user)
        return user

    def delete_with_progress_cascade(self, user: User) -> None:
        """Remove the user. FK ``ON DELETE CASCADE`` cascades dependent rows.

        Cross-slice rows (sessions, otps, login_attempts, lockouts, progress,
        attempts) declare ``ondelete="CASCADE"`` on their FK to ``users.id``,
        so the database performs the cascade once SQLite ``foreign_keys=ON``
        is set (already pinned in ``pragmas.py``).

        TODO(Task 17.1, Req 15.4): retain an anonymized aggregate counter for
        analytics in the admin user-deletion service rather than deleting
        without trace.
        """
        self.db.delete(user)
        self.db.commit()

    def paginated_admin_list(
        self,
        *,
        skip: int,
        limit: int,
        category: Category | None = None,
        is_banned: bool | None = None,
        role: Role | None = None,
    ) -> tuple[list[User], int]:
        """Return ``(rows, total_count)`` for the admin user list.

        ``total_count`` reflects the same filter set as ``rows`` so the caller
        can render pagination controls (Req 15.2). ``skip``/``limit`` bounds
        are validated upstream by ``PaginationParams``.
        """
        filters = []
        if category is not None:
            filters.append(User.category == category.value)
        if is_banned is not None:
            filters.append(User.is_banned.is_(is_banned))
        if role is not None:
            filters.append(User.role == role.value)

        rows_stmt = select(User)
        count_stmt = select(func.count()).select_from(User)
        for f in filters:
            rows_stmt = rows_stmt.where(f)
            count_stmt = count_stmt.where(f)

        rows_stmt = rows_stmt.order_by(User.id).offset(skip).limit(limit)

        rows = list(self.db.execute(rows_stmt).scalars().all())
        total = int(self.db.execute(count_stmt).scalar_one())
        return rows, total
