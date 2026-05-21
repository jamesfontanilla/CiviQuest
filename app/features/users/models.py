"""SQLAlchemy ORM model for users.

Owns the canonical ``User`` row plus the closed enums that other slices
(auth, otp, content, admin) consume. Per design `Table specifications` ->
`users`:

- ``email`` is stored lowercased and unique; lowercasing is enforced at the
  schema layer (see ``schemas.py``) so the repository can compare directly
  against the stored value without re-normalising.
- ``age`` is constrained to ``[15, 100]`` via ``CheckConstraint``
  (Req 1.4).
- ``category``/``role``/``account_state`` are constrained via
  ``CheckConstraint`` to the closed enum values so a Postgres migration later
  has matching DDL.
- ``password_hash`` holds a bcrypt hash (never plaintext) per Req 1.6;
  service code is responsible for hashing.
- ``cross_category_preview`` is the Phase 2 admin-toggleable flag from
  Req 5.4; column lives now to avoid a later schema bump.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from sqlalchemy import Boolean, CheckConstraint, DateTime, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base


class Category(str, Enum):
    """CSE track a learner is preparing for (Req 1.5, 5.1, 5.2)."""

    PROFESSIONAL = "PROFESSIONAL"
    SUB_PROFESSIONAL = "SUB_PROFESSIONAL"


class Role(str, Enum):
    """Authorization role (Req 15.1)."""

    LEARNER = "LEARNER"
    ADMIN = "ADMIN"


class AccountState(str, Enum):
    """Lifecycle state for email verification (Req 2.2, 2.4)."""

    UNVERIFIED = "UNVERIFIED"
    VERIFIED = "VERIFIED"


class User(Base):
    """A registered learner or admin.

    The ``role`` and ``account_state`` columns default to ``LEARNER`` and
    ``UNVERIFIED`` so a fresh signup row is valid without the service layer
    having to set them; admins are promoted in a later admin task.
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    age: Mapped[int] = mapped_column(Integer, nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    google_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True, unique=True, default=None
    )
    role: Mapped[str] = mapped_column(
        String(16), nullable=False, default=Role.LEARNER.value, server_default=Role.LEARNER.value
    )
    account_state: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=AccountState.UNVERIFIED.value,
        server_default=AccountState.UNVERIFIED.value,
    )
    is_banned: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    tz_name: Mapped[str] = mapped_column(
        String(64), nullable=False, default="UTC", server_default="UTC"
    )
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    cross_category_preview: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
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
        CheckConstraint("age BETWEEN 15 AND 100", name="ck_users_age_range"),
        CheckConstraint(
            "category IN ('PROFESSIONAL', 'SUB_PROFESSIONAL')",
            name="ck_users_category",
        ),
        CheckConstraint("role IN ('LEARNER', 'ADMIN')", name="ck_users_role"),
        CheckConstraint(
            "account_state IN ('UNVERIFIED', 'VERIFIED')",
            name="ck_users_account_state",
        ),
        # Composite index for the admin user-list filter (role + ban status, Req 15.2/15.3).
        Index("ix_users_role_is_banned", "role", "is_banned"),
    )
