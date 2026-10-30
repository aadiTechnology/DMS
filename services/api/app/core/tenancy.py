import uuid
from collections.abc import Iterator
from dataclasses import dataclass

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import decode_access_token
from app.db.tenant_session import auth_session, tenant_session
from app.services import audit
from app.services.auth import is_session_usable
from app.services.rbac import has_permission

_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class Principal:
    """The authenticated caller. Tenant comes from the server-side session, never the client."""

    user_id: uuid.UUID
    tenant_id: uuid.UUID
    session_id: uuid.UUID | None = None


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required",
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_principal(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> Principal:
    """Deny by default: valid signed token AND a live session AND active user/membership/tenant.
    Checking the session on every request is what makes revocation immediate."""
    if creds is None:
        raise _unauthorized()
    try:
        claims = decode_access_token(get_settings(), creds.credentials)
        principal = Principal(
            user_id=uuid.UUID(claims["sub"]),
            tenant_id=uuid.UUID(claims["tid"]),
            session_id=uuid.UUID(claims["sid"]),
        )
    except (jwt.PyJWTError, ValueError, KeyError):
        raise _unauthorized() from None
    with auth_session() as db:
        if not is_session_usable(db, principal.session_id):
            raise _unauthorized()
    return principal


def get_tenant_db(principal: Principal = Depends(get_principal)) -> Iterator[Session]:
    with tenant_session(principal.tenant_id) as session:
        yield session


def require_permission(code: str):
    """Dependency factory: 403 unless the caller's roles grant `code`. Denials are audited in a
    separate transaction (the request transaction is rolled back when the 403 is raised)."""

    def dependency(
        principal: Principal = Depends(get_principal), db: Session = Depends(get_tenant_db)
    ) -> Principal:
        if has_permission(db, principal.tenant_id, principal.user_id, code):
            return principal
        with tenant_session(principal.tenant_id) as denial_db:
            audit.record(
                denial_db,
                tenant_id=principal.tenant_id,
                actor_user_id=principal.user_id,
                action="authz.denied",
                resource_type="permission",
                resource_id=code,
                outcome="denied",
            )
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission denied")

    return dependency
