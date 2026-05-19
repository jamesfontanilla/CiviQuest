"""Repository for announcement persistence."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.features.announcements.models import Announcement, AnnouncementDismissal
from app.infrastructure.repositories.base import BaseRepository


class AnnouncementRepository(BaseRepository[Announcement]):
    """Persistence for Announcement rows."""

    model = Announcement

    def __init__(self, db: Session) -> None:
        super().__init__(db=db)

    def create_announcement(
        self,
        *,
        title: str,
        body: str,
        audience_filter: dict[str, Any] | None,
        expires_at: datetime | None,
        created_by: int,
    ) -> Announcement:
        """Create and persist an announcement."""
        announcement = Announcement(
            title=title,
            body=body,
            audience_filter=audience_filter,
            expires_at=expires_at,
            created_by=created_by,
        )
        self.db.add(announcement)
        self.db.commit()
        self.db.refresh(announcement)
        return announcement

    def list_active(self, now: datetime | None = None) -> list[Announcement]:
        """Return announcements that haven't expired."""
        stmt = select(Announcement)
        if now is not None:
            stmt = stmt.where(
                (Announcement.expires_at.is_(None)) | (Announcement.expires_at > now)
            )
        stmt = stmt.order_by(Announcement.created_at.desc())
        return list(self.db.execute(stmt).scalars().all())
