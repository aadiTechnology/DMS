import uuid
from datetime import date, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.api.documents import _authorize
from app.core.tenancy import Principal, get_principal, get_tenant_db
from app.db.tenant_session import tenant_session
from app.services import access, audit, lifecycle, rbac
from app.services.approvals import Forbidden
from app.services.org import Conflict, Invalid, NotFound
from app.storage import get_storage
from app.storage.base import StorageError

router = APIRouter(prefix="/api/v1", tags=["lifecycle"])


class ReasonIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=500)


class OptionalReasonIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str | None = Field(None, max_length=500)


class HoldOut(BaseModel):
    reason: str
    placed_by_user_id: uuid.UUID
    placed_at: datetime
    released_at: datetime | None
    release_reason: str | None


class DeletionOut(BaseModel):
    id: uuid.UUID
    document_id: uuid.UUID
    status: str
    reason: str
    requested_by_user_id: uuid.UUID
    requested_at: datetime
    decision_reason: str | None
    decided_at: datetime | None


class DeletionItem(DeletionOut):
    title: str
    classification: str


class LifecycleOut(BaseModel):
    document_id: uuid.UUID
    lifecycle_state: str
    retention_until: date | None
    review_due_on: date | None
    archived_at: datetime | None
    legal_hold: HoldOut | None
    deletion_request: DeletionOut | None
    deletion_blockers: list[dict[str, Any]]


class DueItem(BaseModel):
    document_id: uuid.UUID
    title: str
    classification: str
    lifecycle_state: str
    due: list[dict[str, str]]


def _hold_out(h) -> HoldOut | None:
    if h is None:
        return None
    return HoldOut(
        reason=h.reason, placed_by_user_id=h.placed_by_user_id, placed_at=h.placed_at,
        released_at=h.released_at, release_reason=h.release_reason,
    )  # fmt: skip


def _request_out(r) -> DeletionOut:
    return DeletionOut(
        id=r.id, document_id=r.document_id, status=r.status, reason=r.reason,
        requested_by_user_id=r.requested_by_user_id, requested_at=r.requested_at,
        decision_reason=r.decision_reason, decided_at=r.decided_at,
    )  # fmt: skip


def _refuse(principal: Principal, document_id, action: str, denied: access.Denied):
    with tenant_session(principal.tenant_id) as audit_db:
        access.record_denied(
            audit_db, principal.tenant_id, principal.user_id, document_id, action, denied.reason
        )
    return HTTPException(status.HTTP_404_NOT_FOUND, detail="document not found")


def _mapped(exc: Exception) -> HTTPException:
    if isinstance(exc, Forbidden):
        return HTTPException(status.HTTP_403_FORBIDDEN, detail=str(exc))
    if isinstance(exc, NotFound):
        return HTTPException(status.HTTP_404_NOT_FOUND, detail=f"{exc} not found")
    if isinstance(exc, Conflict):
        return HTTPException(status.HTTP_409_CONFLICT, detail=str(exc))
    if isinstance(exc, StorageError):
        return HTTPException(
            status.HTTP_502_BAD_GATEWAY, detail="Storage is unavailable; nothing was deleted"
        )
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc))


_HANDLED = (Forbidden, NotFound, Conflict, Invalid, StorageError)


def _need(perms: set[str], code: str) -> None:
    if code not in perms:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Permission denied")


def _load(principal, db, document_id, code, action="view_metadata"):
    perms = rbac.effective_permissions(db, principal.tenant_id, principal.user_id)
    _need(perms, code)
    document, _ = _authorize(principal, db, document_id, action, perms)
    return document, perms


# ---- status -----------------------------------------------------------------------------


@router.get("/documents/{document_id}/lifecycle", response_model=LifecycleOut)
def get_lifecycle(
    document_id: uuid.UUID,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_tenant_db),
):
    """Retention and review dates, archive state, legal hold and any pending deletion request."""
    perms = rbac.effective_permissions(db, principal.tenant_id, principal.user_id)
    document, _ = _authorize(principal, db, document_id, "view_metadata", perms)
    pending = lifecycle.pending_request(db, document.id)
    return LifecycleOut(
        document_id=document.id, lifecycle_state=document.lifecycle_state,
        retention_until=document.retention_until, review_due_on=document.review_due_on,
        archived_at=document.archived_at, legal_hold=_hold_out(lifecycle.active_hold(db, document.id)),
        deletion_request=_request_out(pending) if pending else None,
        deletion_blockers=lifecycle.blockers(db, document),
    )  # fmt: skip


# ---- archive ----------------------------------------------------------------------------


def _change(principal, db, document_id, code, fn):
    document, perms = _load(principal, db, document_id, code)
    try:
        fn(db, principal.tenant_id, principal.user_id, document, perms)
    except access.Denied as denied:
        raise _refuse(principal, document_id, code, denied) from None
    except _HANDLED as exc:
        raise _mapped(exc) from None
    return get_lifecycle(document_id, principal, db)


@router.post("/documents/{document_id}/archive", response_model=LifecycleOut)
def archive(
    document_id: uuid.UUID,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_tenant_db),
):
    """Archive a released document: it stays readable but closed to new versions and edits."""
    return _change(principal, db, document_id, "document.archive", lifecycle.archive)


@router.post("/documents/{document_id}/unarchive", response_model=LifecycleOut)
def unarchive(
    document_id: uuid.UUID,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_tenant_db),
):
    return _change(principal, db, document_id, "document.restore", lifecycle.unarchive)


# ---- legal hold -------------------------------------------------------------------------


@router.post(
    "/documents/{document_id}/legal-hold",
    response_model=LifecycleOut,
    status_code=status.HTTP_201_CREATED,
)
def place_hold(
    document_id: uuid.UUID,
    body: ReasonIn,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_tenant_db),
):
    """Needs `document.approve_delete`. Blocks deletion until released."""
    document, _ = _load(principal, db, document_id, "document.approve_delete")
    try:
        lifecycle.place_hold(db, principal.tenant_id, principal.user_id, document, body.reason)
    except _HANDLED as exc:
        raise _mapped(exc) from None
    return get_lifecycle(document_id, principal, db)


@router.delete("/documents/{document_id}/legal-hold", response_model=LifecycleOut)
def release_hold(
    document_id: uuid.UUID,
    body: ReasonIn,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_tenant_db),
):
    document, _ = _load(principal, db, document_id, "document.approve_delete")
    try:
        lifecycle.release_hold(db, principal.tenant_id, principal.user_id, document, body.reason)
    except _HANDLED as exc:
        raise _mapped(exc) from None
    return get_lifecycle(document_id, principal, db)


# ---- deletion ---------------------------------------------------------------------------


@router.post(
    "/documents/{document_id}/deletion-requests",
    response_model=DeletionOut,
    status_code=status.HTTP_201_CREATED,
)
def request_deletion(
    document_id: uuid.UUID,
    body: ReasonIn,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_tenant_db),
):
    """Ask for permanent deletion. Refused while a legal hold or retention period applies."""
    document, perms = _load(principal, db, document_id, "document.request_delete")
    try:
        request = lifecycle.request_deletion(
            db, principal.tenant_id, principal.user_id, document, perms, body.reason
        )
    except access.Denied as denied:
        raise _refuse(principal, document_id, "request_delete", denied) from None
    except _HANDLED as exc:
        raise _mapped(exc) from None
    return _request_out(request)


@router.get("/deletion-requests", response_model=list[DeletionItem])
def pending_deletions(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_tenant_db),
):
    """Deletion requests waiting for approval (needs `document.approve_delete`)."""
    perms = rbac.effective_permissions(db, principal.tenant_id, principal.user_id)
    _need(perms, "document.approve_delete")
    rows = lifecycle.pending_requests(db, principal.tenant_id, principal.user_id, limit, offset)
    return [
        DeletionItem(**_request_out(r).model_dump(), title=d.title, classification=d.classification)
        for r, d in rows
    ]


def _decide(principal, db, request_id, *, approve: bool, reason: str | None) -> DeletionOut:
    perms = rbac.effective_permissions(db, principal.tenant_id, principal.user_id)
    _need(perms, "document.approve_delete")
    try:
        request = lifecycle.get_request(db, principal.tenant_id, request_id)
        _authorize(principal, db, request.document_id, "view_metadata", perms)
        request = lifecycle.decide_deletion(
            db, principal.tenant_id, principal.user_id, request_id,
            approve=approve, reason=reason, storage=get_storage(),
        )  # fmt: skip
    except _HANDLED as exc:
        raise _mapped(exc) from None
    return _request_out(request)


@router.post("/deletion-requests/{request_id}/approve", response_model=DeletionOut)
def approve_deletion(
    request_id: uuid.UUID,
    body: OptionalReasonIn | None = None,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_tenant_db),
):
    """Approve: every stored file is removed and the document becomes a tombstone. Not for
    your own request. Re-checks legal hold and retention at this moment."""
    return _decide(principal, db, request_id, approve=True, reason=body.reason if body else None)


@router.post("/deletion-requests/{request_id}/reject", response_model=DeletionOut)
def reject_deletion(
    request_id: uuid.UUID,
    body: ReasonIn,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_tenant_db),
):
    return _decide(principal, db, request_id, approve=False, reason=body.reason)


@router.post("/deletion-requests/{request_id}/cancel", response_model=DeletionOut)
def cancel_deletion(
    request_id: uuid.UUID,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_tenant_db),
):
    """The requester withdraws a pending request."""
    try:
        request = lifecycle.cancel_deletion(db, principal.tenant_id, principal.user_id, request_id)
    except _HANDLED as exc:
        raise _mapped(exc) from None
    return _request_out(request)


# ---- reminders --------------------------------------------------------------------------


@router.get("/lifecycle/due", response_model=list[DueItem])
def due_documents(
    days: int = Query(30, ge=0, le=365),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_tenant_db),
):
    """Documents you can see whose retention ends or review falls due within `days` (or is
    already past). Needs `document.archive`. The notification sprint sends these as reminders."""
    perms = rbac.effective_permissions(db, principal.tenant_id, principal.user_id)
    _need(perms, "document.archive")
    rows = lifecycle.due(db, principal.tenant_id, principal.user_id, days, limit, offset)
    if access.PRIVILEGE in perms and rows:
        audit.record(
            db, tenant_id=principal.tenant_id, actor_user_id=principal.user_id,
            action="lifecycle.privileged_due_list", resource_type="document", privileged=True,
            details={"count": len(rows)},
        )  # fmt: skip
    return [
        DueItem(
            document_id=d.id,
            title=d.title,
            classification=d.classification,
            lifecycle_state=d.lifecycle_state,
            due=lifecycle.due_kinds(d, days),
        )
        for d in rows
    ]
