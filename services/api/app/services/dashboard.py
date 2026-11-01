"""Dashboard figures. Every number is computed over exactly the documents the person may see
(the same access clause as the library), so a dashboard can never reveal a hidden document."""

from datetime import UTC, date, datetime, timedelta

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.db.models import (
    AuditEvent,
    Document,
    DocumentVersion,
    EmployeeProfile,
    TenantMembership,
)
from app.services import approvals, sharing
from app.services.access_sql import Viewer
from app.services.search import SearchParams, _base, _filters

UPLOAD_DAYS = 30
DUE_DAYS = 30
LIST_SIZE = 5
RECENT_SIZE = 8
ACTIVITY_SIZE = 8


def build(db: Session, tenant_id, user_id, viewer: Viewer, *, can_see_activity: bool) -> dict:
    where = _filters(db, tenant_id, viewer, SearchParams(), [])
    visible = _base(where).with_only_columns(Document.id, Document.classification).subquery()
    ids = select(visible.c.id)

    total = db.scalar(select(func.count()).select_from(visible)) or 0
    by_class = db.execute(
        select(visible.c.classification, func.count())
        .group_by(visible.c.classification)
        .order_by(func.count().desc(), visible.c.classification)
    ).all()
    storage = db.scalar(
        select(func.coalesce(func.sum(DocumentVersion.size_bytes), 0))
        .select_from(Document)
        .join(
            DocumentVersion,
            and_(
                DocumentVersion.document_id == Document.id,
                DocumentVersion.version_number == Document.current_version_number,
            ),
        )
        .where(Document.id.in_(ids))
    )

    today = datetime.now(UTC).date()
    since = datetime.now(UTC) - timedelta(days=UPLOAD_DAYS - 1)
    day = func.date(func.timezone("UTC", Document.created_at))
    counts = dict(
        db.execute(
            select(day, func.count())
            .where(Document.id.in_(ids), Document.created_at >= since)
            .group_by(day)
        ).all()
    )
    uploads = [
        {"date": d, "count": counts.get(d, 0)}
        for d in (today - timedelta(days=i) for i in range(UPLOAD_DAYS - 1, -1, -1))
    ]

    recent = db.scalars(
        select(Document)
        .where(Document.id.in_(ids))
        .order_by(Document.created_at.desc(), Document.id)
        .limit(RECENT_SIZE)
    ).all()

    queue = approvals.queue(db, tenant_id, user_id, 200, 0)
    horizon = date.today() + timedelta(days=DUE_DAYS)
    due = (
        Document.id.in_(ids),
        Document.lifecycle_state.in_(("approved", "archived")),
        or_(
            and_(Document.retention_until.is_not(None), Document.retention_until <= horizon),
            and_(Document.review_due_on.is_not(None), Document.review_due_on <= horizon),
        ),
    )
    expiring = db.scalars(
        select(Document)
        .where(*due)
        .order_by(Document.retention_until.asc().nulls_last(), Document.id)
        .limit(LIST_SIZE)
    ).all()
    expiring_total = db.scalar(select(func.count()).select_from(Document).where(*due)) or 0
    shared = sharing.shared_with_me(db, tenant_id, user_id, 200, 0)

    return {
        "generated_at": datetime.now(UTC),
        "stats": {
            "documents": total,
            "pending_reviews": len(queue),
            "shared_with_me": len(shared),
            "storage_bytes": int(storage or 0),
        },
        "uploads_by_day": uploads,
        "by_classification": [{"value": v, "count": c} for v, c in by_class],
        "recent_documents": [
            {
                "id": d.id,
                "title": d.title,
                "classification": d.classification,
                "lifecycle_state": d.lifecycle_state,
                "created_at": d.created_at,
            }
            for d in recent
        ],
        "approvals_queue": [
            {
                "request_id": r.id,
                "document_id": d.id,
                "title": d.title,
                "submitted_at": r.submitted_at,
            }
            for r, d in queue[:LIST_SIZE]
        ],
        "expiring_soon": {
            "total": expiring_total,
            "items": [
                {
                    "id": d.id,
                    "title": d.title,
                    "retention_until": d.retention_until,
                    "review_due_on": d.review_due_on,
                }
                for d in expiring
            ],
        },
        "activity": _activity(db, tenant_id) if can_see_activity else None,
    }


def _activity(db: Session, tenant_id) -> list[dict]:
    events = db.scalars(
        select(AuditEvent)
        .where(AuditEvent.tenant_id == tenant_id)
        .order_by(AuditEvent.occurred_at.desc(), AuditEvent.id)
        .limit(ACTIVITY_SIZE)
    ).all()
    actors = {e.actor_user_id for e in events if e.actor_user_id}
    names = dict(
        db.execute(
            select(TenantMembership.user_id, EmployeeProfile.full_name)
            .join(EmployeeProfile, EmployeeProfile.membership_id == TenantMembership.id)
            .where(TenantMembership.tenant_id == tenant_id, TenantMembership.user_id.in_(actors))
        ).all()
    )
    return [
        {
            "action": e.action,
            "outcome": e.outcome,
            "occurred_at": e.occurred_at,
            "actor": names.get(e.actor_user_id) if e.actor_user_id else None,
        }
        for e in events
    ]
