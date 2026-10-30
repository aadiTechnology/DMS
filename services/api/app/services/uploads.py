"""Document upload lifecycle (PRD 8.1), split into short database steps so no transaction is held
open while a file streams in:

  create_upload  -> document + version row in `pending`, everything validated up front
  begin_receive  -> `receiving` (locks out a second concurrent upload of the same reservation)
  (API streams to a temp file, hashes once, validates content, scans, stores via put_file)
  finalize_*     -> `available`, `quarantined` or `rejected`; or revert_to_pending on a
                    transient failure so the same reservation can be retried
  expire_stale   -> job body that abandons reservations nobody completed

A version is only usable when it is `available`: validated, clean and stored.
"""

import hashlib
import logging
import os
import re
import tempfile
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.models import (
    Branch,
    Category,
    Department,
    Document,
    DocumentAssociation,
    DocumentTag,
    DocumentVersion,
    Project,
    Tag,
    TenantMembership,
)
from app.services import audit, taxonomy
from app.services.filetypes import FileRejected, check_declared_type, check_extension
from app.services.metadata import validate_values
from app.services.org import Conflict, Invalid, NotFound
from app.storage import keys
from app.storage.base import StorageProvider

logger = logging.getLogger("dms.uploads")
_IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9._:-]{8,100}$")
CLASSIFICATION_RANK = {c: i for i, c in enumerate(taxonomy.CLASSIFICATIONS)}


def _now() -> datetime:
    return datetime.now(UTC)


# ---- create (reserve) -------------------------------------------------------------------


@dataclass
class UploadRequest:
    category_id: uuid.UUID
    filename: str
    content_type: str
    size_bytes: int
    title: str | None = None
    classification: str | None = None
    owner_membership_id: uuid.UUID | None = None
    associations: dict[str, list[uuid.UUID]] = field(default_factory=dict)
    tag_ids: list[uuid.UUID] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    comment: str | None = None
    idempotency_key: str | None = None


def _active_membership(db: Session, tenant_id, user_id) -> TenantMembership:
    m = db.scalars(
        select(TenantMembership).where(
            TenantMembership.tenant_id == tenant_id,
            TenantMembership.user_id == user_id,
            TenantMembership.status == "active",
        )
    ).first()
    if m is None:
        raise NotFound("employee")
    return m


def _verify_ids(db: Session, tenant_id, model, ids, what: str, *, kind_not=None) -> None:
    unique = set(ids)
    if not unique:
        return
    rows = db.scalars(select(model).where(model.tenant_id == tenant_id, model.id.in_(unique))).all()
    ok = {
        r.id
        for r in rows
        if r.status == "active" and (kind_not is None or getattr(r, "kind", None) != kind_not)
    }
    if ok != unique:
        raise Invalid(f"{what}: unknown, inactive or not permitted")


def create_upload(
    db: Session, settings: Settings, tenant_id, actor_id, req: UploadRequest
) -> tuple[Document, DocumentVersion, bool]:
    """Returns (document, version, created). Replaying the same Idempotency-Key returns the
    original reservation instead of creating another document."""
    if req.idempotency_key is not None:
        if not _IDEMPOTENCY_KEY.match(req.idempotency_key):
            raise Invalid("Idempotency-Key: 8-100 characters of letters, digits . _ : -")
        existing = db.scalars(
            select(DocumentVersion).where(
                DocumentVersion.tenant_id == tenant_id,
                DocumentVersion.uploaded_by_user_id == actor_id,
                DocumentVersion.idempotency_key == req.idempotency_key,
            )
        ).first()
        if existing is not None:
            return db.get(Document, existing.document_id), existing, False

    if not 0 < req.size_bytes <= settings.DMS_MAX_UPLOAD_BYTES:
        raise FileRejected(
            "size_not_allowed",
            f"File size must be between 1 byte and {settings.DMS_MAX_UPLOAD_BYTES} bytes",
            413,
        )
    category = db.get(Category, req.category_id)
    if category is None or category.tenant_id != tenant_id or category.status != "active":
        raise Invalid("category_id: must be an active category")
    version_cfg, fields = taxonomy.get_version(db, tenant_id, category.id)

    filename = keys.sanitize_filename(req.filename)
    ext = check_extension(filename, version_cfg.allowed_extensions)
    check_declared_type(ext, req.content_type)

    classification = req.classification or category.default_classification
    if classification not in CLASSIFICATION_RANK:
        raise Invalid(f"classification: use one of {', '.join(taxonomy.CLASSIFICATIONS)}")
    if CLASSIFICATION_RANK[classification] < CLASSIFICATION_RANK[category.default_classification]:
        raise Invalid(
            f"classification: this category requires at least {category.default_classification}"
        )

    uploader = _active_membership(db, tenant_id, actor_id)
    owner_id = req.owner_membership_id or uploader.id
    if req.owner_membership_id:
        owner = db.get(TenantMembership, req.owner_membership_id)
        if owner is None or owner.tenant_id != tenant_id or owner.status != "active":
            raise Invalid("owner_membership_id: must be an active employee")

    assoc = _validate_associations(db, tenant_id, version_cfg.required_dimensions, req.associations)
    _verify_ids(db, tenant_id, Tag, req.tag_ids, "tag_ids", kind_not="system")

    field_defs = [
        {"key": f.key, "field_type": f.field_type, "required": f.required,
         "validation": f.validation, "default_value": f.default_value}
        for f in fields
    ]  # fmt: skip
    cleaned = validate_values(field_defs, req.metadata)  # raises MetadataInvalid
    _verify_lookups(db, tenant_id, field_defs, cleaned)

    title = (req.title or Path(filename).stem).strip()[:300] or "Untitled"
    document = Document(
        tenant_id=tenant_id, title=title, category_id=category.id,
        category_version_number=version_cfg.version_number, classification=classification,
        owner_membership_id=owner_id, created_by_user_id=actor_id, metadata_values=cleaned,
    )  # fmt: skip
    db.add(document)
    db.flush()
    for dimension, ids in assoc.items():
        db.add_all(
            DocumentAssociation(
                tenant_id=tenant_id, document_id=document.id, dimension=dimension, ref_id=i
            )
            for i in ids
        )
    db.add_all(
        DocumentTag(tenant_id=tenant_id, document_id=document.id, tag_id=t)
        for t in set(req.tag_ids)
    )
    object_key = keys.build_object_key(tenant_id, document.id, 1, uuid.uuid4(), filename)
    version = DocumentVersion(
        tenant_id=tenant_id, document_id=document.id, version_number=1, status="pending",
        original_filename=filename, declared_content_type=req.content_type[:150],
        declared_size_bytes=req.size_bytes, object_key=object_key, comment=req.comment,
        uploaded_by_user_id=actor_id, idempotency_key=req.idempotency_key,
        expires_at=_now() + timedelta(minutes=settings.UPLOAD_RESERVATION_MINUTES),
    )  # fmt: skip
    db.add(version)
    db.flush()
    audit.record(
        db, tenant_id=tenant_id, actor_user_id=actor_id, action="document.upload_requested",
        resource_type="document", resource_id=document.id,
        details={"category_id": str(category.id), "size_bytes": req.size_bytes, "extension": ext},
    )  # fmt: skip
    return document, version, True


def _validate_associations(db, tenant_id, required: list[str], given: dict) -> dict[str, list]:
    unknown = set(given) - {"department", "branch", "project", "employee"}
    if unknown:
        raise Invalid(f"associations: unknown dimension(s): {', '.join(sorted(unknown))}")
    missing = [d for d in required if not given.get(d)]
    if missing:
        raise Invalid(f"associations: this category requires {', '.join(missing)}")
    models = {"department": Department, "branch": Branch, "project": Project}
    out: dict[str, list] = {}
    for dimension, ids in given.items():
        ids = list(dict.fromkeys(ids))
        if len(ids) > 20:
            raise Invalid(f"associations.{dimension}: at most 20")
        if dimension == "employee":
            _verify_ids(db, tenant_id, TenantMembership, ids, "associations.employee")
        else:
            _verify_ids(db, tenant_id, models[dimension], ids, f"associations.{dimension}")
        if ids:
            out[dimension] = ids
    return out


def _verify_lookups(db, tenant_id, field_defs, cleaned: dict) -> None:
    models = {
        "employee_lookup": TenantMembership, "department_lookup": Department,
        "branch_lookup": Branch, "project_lookup": Project,
    }  # fmt: skip
    for f in field_defs:
        value = cleaned.get(f["key"])
        if value is None:
            continue
        ftype = f["field_type"]
        if ftype in models:
            _verify_ids(db, tenant_id, models[ftype], [uuid.UUID(value)], f["key"])
        elif ftype == "tag_selector":
            _verify_ids(
                db, tenant_id, Tag, [uuid.UUID(v) for v in value], f["key"], kind_not="system"
            )


# ---- receive ----------------------------------------------------------------------------


@dataclass
class ReceiveContext:
    version_id: uuid.UUID
    document_id: uuid.UUID
    object_key: str
    filename: str
    declared_content_type: str
    declared_size_bytes: int
    allowed_extensions: list[str] | None
    approval_required: bool


@dataclass
class ReceiveOutcome:
    kind: str  # ok | done | expired
    context: ReceiveContext | None = None
    version: DocumentVersion | None = None
    document: Document | None = None


def _own_version(db: Session, tenant_id, actor_id, version_id, *, lock: bool) -> DocumentVersion:
    stmt = select(DocumentVersion).where(
        DocumentVersion.id == version_id, DocumentVersion.tenant_id == tenant_id
    )
    if lock:
        stmt = stmt.with_for_update()
    version = db.scalars(stmt).first()
    if version is None or version.uploaded_by_user_id != actor_id:
        raise NotFound("upload")  # same answer for other people's uploads
    return version


def begin_receive(db: Session, tenant_id, actor_id, version_id) -> ReceiveOutcome:
    version = _own_version(db, tenant_id, actor_id, version_id, lock=True)
    if version.status == "available":
        return ReceiveOutcome(
            "done", version=version, document=db.get(Document, version.document_id)
        )
    if version.status == "receiving":
        raise Conflict("This upload is already being received")
    if version.status != "pending":
        raise Conflict(f"This upload is {version.status} and cannot be resumed")
    if version.expires_at <= _now():
        version.status = "abandoned"
        audit.record(
            db, tenant_id=tenant_id, actor_user_id=actor_id, action="document.upload_abandoned",
            resource_type="document", resource_id=version.document_id, details={"reason": "expired"},
        )  # fmt: skip
        return ReceiveOutcome("expired", version=version)
    document = db.get(Document, version.document_id)
    cfg, _ = taxonomy.get_version(
        db, tenant_id, document.category_id, document.category_version_number
    )
    version.status = "receiving"
    return ReceiveOutcome(
        "ok",
        context=ReceiveContext(
            version.id, document.id, version.object_key, version.original_filename,
            version.declared_content_type, version.declared_size_bytes,
            cfg.allowed_extensions, cfg.approval_required,
        ),
    )  # fmt: skip


def finalize_available(
    db: Session, tenant_id, actor_id, version_id, *, content_type, size_bytes, sha1, sha256,
    storage_file_id, approval_required: bool,
) -> DocumentVersion:  # fmt: skip
    version = _own_version(db, tenant_id, actor_id, version_id, lock=True)
    document = db.get(Document, version.document_id)
    version.status, version.scan_status = "available", "clean"
    version.content_type, version.size_bytes = content_type, size_bytes
    version.sha1, version.sha256, version.storage_file_id = sha1, sha256, storage_file_id
    version.finalized_at = _now()
    document.current_version_number = version.version_number
    document.lifecycle_state = "submitted" if approval_required else "approved"
    document.row_version += 1
    document.updated_at = _now()
    audit.record(
        db, tenant_id=tenant_id, actor_user_id=actor_id, action="document.uploaded",
        resource_type="document", resource_id=document.id,
        details={"version": version.version_number, "size_bytes": size_bytes,
                 "content_type": content_type, "needs_approval": approval_required},
    )  # fmt: skip
    return version


def finalize_blocked(
    db: Session, tenant_id, actor_id, version_id, *, status: str, reason: str,
    scan_status: str = "pending", scan_detail: str | None = None,
) -> DocumentVersion:  # fmt: skip
    """status is `quarantined` (infected) or `rejected` (failed validation); both are final."""
    version = _own_version(db, tenant_id, actor_id, version_id, lock=True)
    version.status, version.reject_reason = status, reason[:60]
    version.scan_status, version.scan_detail = scan_status, (scan_detail or "")[:200] or None
    version.finalized_at = _now()
    audit.record(
        db, tenant_id=tenant_id, actor_user_id=actor_id,
        action="document.upload_quarantined" if status == "quarantined" else "document.upload_rejected",
        resource_type="document", resource_id=version.document_id,
        outcome="denied" if status == "quarantined" else "failure",
        details={"reason": reason[:60], "scan": scan_status},
    )  # fmt: skip
    return version


def revert_to_pending(db: Session, tenant_id, actor_id, version_id, reason: str) -> None:
    version = _own_version(db, tenant_id, actor_id, version_id, lock=True)
    if version.status == "receiving":
        version.status = "pending"
        audit.record(
            db, tenant_id=tenant_id, actor_user_id=actor_id, action="document.upload_interrupted",
            resource_type="document", resource_id=version.document_id, outcome="failure",
            details={"reason": reason[:60]},
        )  # fmt: skip


def expire_stale(db: Session, tenant_id, storage: StorageProvider, now: datetime | None = None):
    """Job body (one tenant). Abandons reservations past their expiry and removes any object a
    crashed upload left behind. Returns (abandoned, delete_failures); failures are logged and
    the version stays `abandoned` so a later sweep can retry the object removal."""
    now = now or _now()
    stale = db.scalars(
        select(DocumentVersion)
        .where(
            DocumentVersion.tenant_id == tenant_id,
            DocumentVersion.status.in_(("pending", "receiving")),
            DocumentVersion.expires_at <= now,
        )
        .with_for_update(skip_locked=True)
    ).all()
    failures = 0
    for version in stale:
        was_receiving = version.status == "receiving"
        version.status = "abandoned"
        if was_receiving:
            try:
                storage.delete(version.object_key)
            except Exception:
                failures += 1
                logger.exception("could not remove object of abandoned upload %s", version.id)
        audit.record(
            db, tenant_id=tenant_id, actor_user_id=None, action="document.upload_abandoned",
            resource_type="document", resource_id=version.document_id,
            details={"reason": "expired", "had_object_attempt": was_receiving},
        )  # fmt: skip
    return len(stale), failures


# ---- reads (uploader / owner only until the document policy engine ships) ---------------


def _can_see(db: Session, tenant_id, actor_id, document: Document) -> bool:
    if document.created_by_user_id == actor_id:
        return True
    owner = db.get(TenantMembership, document.owner_membership_id)
    return owner is not None and owner.user_id == actor_id


def get_document(db: Session, tenant_id, actor_id, document_id):
    document = db.get(Document, document_id)
    if (
        document is None
        or document.tenant_id != tenant_id
        or not _can_see(db, tenant_id, actor_id, document)
    ):
        raise NotFound("document")
    versions = list(
        db.scalars(
            select(DocumentVersion)
            .where(DocumentVersion.document_id == document.id)
            .order_by(DocumentVersion.version_number)
        )
    )
    assoc = list(
        db.scalars(
            select(DocumentAssociation).where(DocumentAssociation.document_id == document.id)
        )
    )
    tags = [
        t.tag_id
        for t in db.scalars(select(DocumentTag).where(DocumentTag.document_id == document.id))
    ]
    return document, versions, assoc, tags


def list_my_documents(db: Session, tenant_id, actor_id, limit=50, offset=0):
    limit, offset = max(1, min(limit, 200)), max(0, offset)
    owner_ids = select(TenantMembership.id).where(
        TenantMembership.tenant_id == tenant_id, TenantMembership.user_id == actor_id
    )
    stmt = (
        select(Document)
        .where(
            Document.tenant_id == tenant_id,
            (Document.created_by_user_id == actor_id) | Document.owner_membership_id.in_(owner_ids),
        )
        .order_by(Document.created_at.desc(), Document.id)
        .limit(limit)
        .offset(offset)
    )
    return list(db.scalars(stmt))


# ---- temp-file spool --------------------------------------------------------------------


class Spool:
    """Receives the upload on temporary disk (constant memory) and hashes it in one pass."""

    def __init__(self, directory: str, declared_size: int):
        fd, name = tempfile.mkstemp(prefix="dms-upload-", dir=directory or None)
        self.path = Path(name)
        self._handle = os.fdopen(fd, "wb")
        self._declared = declared_size
        self.size = 0
        self._sha1 = hashlib.sha1(usedforsecurity=False)
        self._sha256 = hashlib.sha256()

    def write(self, chunk: bytes) -> None:
        self.size += len(chunk)
        if self.size > self._declared:
            raise FileRejected("size_mismatch", "More data was sent than declared", 413)
        self._sha1.update(chunk)
        self._sha256.update(chunk)
        self._handle.write(chunk)

    def finish(self) -> tuple[str, str]:
        self._handle.close()
        if self.size != self._declared:
            raise FileRejected("size_mismatch", "Less data was sent than declared", 400)
        return self._sha1.hexdigest(), self._sha256.hexdigest()

    def cleanup(self) -> None:
        self._handle.close()
        self.path.unlink(missing_ok=True)
