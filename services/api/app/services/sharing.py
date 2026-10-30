"""Direct sharing of documents with colleagues (PRD 9.3, SHR-001..SHR-006).

- Who may share: someone with `document.share` who may also modify the document (owner, the
  uploader except for Highly Confidential, or the audited administrator privilege). Nobody
  re-shares a document merely because it was shared with them.
- Only released documents can be shared. The recipient must be an active colleague whose role
  already allows what is granted; a share never exceeds the role (SHR-006), and the access
  policy re-checks that on every read.
- Viewing and downloading are separate rights; an expiry is optional and must be in the future.
- Sharing again with the same person updates the active share; revoking keeps the row as
  history. Every change is audited (the hook for notifications).
"""

from datetime import UTC, datetime

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, aliased

from app.db.models import Document, DocumentAccessGrant, EmployeeProfile, TenantMembership
from app.services import access, audit, rbac
from app.services.access import PUBLISHED
from app.services.access_sql import load_viewer, visible_clause
from app.services.org import Conflict, Invalid, NotFound


def _now() -> datetime:
    return datetime.now(UTC)


def _active(now: datetime, grant=DocumentAccessGrant):
    return (grant.revoked_at.is_(None), or_(grant.expires_at.is_(None), grant.expires_at > now))


def share(
    db: Session, tenant_id, actor_user_id, document: Document, permissions: set[str],
    grantee_membership_id, *, can_view: bool, can_download: bool, expires_at: datetime | None,
) -> tuple[DocumentAccessGrant, bool]:  # fmt: skip
    """Create or update a share. Returns the grant and whether it was newly created."""
    if not (can_view or can_download):
        raise Invalid("choose at least one right to share")
    now = _now()
    if expires_at is not None:
        if expires_at.tzinfo is None:
            raise Invalid("expires_at must include a time zone")
        if expires_at <= now:
            raise Invalid("expires_at must be in the future")
    decision = access.can_modify(db, tenant_id, actor_user_id, document, permissions)
    if not decision.allowed:
        raise access.Denied(decision.reason)
    if document.lifecycle_state not in PUBLISHED:
        raise Conflict("Only released documents can be shared")
    grantee = db.get(TenantMembership, grantee_membership_id)
    if grantee is None or grantee.tenant_id != tenant_id or grantee.status != "active":
        raise NotFound("employee")
    if grantee.user_id == actor_user_id:
        raise Invalid("you cannot share a document with yourself")
    if grantee.id == document.owner_membership_id:
        raise Invalid("the owner already has access")
    theirs = rbac.effective_permissions(db, tenant_id, grantee.user_id)
    if "document.view_metadata" not in theirs or (
        can_download and "document.download" not in theirs
    ):
        raise Invalid("that person's role does not allow this kind of access")
    can_view = can_view or can_download  # downloading implies being able to see the document
    grant = db.scalars(
        select(DocumentAccessGrant)
        .where(
            DocumentAccessGrant.document_id == document.id,
            DocumentAccessGrant.grantee_membership_id == grantee.id,
            DocumentAccessGrant.revoked_at.is_(None),
        )
        .with_for_update()
    ).first()
    created = grant is None
    if created:
        grant = DocumentAccessGrant(
            tenant_id=tenant_id, document_id=document.id, grantee_membership_id=grantee.id,
            granted_by_user_id=actor_user_id,
        )  # fmt: skip
        db.add(grant)
    grant.can_view, grant.can_download, grant.expires_at = can_view, can_download, expires_at
    db.flush()
    audit.record(
        db, tenant_id=tenant_id, actor_user_id=actor_user_id,
        action="share.created" if created else "share.updated", resource_type="document",
        resource_id=document.id, privileged=decision.privileged,
        details={
            "grantee_membership_id": str(grantee.id), "can_view": can_view,
            "can_download": can_download,
            "expires_at": expires_at.isoformat() if expires_at else None,
        },
    )  # fmt: skip
    return grant, created


def revoke(
    db: Session, tenant_id, actor_user_id, document: Document, permissions: set[str],
    grantee_membership_id,
) -> DocumentAccessGrant:  # fmt: skip
    decision = access.can_modify(db, tenant_id, actor_user_id, document, permissions)
    if not decision.allowed:
        raise access.Denied(decision.reason)
    grant = db.scalars(
        select(DocumentAccessGrant)
        .where(
            DocumentAccessGrant.document_id == document.id,
            DocumentAccessGrant.grantee_membership_id == grantee_membership_id,
            DocumentAccessGrant.revoked_at.is_(None),
        )
        .with_for_update()
    ).first()
    if grant is None:
        raise NotFound("share")
    grant.revoked_at, grant.revoked_by_user_id = _now(), actor_user_id
    db.flush()
    audit.record(
        db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="share.revoked",
        resource_type="document", resource_id=document.id, privileged=decision.privileged,
        details={"grantee_membership_id": str(grantee_membership_id)},
    )  # fmt: skip
    return grant


def for_document(db: Session, tenant_id, document_id, *, include_history: bool = False):
    stmt = (
        select(DocumentAccessGrant, EmployeeProfile.full_name)
        .outerjoin(
            EmployeeProfile,
            EmployeeProfile.membership_id == DocumentAccessGrant.grantee_membership_id,
        )
        .where(
            DocumentAccessGrant.tenant_id == tenant_id,
            DocumentAccessGrant.document_id == document_id,
        )
        .order_by(DocumentAccessGrant.created_at.desc(), DocumentAccessGrant.id)
    )
    if not include_history:
        stmt = stmt.where(*_active(_now()))
    return db.execute(stmt).all()


def shared_with_me(db: Session, tenant_id, user_id, limit: int, offset: int):
    """Active shares to me for documents I can still see (a share never outlives the role
    ceiling or the document's state)."""
    viewer = load_viewer(db, tenant_id, user_id)
    if viewer is None:
        return []
    mine = aliased(DocumentAccessGrant)
    return db.execute(
        select(mine, Document)
        .join(Document, Document.id == mine.document_id)
        .where(
            mine.tenant_id == tenant_id,
            mine.grantee_membership_id == viewer.membership_id,
            *_active(_now(), mine),
            visible_clause(viewer),
        )
        .order_by(mine.created_at.desc(), mine.id)
        .limit(limit)
        .offset(offset)
    ).all()


def shared_by_me(db: Session, tenant_id, user_id, limit: int, offset: int):
    return db.execute(
        select(DocumentAccessGrant, Document)
        .join(Document, Document.id == DocumentAccessGrant.document_id)
        .where(
            DocumentAccessGrant.tenant_id == tenant_id,
            DocumentAccessGrant.granted_by_user_id == user_id,
            *_active(_now()),
        )
        .order_by(DocumentAccessGrant.created_at.desc(), DocumentAccessGrant.id)
        .limit(limit)
        .offset(offset)
    ).all()
