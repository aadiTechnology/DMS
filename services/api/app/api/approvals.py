import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.api.documents import _authorize, _index_content
from app.core.tenancy import Principal, get_principal, get_tenant_db
from app.db.tenant_session import tenant_session
from app.services import access, approvals, audit, rbac
from app.services.org import Conflict, Invalid, NotFound

router = APIRouter(prefix="/api/v1", tags=["approvals"])


class RequestOut(BaseModel):
    id: uuid.UUID
    document_id: uuid.UUID
    version_number: int
    status: str
    current_step: int
    total_steps: int
    submitted_by_user_id: uuid.UUID
    submitted_at: datetime
    decided_at: datetime | None
    resubmission_of: uuid.UUID | None


class QueueItem(RequestOut):
    title: str
    classification: str
    reviewers_on_step: int | None = None


class AssignmentOut(BaseModel):
    step_number: int
    membership_id: uuid.UUID


class EventOut(BaseModel):
    id: uuid.UUID
    step_number: int | None
    actor_user_id: uuid.UUID | None
    action: str
    comment: str | None
    privileged: bool
    created_at: datetime


class RequestDetail(RequestOut):
    steps: list[dict[str, Any]]
    assignments: list[AssignmentOut]
    events: list[EventOut]
    can_decide: bool


def _request_out(r) -> dict[str, Any]:
    return {
        "id": r.id,
        "document_id": r.document_id,
        "version_number": r.version_number,
        "status": r.status,
        "current_step": r.current_step,
        "total_steps": len(r.steps),
        "submitted_by_user_id": r.submitted_by_user_id,
        "submitted_at": r.submitted_at,
        "decided_at": r.decided_at,
        "resubmission_of": r.resubmission_of,
    }


def _detail(db: Session, principal: Principal, request, perms: set[str]) -> RequestDetail:
    assignments, events = approvals.request_parts(db, request)
    membership = approvals._membership(db, principal.tenant_id, principal.user_id)
    mine = membership is not None and any(
        a.membership_id == membership.id and a.step_number == request.current_step
        for a in assignments
    )
    can_decide = (
        request.status == "pending"
        and request.submitted_by_user_id != principal.user_id
        and (mine or access.PRIVILEGE in perms)
        and ("document.approve" in perms or "document.reject" in perms)
    )
    return RequestDetail(
        **_request_out(request), steps=request.steps,
        assignments=[AssignmentOut(step_number=a.step_number, membership_id=a.membership_id) for a in assignments],
        events=[
            EventOut(id=e.id, step_number=e.step_number, actor_user_id=e.actor_user_id, action=e.action,
                     comment=e.comment, privileged=e.privileged, created_at=e.created_at)
            for e in events
        ],
        can_decide=can_decide,
    )  # fmt: skip


def _refuse(principal: Principal, request_id, action: str, denied: access.Denied) -> HTTPException:
    """Audit the refusal in its own transaction; answer without revealing the request exists."""
    with tenant_session(principal.tenant_id) as audit_db:
        audit.record(
            audit_db, tenant_id=principal.tenant_id, actor_user_id=principal.user_id,
            action="approval.access_denied", resource_type="approval_request",
            resource_id=request_id, outcome="denied", details={"access": action, "reason": denied.reason},
        )  # fmt: skip
    if denied.reason == "role_lacks_permission":
        return HTTPException(status.HTTP_403_FORBIDDEN, detail="Permission denied")
    return HTTPException(status.HTTP_404_NOT_FOUND, detail="request not found")


def _mapped(exc: Exception) -> HTTPException:
    if isinstance(exc, approvals.Forbidden):
        return HTTPException(status.HTTP_403_FORBIDDEN, detail=str(exc))
    if isinstance(exc, NotFound):
        return HTTPException(status.HTTP_404_NOT_FOUND, detail=f"{exc} not found")
    if isinstance(exc, Conflict):
        return HTTPException(status.HTTP_409_CONFLICT, detail=str(exc))
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc))


_HANDLED = (approvals.Forbidden, NotFound, Conflict, Invalid)


# ---- queue and reading ------------------------------------------------------------------


@router.get("/approvals/queue", response_model=list[QueueItem])
def my_queue(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_tenant_db),
):
    """Reviews waiting for your decision, oldest first."""
    rows = approvals.queue(db, principal.tenant_id, principal.user_id, limit, offset)
    return [
        QueueItem(**_request_out(r), title=d.title, classification=d.classification)
        for r, d in rows
    ]


@router.get("/approvals/pending", response_model=list[QueueItem])
def pending_overview(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_tenant_db),
):
    """Every pending review in the organization, including ones with nobody assigned. Needs the
    audited administrator privilege."""
    perms = rbac.effective_permissions(db, principal.tenant_id, principal.user_id)
    if access.PRIVILEGE not in perms:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Permission denied")
    rows = approvals.pending_overview(db, principal.tenant_id, limit, offset)
    audit.record(
        db, tenant_id=principal.tenant_id, actor_user_id=principal.user_id,
        action="approval.privileged_overview", resource_type="approval_request", privileged=True,
        details={"count": len(rows)},
    )  # fmt: skip
    return [
        QueueItem(
            **_request_out(r), title=d.title, classification=d.classification, reviewers_on_step=n
        )
        for r, d, n in rows
    ]


@router.get("/approvals/{request_id}", response_model=RequestDetail)
def get_request(
    request_id: uuid.UUID,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_tenant_db),
):
    """One review with its steps, reviewers and full history. Visible to the submitter, the
    document owner, assigned reviewers and privileged administrators."""
    perms = rbac.effective_permissions(db, principal.tenant_id, principal.user_id)
    try:
        request = approvals.get_request(
            db, principal.tenant_id, principal.user_id, request_id, perms
        )
    except access.Denied as denied:
        raise _refuse(principal, request_id, "view", denied) from None
    return _detail(db, principal, request, perms)


@router.get("/documents/{document_id}/approvals", response_model=list[RequestDetail])
def document_approvals(
    document_id: uuid.UUID,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_tenant_db),
):
    """Review history of a document (every submission and its decisions)."""
    perms = rbac.effective_permissions(db, principal.tenant_id, principal.user_id)
    _authorize(principal, db, document_id, "view_metadata", perms)
    try:
        requests = approvals.document_history(
            db, principal.tenant_id, principal.user_id, document_id, perms
        )
    except access.Denied as denied:
        raise _refuse(principal, document_id, "history", denied) from None
    return [_detail(db, principal, r, perms) for r in requests]


# ---- deciding ---------------------------------------------------------------------------


class ApproveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    comment: str | None = Field(None, max_length=1000)


class RejectIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(
        min_length=1, max_length=1000, description="Required: shown to the submitter"
    )


class CommentIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    comment: str = Field(min_length=1, max_length=1000)


def _decide(principal, db, request_id, action, comment, background) -> RequestDetail:
    perms = rbac.effective_permissions(db, principal.tenant_id, principal.user_id)
    try:
        request, info = approvals.decide(
            db, principal.tenant_id, principal.user_id, request_id, action, comment, perms
        )
    except access.Denied as denied:
        raise _refuse(principal, request_id, action, denied) from None
    except _HANDLED as exc:
        raise _mapped(exc) from None
    if info["changed"]:  # a new version is now the one readers see: extract its text
        background.add_task(_index_content, principal.tenant_id, info["document_id"])
    return _detail(db, principal, request, perms)


@router.post("/approvals/{request_id}/approve", response_model=RequestDetail)
def approve(
    request_id: uuid.UUID,
    background: BackgroundTasks,
    body: ApproveIn | None = None,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_tenant_db),
):
    """Approve the current step; the last step releases the version to readers. You cannot
    decide your own submission. Repeating the call is harmless."""
    return _decide(principal, db, request_id, "approve", body.comment if body else None, background)


@router.post("/approvals/{request_id}/reject", response_model=RequestDetail)
def reject(
    request_id: uuid.UUID,
    body: RejectIn,
    background: BackgroundTasks,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_tenant_db),
):
    """Reject with a mandatory reason. The submitter can correct and resubmit."""
    return _decide(principal, db, request_id, "reject", body.reason, background)


@router.post(
    "/approvals/{request_id}/comments",
    response_model=RequestDetail,
    status_code=status.HTTP_201_CREATED,
)
def comment(
    request_id: uuid.UUID,
    body: CommentIn,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_tenant_db),
):
    perms = rbac.effective_permissions(db, principal.tenant_id, principal.user_id)
    try:
        request = approvals.add_comment(
            db, principal.tenant_id, principal.user_id, request_id, body.comment, perms
        )
    except access.Denied as denied:
        raise _refuse(principal, request_id, "comment", denied) from None
    except _HANDLED as exc:
        raise _mapped(exc) from None
    return _detail(db, principal, request, perms)


@router.post(
    "/documents/{document_id}/resubmit",
    response_model=RequestDetail,
    status_code=status.HTTP_201_CREATED,
)
def resubmit(
    document_id: uuid.UUID,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_tenant_db),
):
    """After a rejection (and any corrections), send the same version for review again.
    Earlier decisions stay on record."""
    perms = rbac.effective_permissions(db, principal.tenant_id, principal.user_id)
    if "document.upload" not in perms:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Permission denied")
    try:
        request = approvals.resubmit(db, principal.tenant_id, principal.user_id, document_id, perms)
    except access.Denied as denied:
        with tenant_session(principal.tenant_id) as audit_db:
            access.record_denied(
                audit_db,
                principal.tenant_id,
                principal.user_id,
                document_id,
                "resubmit",
                denied.reason,
            )
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="document not found") from None
    except _HANDLED as exc:
        raise _mapped(exc) from None
    return _detail(db, principal, request, perms)
