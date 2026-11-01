import uuid
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.tenancy import Principal, get_principal, get_tenant_db
from app.services import dashboard
from app.services.access_sql import load_viewer

router = APIRouter(prefix="/api/v1", tags=["dashboard"])


class Stats(BaseModel):
    documents: int
    pending_reviews: int
    shared_with_me: int
    storage_bytes: int


class DayCount(BaseModel):
    date: date
    count: int


class ClassCount(BaseModel):
    value: str
    count: int


class RecentDoc(BaseModel):
    id: uuid.UUID
    title: str
    classification: str
    lifecycle_state: str
    created_at: datetime


class QueueRow(BaseModel):
    request_id: uuid.UUID
    document_id: uuid.UUID
    title: str
    submitted_at: datetime


class DueDoc(BaseModel):
    id: uuid.UUID
    title: str
    retention_until: date | None
    review_due_on: date | None


class DueBlock(BaseModel):
    total: int
    items: list[DueDoc]


class ActivityRow(BaseModel):
    action: str
    outcome: str
    occurred_at: datetime
    actor: str | None


class DashboardOut(BaseModel):
    generated_at: datetime
    stats: Stats
    uploads_by_day: list[DayCount]
    by_classification: list[ClassCount]
    recent_documents: list[RecentDoc]
    approvals_queue: list[QueueRow]
    expiring_soon: DueBlock
    activity: list[ActivityRow] | None


@router.get("/dashboard", response_model=DashboardOut)
def get_dashboard(
    principal: Principal = Depends(get_principal), db: Session = Depends(get_tenant_db)
):
    """Figures for the home page, over the documents you may see. `activity` is null unless your
    roles allow reading the audit log."""
    viewer = load_viewer(db, principal.tenant_id, principal.user_id)
    if viewer is None or "document.view_metadata" not in viewer.permissions:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Permission denied")
    return dashboard.build(
        db,
        principal.tenant_id,
        principal.user_id,
        viewer,
        can_see_activity="admin.view_audit" in viewer.permissions,
    )
