import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.tenancy import Principal, get_principal, get_tenant_db, require_permission
from app.services import rbac

router = APIRouter(prefix="/api/v1", tags=["authorization"])


class RoleOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    is_system: bool
    status: str
    permissions: list[str]


class AssignmentIn(BaseModel):
    membership_id: uuid.UUID
    role_id: uuid.UUID


class AssignmentOut(BaseModel):
    id: uuid.UUID
    membership_id: uuid.UUID
    role_id: uuid.UUID
    created_at: datetime


class MyPermissionsOut(BaseModel):
    permissions: list[str]


def _assignment(a) -> AssignmentOut:
    return AssignmentOut(
        id=a.id, membership_id=a.membership_id, role_id=a.role_id, created_at=a.created_at
    )


@router.get("/me/permissions", response_model=MyPermissionsOut)
def my_permissions(
    principal: Principal = Depends(get_principal), db: Session = Depends(get_tenant_db)
):
    perms = rbac.effective_permissions(db, principal.tenant_id, principal.user_id)
    return MyPermissionsOut(permissions=sorted(perms))


@router.get("/roles", response_model=list[RoleOut])
def list_roles(
    principal: Principal = Depends(require_permission("admin.manage_users")),
    db: Session = Depends(get_tenant_db),
):
    return [
        RoleOut(
            id=r.id,
            name=r.name,
            description=r.description,
            is_system=r.is_system,
            status=r.status,
            permissions=perms,
        )
        for r, perms in rbac.list_roles(db, principal.tenant_id)
    ]


@router.get("/role-assignments", response_model=list[AssignmentOut])
def list_assignments(
    membership_id: uuid.UUID | None = Query(None),
    principal: Principal = Depends(require_permission("admin.manage_users")),
    db: Session = Depends(get_tenant_db),
):
    return [_assignment(a) for a in rbac.list_assignments(db, principal.tenant_id, membership_id)]


@router.post("/role-assignments", response_model=AssignmentOut, status_code=status.HTTP_201_CREATED)
def assign_role(
    body: AssignmentIn,
    principal: Principal = Depends(require_permission("admin.manage_users")),
    db: Session = Depends(get_tenant_db),
):
    try:
        row = rbac.assign_role(
            db, principal.tenant_id, principal.user_id, body.membership_id, body.role_id
        )
    except rbac.NotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"{exc} not found") from None
    return _assignment(row)


@router.delete("/role-assignments/{assignment_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_role(
    assignment_id: uuid.UUID,
    principal: Principal = Depends(require_permission("admin.manage_users")),
    db: Session = Depends(get_tenant_db),
):
    try:
        rbac.revoke_assignment(db, principal.tenant_id, principal.user_id, assignment_id)
    except rbac.NotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="assignment not found") from None
    except rbac.LastAdmin:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="The organization must keep at least one administrator",
        ) from None
    return Response(status_code=status.HTTP_204_NO_CONTENT)
