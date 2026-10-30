import logging
import uuid
from typing import Any

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    Header,
    HTTPException,
    Response,
    status,
)
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.api.documents import (
    UploadResultOut,
    UploadSessionOut,
    VersionOut,
    _authorize,
    _index_content,
    _result_out,
    _session_out,
)
from app.core.config import get_settings
from app.core.tenancy import (
    Principal,
    check_permission,
    get_principal,
    get_tenant_db,
    require_permission,
)
from app.db.tenant_session import tenant_session
from app.services import access, rbac, uploads, versions
from app.services.filetypes import FileRejected
from app.services.metadata import MetadataInvalid
from app.services.org import Conflict, Invalid, NotFound
from app.storage import get_storage
from app.storage.base import ObjectExists, ObjectNotFound, StorageError

logger = logging.getLogger("dms.versions")
router = APIRouter(prefix="/api/v1/documents", tags=["versions"])


def _denied(principal: Principal, document_id, action: str, denied: access.Denied) -> HTTPException:
    """Audit a refusal in its own transaction and answer without revealing existence."""
    with tenant_session(principal.tenant_id) as audit_db:
        access.record_denied(
            audit_db, principal.tenant_id, principal.user_id, document_id, action, denied.reason
        )
    return HTTPException(status.HTTP_404_NOT_FOUND, detail="document not found")


def _mapped(exc: Exception) -> HTTPException:
    if isinstance(exc, versions.StaleVersion):
        detail: dict[str, Any] = {"code": "stale", "message": str(exc)}
        if exc.latest_version is not None:
            detail["latest_version"] = exc.latest_version
        if exc.row_version is not None:
            detail["row_version"] = exc.row_version
        return HTTPException(status.HTTP_409_CONFLICT, detail=detail)
    if isinstance(exc, FileRejected):
        return HTTPException(exc.status, detail={"code": exc.code, "message": exc.message})
    if isinstance(exc, MetadataInvalid):
        return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail={"fields": exc.errors})
    if isinstance(exc, NotFound):
        return HTTPException(status.HTTP_404_NOT_FOUND, detail=f"{exc} not found")
    if isinstance(exc, Conflict):
        return HTTPException(status.HTTP_409_CONFLICT, detail=str(exc))
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc))


_HANDLED = (
    versions.StaleVersion, FileRejected, MetadataInvalid, NotFound, Conflict, Invalid,
)  # fmt: skip


# ---- new version ------------------------------------------------------------------------


class NewVersionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filename: str = Field(min_length=1, max_length=300)
    content_type: str = Field(min_length=3, max_length=150)
    size_bytes: int = Field(gt=0)
    based_on_version: int = Field(ge=1, description="The newest version number you were looking at")
    comment: str | None = Field(None, max_length=300)


@router.post(
    "/{document_id}/versions/uploads",
    response_model=UploadSessionOut,
    status_code=status.HTTP_201_CREATED,
)
def create_version_upload(
    document_id: uuid.UUID,
    body: NewVersionIn,
    response: Response,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    principal: Principal = Depends(require_permission("document.upload_version")),
    db: Session = Depends(get_tenant_db),
):
    """Reserve a new version. Send the bytes to the returned `upload_url` exactly as for a first
    upload. `based_on_version` must be the newest version number; if someone else added one in
    the meantime you get 409 `stale` instead of overwriting their work."""
    settings = get_settings()
    perms = rbac.effective_permissions(db, principal.tenant_id, principal.user_id)
    try:
        document, version, created = versions.create_version_upload(
            db, settings, principal.tenant_id, principal.user_id, document_id,
            idempotency_key=idempotency_key, permissions=perms, **body.model_dump(),
        )  # fmt: skip
    except access.Denied as denied:
        raise _denied(principal, document_id, "upload_version", denied) from None
    except _HANDLED as exc:
        raise _mapped(exc) from None
    if not created:
        response.status_code = status.HTTP_200_OK
    return _session_out(document, version, settings=settings)


@router.get("/{document_id}/versions", response_model=list[VersionOut])
def list_versions(
    document_id: uuid.UUID,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_tenant_db),
):
    """Version history, newest first. Versions that are not published (awaiting approval,
    rejected, failed) are listed only to their uploader, the owner and privileged administrators."""
    perms = rbac.effective_permissions(db, principal.tenant_id, principal.user_id)
    document, _ = _authorize(principal, db, document_id, "view_metadata", perms)
    _, all_versions, _, _ = uploads.document_detail(db, document)
    visible = access.visible_versions(
        db, principal.tenant_id, principal.user_id, document, all_versions, perms
    )
    return [VersionOut.model_validate(v) for v in reversed(visible)]


# ---- restore ----------------------------------------------------------------------------


class RestoreIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    based_on_version: int = Field(ge=1)


@router.post("/{document_id}/versions/{number}/restore", response_model=UploadResultOut)
def restore_version(
    document_id: uuid.UUID,
    number: int,
    body: RestoreIn,
    background: BackgroundTasks,
    principal: Principal = Depends(get_principal),
):
    """Make an earlier version current again by creating a NEW version from a server-side copy
    of its bytes. History is preserved; categories that need approval hold the new version."""
    check_permission(principal, "document.upload_version")  # restoring creates a new version
    settings = get_settings()
    try:
        with tenant_session(principal.tenant_id) as db:
            perms = rbac.effective_permissions(db, principal.tenant_id, principal.user_id)
            plan = versions.begin_restore(
                db, settings, principal.tenant_id, principal.user_id, document_id, number,
                body.based_on_version, perms,
            )  # fmt: skip
    except access.Denied as denied:
        raise _denied(principal, document_id, "restore", denied) from None
    except _HANDLED as exc:
        raise _mapped(exc) from None

    def abort(reason: str) -> None:
        with tenant_session(principal.tenant_id) as db:
            versions.fail_restore(
                db, principal.tenant_id, principal.user_id, plan.version_id, reason
            )

    try:
        stored = get_storage().copy(
            plan.source_key, plan.target_key, src_file_id=plan.source_file_id
        )
    except (ObjectNotFound, ObjectExists, StorageError) as exc:
        abort(type(exc).__name__)
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            detail={"code": "storage_unavailable", "message": "Storage error; retry"},
        ) from None
    try:
        with tenant_session(principal.tenant_id) as db:
            version = uploads.finalize_available(
                db, principal.tenant_id, principal.user_id, plan.version_id,
                content_type=plan.content_type, size_bytes=stored.size_bytes, sha1=plan.sha1,
                sha256=plan.sha256, storage_file_id=stored.file_id,
                approval_required=plan.approval_required,
            )  # fmt: skip
            document = db.get(uploads.Document, plan.document_id)
    except Exception:
        logger.exception("restore finalize failed for %s", plan.version_id)
        abort("finalize_failed")
        try:
            get_storage().delete(plan.target_key)
        except StorageError:
            logger.exception("could not remove copy of failed restore %s", plan.version_id)
        raise
    background.add_task(_index_content, principal.tenant_id, document.id)
    return _result_out(document, version)


# ---- metadata edit ----------------------------------------------------------------------


class DocumentPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    row_version: int = Field(
        ge=1, description="The row_version you loaded; protects against overwrites"
    )
    title: str | None = Field(None, max_length=300)
    metadata: dict[str, Any] | None = None
    tag_ids: list[uuid.UUID] | None = None


class DocumentPatched(BaseModel):
    id: uuid.UUID
    title: str
    metadata: dict[str, Any]
    tag_ids: list[uuid.UUID]
    row_version: int


@router.patch("/{document_id}", response_model=DocumentPatched)
def edit_document(
    document_id: uuid.UUID,
    body: DocumentPatch,
    principal: Principal = Depends(require_permission("document.edit_metadata")),
    db: Session = Depends(get_tenant_db),
):
    """Change the title, metadata values (null removes a value) and/or tags. Metadata is checked
    against the schema version the document was created under. If `row_version` is out of date
    the edit is refused with 409 and the current number."""
    perms = rbac.effective_permissions(db, principal.tenant_id, principal.user_id)
    try:
        document = versions.update_document(
            db, principal.tenant_id, principal.user_id, document_id,
            row_version=body.row_version, title=body.title, metadata=body.metadata,
            tag_ids=body.tag_ids, permissions=perms,
        )  # fmt: skip
    except access.Denied as denied:
        raise _denied(principal, document_id, "edit_metadata", denied) from None
    except _HANDLED as exc:
        raise _mapped(exc) from None
    tags = [
        t.tag_id
        for t in db.scalars(
            uploads.select(uploads.DocumentTag).where(
                uploads.DocumentTag.document_id == document.id
            )
        )
    ]
    return DocumentPatched(
        id=document.id, title=document.title, metadata=document.metadata_values,
        tag_ids=tags, row_version=document.row_version,
    )  # fmt: skip
