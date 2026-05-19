"""SQLAlchemy ORM models for the auth feature.

Three tables live here per design:

- ``Session`` — denylist + audit trail for issued JWTs (Req 3.1, 3.4, 4.4).
- ``LoginAttempt`` — rolling-window counter for the lockout rule (Req 3.3).
- ``UserLockout`` — flat per-user lockout record so the auth check is a
  single point lookup (Req 3.3).

``LoginAttempt.user_id`` is nullable because Req 3.2 / 3.3 require us to
record failed attempts even for non-existent emails (so an attacker can't use
the lockout response itself as an enumeration oracle).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base


class Session(Base):
    """An issued JWT. Primary key is the ``jti`` claim embedded in the token.

    The auth middleware decodes the JWT, looks up this row, and rejects the
    request if ``revoked_at`` is non-null or ``expires_at`` is in the past.
    """

    __tablename__ = "sessions"

    jti: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        # Common admin/debug query shape: "active sessions for this user".
        Index("ix_sessions_user_revoked", "user_id", "revoked_at"),
    )


class LoginAttempt(Base):
    """One row per login attempt, success or failure (Req 3.3).

    ``user_id`` is nullable so failed attempts against unknown emails are
    still recorded (necessary for byte-equal responses per Req 3.2 to avoid
    enumeration).
    """

    __tablename__ = "login_attempts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
    )
    attempted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        # Rolling-window lockout query: scan recent attempts for this user.
        Index("ix_login_attempts_user_time", "user_id", "attempted_at"),
    )


class UserLockout(Base):
    """At most one lockout per user (PK on ``user_id``).

    ``locked_until`` is moved forward when the threshold is crossed again;
    we never delete the row, so a quick history of past lockouts is
    available for admin review.
    """

    __tablename__ = "user_lockouts"

    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    locked_until: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
