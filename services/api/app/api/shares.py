import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.api.documents import _authorize
from app.core.tenancy import Principal, get_principal, get_tenant_db
from app.db.tenant_session import tenant_session
from app.services import access, rbac, sharing
from app.services.org import Conflict, Invalid, NotFound

router = APIRouter(prefix="/api/v1", tags=["sharing"])


class ShareIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    grantee_membership_id: uuid.UUID
    can_view: bool = True
    can_download: bool = False
    expires_at: datetime | None = None


class ShareOut(BaseModel):
    document_id: uuid.UUID
    grantee_membership_id: uuid.UUID
    grantee_name: str | None = None
    can_view: bool
    can_download: bool
    expires_at: datetime | None
    created_at: datetime
    revoked_at: datetime | None


class SharedDocumentOut(ShareOut):
    title: str
    classification: str


def _out(grant, name=None) -> ShareOut:
    return ShareOut(
        document_id=grant.document_id, grantee_membership_id=grant.grantee_membership_id,
        grantee_name=name, can_view=grant.can_view, can_download=grant.can_download,
        expires_at=grant.expires_at, created_at=grant.created_at, revoked_at=grant.revoked_at,
    )  # fmt: skip


def _refuse(principal: Principal, document_id, action: str, denied: access.Denied):
    with tenant_session(principal.tenant_id) as audit_db:
        access.record_denied(
            audit_db, principal.tenant_id, principal.user_id, document_id, action, denied.reason
        )
    return HTTPException(status.HTTP_404_NOT_FOUND, detail="document not found")


def _mapped(exc: Exception) -> HTTPException:
    if isinstance(exc, NotFound):
        return HTTPException(status.HTTP_404_NOT_FOUND, detail=f"{exc} not found")
    if isinstance(exc, Conflict):
        return HTTPException(status.HTTP_409_CONFLICT, detail=str(exc))
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc))


def _managing(principal, db, document_id, action) -> tuple:
    """Load the document for someone who may share it; everyone else gets 'not found'."""
    perms = rbac.effective_permissions(db, principal.tenant_id, principal.user_id)
    if "document.share" not in perms:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Permission denied")
    document, _ = _authorize(principal, db, document_id, "view_metadata", perms)
    return document, perms


@router.post(
    "/documents/{document_id}/shares", response_model=ShareOut, status_code=status.HTTP_201_CREATED
)
def create_share(
    document_id: uuid.UUID,
    body: ShareIn,
    response: Response,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_tenant_db),
):
    """Share with a colleague (view, and optionally download). Sharing again with the same
    person updates the share (200)."""
    document, perms = _managing(principal, db, document_id, "share")
    try:
        grant, created = sharing.share(
            db, principal.tenant_id, principal.user_id, document, perms,
            body.grantee_membership_id, can_view=body.can_view, can_download=body.can_download,
            expires_at=body.expires_at,
        )  # fmt: skip
    except access.Denied as denied:
        raise _refuse(principal, document_id, "share", denied) from None
    except (NotFound, Conflict, Invalid) as exc:
        raise _mapped(exc) from None
    if not created:
        response.status_code = status.HTTP_200_OK
    return _out(grant)


@router.delete("/documents/{document_id}/shares/{grantee_membership_id}", response_model=ShareOut)
def revoke_share(
    document_id: uuid.UUID,
    grantee_membership_id: uuid.UUID,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_tenant_db),
):
    """Stop sharing. Takes effect immediately for every version of the document."""
    document, perms = _managing(principal, db, document_id, "share")
    try:
        grant = sharing.revoke(
            db, principal.tenant_id, principal.user_id, document, perms, grantee_membership_id
        )
    except access.Denied as denied:
        raise _refuse(principal, document_id, "share", denied) from None
    except NotFound as exc:
        raise _mapped(exc) from None
    return _out(grant)


@router.get("/documents/{document_id}/shares", response_model=list[ShareOut])
def list_document_shares(
    document_id: uuid.UUID,
    history: bool = False,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_tenant_db),
):
    """Who this document is shared with (those who may manage sharing). `history=true` adds
    expired and revoked shares."""
    document, perms = _managing(principal, db, document_id, "share")
    decision = access.can_modify(db, principal.tenant_id, principal.user_id, document, perms)
    if not decision.allowed:
        raise _refuse(principal, document_id, "share", access.Denied(decision.reason))
    rows = sharing.for_document(db, principal.tenant_id, document_id, include_history=history)
    return [_out(g, name) for g, name in rows]


@router.get("/shares/with-me", response_model=list[SharedDocumentOut])
def shared_with_me(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_tenant_db),
):
    rows = sharing.shared_with_me(db, principal.tenant_id, principal.user_id, limit, offset)
    return [
        SharedDocumentOut(**_out(g).model_dump(), title=d.title, classification=d.classification)
        for g, d in rows
    ]


@router.get("/shares/by-me", response_model=list[SharedDocumentOut])
def shared_by_me(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_tenant_db),
):
    rows = sharing.shared_by_me(db, principal.tenant_id, principal.user_id, limit, offset)
    return [
        SharedDocumentOut(**_out(g).model_dump(), title=d.title, classification=d.classification)
        for g, d in rows
    ]
