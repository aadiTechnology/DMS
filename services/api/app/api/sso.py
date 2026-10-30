import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.api.auth import TokenOut, _tokens
from app.core.config import get_settings
from app.core.ratelimit import limit_auth_requests
from app.db.tenant_session import auth_session
from app.services import sso

router = APIRouter(prefix="/api/v1/auth/sso", tags=["authentication"])
Provider = Literal["google", "microsoft"]
FAILED = "Sign-in failed"


class ProviderOut(BaseModel):
    provider: str
    client_id: str


class SsoIn(BaseModel):
    id_token: str = Field(min_length=20, max_length=8192)
    nonce: str | None = Field(None, max_length=200)
    tenant_id: uuid.UUID | None = None
    invite_token: str | None = Field(None, min_length=20, max_length=200)


@router.get("/providers", response_model=list[ProviderOut])
def providers():
    """Which providers are configured (public client ids only)."""
    settings = get_settings()
    return [
        ProviderOut(provider=p, client_id=sso.client_id(settings, p))
        for p in ("google", "microsoft")
        if sso.client_id(settings, p)
    ]


@router.post("/{provider}", response_model=TokenOut, dependencies=[Depends(limit_auth_requests)])
def sso_sign_in(provider: Provider, body: SsoIn):
    """Sign in with a Google/Microsoft ID token. Existing accounts only; never creates one."""
    settings = get_settings()
    try:
        identity = sso.verify_id_token(settings, provider, body.id_token, body.nonce)
    except sso.ProviderDisabled:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Provider not available") from None
    except sso.SsoError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail=FAILED) from None
    with auth_session() as db:
        result = sso.sso_login(db, settings, identity, body.tenant_id, body.invite_token)
    if result.status == "tenant_required":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={
                "code": "tenant_required",
                "tenants": [{"id": str(t["id"]), "name": t["name"]} for t in result.tenants],
            },
        )
    if result.status != "ok":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail=FAILED)
    return _tokens(result)
