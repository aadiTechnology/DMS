import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.core.ratelimit import limit_auth_requests
from app.core.security import MAX_PASSWORD_LENGTH
from app.core.tenancy import Principal, get_principal
from app.db.tenant_session import auth_session
from app.services import auth as auth_service

router = APIRouter(prefix="/api/v1/auth", tags=["authentication"])

INVALID = "Invalid email or password"


class LoginIn(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=MAX_PASSWORD_LENGTH)
    tenant_id: uuid.UUID | None = None


class RefreshIn(BaseModel):
    refresh_token: str = Field(min_length=20, max_length=200)


class TokenOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str
    expires_in: int


class MeOut(BaseModel):
    user_id: uuid.UUID
    tenant_id: uuid.UUID


def _tokens(result: auth_service.AuthResult) -> TokenOut:
    t = result.tokens
    return TokenOut(
        access_token=t.access_token,
        refresh_token=t.refresh_token,
        token_type=t.token_type,
        expires_in=t.expires_in,
    )


@router.post("/login", response_model=TokenOut, dependencies=[Depends(limit_auth_requests)])
def login(body: LoginIn):
    # Commit happens when the session block exits, so failed-login counters persist.
    with auth_session() as db:
        result = auth_service.login(db, get_settings(), body.email, body.password, body.tenant_id)
    if result.status == "tenant_required":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={
                "code": "tenant_required",
                "tenants": [{"id": str(t["id"]), "name": t["name"]} for t in result.tenants],
            },
        )
    if result.status != "ok":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail=INVALID)
    return _tokens(result)


@router.post("/refresh", response_model=TokenOut, dependencies=[Depends(limit_auth_requests)])
def refresh(body: RefreshIn):
    with auth_session() as db:
        result = auth_service.refresh(db, get_settings(), body.refresh_token)
    if result.status != "ok":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired session")
    return _tokens(result)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(principal: Principal = Depends(get_principal)):
    with auth_session() as db:
        auth_service.logout(db, principal.session_id)


@router.get("/me", response_model=MeOut)
def me(principal: Principal = Depends(get_principal)):
    return MeOut(user_id=principal.user_id, tenant_id=principal.tenant_id)
