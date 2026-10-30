import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

MAX_PAGE_SIZE = 200


class TenantRepository[T]:
    """Base for tenant-owned tables. Every query is filtered by tenant_id in the application;
    row-level security enforces the same rule in the database. Other tenants' rows are simply
    "not found" so existence is never revealed.
    """

    model: type[T]

    def __init__(self, session: Session, tenant_id: uuid.UUID):
        self.session = session
        self.tenant_id = tenant_id

    def get(self, id_: uuid.UUID) -> T | None:
        stmt = select(self.model).where(
            self.model.id == id_,  # type: ignore[attr-defined]
            self.model.tenant_id == self.tenant_id,  # type: ignore[attr-defined]
        )
        return self.session.scalars(stmt).one_or_none()

    def list(self, limit: int = 50, offset: int = 0) -> list[T]:
        limit = max(1, min(limit, MAX_PAGE_SIZE))
        stmt = (
            select(self.model)
            .where(self.model.tenant_id == self.tenant_id)  # type: ignore[attr-defined]
            .order_by(self.model.id)  # type: ignore[attr-defined]
            .limit(limit)
            .offset(max(0, offset))
        )
        return list(self.session.scalars(stmt))

    def add(self, **fields: Any) -> T:
        """Create a row in the caller's tenant. A client-supplied tenant_id is never honored."""
        fields.pop("tenant_id", None)
        obj = self.model(tenant_id=self.tenant_id, **fields)
        self.session.add(obj)
        self.session.flush()
        return obj
