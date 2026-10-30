import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.core.tenancy import Principal, get_tenant_db, require_permission
from app.services import audit

router = APIRouter(prefix="/api/v1/audit-events", tags=["audit"])


class AuditEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    occurred_at: datetime
    actor_user_id: uuid.UUID | None
    action: str
    resource_type: str
    resource_id: str | None
    outcome: str
    privileged: bool
    details: dict[str, Any]


@router.get("", response_model=list[AuditEventOut])
def list_audit_events(
    action: str | None = Query(None, max_length=80),
    since: datetime | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    principal: Principal = Depends(require_permission("admin.view_audit")),
    db: Session = Depends(get_tenant_db),
):
    return audit.search(
        db, principal.tenant_id, action=action, since=since, limit=limit, offset=offset
    )
