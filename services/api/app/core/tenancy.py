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
from app.services.auth import is_session_usable

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
