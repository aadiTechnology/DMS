"""Approval workflow (PRD 8.2, WF-001..WF-006).

A category can require approval and define ordered steps (a named employee, everyone holding a
role, or the managers of the document's departments). Without steps there is one default step:
anyone holding `document.approve`. Reviewers are chosen when each step starts and stored, so
later role changes never rewrite history. Rules:

- The person who submitted a version can never decide it (not even an administrator).
- An assigned reviewer of the current step decides; one approval completes a step.
  Administrators with the audited privilege (`document.access_all`) may also decide; that is
  flagged privileged in the history and the audit log.
- Rejection needs a reason. The submitter corrects (edit or new version) and resubmits; earlier
  requests and their decisions stay on record.
- Decisions, comments and assignments are insert-only; repeating a decision is harmless.
- Releasing a version (final approval) makes it the version readers see.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import (
    ApprovalAssignment,
    ApprovalEvent,
    ApprovalRequest,
    Department,
    Document,
    DocumentAssociation,
    DocumentVersion,
    Role,
    RolePermission,
    TenantMembership,
    UserRoleAssignment,
)
from app.services import access, audit, extraction, search, taxonomy
from app.services.access import PRIVILEGE, PUBLISHED
from app.services.org import Conflict, Invalid, NotFound

MAX_COMMENT = 1000
DEFAULT_STEP = {"type": "default", "ref": None}


class Forbidden(Exception):
    """The caller is known but not allowed (for example approving their own submission)."""


def _now() -> datetime:
    return datetime.now(UTC)


def _membership(db: Session, tenant_id, user_id) -> TenantMembership | None:
    return db.scalars(
        select(TenantMembership).where(
            TenantMembership.tenant_id == tenant_id,
            TenantMembership.user_id == user_id,
            TenantMembership.status == "active",
        )
    ).first()


def _clean_comment(text: str | None, *, required: bool, label: str = "comment") -> str | None:
    value = (text or "").strip()
    if required and not value:
        raise Invalid(f"{label} is required")
    if len(value) > MAX_COMMENT:
        raise Invalid(f"{label}: at most {MAX_COMMENT} characters")
    return value or None


# ---- reviewers --------------------------------------------------------------------------


def _members_with_permission(db: Session, tenant_id, code: str) -> set:
    rows = db.scalars(
        select(TenantMembership.id)
        .join(UserRoleAssignment, UserRoleAssignment.membership_id == TenantMembership.id)
        .join(Role, Role.id == UserRoleAssignment.role_id)
        .join(RolePermission, RolePermission.role_id == Role.id)
        .where(
            TenantMembership.tenant_id == tenant_id,
            TenantMembership.status == "active",
            UserRoleAssignment.revoked_at.is_(None),
            Role.status == "active",
            RolePermission.permission_code == code,
        )
        .distinct()
    )
    return set(rows)


def eligible_reviewers(
    db: Session, tenant_id, document: Document, step: dict, submitter_user_id
) -> set:
    """Active employees who may review at this step. Everyone must hold `document.approve`;
    the submitter is always excluded."""
    candidates = _members_with_permission(db, tenant_id, "document.approve")
    kind, ref = step["type"], step.get("ref")
    if kind == "user":
        candidates &= {uuid.UUID(ref)}
    elif kind == "role":
        holders = db.scalars(
            select(UserRoleAssignment.membership_id).where(
                UserRoleAssignment.role_id == uuid.UUID(ref),
                UserRoleAssignment.revoked_at.is_(None),
            )
        )
        candidates &= set(holders)
    elif kind == "department_manager":
        departments = db.scalars(
            select(DocumentAssociation.ref_id).where(
                DocumentAssociation.document_id == document.id,
                DocumentAssociation.dimension == "department",
            )
        ).all()
        managers = db.scalars(
            select(Department.manager_membership_id).where(
                Department.id.in_(departments), Department.manager_membership_id.is_not(None)
            )
        )
        candidates &= set(managers)
    submitter = _membership(db, tenant_id, submitter_user_id)
    if submitter is not None:
        candidates.discard(submitter.id)
    return candidates


def _start_step(db: Session, request: ApprovalRequest, document: Document, number: int) -> int:
    step = request.steps[number - 1]
    members = eligible_reviewers(
        db, request.tenant_id, document, step, request.submitted_by_user_id
    )
    db.add_all(
        ApprovalAssignment(
            tenant_id=request.tenant_id, request_id=request.id, step_number=number, membership_id=m
        )
        for m in members
    )
    db.add(
        ApprovalEvent(
            tenant_id=request.tenant_id, request_id=request.id, step_number=number,
            action="step_started",
        )
    )  # fmt: skip
    audit.record(
        db, tenant_id=request.tenant_id, actor_user_id=None, action="approval.step_started",
        resource_type="approval_request", resource_id=request.id,
        details={"step": number, "reviewers": len(members), "document_id": str(document.id)},
    )  # fmt: skip
    return len(members)


# ---- submit / resubmit ------------------------------------------------------------------


def submit(
    db: Session, tenant_id, document: Document, version: DocumentVersion, submitter_user_id,
    *, resubmission_of=None,
) -> ApprovalRequest:  # fmt: skip
    cfg, _ = taxonomy.get_version(
        db, tenant_id, document.category_id, document.category_version_number
    )
    steps = list(cfg.approval_steps or []) or [DEFAULT_STEP]
    request = ApprovalRequest(
        tenant_id=tenant_id, document_id=document.id, version_number=version.version_number,
        steps=steps, submitted_by_user_id=submitter_user_id, resubmission_of=resubmission_of,
    )  # fmt: skip
    db.add(request)
    db.flush()
    db.add(
        ApprovalEvent(
            tenant_id=tenant_id, request_id=request.id, actor_user_id=submitter_user_id,
            action="resubmitted" if resubmission_of else "submitted",
        )
    )  # fmt: skip
    audit.record(
        db, tenant_id=tenant_id, actor_user_id=submitter_user_id,
        action="approval.resubmitted" if resubmission_of else "approval.submitted",
        resource_type="approval_request", resource_id=request.id,
        details={"document_id": str(document.id), "version": version.version_number, "steps": len(steps)},
    )  # fmt: skip
    _start_step(db, request, document, 1)
    return request


def resubmit(
    db: Session, tenant_id, actor_id, document_id, permissions: set[str]
) -> ApprovalRequest:
    document = db.scalars(
        select(Document)
        .where(Document.id == document_id, Document.tenant_id == tenant_id)
        .with_for_update()
    ).first()
    if document is None:
        raise access.Denied("missing")
    decision = access.can_modify(db, tenant_id, actor_id, document, permissions)
    if not decision.allowed:
        raise access.Denied(decision.reason)
    version = db.scalars(
        select(DocumentVersion)
        .where(
            DocumentVersion.document_id == document.id,
            DocumentVersion.status == "available",
            DocumentVersion.review_status == "rejected",
        )
        .order_by(DocumentVersion.version_number.desc())
    ).first()
    if version is None:
        raise Conflict("There is no rejected version to resubmit")
    latest = db.scalar(
        select(func.max(DocumentVersion.version_number)).where(
            DocumentVersion.document_id == document.id
        )
    )
    if latest != version.version_number:
        raise Conflict("A newer version exists; resubmit that one instead")
    previous = db.scalars(
        select(ApprovalRequest)
        .where(
            ApprovalRequest.document_id == document.id,
            ApprovalRequest.version_number == version.version_number,
        )
        .order_by(ApprovalRequest.submitted_at.desc())
    ).first()
    version.review_status = "pending"
    if document.lifecycle_state == "rejected":
        document.lifecycle_state = "submitted"
    document.row_version += 1
    document.updated_at = _now()
    return submit(
        db,
        tenant_id,
        document,
        version,
        actor_id,
        resubmission_of=previous.id if previous else None,
    )


# ---- deciding ---------------------------------------------------------------------------


def _locked_request(db: Session, tenant_id, request_id) -> ApprovalRequest:
    request = db.scalars(
        select(ApprovalRequest)
        .where(ApprovalRequest.id == request_id, ApprovalRequest.tenant_id == tenant_id)
        .with_for_update()
    ).first()
    if request is None:
        raise access.Denied("missing")
    return request


def _assigned(db: Session, request: ApprovalRequest, membership_id, *, any_step=False) -> bool:
    stmt = select(ApprovalAssignment.id).where(
        ApprovalAssignment.request_id == request.id,
        ApprovalAssignment.membership_id == membership_id,
    )
    if not any_step:
        stmt = stmt.where(ApprovalAssignment.step_number == request.current_step)
    return db.scalars(stmt).first() is not None


def _has_event(db: Session, request, actor_id, action: str) -> bool:
    return (
        db.scalars(
            select(ApprovalEvent.id).where(
                ApprovalEvent.request_id == request.id,
                ApprovalEvent.actor_user_id == actor_id,
                ApprovalEvent.action == action,
            )
        ).first()
        is not None
    )


def decide(
    db: Session, tenant_id, actor_id, request_id, action: str, comment: str | None,
    permissions: set[str],
) -> tuple[ApprovalRequest, dict]:  # fmt: skip
    """`action` is approve or reject. Returns (request, info) where info says whether the
    request was completed, which document it concerns, and whether the served version changed."""
    event_action = "approved" if action == "approve" else "rejected"
    needed = "document.approve" if action == "approve" else "document.reject"
    request = _locked_request(db, tenant_id, request_id)
    if needed not in permissions:
        raise access.Denied("role_lacks_permission")
    info = {
        "document_id": request.document_id,
        "completed": False,
        "changed": False,
        "repeat": False,
    }
    if _has_event(db, request, actor_id, event_action):
        info["repeat"] = True  # the same person already did this: harmless repeat
        return request, info
    if request.submitted_by_user_id == actor_id:
        raise Forbidden("You cannot decide your own submission")
    if request.status != "pending":
        raise Conflict(f"This request is already {request.status}")
    membership = _membership(db, tenant_id, actor_id)
    if membership is None:
        raise access.Denied("not_a_member")
    assigned = _assigned(db, request, membership.id)
    privileged = (not assigned) and PRIVILEGE in permissions
    if not assigned and not privileged:
        raise access.Denied("not_assigned")
    text = _clean_comment(comment, required=action == "reject", label="reason")

    document = db.scalars(
        select(Document).where(Document.id == request.document_id).with_for_update()
    ).one()
    version = db.scalars(
        select(DocumentVersion).where(
            DocumentVersion.document_id == document.id,
            DocumentVersion.version_number == request.version_number,
        )
    ).one()
    step = request.current_step
    db.add(
        ApprovalEvent(
            tenant_id=tenant_id, request_id=request.id, step_number=step, actor_user_id=actor_id,
            action=event_action, comment=text, privileged=privileged,
        )
    )  # fmt: skip
    audit.record(
        db, tenant_id=tenant_id, actor_user_id=actor_id, action=f"approval.{event_action}",
        resource_type="approval_request", resource_id=request.id, privileged=privileged,
        details={"document_id": str(document.id), "version": version.version_number, "step": step,
                 "basis": "administrator_privilege" if privileged else "assigned_reviewer"},
    )  # fmt: skip
    if document.lifecycle_state == "submitted":
        document.lifecycle_state = "under_review"
    if action == "reject":
        _finish_rejected(db, request, document, version)
        info["completed"] = True
    elif step < len(request.steps):
        request.current_step = step + 1
        _start_step(db, request, document, step + 1)
    else:
        info["changed"] = _finish_approved(db, request, document, version)
        info["completed"] = True
    document.row_version += 1
    document.updated_at = _now()
    db.flush()
    return request, info


def _finish_rejected(db: Session, request, document: Document, version: DocumentVersion) -> None:
    request.status, request.decided_at = "rejected", _now()
    version.review_status = "rejected"
    if document.lifecycle_state not in PUBLISHED:
        document.lifecycle_state = "rejected"
    audit.record(
        db, tenant_id=request.tenant_id, actor_user_id=None, action="approval.completed",
        resource_type="approval_request", resource_id=request.id, outcome="denied",
        details={"document_id": str(document.id), "version": version.version_number, "result": "rejected"},
    )  # fmt: skip


def _finish_approved(db: Session, request, document: Document, version: DocumentVersion) -> bool:
    """Release the version. Returns True when the version readers see has changed."""
    request.status, request.decided_at = "approved", _now()
    version.review_status = "approved"
    if document.lifecycle_state not in PUBLISHED:
        document.lifecycle_state = "approved"
    previous = document.current_version_number
    document.current_version_number = max(previous or 0, version.version_number)
    changed = document.current_version_number != previous
    if changed:  # the newly released version must become searchable by content
        search.index_metadata(
            db, document, version.original_filename,
            content_supported=search.extraction_ext(version.original_filename) in extraction.SUPPORTED,
        )  # fmt: skip
    audit.record(
        db, tenant_id=request.tenant_id, actor_user_id=None, action="approval.completed",
        resource_type="approval_request", resource_id=request.id,
        details={"document_id": str(document.id), "version": version.version_number, "result": "approved"},
    )  # fmt: skip
    return changed


def add_comment(
    db: Session, tenant_id, actor_id, request_id, comment: str | None, permissions: set[str]
) -> ApprovalRequest:  # fmt: skip
    request = _locked_request(db, tenant_id, request_id)
    if not can_view_request(db, tenant_id, actor_id, request, permissions):
        raise access.Denied("not_assigned")
    text = _clean_comment(comment, required=True)
    membership = _membership(db, tenant_id, actor_id)
    db.add(
        ApprovalEvent(
            tenant_id=tenant_id, request_id=request.id, step_number=request.current_step,
            actor_user_id=actor_id, action="commented", comment=text,
            privileged=bool(membership and not _assigned(db, request, membership.id, any_step=True)
                            and request.submitted_by_user_id != actor_id and PRIVILEGE in permissions),
        )
    )  # fmt: skip
    return request


# ---- reading ----------------------------------------------------------------------------


def can_view_request(
    db: Session, tenant_id, user_id, request: ApprovalRequest, permissions
) -> bool:
    if request.submitted_by_user_id == user_id or PRIVILEGE in permissions:
        return True
    membership = _membership(db, tenant_id, user_id)
    if membership is None:
        return False
    document = db.get(Document, request.document_id)
    if document is not None and document.owner_membership_id == membership.id:
        return True
    return _assigned(db, request, membership.id, any_step=True)


def get_request(db: Session, tenant_id, user_id, request_id, permissions) -> ApprovalRequest:
    request = db.get(ApprovalRequest, request_id)
    if request is None or request.tenant_id != tenant_id:
        raise access.Denied("missing")
    if not can_view_request(db, tenant_id, user_id, request, permissions):
        raise access.Denied("not_assigned")
    return request


def request_parts(db: Session, request: ApprovalRequest):
    assignments = list(
        db.scalars(
            select(ApprovalAssignment)
            .where(ApprovalAssignment.request_id == request.id)
            .order_by(ApprovalAssignment.step_number, ApprovalAssignment.created_at)
        )
    )
    events = list(
        db.scalars(
            select(ApprovalEvent)
            .where(ApprovalEvent.request_id == request.id)
            .order_by(ApprovalEvent.created_at, ApprovalEvent.id)
        )
    )
    return assignments, events


def queue(db: Session, tenant_id, user_id, limit: int = 50, offset: int = 0):
    """Pending requests waiting for this person's decision, oldest first."""
    membership = _membership(db, tenant_id, user_id)
    if membership is None:
        return []
    limit, offset = max(1, min(limit, 200)), max(0, offset)
    stmt = (
        select(ApprovalRequest, Document)
        .join(Document, Document.id == ApprovalRequest.document_id)
        .join(
            ApprovalAssignment,
            (ApprovalAssignment.request_id == ApprovalRequest.id)
            & (ApprovalAssignment.step_number == ApprovalRequest.current_step),
        )
        .where(
            ApprovalRequest.tenant_id == tenant_id,
            ApprovalRequest.status == "pending",
            ApprovalAssignment.membership_id == membership.id,
            ApprovalRequest.submitted_by_user_id != user_id,
        )
        .order_by(ApprovalRequest.submitted_at, ApprovalRequest.id)
        .limit(limit)
        .offset(offset)
    )
    return db.execute(stmt).all()


def pending_overview(db: Session, tenant_id, limit: int = 50, offset: int = 0):
    """All pending requests with how many reviewers are assigned now (privileged view)."""
    limit, offset = max(1, min(limit, 200)), max(0, offset)
    assigned = (
        select(func.count(ApprovalAssignment.id))
        .where(
            ApprovalAssignment.request_id == ApprovalRequest.id,
            ApprovalAssignment.step_number == ApprovalRequest.current_step,
        )
        .scalar_subquery()
    )
    stmt = (
        select(ApprovalRequest, Document, assigned)
        .join(Document, Document.id == ApprovalRequest.document_id)
        .where(ApprovalRequest.tenant_id == tenant_id, ApprovalRequest.status == "pending")
        .order_by(ApprovalRequest.submitted_at, ApprovalRequest.id)
        .limit(limit)
        .offset(offset)
    )
    return db.execute(stmt).all()


def document_history(db: Session, tenant_id, user_id, document_id, permissions):
    document = db.get(Document, document_id)
    if document is None or document.tenant_id != tenant_id:
        raise access.Denied("missing")
    requests = list(
        db.scalars(
            select(ApprovalRequest)
            .where(ApprovalRequest.document_id == document_id)
            .order_by(ApprovalRequest.submitted_at.desc(), ApprovalRequest.id)
        )
    )
    visible = [r for r in requests if can_view_request(db, tenant_id, user_id, r, permissions)]
    if requests and not visible:
        raise access.Denied("not_assigned")
    return visible


__all__ = ["Conflict", "Forbidden", "Invalid", "NotFound"]
