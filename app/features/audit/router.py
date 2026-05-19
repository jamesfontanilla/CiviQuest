"""FastAPI router for the audit-log admin viewer.

Mounts under ``/v1/admin`` and exposes:
- GET /audit-log — paginated, admin-only (Req 21.1, 21.2)
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.common.deps import require_admin
from app.common.schemas.request import PaginationParams
from app.common.schemas.response import PaginatedResponse
from app.features.audit.repository import AuditLogRepository
from app.features.audit.schemas import AuditLogResponse
from app.features.audit.service import AuditLogger
from app.features.users.models import User
from app.infrastructure.database.session import get_db

router = APIRouter(prefix="/v1/admin", tags=["audit"])


def get_audit_logger(db: Session = Depends(get_db)) -> AuditLogger:
    """Construct AuditLogger for the request scope."""
    return AuditLogger(repo=AuditLogRepository(db=db))


@router.get("/audit-log", response_model=PaginatedResponse[AuditLogResponse])
def list_audit_log(
    pagination: PaginationParams = Depends(),
    admin: User = Depends(require_admin),
    service: AuditLogger = Depends(get_audit_logger),
) -> PaginatedResponse[AuditLogResponse]:
    """Paginated audit log (Req 21.1, 21.2). Admin-only."""
    rows, total = service.list_paginated(skip=pagination.skip, limit=pagination.limit)
    items = [AuditLogResponse.model_validate(row) for row in rows]
    return PaginatedResponse[AuditLogResponse](
        items=items, total=total, skip=pagination.skip, limit=pagination.limit
    )
