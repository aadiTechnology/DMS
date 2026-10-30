"""Search and indexing (PRD section 9, SRCH-001..006, SRCH-009).

Index: PostgreSQL full-text search with the language-neutral `simple` configuration (verified to
keep Hindi and Marathi words intact; no stemming for any language). Two vectors per document:
- meta: title (weight A), file name (B), searchable metadata + tags (C)
- content: text extracted from the current version
The index carries NO access information. Every query applies `access_sql.visible_clause`, so a
permission change, share revocation or deactivation takes effect on the very next request, and
totals, facets and suggestions can only count documents the caller may see.
"""

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import and_, exists, func, literal, or_, select, text
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.models import (
    Category,
    Document,
    DocumentAssociation,
    DocumentSearch,
    DocumentTag,
    DocumentVersion,
    Tag,
)
from app.services import extraction, taxonomy
from app.services.access_sql import Viewer, visible_clause
from app.services.org import Invalid
from app.storage.base import StorageError, StorageProvider

SIMPLE = "simple"
_TS_META = re.compile(r"[&|!():*'\"\\<>\x00-\x1f]")
MAX_TOKENS, MAX_TOKEN_LEN, MAX_QUERY_LEN = 8, 50, 200
SORTS = ("relevance", "date", "title")
DATE_FIELDS = ("created", "modified", "uploaded")
MAX_PAGE = 100


# ---- query text -------------------------------------------------------------------------


def build_tsquery(q: str) -> str | None:
    """User text -> a safe prefix tsquery ('foo':* & 'bar':*). Operators in user text are
    neutralized, so input can never change the query structure. Unicode is preserved."""
    if len(q) > MAX_QUERY_LEN:
        raise Invalid(f"q: at most {MAX_QUERY_LEN} characters")
    tokens = [t[:MAX_TOKEN_LEN] for t in _TS_META.sub(" ", q).split() if t.strip()]
    if len(tokens) > MAX_TOKENS:
        raise Invalid(f"q: at most {MAX_TOKENS} words")
    return " & ".join(f"'{t}':*" for t in tokens) if tokens else None


def query_terms(q: str) -> list[str]:
    """One safe prefix tsquery per word. A document matches when EVERY word is found in either
    its title/metadata or its extracted content (words may be split between the two)."""
    built = build_tsquery(q)
    return built.split(" & ") if built else []


# ---- indexing ---------------------------------------------------------------------------


def _flatten(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, bool) or value is None:
        return []
    if isinstance(value, (int, float)):
        return [str(value)]
    if isinstance(value, list):
        return [s for v in value for s in _flatten(v)]
    if isinstance(value, dict):
        return [s for v in value.values() for s in _flatten(v)]
    return []


_ID_FIELDS = {"employee_lookup", "department_lookup", "branch_lookup", "project_lookup"}


def reindex_metadata_only(db: Session, document: Document, filename: str) -> None:
    """Refresh title/file name/metadata/tags in the index without re-extracting content."""
    index_metadata(db, document, filename, content_supported=True, reset_extraction=False)


def index_metadata(
    db: Session,
    document: Document,
    filename: str,
    *,
    content_supported: bool,
    reset_extraction: bool = True,
) -> None:
    """(Re)build the metadata vector. Called when a version becomes available and whenever
    title, metadata or tags change. Marks content extraction `pending` for a new version."""
    _, fields = taxonomy.get_version(
        db, document.tenant_id, document.category_id, document.category_version_number
    )
    extra: list[str] = []
    for f in fields:
        if f.searchable and f.field_type not in _ID_FIELDS and f.field_type != "tag_selector":
            extra += _flatten(document.metadata_values.get(f.key))
    tag_names = db.scalars(
        select(Tag.name)
        .join(DocumentTag, DocumentTag.tag_id == Tag.id)
        .where(DocumentTag.document_id == document.id)
    ).all()
    extra += list(tag_names)
    db.execute(
        text(
            "INSERT INTO document_search (document_id, tenant_id, meta_tsv, extraction_status) "
            "VALUES (:d, :t, "
            "setweight(to_tsvector('simple', :title), 'A') || "
            "setweight(to_tsvector('simple', :fname), 'B') || "
            "setweight(to_tsvector('simple', :extra), 'C'), :status) "
            "ON CONFLICT (document_id) DO UPDATE SET meta_tsv = EXCLUDED.meta_tsv, "
            "extraction_status = CASE WHEN :reset THEN EXCLUDED.extraction_status "
            "ELSE document_search.extraction_status END, "
            "attempts = CASE WHEN :reset THEN 0 ELSE document_search.attempts END, "
            "updated_at = now()"
        ),
        {
            "d": document.id, "t": document.tenant_id, "title": document.title, "fname": filename,
            "extra": " ".join(extra), "status": "pending" if content_supported else "unsupported",
            "reset": reset_extraction,
        },
    )  # fmt: skip


def _claim_next(
    db: Session, tenant_id, document_id=None
) -> tuple[DocumentSearch, Document, DocumentVersion] | None:
    stmt = (
        select(DocumentSearch)
        .where(DocumentSearch.tenant_id == tenant_id, DocumentSearch.extraction_status == "pending")
        .order_by(DocumentSearch.updated_at)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if document_id is not None:
        stmt = stmt.where(DocumentSearch.document_id == document_id)
    entry = db.scalars(stmt).first()
    if entry is None:
        return None
    document = db.get(Document, entry.document_id)
    version = db.scalars(
        select(DocumentVersion).where(
            DocumentVersion.document_id == document.id,
            DocumentVersion.version_number == document.current_version_number,
            DocumentVersion.status == "available",
        )
    ).first()
    entry.extraction_status, entry.attempts = "processing", entry.attempts + 1
    return entry, document, version


@dataclass
class IndexRunStats:
    indexed: int = 0
    failed: int = 0
    unsupported: int = 0
    errors: list[str] = field(default_factory=list)


def process_pending(
    tenant_id, storage: StorageProvider, settings: Settings, *, document_id=None, limit: int = 10,
    tenant_session=None,
) -> IndexRunStats:  # fmt: skip
    """Job body: extract text for documents waiting in the index queue (Postgres is the queue;
    SKIP LOCKED lets several workers run safely). Each document uses short transactions: claim,
    extract outside any transaction, write the result."""
    from app.db.tenant_session import tenant_session as default_session

    open_session = tenant_session or default_session
    stats = IndexRunStats()
    for _ in range(limit):
        with open_session(tenant_id) as db:
            claimed = _claim_next(db, tenant_id, document_id)
            if claimed is None:
                break
            entry, document, version = claimed
            snapshot = (document.id, version, entry.attempts)
            version_info = None if version is None else (
                version.object_key, version.storage_file_id, version.original_filename,
                version.version_number,
            )  # fmt: skip
        doc_id, _, attempts = snapshot
        if version_info is None:
            _finish(
                open_session,
                tenant_id,
                doc_id,
                None,
                "failed",
                "no_available_version",
                attempts,
                settings,
            )
            stats.failed += 1
            continue
        key, file_id, filename, number = version_info
        ext = extraction_ext(filename)
        result = _extract_from_storage(storage, key, file_id, ext, settings)
        if result.status == "ok":
            _finish(
                open_session, tenant_id, doc_id, result, "indexed", None, attempts, settings, number
            )
            stats.indexed += 1
        elif result.status == "unsupported":
            _finish(
                open_session,
                tenant_id,
                doc_id,
                result,
                "unsupported",
                result.reason,
                attempts,
                settings,
                number,
            )
            stats.unsupported += 1
        else:
            _finish(
                open_session,
                tenant_id,
                doc_id,
                result,
                "failed",
                result.reason,
                attempts,
                settings,
                number,
            )
            stats.failed += 1
            stats.errors.append(result.reason or "extraction_error")
    return stats


def extraction_ext(filename: str) -> str:
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


def _extract_from_storage(storage, key, file_id, ext, settings) -> extraction.ExtractResult:
    if ext not in extraction.SUPPORTED:
        return extraction.ExtractResult("unsupported", reason="format_not_supported")
    import tempfile

    with tempfile.TemporaryDirectory(prefix="dms-extract-") as directory:
        path = Path(directory) / f"object.{ext}"
        try:
            with path.open("wb") as handle:
                for chunk in storage.read_stream(key, file_id=file_id):
                    handle.write(chunk)
        except StorageError:
            return extraction.ExtractResult("failed", reason="storage_read_failed")
        return extraction.extract(path, ext, settings)


def _finish(
    open_session,
    tenant_id,
    document_id,
    result,
    status,
    reason,
    attempts,
    settings,
    version_number=None,
):
    with open_session(tenant_id) as db:
        entry = db.get(DocumentSearch, document_id)
        if status == "failed" and attempts < settings.EXTRACT_MAX_ATTEMPTS and reason in (
            "extraction_timeout", "storage_read_failed", "extractor_unavailable",
        ):  # fmt: skip
            entry.extraction_status, entry.failure_reason = "pending", reason  # transient: retry
            return
        entry.extraction_status, entry.failure_reason = status, reason
        entry.content_version_number = version_number
        entry.truncated = bool(result and result.truncated)
        if status == "indexed":
            db.execute(
                text(
                    "UPDATE document_search SET content_tsv = to_tsvector('simple', :t), "
                    "indexed_at = now(), updated_at = now() WHERE document_id = :d"
                ),
                {"t": result.text, "d": document_id},
            )
        else:
            entry.content_tsv = None
            entry.updated_at = func.now()


def index_status(db: Session, tenant_id) -> dict[str, int]:
    rows = db.execute(
        select(DocumentSearch.extraction_status, func.count())
        .where(DocumentSearch.tenant_id == tenant_id)
        .group_by(DocumentSearch.extraction_status)
    ).all()
    return {status: count for status, count in rows}


def list_failures(db: Session, tenant_id, limit=50, offset=0):
    limit, offset = max(1, min(limit, 200)), max(0, offset)
    return list(
        db.scalars(
            select(DocumentSearch)
            .where(
                DocumentSearch.tenant_id == tenant_id, DocumentSearch.extraction_status == "failed"
            )
            .order_by(DocumentSearch.updated_at.desc(), DocumentSearch.document_id)
            .limit(limit)
            .offset(offset)
        )
    )


def requeue_failures(db: Session, tenant_id) -> int:
    result = db.execute(
        text(
            "UPDATE document_search SET extraction_status='pending', attempts=0, updated_at=now() "
            "WHERE tenant_id=:t AND extraction_status='failed'"
        ),
        {"t": tenant_id},
    )
    return result.rowcount


# ---- querying ---------------------------------------------------------------------------


@dataclass
class SearchParams:
    q: str | None = None
    category_id: uuid.UUID | None = None
    include_subcategories: bool = True
    department_id: uuid.UUID | None = None
    branch_id: uuid.UUID | None = None
    project_id: uuid.UUID | None = None
    employee_id: uuid.UUID | None = None
    owner_id: uuid.UUID | None = None
    uploader_id: uuid.UUID | None = None
    status: str | None = None
    classification: str | None = None
    tag_id: uuid.UUID | None = None
    date_field: str = "created"
    date_from: datetime | None = None
    date_to: datetime | None = None
    sort: str = "relevance"
    limit: int = 20
    offset: int = 0


def _filters(db: Session, tenant_id, viewer: Viewer, p: SearchParams, terms):
    if p.sort not in SORTS:
        raise Invalid(f"sort: use one of {', '.join(SORTS)}")
    if p.date_field not in DATE_FIELDS:
        raise Invalid(f"date_field: use one of {', '.join(DATE_FIELDS)}")
    where = [Document.tenant_id == tenant_id, visible_clause(viewer)]
    for term in terms:
        where.append(
            or_(DocumentSearch.meta_tsv.op("@@")(term), DocumentSearch.content_tsv.op("@@")(term))
        )
    if p.category_id:
        ids = {p.category_id}
        if p.include_subcategories:
            tree = {
                c.id: c.parent_id
                for c in db.scalars(select(Category).where(Category.tenant_id == tenant_id))
            }
            grew = True
            while grew:
                grew = False
                for cid, parent in tree.items():
                    if parent in ids and cid not in ids:
                        ids.add(cid)
                        grew = True
        where.append(Document.category_id.in_(ids))
    for dimension, ref in (
        ("department", p.department_id), ("branch", p.branch_id),
        ("project", p.project_id), ("employee", p.employee_id),
    ):  # fmt: skip
        if ref:
            where.append(
                exists().where(
                    DocumentAssociation.document_id == Document.id,
                    DocumentAssociation.dimension == dimension,
                    DocumentAssociation.ref_id == ref,
                )
            )
    if p.owner_id:
        where.append(Document.owner_membership_id == p.owner_id)
    if p.uploader_id:
        where.append(Document.created_by_user_id == p.uploader_id)
    if p.status:
        where.append(Document.lifecycle_state == p.status)
    if p.classification:
        where.append(Document.classification == p.classification)
    if p.tag_id:
        where.append(
            exists().where(DocumentTag.document_id == Document.id, DocumentTag.tag_id == p.tag_id)
        )
    date_col = {
        "created": Document.created_at,
        "modified": Document.updated_at,
        "uploaded": DocumentVersion.finalized_at,
    }[p.date_field]
    if p.date_from:
        where.append(date_col >= p.date_from)
    if p.date_to:
        where.append(date_col <= p.date_to)
    return where


def _base(where):
    return (
        select(Document)
        .select_from(Document)
        .outerjoin(DocumentSearch, DocumentSearch.document_id == Document.id)
        .outerjoin(
            DocumentVersion,
            and_(
                DocumentVersion.document_id == Document.id,
                DocumentVersion.version_number == Document.current_version_number,
            ),
        )
        .where(*where)
    )


def search(db: Session, tenant_id, viewer: Viewer, p: SearchParams) -> dict[str, Any]:
    terms = [func.to_tsquery(SIMPLE, literal(t)) for t in query_terms(p.q)] if p.q else []
    where = _filters(db, tenant_id, viewer, p, terms)
    limit, offset = max(1, min(p.limit, MAX_PAGE)), max(0, p.offset)

    base = _base(where)
    total = db.scalar(select(func.count()).select_from(base.subquery()))
    if terms and p.sort == "relevance":
        rank = sum(
            func.coalesce(func.ts_rank(DocumentSearch.meta_tsv, t), 0) * 2
            + func.coalesce(func.ts_rank(DocumentSearch.content_tsv, t), 0)
            for t in terms
        )
        order = (rank.desc(), Document.created_at.desc(), Document.id)
    elif p.sort == "title":
        order = (func.lower(Document.title), Document.id)
    else:
        order = (Document.created_at.desc(), Document.id)  # total order => stable pages
    stmt = (
        base.add_columns(
            DocumentVersion.original_filename,
            DocumentVersion.content_type,
            DocumentVersion.size_bytes,
        )
        .order_by(*order)
        .limit(limit)
        .offset(offset)
    )
    items = [
        {"document": row[0], "filename": row[1], "content_type": row[2], "size_bytes": row[3]}
        for row in db.execute(stmt).all()
    ]
    return {
        "items": items,
        "total": total,
        "facets": _facets(db, where),
        "limit": limit,
        "offset": offset,
    }


def _facets(db: Session, where) -> dict[str, list[dict[str, Any]]]:
    """Counts over exactly the documents the caller may see and that match the filters."""
    sub = (
        _base(where)
        .with_only_columns(
            Document.id, Document.category_id, Document.classification, Document.lifecycle_state
        )
        .subquery()
    )
    facets: dict[str, list[dict[str, Any]]] = {}
    for name, column in (
        ("category", sub.c.category_id), ("classification", sub.c.classification), ("status", sub.c.lifecycle_state),
    ):  # fmt: skip
        rows = db.execute(
            select(column, func.count()).group_by(column).order_by(func.count().desc(), column)
        ).all()
        facets[name] = [{"value": str(v), "count": c} for v, c in rows]
    dept = db.execute(
        select(DocumentAssociation.ref_id, func.count(func.distinct(sub.c.id)))
        .join(sub, sub.c.id == DocumentAssociation.document_id)
        .where(DocumentAssociation.dimension == "department")
        .group_by(DocumentAssociation.ref_id)
        .order_by(func.count(func.distinct(sub.c.id)).desc(), DocumentAssociation.ref_id)
    ).all()
    facets["department"] = [{"value": str(v), "count": c} for v, c in dept]
    return facets
