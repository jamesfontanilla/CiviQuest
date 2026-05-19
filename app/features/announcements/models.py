"""SQLAlchemy ORM models for announcements and dismissals.

Per design ``Announcements (Phase 2)``:
- Announcement: id, title, body, audience_filter JSON, expires_at, created_by FK, created_at/updated_at
- AnnouncementDismissal: user_id, announcement_id, seen_at, UNIQUE pair

The data model lands in MVP (Task 17.6) so the admin POST route works;
the learner-facing display is Phase 2 (Task 17.7 / 21.x).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base


class Announcement(Base):
    """Admin-created announcement (Req 17.4).

    ``audience_filter`` is a JSON dict that can filter by category and/or role.
    Example: {"category": "PROFESSIONAL"} or {"role": "LEARNER"} or null (all).
    ``expires_at`` is optional; null means the announcement never expires.
    """

    __tablename__ = "announcements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    audience_filter: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_by: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=False,
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


class AnnouncementDismissal(Base):
    """Per-user dismissal record so a user only sees an announcement once.

    UNIQUE on (user_id, announcement_id) prevents duplicate dismissals.
    """

    __tablename__ = "announcement_dismissals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    announcement_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("announcements.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
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
        UniqueConstraint(
            "user_id",
            "announcement_id",
            name="uq_announcement_dismissals_user_announcement",
        ),
    )
