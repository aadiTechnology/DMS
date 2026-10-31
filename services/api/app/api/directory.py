import uuid

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.tenancy import Principal, get_tenant_db, require_permission
from app.db.models import Department, EmployeeProfile, TenantMembership

router = APIRouter(prefix="/api/v1", tags=["directory"])


class PersonOut(BaseModel):
    membership_id: uuid.UUID
    full_name: str
    department: str | None


def _like(text: str) -> str:
    return "%" + text.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_") + "%"


@router.get("/directory", response_model=list[PersonOut])
def find_colleagues(
    q: str = Query("", max_length=80),
    limit: int = Query(20, ge=1, le=50),
    principal: Principal = Depends(require_permission("document.share")),
    db: Session = Depends(get_tenant_db),
):
    """Active colleagues in your organization by name, for choosing who to share with. Shows only
    the name and department (never email or role); excludes you and people who have left."""
    stmt = (
        select(TenantMembership.id, EmployeeProfile.full_name, Department.name)
        .join(EmployeeProfile, EmployeeProfile.membership_id == TenantMembership.id)
        .outerjoin(Department, Department.id == EmployeeProfile.department_id)
        .where(
            TenantMembership.tenant_id == principal.tenant_id,
            TenantMembership.status == "active",
            TenantMembership.user_id != principal.user_id,
            EmployeeProfile.employment_status != "exited",
        )
        .order_by(EmployeeProfile.full_name, TenantMembership.id)
        .limit(limit)
    )
    if q.strip():
        stmt = stmt.where(EmployeeProfile.full_name.ilike(_like(q.strip()), escape="\\"))
    return [PersonOut(membership_id=m, full_name=n, department=d) for m, n, d in db.execute(stmt)]
