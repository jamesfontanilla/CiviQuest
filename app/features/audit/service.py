"""Audit service: log writer invoked from admin actions and security events.

The ``AuditLogger`` redacts sensitive fields from the payload before
persisting, using the same ``redact`` helper that the logging middleware uses
(Req 21.3).
"""

from __future__ import annotations

from typing import Any

from app.common.middlewares.logging import redact
from app.features.audit.models import AuditLog
from app.features.audit.repository import AuditLogRepository


class AuditLogger:
    """Append-only audit log writer.

    Constructor receives an ``AuditLogRepository`` via dependency injection.
    The ``log`` method redacts the payload and delegates to the repository's
    ``write`` method.
    """

    def __init__(self, *, repo: AuditLogRepository) -> None:
        self._repo = repo

    def log(
        self,
        actor_id: int | None,
        action: str,
        target_kind: str,
        target_id: str | None = None,
        payload: dict[str, Any] | None = None,
        request_id: str | None = None,
    ) -> AuditLog:
        """Write an audit log entry with redacted payload.

        The payload is deep-copied and redacted before persistence so
        sensitive fields (password, token, otp_code, etc.) never reach
        the database (Req 21.3).
        """
        redacted_payload = redact(payload) if payload is not None else None
        return self._repo.write(
            actor_id=actor_id,
            action=action,
            target_kind=target_kind,
            target_id=target_id,
            payload_json=redacted_payload,
            request_id=request_id,
        )

    def list_paginated(self, *, skip: int, limit: int) -> tuple[list[AuditLog], int]:
        """Delegate paginated read to the repository (admin-only)."""
        return self._repo.list_paginated(skip=skip, limit=limit)
