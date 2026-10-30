import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy.orm import Session

from app.core.tenancy import Principal, get_principal, get_tenant_db, require_permission
from app.services import org

router = APIRouter(prefix="/api/v1", tags=["organization"])
Kind = Literal["departments", "branches", "projects", "designations"]
manage = require_permission("admin.manage_organization")


@contextmanager
def _errors() -> Iterator[None]:
    try:
        yield
    except org.NotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"{exc} not found") from None
    except org.Conflict as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from None
    except org.Invalid as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from None


class OrgIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(None, max_length=200)
    code: str | None = Field(None, max_length=40)
    parent_id: uuid.UUID | None = None
    manager_membership_id: uuid.UUID | None = None
    status: Literal["active", "inactive"] | None = None


class OrgOut(BaseModel):
    id: uuid.UUID
    name: str
    code: str | None = None
    status: str
    parent_id: uuid.UUID | None = None
    manager_membership_id: uuid.UUID | None = None
    created_at: datetime


def _org_out(row) -> OrgOut:
    return OrgOut(
        id=row.id,
        name=row.name,
        code=getattr(row, "code", None),
        status=row.status,
        parent_id=getattr(row, "parent_id", None),
        manager_membership_id=getattr(row, "manager_membership_id", None),
        created_at=row.created_at,
    )


@router.get("/org/{kind}", response_model=list[OrgOut])
def list_entities(
    kind: Kind,
    status_filter: Literal["active", "inactive"] | None = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_tenant_db),
):
    """Readable by every member (needed by upload forms and filters)."""
    rows = org.list_entities(db, principal.tenant_id, kind, status_filter, limit, offset)
    return [_org_out(r) for r in rows]


@router.post("/org/{kind}", response_model=OrgOut, status_code=status.HTTP_201_CREATED)
def create_entity(
    kind: Kind,
    body: OrgIn,
    principal: Principal = Depends(manage),
    db: Session = Depends(get_tenant_db),
):
    with _errors():
        row = org.create_entity(
            db, principal.tenant_id, principal.user_id, kind, body.model_dump(exclude_unset=True)
        )
    return _org_out(row)


@router.patch("/org/{kind}/{entity_id}", response_model=OrgOut)
def update_entity(
    kind: Kind,
    entity_id: uuid.UUID,
    body: OrgIn,
    principal: Principal = Depends(manage),
    db: Session = Depends(get_tenant_db),
):
    """Edit fields or deactivate/reactivate via `status`. There is no delete (PRD ORG-008)."""
    with _errors():
        row = org.update_entity(
            db,
            principal.tenant_id,
            principal.user_id,
            kind,
            entity_id,
            body.model_dump(exclude_unset=True),
        )
    return _org_out(row)


# ---- employees ----------------------------------------------------------------------------


class ProfileIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    full_name: str | None = Field(None, max_length=200)
    work_email: EmailStr | None = None
    department_id: uuid.UUID | None = None
    branch_id: uuid.UUID | None = None
    designation_id: uuid.UUID | None = None
    reporting_manager_membership_id: uuid.UUID | None = None
    employment_status: Literal["active", "on_leave", "exited"] | None = None


class EmployeeOut(BaseModel):
    membership_id: uuid.UUID
    user_id: uuid.UUID
    membership_status: str
    employee_number: str | None
    joined_at: datetime
    full_name: str | None = None
    work_email: str | None = None
    department_id: uuid.UUID | None = None
    branch_id: uuid.UUID | None = None
    designation_id: uuid.UUID | None = None
    reporting_manager_membership_id: uuid.UUID | None = None
    employment_status: str | None = None


def _employee_out(row) -> EmployeeOut:
    m, p = row
    return EmployeeOut(
        membership_id=m.id,
        user_id=m.user_id,
        membership_status=m.status,
        employee_number=m.employee_number,
        joined_at=m.joined_at,
        full_name=p.full_name if p else None,
        work_email=p.work_email if p else None,
        department_id=p.department_id if p else None,
        branch_id=p.branch_id if p else None,
        designation_id=p.designation_id if p else None,
        reporting_manager_membership_id=p.reporting_manager_membership_id if p else None,
        employment_status=p.employment_status if p else None,
    )


@router.get("/employees", response_model=list[EmployeeOut])
def list_employees(
    department_id: uuid.UUID | None = None,
    branch_id: uuid.UUID | None = None,
    membership_status: Literal["invited", "active", "inactive"] | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    principal: Principal = Depends(manage),
    db: Session = Depends(get_tenant_db),
):
    rows = org.list_employees(
        db,
        principal.tenant_id,
        department_id=department_id,
        branch_id=branch_id,
        status=membership_status,
        limit=limit,
        offset=offset,
    )
    return [_employee_out(r) for r in rows]


@router.get("/employees/{membership_id}", response_model=EmployeeOut)
def get_employee(
    membership_id: uuid.UUID,
    principal: Principal = Depends(manage),
    db: Session = Depends(get_tenant_db),
):
    with _errors():
        return _employee_out(org.get_employee(db, principal.tenant_id, membership_id))


@router.put("/employees/{membership_id}/profile", response_model=EmployeeOut)
def put_profile(
    membership_id: uuid.UUID,
    body: ProfileIn,
    principal: Principal = Depends(manage),
    db: Session = Depends(get_tenant_db),
):
    """Create or update the employee's organizational profile (only the fields you send)."""
    with _errors():
        org.upsert_profile(
            db,
            principal.tenant_id,
            principal.user_id,
            membership_id,
            body.model_dump(exclude_unset=True),
        )
        return _employee_out(org.get_employee(db, principal.tenant_id, membership_id))


# ---- project members -------------------------------------------------------------------


class ProjectMemberIn(BaseModel):
    project_role: str = Field("member", min_length=1, max_length=60)
    starts_on: date | None = None
    ends_on: date | None = None


class ProjectMemberOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    membership_id: uuid.UUID
    project_role: str
    starts_on: date
    ends_on: date | None


@router.get("/projects/{project_id}/members", response_model=list[ProjectMemberOut])
def list_project_members(
    project_id: uuid.UUID,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    principal: Principal = Depends(manage),
    db: Session = Depends(get_tenant_db),
):
    with _errors():
        return org.list_project_members(db, principal.tenant_id, project_id, limit, offset)


@router.put("/projects/{project_id}/members/{membership_id}", response_model=ProjectMemberOut)
def set_project_member(
    project_id: uuid.UUID,
    membership_id: uuid.UUID,
    body: ProjectMemberIn,
    principal: Principal = Depends(manage),
    db: Session = Depends(get_tenant_db),
):
    with _errors():
        return org.set_project_member(
            db,
            principal.tenant_id,
            principal.user_id,
            project_id,
            membership_id,
            body.project_role,
            body.starts_on,
            body.ends_on,
        )


@router.delete("/projects/{project_id}/members/{membership_id}", status_code=204)
def end_project_member(
    project_id: uuid.UUID,
    membership_id: uuid.UUID,
    principal: Principal = Depends(manage),
    db: Session = Depends(get_tenant_db),
):
    """Ends the assignment today; history is kept."""
    with _errors():
        org.end_project_member(
            db, principal.tenant_id, principal.user_id, project_id, membership_id
        )
    return Response(status_code=204)
