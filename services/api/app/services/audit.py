import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import insert, select
from sqlalchemy.orm import Session

from app.db.models import AuditEvent

MAX_PAGE_SIZE = 200


def record(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    actor_user_id: uuid.UUID | None,
    action: str,
    resource_type: str,
    resource_id: uuid.UUID | str | None = None,
    outcome: str = "success",
    privileged: bool = False,
    details: dict[str, Any] | None = None,
) -> None:
    """Append an audit event in the caller's transaction. `details` must be safe metadata only:
    never passwords, tokens, signed URLs or document content. Core insert (no RETURNING) so it
    also works for roles that may write but not read audit rows.
    """
    db.execute(
        insert(AuditEvent.__table__).values(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            action=action,
            resource_type=resource_type,
            resource_id=None if resource_id is None else str(resource_id),
            outcome=outcome,
            privileged=privileged,
            details=details or {},
        )
    )


def search(
    db: Session,
    tenant_id: uuid.UUID,
    *,
    action: str | None = None,
    since: datetime | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[AuditEvent]:
    stmt = select(AuditEvent).where(AuditEvent.tenant_id == tenant_id)
    if action:
        stmt = stmt.where(AuditEvent.action == action)
    if since:
        stmt = stmt.where(AuditEvent.occurred_at >= since)
    stmt = (
        stmt.order_by(AuditEvent.occurred_at.desc(), AuditEvent.id)
        .limit(max(1, min(limit, MAX_PAGE_SIZE)))
        .offset(max(0, offset))
    )
    return list(db.scalars(stmt))
