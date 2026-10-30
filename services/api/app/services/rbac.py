import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.permissions import ADMIN_ROLE, DEFAULT_ROLES
from app.db.models import Role, RolePermission, TenantMembership, UserRoleAssignment
from app.services import audit


class NotFound(Exception):
    """Target does not exist in the caller's tenant (same answer for other tenants' ids)."""


class LastAdmin(Exception):
    """Refused: a tenant must always keep at least one active organization administrator."""


def effective_permissions(db: Session, tenant_id: uuid.UUID, user_id: uuid.UUID) -> set[str]:
    """Single indexed query: active membership -> live assignments -> active roles -> codes."""
    rows = db.execute(
        select(RolePermission.permission_code)
        .join(Role, Role.id == RolePermission.role_id)
        .join(UserRoleAssignment, UserRoleAssignment.role_id == Role.id)
        .join(TenantMembership, TenantMembership.id == UserRoleAssignment.membership_id)
        .where(
            UserRoleAssignment.tenant_id == tenant_id,
            UserRoleAssignment.revoked_at.is_(None),
            TenantMembership.tenant_id == tenant_id,
            TenantMembership.user_id == user_id,
            TenantMembership.status == "active",
            Role.status == "active",
        )
        .distinct()
    ).all()
    return {r[0] for r in rows}


def has_permission(db: Session, tenant_id: uuid.UUID, user_id: uuid.UUID, code: str) -> bool:
    return code in effective_permissions(db, tenant_id, user_id)


def seed_default_roles(db: Session, tenant_id: uuid.UUID) -> dict[str, uuid.UUID]:
    """Create the system role templates for a tenant. Idempotent; returns name -> role id."""
    existing = {r.name: r for r in db.scalars(select(Role).where(Role.tenant_id == tenant_id))}
    ids: dict[str, uuid.UUID] = {}
    for name, (description, perms) in DEFAULT_ROLES.items():
        role = existing.get(name)
        if role is None:
            role = Role(tenant_id=tenant_id, name=name, description=description, is_system=True)
            db.add(role)
            db.flush()
            db.add_all(
                RolePermission(tenant_id=tenant_id, role_id=role.id, permission_code=p)
                for p in perms
            )
        ids[name] = role.id
    db.flush()
    return ids


def list_roles(db: Session, tenant_id: uuid.UUID) -> list[tuple[Role, list[str]]]:
    roles = list(db.scalars(select(Role).where(Role.tenant_id == tenant_id).order_by(Role.name)))
    perms: dict[uuid.UUID, list[str]] = {r.id: [] for r in roles}
    for rid, code in db.execute(
        select(RolePermission.role_id, RolePermission.permission_code).where(
            RolePermission.tenant_id == tenant_id
        )
    ):
        perms[rid].append(code)
    return [(r, sorted(perms[r.id])) for r in roles]


def assign_role(
    db: Session, tenant_id: uuid.UUID, actor_user_id: uuid.UUID, membership_id, role_id
) -> UserRoleAssignment:
    membership = db.get(TenantMembership, membership_id)
    role = db.get(Role, role_id)
    if membership is None or membership.tenant_id != tenant_id or membership.status == "inactive":
        raise NotFound("membership")
    if role is None or role.tenant_id != tenant_id or role.status != "active":
        raise NotFound("role")
    current = db.scalars(
        select(UserRoleAssignment).where(
            UserRoleAssignment.membership_id == membership_id,
            UserRoleAssignment.role_id == role_id,
            UserRoleAssignment.revoked_at.is_(None),
        )
    ).first()
    if current is not None:
        return current  # idempotent
    row = UserRoleAssignment(
        tenant_id=tenant_id,
        membership_id=membership_id,
        role_id=role_id,
        assigned_by_user_id=actor_user_id,
    )
    db.add(row)
    db.flush()
    audit.record(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="rbac.role_assigned",
        resource_type="user_role_assignment",
        resource_id=row.id,
        details={"membership_id": str(membership_id), "role": role.name},
    )
    return row


def revoke_assignment(
    db: Session, tenant_id: uuid.UUID, actor_user_id: uuid.UUID, assignment_id
) -> None:
    row = db.get(UserRoleAssignment, assignment_id)
    if row is None or row.tenant_id != tenant_id or row.revoked_at is not None:
        raise NotFound("assignment")
    role = db.get(Role, row.role_id)
    if role.name == ADMIN_ROLE and _active_admin_count(db, tenant_id) <= 1:
        raise LastAdmin()
    row.revoked_at = datetime.now(UTC)
    row.revoked_by_user_id = actor_user_id
    audit.record(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="rbac.role_revoked",
        resource_type="user_role_assignment",
        resource_id=row.id,
        details={"membership_id": str(row.membership_id), "role": role.name},
    )


def _active_admin_count(db: Session, tenant_id: uuid.UUID) -> int:
    return db.scalar(
        select(func.count(UserRoleAssignment.id))
        .join(Role, Role.id == UserRoleAssignment.role_id)
        .join(TenantMembership, TenantMembership.id == UserRoleAssignment.membership_id)
        .where(
            UserRoleAssignment.tenant_id == tenant_id,
            UserRoleAssignment.revoked_at.is_(None),
            Role.name == ADMIN_ROLE,
            TenantMembership.status == "active",
        )
    )


def list_assignments(
    db: Session, tenant_id: uuid.UUID, membership_id: uuid.UUID | None = None
) -> list[UserRoleAssignment]:
    stmt = select(UserRoleAssignment).where(
        UserRoleAssignment.tenant_id == tenant_id, UserRoleAssignment.revoked_at.is_(None)
    )
    if membership_id:
        stmt = stmt.where(UserRoleAssignment.membership_id == membership_id)
    return list(db.scalars(stmt.order_by(UserRoleAssignment.created_at)))
