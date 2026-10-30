import logging
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session
from starlette.requests import ClientDisconnect

from app.core.config import get_settings
from app.core.tenancy import (
    Principal,
    check_permission,
    get_principal,
    get_tenant_db,
    require_permission,
)
from app.db.tenant_session import tenant_session
from app.services import uploads
from app.services.filetypes import FileRejected, check_declared_type, detect, extension_of
from app.services.metadata import MetadataInvalid
from app.services.org import Conflict, Invalid, NotFound
from app.services.scanner import build_scanner
from app.storage import get_storage
from app.storage.base import ObjectExists, StorageError

logger = logging.getLogger("dms.documents")
router = APIRouter(prefix="/api/v1/documents", tags=["documents"])
can_upload = require_permission("document.upload")


def _http(exc: Exception) -> HTTPException:
    if isinstance(exc, FileRejected):
        return HTTPException(exc.status, detail={"code": exc.code, "message": exc.message})
    if isinstance(exc, MetadataInvalid):
        return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail={"fields": exc.errors})
    if isinstance(exc, NotFound):
        return HTTPException(status.HTTP_404_NOT_FOUND, detail=f"{exc} not found")
    if isinstance(exc, Conflict):
        return HTTPException(status.HTTP_409_CONFLICT, detail=str(exc))
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc))


# ---- schemas ----------------------------------------------------------------------------


class UploadIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category_id: uuid.UUID
    filename: str = Field(min_length=1, max_length=300)
    content_type: str = Field(min_length=3, max_length=150)
    size_bytes: int = Field(gt=0)
    title: str | None = Field(None, max_length=300)
    classification: str | None = None
    owner_membership_id: uuid.UUID | None = None
    associations: dict[str, list[uuid.UUID]] = {}
    tag_ids: list[uuid.UUID] = []
    metadata: dict[str, Any] = {}
    comment: str | None = Field(None, max_length=300)


class UploadSessionOut(BaseModel):
    document_id: uuid.UUID
    version_id: uuid.UUID
    upload_url: str
    expires_at: datetime
    max_bytes: int
    status: str


class UploadResultOut(BaseModel):
    document_id: uuid.UUID
    version_id: uuid.UUID
    status: str
    lifecycle_state: str
    content_type: str | None
    size_bytes: int | None
    sha256: str | None


class VersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    version_number: int
    status: str
    original_filename: str
    content_type: str | None
    size_bytes: int | None
    sha256: str | None
    scan_status: str
    reject_reason: str | None
    created_at: datetime


class DocumentOut(BaseModel):
    id: uuid.UUID
    title: str
    category_id: uuid.UUID
    category_version_number: int
    classification: str
    lifecycle_state: str
    owner_membership_id: uuid.UUID
    current_version_number: int | None
    metadata: dict[str, Any]
    associations: dict[str, list[uuid.UUID]]
    tag_ids: list[uuid.UUID]
    versions: list[VersionOut]
    created_at: datetime


def _session_out(document, version, *, settings) -> UploadSessionOut:
    return UploadSessionOut(
        document_id=document.id, version_id=version.id,
        upload_url=f"/api/v1/documents/uploads/{version.id}/content",
        expires_at=version.expires_at, max_bytes=settings.DMS_MAX_UPLOAD_BYTES, status=version.status,
    )  # fmt: skip


def _result_out(document, version) -> UploadResultOut:
    return UploadResultOut(
        document_id=document.id, version_id=version.id, status=version.status,
        lifecycle_state=document.lifecycle_state, content_type=version.content_type,
        size_bytes=version.size_bytes, sha256=version.sha256,
    )  # fmt: skip


# ---- reserve ----------------------------------------------------------------------------


@router.post("/uploads", response_model=UploadSessionOut, status_code=status.HTTP_201_CREATED)
def create_upload(
    body: UploadIn,
    response: Response,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    principal: Principal = Depends(can_upload),
    db: Session = Depends(get_tenant_db),
):
    """Step 1: validate everything (category rules, metadata, organization associations, file
    name/type/size) and reserve the upload. No bytes are sent yet. Any employee may upload; that
    never grants read access to other documents."""
    settings = get_settings()
    try:
        document, version, created = uploads.create_upload(
            db, settings, principal.tenant_id, principal.user_id,
            uploads.UploadRequest(idempotency_key=idempotency_key, **body.model_dump()),
        )  # fmt: skip
    except (FileRejected, MetadataInvalid, Invalid, Conflict, NotFound) as exc:
        raise _http(exc) from None
    if not created:
        response.status_code = status.HTTP_200_OK
    return _session_out(document, version, settings=settings)


# ---- receive (streamed; no database transaction is open while bytes arrive) -------------


def _begin(principal: Principal, version_id) -> uploads.ReceiveOutcome:
    try:
        with tenant_session(principal.tenant_id) as db:
            return uploads.begin_receive(db, principal.tenant_id, principal.user_id, version_id)
    except (NotFound, Conflict) as exc:
        raise _http(exc) from None


def _complete(principal: Principal, version_id, **fields):
    with tenant_session(principal.tenant_id) as db:
        version = uploads.finalize_available(
            db, principal.tenant_id, principal.user_id, version_id, **fields
        )
        return version, db.get(uploads.Document, version.document_id)


def _block(principal: Principal, version_id, **fields) -> None:
    with tenant_session(principal.tenant_id) as db:
        uploads.finalize_blocked(db, principal.tenant_id, principal.user_id, version_id, **fields)


def _retry_later(principal: Principal, version_id, reason: str) -> None:
    try:
        with tenant_session(principal.tenant_id) as db:
            uploads.revert_to_pending(
                db, principal.tenant_id, principal.user_id, version_id, reason
            )
    except Exception:
        logger.exception("could not reopen upload %s after %s", version_id, reason)


def _validate_and_scan(ctx, spool, settings):
    ext = extension_of(ctx.filename)
    check_declared_type(ext, ctx.declared_content_type)
    content_type = detect(ext, spool.path)
    return content_type, build_scanner(settings).scan(spool.path)


@router.put("/uploads/{version_id}/content", response_model=UploadResultOut)
async def upload_content(
    version_id: uuid.UUID, request: Request, principal: Principal = Depends(get_principal)
):
    """Step 2: send the raw file bytes as the request body (Content-Length required). The server
    streams them to temporary disk, hashes once, checks the real file type, scans for malware,
    and only then stores the file. Repeating the call for a finished upload is harmless."""
    settings = get_settings()
    await run_in_threadpool(check_permission, principal, "document.upload")
    outcome = await run_in_threadpool(_begin, principal, version_id)
    if outcome.kind == "done":
        return _result_out(outcome.document, outcome.version)
    if outcome.kind == "expired":
        raise HTTPException(status.HTTP_410_GONE, detail="This upload reservation has expired")
    ctx = outcome.context

    spool = uploads.Spool(settings.UPLOAD_TMP_DIR, ctx.declared_size_bytes)
    try:
        declared = request.headers.get("content-length")
        if declared is None or int(declared) != ctx.declared_size_bytes:
            raise FileRejected("size_mismatch", "Content-Length must equal the declared size", 400)
        async for chunk in request.stream():
            spool.write(chunk)
        sha1, sha256 = spool.finish()
        content_type, scan = await run_in_threadpool(_validate_and_scan, ctx, spool, settings)
        if scan.status == "infected":
            await run_in_threadpool(
                _block, principal, version_id, status="quarantined", reason="malware_detected",
                scan_status="infected", scan_detail=scan.detail,
            )  # fmt: skip
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={"code": "malware_detected", "message": "The file failed the security scan"},
            )
        if scan.status != "clean":
            await run_in_threadpool(_retry_later, principal, version_id, "scan_unavailable")
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={"code": "scan_unavailable", "message": "Security scan unavailable; retry"},
            )
        stored = await run_in_threadpool(
            lambda: get_storage().put_file(
                ctx.object_key, spool.path, content_type=content_type, sha1=sha1, sha256=sha256
            )
        )
        version, document = await run_in_threadpool(
            lambda: _complete(
                principal,
                version_id,
                content_type=content_type,
                size_bytes=spool.size,
                sha1=sha1,
                sha256=sha256,
                storage_file_id=stored.file_id,
                approval_required=ctx.approval_required,
            )
        )
        return _result_out(document, version)
    except FileRejected as exc:
        await run_in_threadpool(
            _block, principal, version_id, status="rejected", reason=exc.code, scan_status="pending"
        )
        raise _http(exc) from None
    except ClientDisconnect:
        await run_in_threadpool(_retry_later, principal, version_id, "client_disconnected")
        raise
    except ObjectExists:
        await run_in_threadpool(_retry_later, principal, version_id, "object_exists")
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail="Stored object already exists"
        ) from None
    except StorageError:
        await run_in_threadpool(_retry_later, principal, version_id, "storage_error")
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            detail={"code": "storage_unavailable", "message": "Storage error; retry"},
        ) from None
    finally:
        spool.cleanup()


# ---- read own ---------------------------------------------------------------------------


def _document_out(document, versions, assoc, tag_ids) -> DocumentOut:
    grouped: dict[str, list[uuid.UUID]] = {}
    for a in assoc:
        grouped.setdefault(a.dimension, []).append(a.ref_id)
    return DocumentOut(
        id=document.id, title=document.title, category_id=document.category_id,
        category_version_number=document.category_version_number,
        classification=document.classification, lifecycle_state=document.lifecycle_state,
        owner_membership_id=document.owner_membership_id,
        current_version_number=document.current_version_number,
        metadata=document.metadata_values, associations=grouped, tag_ids=tag_ids,
        versions=[VersionOut.model_validate(v) for v in versions], created_at=document.created_at,
    )  # fmt: skip


@router.get("/mine", response_model=list[DocumentOut])
def my_documents(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_tenant_db),
):
    """Documents you uploaded or own, including pending ones. Wider visibility (search, shares,
    department scope, reviewers) arrives with the document policy engine."""
    docs = uploads.list_my_documents(db, principal.tenant_id, principal.user_id, limit, offset)
    return [
        _document_out(*uploads.get_document(db, principal.tenant_id, principal.user_id, d.id))
        for d in docs
    ]


@router.get("/{document_id}", response_model=DocumentOut)
def get_document(
    document_id: uuid.UUID,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_tenant_db),
):
    try:
        return _document_out(
            *uploads.get_document(db, principal.tenant_id, principal.user_id, document_id)
        )
    except NotFound as exc:
        raise _http(exc) from None
