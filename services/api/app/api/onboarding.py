import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy.orm import Session

from app.api.org import EmployeeOut, _employee_out, _errors
from app.core.config import get_settings
from app.core.tenancy import Principal, get_tenant_db, require_permission
from app.services import onboarding, org

router = APIRouter(prefix="/api/v1", tags=["onboarding"])
manage_users = require_permission("admin.manage_users")
manage_org = require_permission("admin.manage_organization")


class InviteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    full_name: str = Field(min_length=1, max_length=200)
    role_id: uuid.UUID | None = None
    employee_number: str | None = Field(None, max_length=64)


@router.post("/invitations", response_model=EmployeeOut, status_code=status.HTTP_201_CREATED)
def create_invitation(
    body: InviteIn,
    principal: Principal = Depends(manage_users),
    db: Session = Depends(get_tenant_db),
):
    """Invite a person by email: creates their (pending) employee record and sends a single-use
    setup link. The email is sent only after the record is saved."""
    with _errors():
        membership, messages = onboarding.invite(
            db,
            get_settings(),
            principal.tenant_id,
            principal.user_id,
            email=body.email,
            full_name=body.full_name,
            role_id=body.role_id,
            employee_number=body.employee_number,
        )
        row = org.get_employee(db, principal.tenant_id, membership.id)
    db.info["outbox"].extend(messages)
    return _employee_out(row)


@router.get("/invitations", response_model=list[EmployeeOut])
def list_invitations(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    principal: Principal = Depends(manage_users),
    db: Session = Depends(get_tenant_db),
):
    rows = org.list_employees(db, principal.tenant_id, status="invited", limit=limit, offset=offset)
    return [_employee_out(r) for r in rows]


@router.post("/invitations/{membership_id}/resend", status_code=status.HTTP_202_ACCEPTED)
def resend_invitation(
    membership_id: uuid.UUID,
    principal: Principal = Depends(manage_users),
    db: Session = Depends(get_tenant_db),
):
    with _errors():
        messages = onboarding.resend_invitation(
            db, get_settings(), principal.tenant_id, principal.user_id, membership_id
        )
    db.info["outbox"].extend(messages)
    return {"detail": "Invitation sent again; earlier links no longer work"}


@router.delete("/invitations/{membership_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_invitation(
    membership_id: uuid.UUID,
    principal: Principal = Depends(manage_users),
    db: Session = Depends(get_tenant_db),
):
    with _errors():
        onboarding.revoke_invitation(db, principal.tenant_id, principal.user_id, membership_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---- self-registration approval ---------------------------------------------------------


class RegistrationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    full_name: str
    status: str
    created_at: datetime
    decided_at: datetime | None


class DecisionIn(BaseModel):
    note: str | None = Field(None, max_length=300)


@router.get("/registration-requests", response_model=list[RegistrationOut])
def list_registration_requests(
    request_status: Literal["pending", "approved", "rejected"] = Query("pending", alias="status"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    principal: Principal = Depends(manage_users),
    db: Session = Depends(get_tenant_db),
):
    return onboarding.list_registrations(db, principal.tenant_id, request_status, limit, offset)


@router.post(
    "/registration-requests/{request_id}/{decision}", status_code=status.HTTP_204_NO_CONTENT
)
def decide_registration_request(
    request_id: uuid.UUID,
    decision: Literal["approve", "reject"],
    body: DecisionIn | None = None,
    principal: Principal = Depends(manage_users),
    db: Session = Depends(get_tenant_db),
):
    """Approving sends the person an invitation email; rejecting sends nothing."""
    with _errors():
        messages = onboarding.decide_registration(
            db,
            get_settings(),
            principal.tenant_id,
            principal.user_id,
            request_id,
            decision == "approve",
            body.note if body else None,
        )
    db.info["outbox"].extend(messages)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---- organization settings ----------------------------------------------------------------


class SettingsOut(BaseModel):
    slug: str | None
    self_registration_enabled: bool


class SettingsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    self_registration_enabled: bool


@router.get("/tenant/settings", response_model=SettingsOut)
def get_settings_endpoint(
    principal: Principal = Depends(manage_org), db: Session = Depends(get_tenant_db)
):
    from app.db.models import Tenant

    tenant = db.get(Tenant, principal.tenant_id)
    return SettingsOut(slug=tenant.slug, self_registration_enabled=tenant.self_registration_enabled)


@router.patch("/tenant/settings", response_model=SettingsOut)
def update_settings(
    body: SettingsIn,
    principal: Principal = Depends(manage_org),
    db: Session = Depends(get_tenant_db),
):
    try:
        tenant = onboarding.set_self_registration(
            db, principal.tenant_id, principal.user_id, body.self_registration_enabled
        )
    except onboarding.NotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="not found") from None
    return SettingsOut(slug=tenant.slug, self_registration_enabled=tenant.self_registration_enabled)
