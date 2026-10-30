import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.org import _errors
from app.core.config import get_settings
from app.core.ratelimit import limit_auth_requests
from app.core.security import MAX_PASSWORD_LENGTH
from app.core.tenancy import Principal, get_principal, get_tenant_db, require_permission
from app.db.models import User
from app.db.tenant_session import auth_session
from app.services import mfa

router = APIRouter(prefix="/api/v1", tags=["authentication"])
manage_users = require_permission("admin.manage_users")


class SetupOut(BaseModel):
    secret: str
    otpauth_uri: str


class CodeIn(BaseModel):
    code: str = Field(min_length=6, max_length=32)


class DisableIn(CodeIn):
    password: str = Field(min_length=1, max_length=MAX_PASSWORD_LENGTH)


class RecoveryOut(BaseModel):
    recovery_codes: list[str]


class StatusOut(BaseModel):
    enabled: bool


def _map(exc: Exception) -> HTTPException:
    if isinstance(exc, mfa.Conflict):
        return HTTPException(status.HTTP_409_CONFLICT, detail=str(exc))
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc))


@router.get("/auth/mfa", response_model=StatusOut)
def mfa_status(principal: Principal = Depends(get_principal)):
    with auth_session() as db:
        return StatusOut(enabled=db.get(User, principal.user_id).mfa_enabled)


@router.post(
    "/auth/mfa/setup", response_model=SetupOut, dependencies=[Depends(limit_auth_requests)]
)
def setup(principal: Principal = Depends(get_principal)):
    """Step 1: get a secret to add to an authenticator app. Not active until confirmed."""
    try:
        with auth_session() as db:
            secret, uri = mfa.begin_setup(db, get_settings(), db.get(User, principal.user_id))
    except (mfa.Conflict, mfa.Invalid) as exc:
        raise _map(exc) from None
    return SetupOut(secret=secret, otpauth_uri=uri)


@router.post(
    "/auth/mfa/enable", response_model=RecoveryOut, dependencies=[Depends(limit_auth_requests)]
)
def enable(body: CodeIn, principal: Principal = Depends(get_principal)):
    """Step 2: confirm with a code. Returns one-time recovery codes, shown only now."""
    try:
        with auth_session() as db:
            user = db.get(User, principal.user_id)
            codes = mfa.confirm_setup(db, get_settings(), user, body.code)
            _audit(db, principal, "auth.mfa_enabled")
    except (mfa.Conflict, mfa.Invalid) as exc:
        raise _map(exc) from None
    return RecoveryOut(recovery_codes=codes)


@router.post(
    "/auth/mfa/disable",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(limit_auth_requests)],
)
def disable(body: DisableIn, principal: Principal = Depends(get_principal)):
    try:
        with auth_session() as db:
            user = db.get(User, principal.user_id)
            mfa.disable(db, get_settings(), user, body.password, body.code)
            _audit(db, principal, "auth.mfa_disabled")
    except (mfa.Conflict, mfa.Invalid) as exc:
        raise _map(exc) from None
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/employees/{membership_id}/mfa/reset", status_code=status.HTTP_204_NO_CONTENT)
def admin_reset(
    membership_id: uuid.UUID,
    principal: Principal = Depends(manage_users),
    db: Session = Depends(get_tenant_db),
):
    """Help-desk recovery for a lost device (audited as privileged)."""
    with _errors():
        mfa.admin_reset(db, principal.tenant_id, principal.user_id, membership_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _audit(db, principal: Principal, action: str) -> None:
    from app.services import audit

    audit.record(
        db,
        tenant_id=principal.tenant_id,
        actor_user_id=principal.user_id,
        action=action,
        resource_type="user",
        resource_id=principal.user_id,
    )
