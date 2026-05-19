"""SQLAlchemy ORM model for the OTP feature.

Owns the ``OTP`` row plus the ``OTPPurpose`` closed enum. Per design table
spec for ``otps``:

- ``code_hash`` stores a bcrypt hash; plaintext is never persisted (Req 2.3
  read in conjunction with ``security-policy.md``).
- ``expires_at`` is timezone-aware so day-light/timezone migrations to
  Postgres later don't silently lose offset info.
- Two indexes per design:
    * ``ix_otps_verify_lookup`` — covers the verify-latest-active query
      (Req 2.2).
    * ``ix_otps_issuance_window`` — covers the rolling 60-min issuance
      counter (Req 2.6).
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base


class OTPPurpose(str, Enum):
    """Why this OTP was issued (Req 2 vs Req 4)."""

    VERIFY_EMAIL = "VERIFY_EMAIL"
    PASSWORD_RESET = "PASSWORD_RESET"


class OTP(Base):
    """A one-time password issued to a user for a specific purpose.

    Soft-deletion semantics: once an OTP is consumed (``used=True``) or
    revoked (``invalidated=True``) the row stays for audit / rate-limit
    accounting; the hourly cleanup job (Task 3.3) hard-deletes records past
    the 24-hour retention window.
    """

    __tablename__ = "otps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    purpose: Mapped[str] = mapped_column(String(32), nullable=False)
    code_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    invalidated: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
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
        CheckConstraint(
            "purpose IN ('VERIFY_EMAIL', 'PASSWORD_RESET')",
            name="ck_otps_purpose",
        ),
        # Verify-latest query: filter by user, purpose, used, invalidated then
        # order by expires_at; this composite covers the where + order.
        Index(
            "ix_otps_verify_lookup",
            "user_id",
            "purpose",
            "used",
            "invalidated",
            "expires_at",
        ),
        # Issuance rate-limit query: count rows in (user_id, created_at >= cutoff).
        Index("ix_otps_issuance_window", "user_id", "created_at"),
    )
