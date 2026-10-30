import re
import uuid

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.models import Tenant, TenantMembership, UserRoleAssignment
from app.db.rls import TENANT_SETTING
from app.services import audit, rbac, taxonomy


def slugify(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:50] or "org"
    return base


def provision_tenant(
    db: Session, name: str, admin_user_id: uuid.UUID, slug: str | None = None
) -> uuid.UUID:
    """Platform operation: create a tenant, its default roles, and its first administrator.

    Runs on the owner connection. The tenant id is generated first and set as the transaction's
    tenant context so row-level security accepts the inserts (it applies even to the owner role
    unless that role is a superuser).
    """
    tenant_id = uuid.uuid4()
    db.execute(text("SELECT set_config(:n, :v, true)"), {"n": TENANT_SETTING, "v": str(tenant_id)})
    slug = slug or slugify(name)
    taken = db.execute(text("SELECT 1 FROM tenants WHERE slug = :s"), {"s": slug}).first()
    if taken:
        slug = f"{slug}-{tenant_id.hex[:6]}"
    db.add(Tenant(id=tenant_id, name=name, slug=slug))
    db.flush()
    membership = TenantMembership(tenant_id=tenant_id, user_id=admin_user_id, status="active")
    db.add(membership)
    roles = rbac.seed_default_roles(db, tenant_id)
    taxonomy.seed_system_tags(db, tenant_id)
    db.flush()
    db.add(
        UserRoleAssignment(
            tenant_id=tenant_id,
            membership_id=membership.id,
            role_id=roles["org_admin"],
            assigned_by_user_id=None,
        )
    )
    audit.record(
        db,
        tenant_id=tenant_id,
        actor_user_id=None,
        action="tenant.provisioned",
        resource_type="tenant",
        resource_id=tenant_id,
        details={"first_admin_user_id": str(admin_user_id)},
    )
    db.flush()
    return tenant_id
