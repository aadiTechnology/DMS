import uuid
from collections.abc import Iterator
from dataclasses import dataclass

from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.tenant_session import tenant_session


@dataclass(frozen=True)
class Principal:
    """The authenticated caller. Tenant comes from server-side membership, never from the client."""

    user_id: uuid.UUID
    tenant_id: uuid.UUID


def get_principal() -> Principal:
    """Deny by default. Replaced by real token authentication in the auth sprint (Sprint 3);
    until then every protected endpoint answers 401.
    """
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required",
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_tenant_db(principal: Principal = Depends(get_principal)) -> Iterator[Session]:
    with tenant_session(principal.tenant_id) as session:
        yield session
