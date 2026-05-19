"""Pydantic schemas for audit-log entries."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class AuditLogResponse(BaseModel):
    """Response schema for a single audit log entry."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    actor_id: int | None
    action: str
    target_kind: str
    target_id: str | None
    payload_json: dict | None
    request_id: str | None
    occurred_at: datetime
