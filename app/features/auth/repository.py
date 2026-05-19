"""Repository for auth-related persistence (sessions, login attempts, lockouts).

``AuthRepository`` keeps the three closely-related tables under one class for
slice cohesion. The "primary" model is ``Session`` so the inherited
``BaseRepository`` CRUD lines up with the most common case (read/write a JWT
row). Helpers for ``LoginAttempt`` and ``UserLockout`` live as named methods.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session as DBSession

from app.features.auth.models import LoginAttempt, Session, UserLockout
from app.infrastructure.repositories.base import BaseRepository


def _utcnow() -> datetime:
    """Aware UTC `now`."""
    return datetime.now(tz=timezone.utc)


class AuthRepository(BaseRepository[Session]):
    """Persistence for sessions, login attempts, and user lockouts."""

    model = Session

    def __init__(self, db: DBSession) -> None:
        super().__init__(db=db)

    # --- sessions ----------------------------------------------------------

    def create_session(
        self,
        *,
        jti: str,
        user_id: int,
        issued_at: datetime,
        expires_at: datetime,
    ) -> Session:
        """Persist a freshly-minted session row (Req 3.1)."""
        session = Session(
            jti=jti,
            user_id=user_id,
            issued_at=issued_at,
            expires_at=expires_at,
        )
        self.db.add(session)
        self.db.commit()
        self.db.refresh(session)
        return session

    def revoke_session_by_jti(
        self, jti: str, *, now: datetime | None = None
    ) -> bool:
        """Set ``revoked_at`` for the given ``jti``.

        Returns ``True`` when a row was updated, ``False`` if no session with
        that ``jti`` exists. Idempotent: revoking an already-revoked session
        still returns ``True`` because the row exists. (Req 3.4)
        """
        stamp = now or _utcnow()
        stmt = update(Session).where(Session.jti == jti).values(revoked_at=stamp)
        result = self.db.execute(stmt)
        self.db.commit()
        return bool(result.rowcount)

    def revoke_all_for_user(
        self, user_id: int, *, now: datetime | None = None
    ) -> int:
        """Revoke every non-revoked session for ``user_id``. Returns count.

        Used after a successful password reset (Req 4.4).
        """
        stamp = now or _utcnow()
        stmt = (
            update(Session)
            .where(Session.user_id == user_id, Session.revoked_at.is_(None))
            .values(revoked_at=stamp)
        )
        result = self.db.execute(stmt)
        self.db.commit()
        return int(result.rowcount or 0)

    def is_jti_active(
        self, jti: str, *, now: datetime | None = None
    ) -> bool:
        """Return ``True`` iff the session exists, is not revoked, and not expired.

        Used by ``get_current_user`` to gate every authenticated request
        (Req 3.5).
        """
        cutoff = now or _utcnow()
        stmt = select(Session).where(
            Session.jti == jti,
            Session.revoked_at.is_(None),
            Session.expires_at > cutoff,
        )
        return self.db.execute(stmt).scalar_one_or_none() is not None

    def get_session_by_jti(self, jti: str) -> Session | None:
        """Return the session row for ``jti`` or ``None`` if absent.

        Caller is responsible for inspecting ``revoked_at`` / ``expires_at``;
        the auth service uses this so a single load can drive both the
        active-check and the user-lookup paths during logout (Req 3.4, 3.5).
        """
        return self.db.get(Session, jti)

    # --- login attempts ----------------------------------------------------

    def record_login_attempt(
        self,
        *,
        user_id: int | None,
        attempted_at: datetime,
        success: bool,
    ) -> LoginAttempt:
        """Record a single login attempt (Req 3.3)."""
        attempt = LoginAttempt(
            user_id=user_id,
            attempted_at=attempted_at,
            success=success,
        )
        self.db.add(attempt)
        self.db.commit()
        self.db.refresh(attempt)
        return attempt

    def failed_count_in_window(self, user_id: int, *, since: datetime) -> int:
        """Count failed attempts for ``user_id`` since ``since`` (Req 3.3)."""
        stmt = (
            select(func.count())
            .select_from(LoginAttempt)
            .where(
                LoginAttempt.user_id == user_id,
                LoginAttempt.success.is_(False),
                LoginAttempt.attempted_at >= since,
            )
        )
        return int(self.db.execute(stmt).scalar_one())

    # --- lockouts ----------------------------------------------------------

    def set_lockout(self, user_id: int, *, locked_until: datetime) -> UserLockout:
        """Upsert a lockout row: insert if absent, otherwise update.

        SQLite has ``ON CONFLICT`` but that's dialect-bound; doing a
        select-then-set keeps the code portable to Postgres later without
        rewriting (Req 3.3).
        """
        existing = self.get_lockout(user_id)
        if existing is None:
            existing = UserLockout(user_id=user_id, locked_until=locked_until)
            self.db.add(existing)
        else:
            existing.locked_until = locked_until
        self.db.commit()
        self.db.refresh(existing)
        return existing

    def get_lockout(self, user_id: int) -> UserLockout | None:
        """Return the lockout row for ``user_id`` or ``None``."""
        return self.db.get(UserLockout, user_id)
