"""Repository for audit-log writes and reads.

Append-only per Req 15.5 — no update or delete methods are exposed.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.features.audit.models import AuditLog


class AuditLogRepository:
    """Append-only audit log repository.

    Only ``write`` (insert) and ``list_paginated`` (read) are exposed.
    No update or delete operations exist on this repository.
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    def write(
        self,
        *,
        actor_id: int | None,
        action: str,
        target_kind: str,
        target_id: str | None,
        payload_json: dict[str, Any] | None,
        request_id: str | None,
    ) -> AuditLog:
        """Insert a single audit log entry. Returns the persisted row."""
        entry = AuditLog(
            actor_id=actor_id,
            action=action,
            target_kind=target_kind,
            target_id=target_id,
            payload_json=payload_json,
            request_id=request_id,
        )
        self.db.add(entry)
        self.db.flush()
        return entry

    def list_paginated(self, *, skip: int, limit: int) -> tuple[list[AuditLog], int]:
        """Return paginated audit log entries (newest first) and total count."""
        total_stmt = select(func.count()).select_from(AuditLog)
        total: int = self.db.execute(total_stmt).scalar_one()

        rows_stmt = (
            select(AuditLog)
            .order_by(AuditLog.occurred_at.desc(), AuditLog.id.desc())
            .offset(skip)
            .limit(limit)
        )
        rows = list(self.db.execute(rows_stmt).scalars().all())
        return rows, total
