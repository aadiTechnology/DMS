"""Retention, archive, legal hold and approved deletion (PRD 8.5, LIF-001..LIF-008).

- The category version a document was created under gives its retention period and review
  interval; both clocks start when the document is first released.
- Archiving keeps a document readable but closed to new versions and edits; restoring reopens it.
- A legal hold blocks deletion until released; holds and releases need a reason and are audited.
- Deleting is a request approved by a second person holding `document.approve_delete`. It is
  refused while a hold is active or the retention period has not ended (checked again at
  approval). Approval removes the stored files and leaves a tombstone (metadata, history and
  audit trail); nobody can open a deleted document.
"""

from datetime import UTC, date, datetime, timedelta

from sqlalchemy import and_, or_, select, update
from sqlalchemy.orm import Session

from app.db.models import (
    ApprovalRequest,
    DeletionRequest,
    Document,
    DocumentAccessGrant,
    DocumentSearch,
    DocumentVersion,
    LegalHold,
)
from app.services import access, audit, taxonomy
from app.services.access_sql import load_viewer, visible_clause
from app.services.approvals import Forbidden
from app.services.org import Conflict, Invalid, NotFound
from app.storage.base import StorageProvider

MAX_REASON = 500


def _now() -> datetime:
    return datetime.now(UTC)


def _today() -> date:
    return _now().date()


def _reason(text: str | None, label: str = "reason") -> str:
    value = (text or "").strip()
    if not value:
        raise Invalid(f"{label} is required")
    if len(value) > MAX_REASON:
        raise Invalid(f"{label}: at most {MAX_REASON} characters")
    return value


# ---- retention and review clocks --------------------------------------------------------


def start_clock(db: Session, document: Document) -> None:
    """Called once, when the document is first released."""
    cfg, _ = taxonomy.get_version(
        db, document.tenant_id, document.category_id, document.category_version_number
    )
    today = _today()
    if cfg.retention_days:
        document.retention_until = today + timedelta(days=cfg.retention_days)
    if cfg.review_interval_days:
        document.review_due_on = today + timedelta(days=cfg.review_interval_days)


# ---- archive ----------------------------------------------------------------------------


def _modifiable(db, tenant_id, actor_id, document, permissions):
    decision = access.can_modify(db, tenant_id, actor_id, document, permissions)
    if not decision.allowed:
        raise access.Denied(decision.reason)
    return decision


def archive(db: Session, tenant_id, actor_id, document: Document, permissions: set[str]) -> None:
    decision = _modifiable(db, tenant_id, actor_id, document, permissions)
    if document.lifecycle_state == "archived":
        raise Conflict("The document is already archived")
    if document.lifecycle_state != "approved":
        raise Conflict("Only released documents can be archived")
    if db.scalars(
        select(ApprovalRequest.id).where(
            ApprovalRequest.document_id == document.id, ApprovalRequest.status == "pending"
        )
    ).first():
        raise Conflict("A version is awaiting approval; finish the review first")
    document.lifecycle_state, document.archived_at = "archived", _now()
    document.row_version += 1
    document.updated_at = _now()
    audit.record(
        db, tenant_id=tenant_id, actor_user_id=actor_id, action="document.archived",
        resource_type="document", resource_id=document.id, privileged=decision.privileged,
    )  # fmt: skip


def unarchive(db: Session, tenant_id, actor_id, document: Document, permissions: set[str]) -> None:
    decision = _modifiable(db, tenant_id, actor_id, document, permissions)
    if document.lifecycle_state != "archived":
        raise Conflict("The document is not archived")
    document.lifecycle_state, document.archived_at = "approved", None
    document.row_version += 1
    document.updated_at = _now()
    audit.record(
        db, tenant_id=tenant_id, actor_user_id=actor_id, action="document.unarchived",
        resource_type="document", resource_id=document.id, privileged=decision.privileged,
    )  # fmt: skip


# ---- legal hold -------------------------------------------------------------------------


def active_hold(db: Session, document_id) -> LegalHold | None:
    return db.scalars(
        select(LegalHold).where(
            LegalHold.document_id == document_id, LegalHold.released_at.is_(None)
        )
    ).first()


def place_hold(db: Session, tenant_id, actor_id, document: Document, reason: str) -> LegalHold:
    reason = _reason(reason)
    if document.lifecycle_state == "deleted":
        raise Conflict("The document has been deleted")
    if active_hold(db, document.id) is not None:
        raise Conflict("The document is already under a legal hold")
    hold = LegalHold(
        tenant_id=tenant_id, document_id=document.id, reason=reason, placed_by_user_id=actor_id
    )
    db.add(hold)
    db.flush()
    audit.record(
        db, tenant_id=tenant_id, actor_user_id=actor_id, action="document.legal_hold_placed",
        resource_type="document", resource_id=document.id, details={"reason": reason},
    )  # fmt: skip
    return hold


def release_hold(db: Session, tenant_id, actor_id, document: Document, reason: str) -> LegalHold:
    reason = _reason(reason)
    hold = active_hold(db, document.id)
    if hold is None:
        raise NotFound("legal hold")
    hold.released_at, hold.released_by_user_id, hold.release_reason = _now(), actor_id, reason
    db.flush()
    audit.record(
        db, tenant_id=tenant_id, actor_user_id=actor_id, action="document.legal_hold_released",
        resource_type="document", resource_id=document.id, details={"reason": reason},
    )  # fmt: skip
    return hold


# ---- deletion ---------------------------------------------------------------------------


def blockers(db: Session, document: Document) -> list[dict]:
    found = []
    if active_hold(db, document.id) is not None:
        found.append({"code": "legal_hold"})
    if document.retention_until is not None and document.retention_until > _today():
        found.append({"code": "retention", "until": document.retention_until.isoformat()})
    return found


def _check_deletable(db: Session, document: Document) -> None:
    if document.lifecycle_state == "deleted":
        raise Conflict("The document has already been deleted")
    found = blockers(db, document)
    if found:
        raise Conflict(
            "Deletion is blocked: " + ", ".join(
                "legal hold" if b["code"] == "legal_hold" else f"retention until {b['until']}"
                for b in found
            )
        )  # fmt: skip


def pending_request(db: Session, document_id) -> DeletionRequest | None:
    return db.scalars(
        select(DeletionRequest).where(
            DeletionRequest.document_id == document_id, DeletionRequest.status == "pending"
        )
    ).first()


def request_deletion(
    db: Session, tenant_id, actor_id, document: Document, permissions: set[str], reason: str
) -> DeletionRequest:  # fmt: skip
    decision = _modifiable(db, tenant_id, actor_id, document, permissions)
    reason = _reason(reason)
    _check_deletable(db, document)
    if pending_request(db, document.id) is not None:
        raise Conflict("A deletion request is already pending")
    if db.scalars(
        select(ApprovalRequest.id).where(
            ApprovalRequest.document_id == document.id, ApprovalRequest.status == "pending"
        )
    ).first():
        raise Conflict("A version is awaiting approval; finish the review first")
    request = DeletionRequest(
        tenant_id=tenant_id, document_id=document.id, reason=reason, requested_by_user_id=actor_id
    )
    db.add(request)
    db.flush()
    audit.record(
        db, tenant_id=tenant_id, actor_user_id=actor_id, action="deletion.requested",
        resource_type="document", resource_id=document.id, privileged=decision.privileged,
        details={"reason": reason, "request_id": str(request.id)},
    )  # fmt: skip
    return request


def get_request(db: Session, tenant_id, request_id, *, lock: bool = False) -> DeletionRequest:
    stmt = select(DeletionRequest).where(
        DeletionRequest.id == request_id, DeletionRequest.tenant_id == tenant_id
    )
    request = db.scalars(stmt.with_for_update() if lock else stmt).first()
    if request is None:
        raise NotFound("deletion request")
    return request


def cancel_deletion(db: Session, tenant_id, actor_id, request_id) -> DeletionRequest:
    request = get_request(db, tenant_id, request_id, lock=True)
    if request.requested_by_user_id != actor_id:
        raise NotFound("deletion request")
    if request.status != "pending":
        raise Conflict(f"This request is already {request.status}")
    request.status, request.decided_at = "cancelled", _now()
    audit.record(
        db, tenant_id=tenant_id, actor_user_id=actor_id, action="deletion.cancelled",
        resource_type="document", resource_id=request.document_id,
        details={"request_id": str(request.id)},
    )  # fmt: skip
    return request


def decide_deletion(
    db: Session, tenant_id, actor_id, request_id, *, approve: bool, reason: str | None,
    storage: StorageProvider,
) -> DeletionRequest:  # fmt: skip
    request = get_request(db, tenant_id, request_id, lock=True)
    if request.requested_by_user_id == actor_id:
        raise Forbidden("You cannot decide your own deletion request")
    if request.status != "pending":
        raise Conflict(f"This request is already {request.status}")
    if not approve:
        reason = _reason(reason)
    document = db.get(Document, request.document_id)
    now = _now()
    request.decided_by_user_id, request.decided_at = actor_id, now
    request.decision_reason = (reason or "").strip()[:MAX_REASON] or None
    if not approve:
        request.status = "rejected"
        audit.record(
            db, tenant_id=tenant_id, actor_user_id=actor_id, action="deletion.rejected",
            resource_type="document", resource_id=document.id,
            details={"request_id": str(request.id), "reason": request.decision_reason},
        )  # fmt: skip
        return request
    _check_deletable(db, document)  # a hold or retention date may have appeared since
    request.status = "approved"
    _purge(db, tenant_id, actor_id, document, storage, now)
    audit.record(
        db, tenant_id=tenant_id, actor_user_id=actor_id, action="deletion.approved",
        resource_type="document", resource_id=document.id,
        details={"request_id": str(request.id), "reason": request.decision_reason},
    )  # fmt: skip
    return request


def _purge(db, tenant_id, actor_id, document: Document, storage: StorageProvider, now) -> None:
    """Remove every stored file, close shares, empty the search index, keep the tombstone. A
    storage failure raises, which rolls the whole transaction back (nothing is half-deleted)."""
    versions = db.scalars(
        select(DocumentVersion).where(
            DocumentVersion.document_id == document.id, DocumentVersion.purged_at.is_(None)
        )
    ).all()
    for version in versions:
        if version.status in ("available", "quarantined"):
            storage.delete(version.object_key)
        version.purged_at = now
    db.execute(
        update(DocumentAccessGrant)
        .where(DocumentAccessGrant.document_id == document.id, DocumentAccessGrant.revoked_at.is_(None))
        .values(revoked_at=now, revoked_by_user_id=actor_id)
    )  # fmt: skip
    db.execute(
        update(DocumentSearch)
        .where(DocumentSearch.document_id == document.id)
        .values(meta_tsv=None, content_tsv=None)
    )
    document.lifecycle_state, document.deleted_at = "deleted", now
    document.row_version += 1
    document.updated_at = now


# ---- reading ----------------------------------------------------------------------------


def pending_requests(db: Session, tenant_id, user_id, limit: int, offset: int):
    viewer = load_viewer(db, tenant_id, user_id)
    if viewer is None:
        return []
    return db.execute(
        select(DeletionRequest, Document)
        .join(Document, Document.id == DeletionRequest.document_id)
        .where(
            DeletionRequest.tenant_id == tenant_id,
            DeletionRequest.status == "pending",
            visible_clause(viewer),
        )
        .order_by(DeletionRequest.requested_at, DeletionRequest.id)
        .limit(limit)
        .offset(offset)
    ).all()


def due(db: Session, tenant_id, user_id, days: int, limit: int, offset: int):
    """Documents the viewer can see whose retention ends or review falls due within `days`."""
    viewer = load_viewer(db, tenant_id, user_id)
    if viewer is None:
        return []
    horizon = _today() + timedelta(days=days)
    return db.scalars(
        select(Document)
        .where(
            Document.tenant_id == tenant_id,
            Document.lifecycle_state.in_(("approved", "archived")),
            or_(
                and_(Document.retention_until.is_not(None), Document.retention_until <= horizon),
                and_(Document.review_due_on.is_not(None), Document.review_due_on <= horizon),
            ),
            visible_clause(viewer),
        )
        .order_by(Document.retention_until.asc().nulls_last(), Document.id)
        .limit(limit)
        .offset(offset)
    ).all()


def due_kinds(document: Document, days: int) -> list[dict]:
    horizon = _today() + timedelta(days=days)
    today = _today()
    kinds = []
    if document.retention_until is not None and document.retention_until <= horizon:
        kinds.append(
            {"kind": "retention_ended" if document.retention_until <= today else "retention_ending",
             "date": document.retention_until.isoformat()}
        )  # fmt: skip
    if document.review_due_on is not None and document.review_due_on <= horizon:
        kinds.append(
            {"kind": "review_overdue" if document.review_due_on < today else "review_due",
             "date": document.review_due_on.isoformat()}
        )  # fmt: skip
    return kinds
