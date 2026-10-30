import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.core.tenancy import Principal, get_principal, get_tenant_db
from app.repositories.memberships import MembershipRepository

router = APIRouter(prefix="/api/v1/memberships", tags=["organization"])


class MembershipOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    status: str
    employee_number: str | None
    joined_at: datetime


@router.get("", response_model=list[MembershipOut])
def list_memberships(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_tenant_db),
):
    """Members of the caller's own tenant only."""
    return MembershipRepository(db, principal.tenant_id).list(limit=limit, offset=offset)
