"""Organization structure: departments, branches, projects, designations, employee profiles and
project membership. Callers pass the tenant-bound session; every change is audited. Nothing is
ever deleted: entities are deactivated so historical references stay valid (ORG-008).
"""

from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db.models import (
    Branch,
    Department,
    Designation,
    EmployeeProfile,
    Project,
    ProjectMembership,
    TenantMembership,
)
from app.services import audit

MAX_PAGE_SIZE = 200
KINDS: dict[str, type] = {
    "departments": Department,
    "branches": Branch,
    "projects": Project,
    "designations": Designation,
}
SINGULAR = {
    "departments": "department",
    "branches": "branch",
    "projects": "project",
    "designations": "designation",
}
FIELDS: dict[str, set[str]] = {
    "departments": {"name", "code", "parent_id", "manager_membership_id"},
    "branches": {"name", "code"},
    "projects": {"name", "code", "manager_membership_id"},
    "designations": {"name"},
}


class NotFound(Exception):
    """Target is absent from the caller's tenant (other tenants' ids look identical)."""


class Conflict(Exception):
    pass


class Invalid(Exception):
    pass


def _page(limit: int, offset: int) -> tuple[int, int]:
    return max(1, min(limit, MAX_PAGE_SIZE)), max(0, offset)


def _active_membership(db: Session, tenant_id, membership_id, field: str) -> TenantMembership:
    m = db.get(TenantMembership, membership_id)
    if m is None or m.tenant_id != tenant_id or m.status != "active":
        raise Invalid(f"{field}: must be an active employee of this organization")
    return m


def _check_unique(db: Session, model, tenant_id, kind: str, data: dict, self_id=None) -> None:
    clauses = [model.name == data["name"]] if "name" in data else []
    if "code" in data:
        clauses.append(model.code == data["code"])
    if not clauses:
        return
    stmt = select(model.id).where(model.tenant_id == tenant_id, or_(*clauses))
    if self_id is not None:
        stmt = stmt.where(model.id != self_id)
    if db.execute(stmt).first() is not None:
        raise Conflict(f"A {SINGULAR[kind]} with that name or code already exists")


def _clean(kind: str, data: dict[str, Any], creating: bool) -> dict[str, Any]:
    unknown = set(data) - FIELDS[kind] - {"status"}
    if unknown:
        raise Invalid(f"Unsupported field(s) for {kind}: {', '.join(sorted(unknown))}")
    out = dict(data)
    for key in ("name", "code"):
        if key in out:
            out[key] = (out[key] or "").strip()
            if not out[key]:
                raise Invalid(f"{key} must not be empty")
    if creating:
        for key in ("name", "code") if "code" in FIELDS[kind] else ("name",):
            if key not in out:
                raise Invalid(f"{key} is required")
    return out


def _check_parent(db: Session, tenant_id, parent_id, self_id) -> None:
    parent = db.get(Department, parent_id)
    if parent is None or parent.tenant_id != tenant_id or parent.status != "active":
        raise Invalid("parent_id: must be an active department")
    seen, node = set(), parent
    while node is not None:  # walk up; reaching self means a cycle
        if node.id == self_id or node.id in seen:
            raise Invalid("parent_id: would create a cycle")
        seen.add(node.id)
        node = db.get(Department, node.parent_id) if node.parent_id else None


def list_entities(db, tenant_id, kind, status=None, limit=50, offset=0) -> list:
    model = KINDS[kind]
    limit, offset = _page(limit, offset)
    stmt = select(model).where(model.tenant_id == tenant_id)
    if status:
        stmt = stmt.where(model.status == status)
    return list(db.scalars(stmt.order_by(model.name, model.id).limit(limit).offset(offset)))


def create_entity(db: Session, tenant_id, actor_id, kind: str, data: dict[str, Any]):
    model = KINDS[kind]
    data = _clean(kind, data, creating=True)
    data.pop("status", None)
    _check_unique(db, model, tenant_id, kind, data)
    if data.get("manager_membership_id"):
        _active_membership(db, tenant_id, data["manager_membership_id"], "manager_membership_id")
    if data.get("parent_id"):
        _check_parent(db, tenant_id, data["parent_id"], None)
    row = model(tenant_id=tenant_id, **data)
    db.add(row)
    db.flush()
    audit.record(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_id,
        action=f"org.{SINGULAR[kind]}.created",
        resource_type=SINGULAR[kind],
        resource_id=row.id,
        details={"name": row.name},
    )
    return row


def update_entity(db: Session, tenant_id, actor_id, kind: str, entity_id, data: dict[str, Any]):
    model = KINDS[kind]
    row = db.get(model, entity_id)
    if row is None or row.tenant_id != tenant_id:
        raise NotFound(kind)
    data = _clean(kind, data, creating=False)
    new_status = data.pop("status", None)
    if new_status is not None and new_status not in ("active", "inactive"):
        raise Invalid("status: must be 'active' or 'inactive'")
    _check_unique(db, model, tenant_id, kind, data, self_id=row.id)
    if data.get("manager_membership_id"):
        _active_membership(db, tenant_id, data["manager_membership_id"], "manager_membership_id")
    if data.get("parent_id"):
        _check_parent(db, tenant_id, data["parent_id"], row.id)
    changed = [k for k, v in data.items() if getattr(row, k) != v]
    for key in changed:
        setattr(row, key, data[key])
    if changed:
        audit.record(
            db,
            tenant_id=tenant_id,
            actor_user_id=actor_id,
            action=f"org.{SINGULAR[kind]}.updated",
            resource_type=SINGULAR[kind],
            resource_id=row.id,
            details={"changed": sorted(changed)},
        )
    if new_status is not None and new_status != row.status:
        row.status = new_status
        verb = "reactivated" if new_status == "active" else "deactivated"
        audit.record(
            db,
            tenant_id=tenant_id,
            actor_user_id=actor_id,
            action=f"org.{SINGULAR[kind]}.{verb}",
            resource_type=SINGULAR[kind],
            resource_id=row.id,
            details={"name": row.name},
        )
    db.flush()
    return row


# ---- employees --------------------------------------------------------------------------

PROFILE_REFS = {"department_id": Department, "branch_id": Branch, "designation_id": Designation}


def upsert_profile(db: Session, tenant_id, actor_id, membership_id, data: dict[str, Any]):
    membership = db.get(TenantMembership, membership_id)
    if membership is None or membership.tenant_id != tenant_id:
        raise NotFound("employee")
    profile = db.scalars(
        select(EmployeeProfile).where(EmployeeProfile.membership_id == membership_id)
    ).first()
    if profile is None and not (data.get("full_name") or "").strip():
        raise Invalid("full_name is required when creating a profile")
    if "full_name" in data:
        data["full_name"] = (data["full_name"] or "").strip()
        if not data["full_name"]:
            raise Invalid("full_name must not be empty")
    for field, model in PROFILE_REFS.items():
        value = data.get(field)
        if value is not None and (profile is None or getattr(profile, field) != value):
            ref = db.get(model, value)
            if ref is None or ref.tenant_id != tenant_id or ref.status != "active":
                raise Invalid(f"{field}: must be an active {SINGULAR[model.__tablename__]}")
    mgr = data.get("reporting_manager_membership_id")
    if mgr is not None:
        if mgr == membership_id:
            raise Invalid("reporting_manager_membership_id: cannot be the employee")
        _active_membership(db, tenant_id, mgr, "reporting_manager_membership_id")
    if profile is None:
        profile = EmployeeProfile(tenant_id=tenant_id, membership_id=membership_id, **data)
        db.add(profile)
        changed = sorted(data)
    else:
        changed = sorted(k for k, v in data.items() if getattr(profile, k) != v)
        for key in changed:
            setattr(profile, key, data[key])
        profile.updated_at = datetime.now(UTC)
    db.flush()
    if changed:
        audit.record(
            db,
            tenant_id=tenant_id,
            actor_user_id=actor_id,
            action="org.employee_profile.updated",
            resource_type="employee",
            resource_id=membership_id,
            details={"changed": changed},
        )
    return profile


def list_employees(
    db: Session, tenant_id, *, department_id=None, branch_id=None, status=None, limit=50, offset=0
):
    limit, offset = _page(limit, offset)
    stmt = (
        select(TenantMembership, EmployeeProfile)
        .outerjoin(EmployeeProfile, EmployeeProfile.membership_id == TenantMembership.id)
        .where(TenantMembership.tenant_id == tenant_id)
    )
    if department_id:
        stmt = stmt.where(EmployeeProfile.department_id == department_id)
    if branch_id:
        stmt = stmt.where(EmployeeProfile.branch_id == branch_id)
    if status:
        stmt = stmt.where(TenantMembership.status == status)
    stmt = stmt.order_by(EmployeeProfile.full_name.asc().nulls_last(), TenantMembership.id)
    return db.execute(stmt.limit(limit).offset(offset)).all()


def get_employee(db: Session, tenant_id, membership_id):
    row = db.execute(
        select(TenantMembership, EmployeeProfile)
        .outerjoin(EmployeeProfile, EmployeeProfile.membership_id == TenantMembership.id)
        .where(TenantMembership.tenant_id == tenant_id, TenantMembership.id == membership_id)
    ).first()
    if row is None:
        raise NotFound("employee")
    return row


# ---- project membership -----------------------------------------------------------------


def set_project_member(
    db: Session,
    tenant_id,
    actor_id,
    project_id,
    membership_id,
    project_role: str,
    starts_on: date | None,
    ends_on: date | None,
):
    project = db.get(Project, project_id)
    if project is None or project.tenant_id != tenant_id:
        raise NotFound("project")
    if project.status != "active":
        raise Invalid("project is inactive")
    _active_membership(db, tenant_id, membership_id, "membership_id")
    if starts_on and ends_on and ends_on < starts_on:
        raise Invalid("ends_on must not be before starts_on")
    row = db.scalars(
        select(ProjectMembership).where(
            ProjectMembership.project_id == project_id,
            ProjectMembership.membership_id == membership_id,
        )
    ).first()
    if row is None:
        row = ProjectMembership(
            tenant_id=tenant_id, project_id=project_id, membership_id=membership_id
        )
        db.add(row)
    row.project_role = project_role.strip() or "member"
    if starts_on:
        row.starts_on = starts_on
    row.ends_on = ends_on  # re-adding a former member clears the end date
    db.flush()
    audit.record(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_id,
        action="org.project_member.set",
        resource_type="project",
        resource_id=project_id,
        details={"membership_id": str(membership_id), "project_role": row.project_role},
    )
    return row


def end_project_member(db: Session, tenant_id, actor_id, project_id, membership_id) -> None:
    row = db.scalars(
        select(ProjectMembership).where(
            ProjectMembership.tenant_id == tenant_id,
            ProjectMembership.project_id == project_id,
            ProjectMembership.membership_id == membership_id,
        )
    ).first()
    today = datetime.now(UTC).date()
    if row is None or (row.ends_on is not None and row.ends_on <= today):
        raise NotFound("project member")
    row.ends_on = today
    audit.record(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_id,
        action="org.project_member.ended",
        resource_type="project",
        resource_id=project_id,
        details={"membership_id": str(membership_id)},
    )


def list_project_members(db: Session, tenant_id, project_id, limit=50, offset=0):
    limit, offset = _page(limit, offset)
    today = datetime.now(UTC).date()
    project = db.get(Project, project_id)
    if project is None or project.tenant_id != tenant_id:
        raise NotFound("project")
    stmt = (
        select(ProjectMembership)
        .where(
            ProjectMembership.tenant_id == tenant_id,
            ProjectMembership.project_id == project_id,
            or_(ProjectMembership.ends_on.is_(None), ProjectMembership.ends_on >= today),
        )
        .order_by(ProjectMembership.starts_on, ProjectMembership.id)
        .limit(limit)
        .offset(offset)
    )
    return list(db.scalars(stmt))
