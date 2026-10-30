import uuid
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.ratelimit import limit_search
from app.core.tenancy import Principal, get_principal, get_tenant_db, require_permission
from app.services import audit, search
from app.services.access import PRIVILEGE
from app.services.access_sql import load_viewer
from app.services.org import Invalid
from app.storage import get_storage

router = APIRouter(prefix="/api/v1/search", tags=["search"])
manage = require_permission("admin.manage_organization")


class ResultItem(BaseModel):
    id: uuid.UUID
    title: str
    category_id: uuid.UUID
    classification: str
    lifecycle_state: str
    owner_membership_id: uuid.UUID
    current_version_number: int | None
    filename: str | None
    content_type: str | None
    size_bytes: int | None
    created_at: datetime
    updated_at: datetime


class FacetValue(BaseModel):
    value: str
    count: int


class SearchOut(BaseModel):
    items: list[ResultItem]
    total: int
    facets: dict[str, list[FacetValue]]
    limit: int
    offset: int


@router.get("", response_model=SearchOut)
def search_documents(
    q: str | None = Query(None, max_length=200),
    category_id: uuid.UUID | None = None,
    include_subcategories: bool = True,
    department_id: uuid.UUID | None = None,
    branch_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
    employee_id: uuid.UUID | None = None,
    owner_id: uuid.UUID | None = None,
    uploader_id: uuid.UUID | None = None,
    status_filter: Literal["draft", "submitted", "under_review", "approved", "rejected", "archived"]
    | None = Query(None, alias="status"),
    classification: Literal["public", "internal", "confidential", "highly_confidential"]
    | None = None,
    tag_id: uuid.UUID | None = None,
    date_field: Literal["created", "modified", "uploaded"] = "created",
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    sort: Literal["relevance", "date", "title"] = "relevance",
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0, le=10_000),
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_tenant_db),
):
    """Search and list the documents you are allowed to see. With no `q` this is the filtered
    document list. Results, `total` and facet counts are computed only over documents the access
    policy lets you see, so nothing about hidden documents can leak through them."""
    limit_search(str(principal.user_id))
    viewer = load_viewer(db, principal.tenant_id, principal.user_id)
    if viewer is None or "document.view_metadata" not in viewer.permissions:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Permission denied")
    params = search.SearchParams(
        q=q, category_id=category_id, include_subcategories=include_subcategories,
        department_id=department_id, branch_id=branch_id, project_id=project_id,
        employee_id=employee_id, owner_id=owner_id, uploader_id=uploader_id, status=status_filter,
        classification=classification, tag_id=tag_id, date_field=date_field, date_from=date_from,
        date_to=date_to, sort=sort, limit=limit, offset=offset,
    )  # fmt: skip
    try:
        result = search.search(db, principal.tenant_id, viewer, params)
    except Invalid as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from None
    if PRIVILEGE in viewer.permissions:
        audit.record(
            db, tenant_id=principal.tenant_id, actor_user_id=principal.user_id,
            action="document.privileged_search", resource_type="search", privileged=True,
            details={"has_query": bool(q), "total": result["total"]},
        )  # fmt: skip
    items = []
    for row in result["items"]:
        d = row["document"]
        items.append(
            ResultItem(
                id=d.id, title=d.title, category_id=d.category_id, classification=d.classification,
                lifecycle_state=d.lifecycle_state, owner_membership_id=d.owner_membership_id,
                current_version_number=d.current_version_number, filename=row["filename"],
                content_type=row["content_type"], size_bytes=row["size_bytes"],
                created_at=d.created_at, updated_at=d.updated_at,
            )
        )  # fmt: skip
    return SearchOut(
        items=items, total=result["total"], limit=result["limit"], offset=result["offset"],
        facets={k: [FacetValue(**v) for v in vals] for k, vals in result["facets"].items()},
    )  # fmt: skip


# ---- index health (administrators) ------------------------------------------------------


class FailureItem(BaseModel):
    document_id: uuid.UUID
    reason: str | None
    attempts: int
    updated_at: datetime


class IndexStatusOut(BaseModel):
    counts: dict[str, int]
    failures: list[FailureItem]


@router.get("/index/status", response_model=IndexStatusOut)
def index_status(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    principal: Principal = Depends(manage),
    db: Session = Depends(get_tenant_db),
):
    """Extraction health. Failures list document ids and reasons only (no titles or content)."""
    failures = search.list_failures(db, principal.tenant_id, limit, offset)
    return IndexStatusOut(
        counts=search.index_status(db, principal.tenant_id),
        failures=[
            FailureItem(
                document_id=f.document_id,
                reason=f.failure_reason,
                attempts=f.attempts,
                updated_at=f.updated_at,
            )
            for f in failures
        ],
    )


@router.post("/index/retry")
def retry_failed(
    principal: Principal = Depends(manage), db: Session = Depends(get_tenant_db)
) -> dict[str, Any]:
    """Queue every failed extraction again."""
    count = search.requeue_failures(db, principal.tenant_id)
    audit.record(
        db, tenant_id=principal.tenant_id, actor_user_id=principal.user_id,
        action="search.index_retry", resource_type="search", details={"requeued": count},
    )  # fmt: skip
    return {"requeued": count}


@router.post("/index/run")
def run_index(
    principal: Principal = Depends(manage), limit: int = Query(10, ge=1, le=50)
) -> dict[str, Any]:
    """Process queued extractions now (a scheduled worker does this in production)."""
    stats = search.process_pending(principal.tenant_id, get_storage(), get_settings(), limit=limit)
    return {"indexed": stats.indexed, "failed": stats.failed, "unsupported": stats.unsupported}
