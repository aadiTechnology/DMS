"""Document versions and metadata edits (PRD 8.3).

- A new version never overwrites anything: it gets its own immutable object (and number).
- `based_on_version` makes concurrent updates safe: if someone else added a version since the
  caller last looked, the request is refused (409) instead of silently overwriting their work.
- In categories that require approval a new version is held back (`review_status = pending`):
  readers keep seeing the last approved version until the approval workflow releases it.
- Restoring an old version creates a NEW version that is a server-side copy of the old bytes;
  history is preserved and nothing is mutated.
- Historical versions are subject to the CURRENT authorization; an old version never bypasses it.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.models import Category, Document, DocumentTag, DocumentVersion, Tag
from app.services import access, audit, search, taxonomy
from app.services.filetypes import FileRejected, check_declared_type, check_extension
from app.services.metadata import validate_values
from app.services.org import Conflict, Invalid
from app.services.uploads import _IDEMPOTENCY_KEY, _verify_ids, _verify_lookups
from app.storage import keys


class StaleVersion(Conflict):
    """The document changed since the caller looked (409 with the current numbers)."""

    def __init__(
        self, message: str, *, latest_version: int | None = None, row_version: int | None = None
    ):
        super().__init__(message)
        self.latest_version, self.row_version = latest_version, row_version


def _now() -> datetime:
    return datetime.now(UTC)


def _lock_document(db: Session, tenant_id, document_id) -> Document:
    document = db.scalars(
        select(Document)
        .where(Document.id == document_id, Document.tenant_id == tenant_id)
        .with_for_update()
    ).first()
    if document is None:
        raise access.Denied("missing")
    return document


def _guard_new_version(db: Session, tenant_id, actor_id, document: Document, based_on: int, perms):
    """Shared preconditions for uploading or restoring a version. Returns the next number."""
    decision = access.can_modify(db, tenant_id, actor_id, document, perms)
    if not decision.allowed:
        raise access.Denied(decision.reason)
    if document.lifecycle_state == "archived":
        raise Conflict("Restore the document from the archive before adding versions")
    category = db.get(Category, document.category_id)
    if category is None or category.status != "active":
        raise Conflict("The category is switched off; reactivate it first")
    latest = db.scalar(
        select(func.max(DocumentVersion.version_number)).where(
            DocumentVersion.document_id == document.id
        )
    )
    if based_on != latest:
        raise StaleVersion(
            f"Version {latest} exists; reload the document and try again", latest_version=latest
        )
    open_upload = db.scalars(
        select(DocumentVersion.id).where(
            DocumentVersion.document_id == document.id,
            DocumentVersion.status.in_(("pending", "receiving")),
            DocumentVersion.expires_at > _now(),
        )
    ).first()
    if open_upload is not None:
        raise Conflict("An upload for this document is already in progress")
    waiting = db.scalars(
        select(DocumentVersion.version_number).where(
            DocumentVersion.document_id == document.id, DocumentVersion.review_status == "pending"
        )
    ).first()
    if waiting is not None:
        raise Conflict(f"Version {waiting} is awaiting approval")
    return latest + 1, decision


def create_version_upload(
    db: Session, settings: Settings, tenant_id, actor_id, document_id, *, filename: str,
    content_type: str, size_bytes: int, based_on_version: int, comment: str | None,
    idempotency_key: str | None, permissions: set[str],
) -> tuple[Document, DocumentVersion, bool]:  # fmt: skip
    if idempotency_key is not None:
        if not _IDEMPOTENCY_KEY.match(idempotency_key):
            raise Invalid("Idempotency-Key: 8-100 characters of letters, digits . _ : -")
        existing = db.scalars(
            select(DocumentVersion).where(
                DocumentVersion.tenant_id == tenant_id,
                DocumentVersion.uploaded_by_user_id == actor_id,
                DocumentVersion.idempotency_key == idempotency_key,
            )
        ).first()
        if existing is not None:
            return db.get(Document, existing.document_id), existing, False
    if not 0 < size_bytes <= settings.DMS_MAX_UPLOAD_BYTES:
        raise FileRejected(
            "size_not_allowed", f"File size must be between 1 byte and {settings.DMS_MAX_UPLOAD_BYTES} bytes", 413
        )  # fmt: skip
    document = _lock_document(db, tenant_id, document_id)
    number, decision = _guard_new_version(
        db, tenant_id, actor_id, document, based_on_version, permissions
    )
    cfg, _ = taxonomy.get_version(
        db, tenant_id, document.category_id, document.category_version_number
    )
    safe_name = keys.sanitize_filename(filename)
    ext = check_extension(safe_name, cfg.allowed_extensions)
    check_declared_type(ext, content_type)
    version = DocumentVersion(
        tenant_id=tenant_id, document_id=document.id, version_number=number, status="pending",
        original_filename=safe_name, declared_content_type=content_type[:150],
        declared_size_bytes=size_bytes, comment=comment, uploaded_by_user_id=actor_id,
        object_key=keys.build_object_key(tenant_id, document.id, number, uuid.uuid4(), safe_name),
        idempotency_key=idempotency_key,
        expires_at=_now() + timedelta(minutes=settings.UPLOAD_RESERVATION_MINUTES),
    )  # fmt: skip
    db.add(version)
    db.flush()
    audit.record(
        db, tenant_id=tenant_id, actor_user_id=actor_id, action="document.version_upload_requested",
        resource_type="document", resource_id=document.id, privileged=decision.privileged,
        details={"version": number, "size_bytes": size_bytes, "extension": ext, "basis": decision.reason},
    )  # fmt: skip
    return document, version, True


# ---- restore ----------------------------------------------------------------------------


@dataclass
class RestorePlan:
    version_id: uuid.UUID
    document_id: uuid.UUID
    source_key: str
    source_file_id: str | None
    target_key: str
    new_number: int
    approval_required: bool
    content_type: str
    size_bytes: int
    sha1: str
    sha256: str | None


def begin_restore(
    db: Session, settings: Settings, tenant_id, actor_id, document_id, source_number: int,
    based_on_version: int, permissions: set[str],
) -> RestorePlan:  # fmt: skip
    document = _lock_document(db, tenant_id, document_id)
    source = db.scalars(
        select(DocumentVersion).where(
            DocumentVersion.document_id == document.id,
            DocumentVersion.version_number == source_number,
        )
    ).first()
    if source is None:
        raise access.Denied("missing")
    if source.status != "available" or source.review_status not in ("none", "approved"):
        raise Conflict("Only a published, available version can be restored")
    # restoring copies the content, so the caller needs download rights on that version today
    if not access.decide_version(
        db, tenant_id, actor_id, document, source, "download", permissions
    ).allowed:
        raise access.Denied("not_authorized")
    number, _ = _guard_new_version(db, tenant_id, actor_id, document, based_on_version, permissions)
    cfg, _ = taxonomy.get_version(
        db, tenant_id, document.category_id, document.category_version_number
    )
    target_key = keys.build_object_key(
        tenant_id, document.id, number, uuid.uuid4(), source.original_filename
    )
    version = DocumentVersion(
        tenant_id=tenant_id, document_id=document.id, version_number=number, status="receiving",
        original_filename=source.original_filename, declared_content_type=source.content_type or source.declared_content_type,
        declared_size_bytes=source.size_bytes, object_key=target_key, uploaded_by_user_id=actor_id,
        restored_from_version=source_number, comment=f"Restored from version {source_number}",
        expires_at=_now() + timedelta(minutes=settings.UPLOAD_RESERVATION_MINUTES),
    )  # fmt: skip
    db.add(version)
    db.flush()
    return RestorePlan(
        version.id, document.id, source.object_key, source.storage_file_id, target_key, number,
        cfg.approval_required, source.content_type, source.size_bytes, source.sha1, source.sha256,
    )  # fmt: skip


def fail_restore(db: Session, tenant_id, actor_id, version_id, reason: str) -> None:
    version = db.get(DocumentVersion, version_id)
    if version is not None and version.status == "receiving":
        version.status = "abandoned"
        audit.record(
            db, tenant_id=tenant_id, actor_user_id=actor_id, action="document.restore_failed",
            resource_type="document", resource_id=version.document_id, outcome="failure",
            details={"reason": reason[:60]},
        )  # fmt: skip


# ---- metadata edits ---------------------------------------------------------------------


def update_document(
    db: Session, tenant_id, actor_id, document_id, *, row_version: int, title: str | None,
    metadata: dict | None, tag_ids: list[uuid.UUID] | None, permissions: set[str],
) -> Document:  # fmt: skip
    document = _lock_document(db, tenant_id, document_id)
    decision = access.can_modify(db, tenant_id, actor_id, document, permissions)
    if not decision.allowed:
        raise access.Denied(decision.reason)
    if document.row_version != row_version:
        raise StaleVersion(
            "The document was changed by someone else; reload it and try again",
            row_version=document.row_version,
        )
    if document.lifecycle_state == "archived":
        raise Conflict("Restore the document from the archive before editing it")
    changed: list[str] = []
    if title is not None:
        title = title.strip()
        if not title or len(title) > 300:
            raise Invalid("title: 1 to 300 characters")
        if title != document.title:
            document.title = title
            changed.append("title")
    if metadata is not None:
        # the document keeps the metadata schema version it was created under (CAT-004)
        _, fields = taxonomy.get_version(
            db, tenant_id, document.category_id, document.category_version_number
        )
        defs = [
            {"key": f.key, "field_type": f.field_type, "required": f.required,
             "validation": f.validation, "default_value": f.default_value}
            for f in fields
        ]  # fmt: skip
        merged = {**document.metadata_values, **metadata}
        merged = {k: v for k, v in merged.items() if v is not None}  # null removes a value
        cleaned = validate_values(defs, merged)
        _verify_lookups(db, tenant_id, defs, cleaned)
        if cleaned != document.metadata_values:
            document.metadata_values = cleaned
            changed.append("metadata")
    if tag_ids is not None:
        _verify_ids(db, tenant_id, Tag, tag_ids, "tag_ids", kind_not="system")
        current = {
            t.tag_id: t
            for t in db.scalars(select(DocumentTag).where(DocumentTag.document_id == document.id))
        }
        system_ids = set(
            db.scalars(select(Tag.id).where(Tag.tenant_id == tenant_id, Tag.kind == "system")).all()
        )
        wanted = set(tag_ids)
        removable = {tid for tid in current if tid not in system_ids}
        if wanted != removable:
            for tid in wanted - set(current):
                db.add(DocumentTag(tenant_id=tenant_id, document_id=document.id, tag_id=tid))
            # tag links are plain labels: removal is allowed and recorded in the audit event
            for tid in removable - wanted:
                db.delete(current[tid])
            changed.append("tags")
    if not changed:
        return document
    document.row_version += 1
    document.updated_at = _now()
    db.flush()
    current_version = db.scalars(
        select(DocumentVersion).where(
            DocumentVersion.document_id == document.id,
            DocumentVersion.version_number == document.current_version_number,
        )
    ).first()
    if current_version is not None:
        search.reindex_metadata_only(db, document, current_version.original_filename)
    audit.record(
        db, tenant_id=tenant_id, actor_user_id=actor_id, action="document.metadata_updated",
        resource_type="document", resource_id=document.id, privileged=decision.privileged,
        details={"changed": sorted(changed), "basis": decision.reason},
    )  # fmt: skip
    return document
