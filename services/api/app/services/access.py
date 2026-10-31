"""Document access policy (PRD section 7).

`decide()` answers "may this person do this action on this document right now?". Every protected
read, preview and download goes through it; hiding a button is never the control.

Inputs, in order:
 1. Role ceiling: the person's roles must grant the matching permission (view_metadata,
    preview, download). Explicit shares can never exceed it (SHR-006).
 2. Publication state: a document that is not yet published (draft, submitted, under review,
    rejected) is visible only to its uploader and owner (WF-005; reviewers join with the
    approval workflow).
 3. Classification (PRD 7.1):
      public / internal  every active employee of the organization
      confidential       owner, uploader, direct grants, members and managers of the
                         associated departments, members and managers of associated projects
      highly_confidential owner, managers of the associated departments, direct grants
                         (the uploader keeps metadata access only, to follow their upload)
 4. Direct grants: `can_view` covers metadata + preview; `can_download` is separate.
 5. Privileged access: holders of `document.access_all` (organization administrators by
    default) may reach any document. That path is flagged `privileged` and audited by the caller.

The same rules will be expressed as a SQL filter for lists and search (next sprint); a test
there compares both implementations so they cannot drift.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    ApprovalAssignment,
    ApprovalRequest,
    Department,
    Document,
    DocumentAccessGrant,
    DocumentAssociation,
    EmployeeProfile,
    Project,
    ProjectMembership,
    TenantMembership,
)
from app.services import audit, rbac

ACTION_PERMISSION = {
    "view_metadata": "document.view_metadata",
    "preview": "document.preview",
    "download": "document.download",
}
PUBLISHED = ("approved", "archived")
PRIVILEGE = "document.access_all"


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str
    privileged: bool = False


def _deny(reason: str) -> Decision:
    return Decision(False, reason)


class _Facts:
    """Lazily loaded facts about one person and one document (most documents need none)."""

    def __init__(self, db: Session, tenant_id, membership: TenantMembership, document: Document):
        self.db, self.tenant_id, self.m, self.doc = db, tenant_id, membership, document
        self._assoc: dict[str, set] | None = None

    @property
    def assoc(self) -> dict[str, set]:
        if self._assoc is None:
            rows = self.db.execute(
                select(DocumentAssociation.dimension, DocumentAssociation.ref_id).where(
                    DocumentAssociation.document_id == self.doc.id
                )
            ).all()
            out: dict[str, set] = {}
            for dimension, ref in rows:
                out.setdefault(dimension, set()).add(ref)
            self._assoc = out
        return self._assoc

    def manages_associated_department(self) -> bool:
        ids = self.assoc.get("department")
        if not ids:
            return False
        return (
            self.db.scalars(
                select(Department.id).where(
                    Department.id.in_(ids), Department.manager_membership_id == self.m.id
                )
            ).first()
            is not None
        )

    def in_associated_department(self) -> bool:
        ids = self.assoc.get("department")
        if not ids:
            return False
        return (
            self.db.scalars(
                select(EmployeeProfile.id).where(
                    EmployeeProfile.membership_id == self.m.id,
                    EmployeeProfile.department_id.in_(ids),
                    EmployeeProfile.employment_status != "exited",
                )
            ).first()
            is not None
        )

    def on_associated_project(self) -> bool:
        ids = self.assoc.get("project")
        if not ids:
            return False
        today = date.today()
        managed = self.db.scalars(
            select(Project.id).where(
                Project.id.in_(ids), Project.manager_membership_id == self.m.id
            )
        ).first()
        if managed is not None:
            return True
        member = self.db.scalars(
            select(ProjectMembership.id).where(
                ProjectMembership.membership_id == self.m.id,
                ProjectMembership.project_id.in_(ids),
                (ProjectMembership.ends_on.is_(None)) | (ProjectMembership.ends_on >= today),
            )
        ).first()
        return member is not None

    def grant(self) -> DocumentAccessGrant | None:
        now = datetime.now(UTC)
        return self.db.scalars(
            select(DocumentAccessGrant).where(
                DocumentAccessGrant.document_id == self.doc.id,
                DocumentAccessGrant.grantee_membership_id == self.m.id,
                DocumentAccessGrant.revoked_at.is_(None),
                (DocumentAccessGrant.expires_at.is_(None)) | (DocumentAccessGrant.expires_at > now),
            )
        ).first()


def is_assigned_reviewer(
    db: Session, membership_id, document_id, version_number: int | None = None
) -> bool:
    """Is this person a reviewer of a still-pending request on the document (or version)?"""
    stmt = (
        select(ApprovalAssignment.id)
        .join(ApprovalRequest, ApprovalRequest.id == ApprovalAssignment.request_id)
        .where(
            ApprovalRequest.document_id == document_id,
            ApprovalRequest.status == "pending",
            ApprovalAssignment.membership_id == membership_id,
        )
    )
    if version_number is not None:
        stmt = stmt.where(ApprovalRequest.version_number == version_number)
    return db.scalars(stmt).first() is not None


def decide(
    db: Session,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    document: Document,
    action: str,
    permissions: set[str] | None = None,
) -> Decision:
    if document.tenant_id != tenant_id:
        return _deny("other_tenant")  # defense in depth: queries are already tenant-scoped
    perms = (
        permissions
        if permissions is not None
        else rbac.effective_permissions(db, tenant_id, user_id)
    )
    if ACTION_PERMISSION[action] not in perms:
        return _deny("role_lacks_permission")
    membership = db.scalars(
        select(TenantMembership).where(
            TenantMembership.tenant_id == tenant_id,
            TenantMembership.user_id == user_id,
            TenantMembership.status == "active",
        )
    ).first()
    if membership is None:
        return _deny("not_a_member")

    if document.lifecycle_state == "deleted":  # a tombstone: nobody reads it, not even admins
        return _deny("deleted")
    is_owner = document.owner_membership_id == membership.id
    is_uploader = document.created_by_user_id == user_id
    privileged = Decision(True, "administrator_privilege", True) if PRIVILEGE in perms else None
    if action == "view_metadata" and is_assigned_reviewer(db, membership.id, document.id):
        return Decision(True, "reviewer")  # preview/download go through decide_version

    if document.lifecycle_state not in PUBLISHED:  # pending / rejected: not for general viewing
        if is_owner or is_uploader:
            return Decision(True, "owner" if is_owner else "uploader")
        return privileged or _deny("not_published")

    facts = _Facts(db, tenant_id, membership, document)
    classification = document.classification
    if classification in ("public", "internal"):
        return Decision(True, "organization")
    if is_owner:
        return Decision(True, "owner")
    if classification == "highly_confidential" and is_uploader and action == "view_metadata":
        return Decision(True, "uploader")  # may follow their own upload, not open its content
    if classification == "confidential" and is_uploader:
        return Decision(True, "uploader")
    grant = facts.grant()
    if grant is not None and (grant.can_download if action == "download" else grant.can_view):
        return Decision(True, "shared")
    if facts.manages_associated_department():
        return Decision(True, "department_manager")
    if classification == "confidential":
        if facts.in_associated_department():
            return Decision(True, "department_member")
        if facts.on_associated_project():
            return Decision(True, "project")
    return privileged or _deny("not_authorized")


def require(
    db: Session,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    document_id: uuid.UUID,
    action: str,
    permissions: set[str] | None = None,
) -> tuple[Document, Decision]:
    """Load a document and authorize `action`. Raises `Denied` (answered as 404 so existence is
    not revealed) with the reason, for the caller to audit in its own transaction."""
    document = db.get(Document, document_id)
    if document is None or document.tenant_id != tenant_id:
        raise Denied("missing")
    decision = decide(db, tenant_id, user_id, document, action, permissions)
    if not decision.allowed:
        raise Denied(decision.reason)
    return document, decision


class Denied(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def record_access(
    db: Session,
    tenant_id,
    user_id,
    document: Document,
    decision: Decision,
    action: str,
    *,
    version_number: int | None = None,
    always: bool = False,
) -> None:
    """Audit access. Previews and downloads are always recorded (PRD 15.1, DASH-007);
    metadata views only when they used the privileged path."""
    if not (always or decision.privileged):
        return
    audit.record(
        db, tenant_id=tenant_id, actor_user_id=user_id,
        action="document.privileged_access" if decision.privileged else f"document.{action}",
        resource_type="document", resource_id=document.id, privileged=decision.privileged,
        details={"access": action, "version": version_number,
                 "classification": document.classification, "basis": decision.reason},
    )  # fmt: skip


def record_denied(db: Session, tenant_id, user_id, document_id, action: str, reason: str) -> None:
    audit.record(
        db, tenant_id=tenant_id, actor_user_id=user_id, action="document.access_denied",
        resource_type="document", resource_id=document_id, outcome="denied",
        details={"access": action, "reason": reason},
    )  # fmt: skip


# ---- versions and modification (Sprint 14) ----------------------------------------------


def _membership(db: Session, tenant_id, user_id) -> TenantMembership | None:
    return db.scalars(
        select(TenantMembership).where(
            TenantMembership.tenant_id == tenant_id,
            TenantMembership.user_id == user_id,
            TenantMembership.status == "active",
        )
    ).first()


def can_modify(
    db: Session, tenant_id, user_id, document: Document, permissions: set[str]
) -> Decision:
    """May this person add versions, restore, or edit metadata? Owner; the uploader (not for
    Highly Confidential documents they do not own); or the audited administrator privilege.
    The caller separately checks the role permission (upload_version, restore, edit_metadata)."""
    membership = _membership(db, tenant_id, user_id)
    if membership is None or document.tenant_id != tenant_id:
        return _deny("not_a_member")
    if document.owner_membership_id == membership.id:
        return Decision(True, "owner")
    if document.created_by_user_id == user_id and document.classification != "highly_confidential":
        return Decision(True, "uploader")
    if PRIVILEGE in permissions:
        return Decision(True, "administrator_privilege", True)
    return _deny("not_authorized")


def decide_version(
    db: Session,
    tenant_id,
    user_id,
    document: Document,
    version,
    action: str,
    permissions: set[str] | None = None,
) -> Decision:
    """Access to one specific version. Published versions follow the document rules. A version
    that is not published (still uploading, awaiting approval, rejected, quarantined,
    abandoned) is visible only to its uploader, the document owner, and administrators with the
    audited privilege. An old version never bypasses today's authorization."""
    perms = (
        permissions
        if permissions is not None
        else rbac.effective_permissions(db, tenant_id, user_id)
    )
    if ACTION_PERMISSION[action] not in perms:
        return _deny("role_lacks_permission")
    published = version.status == "available" and version.review_status in ("none", "approved")
    if published:
        return decide(db, tenant_id, user_id, document, action, perms)
    if action != "view_metadata" and version.status != "available":
        return _deny("version_unavailable")
    membership = _membership(db, tenant_id, user_id)
    if membership is None or document.tenant_id != tenant_id:
        return _deny("not_a_member")
    if document.owner_membership_id == membership.id:
        return Decision(True, "owner")
    if version.uploaded_by_user_id == user_id:
        return Decision(True, "uploader")
    if is_assigned_reviewer(db, membership.id, document.id, version.version_number):
        return Decision(True, "reviewer")
    if PRIVILEGE in perms:
        return Decision(True, "administrator_privilege", True)
    return _deny("version_not_published")


def require_version(
    db: Session, tenant_id, user_id, document_id, number: int, action: str,
    permissions: set[str] | None = None,
):  # fmt: skip
    """Load document + version and authorize `action` on that version (`Denied` otherwise)."""
    from app.db.models import DocumentVersion

    document = db.get(Document, document_id)
    if document is None or document.tenant_id != tenant_id:
        raise Denied("missing")
    version = db.scalars(
        select(DocumentVersion).where(
            DocumentVersion.document_id == document.id, DocumentVersion.version_number == number
        )
    ).first()
    if version is None:
        raise Denied("missing")
    decision = decide_version(db, tenant_id, user_id, document, version, action, permissions)
    if not decision.allowed:
        raise Denied(decision.reason)
    return document, version, decision


def visible_versions(db: Session, tenant_id, user_id, document: Document, versions, permissions):
    return [
        v
        for v in versions
        if decide_version(db, tenant_id, user_id, document, v, "view_metadata", permissions).allowed
    ]
