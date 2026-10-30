"""Categories, versioned category policy + metadata schema, and tags (PRD sections 6, 8.4).

Callers pass the tenant-bound session. Nothing is deleted: categories and tags are deactivated.
A category's policy and metadata fields live in immutable, numbered versions so existing
documents keep the schema they were created under (CAT-004); a change creates a new version.
"""

import re
import unicodedata
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import Category, CategoryVersion, MetadataFieldDefinition, Tag, Tenant
from app.services import audit
from app.services.metadata import MetadataInvalid, validate_field_set
from app.services.org import Conflict, Invalid, NotFound

CLASSIFICATIONS = ("public", "internal", "confidential", "highly_confidential")
DIMENSIONS = ("department", "branch", "project", "employee")
SYSTEM_TAGS = ("Pending", "Approved", "Archived")  # TAG-003
MAX_PAGE_SIZE = 200
MAX_APPROVAL_STEPS = 5
STEP_TYPES = ("user", "role", "department_manager")
_EXT = re.compile(r"^[a-z0-9]{1,10}$")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def _page(limit: int, offset: int) -> tuple[int, int]:
    return max(1, min(limit, MAX_PAGE_SIZE)), max(0, offset)


def _clean_name(value: Any, field: str, limit: int) -> str:
    name = re.sub(r"\s+", " ", unicodedata.normalize("NFC", str(value or ""))).strip()
    if not name or len(name) > limit or _CONTROL.search(name):
        raise Invalid(f"{field}: required, up to {limit} characters, no control characters")
    return name


# ---- policy -----------------------------------------------------------------------------


def normalize_policy(policy: dict[str, Any] | None) -> dict[str, Any]:
    p = dict(policy or {})
    unknown = set(p) - {
        "approval_required",
        "required_dimensions",
        "allowed_extensions",
        "retention_days",
        "review_interval_days",
        "expiry_action",
        "reminder_days",
        "approval_steps",
    }
    if unknown:
        raise Invalid(f"policy: unknown setting(s): {', '.join(sorted(unknown))}")
    dims = p.get("required_dimensions") or []
    if not isinstance(dims, list) or not set(dims) <= set(DIMENSIONS):
        raise Invalid(f"policy.required_dimensions: use any of {', '.join(DIMENSIONS)}")
    exts = p.get("allowed_extensions")
    if exts is not None:
        exts = [str(e).lower().lstrip(".") for e in exts]
        if not exts or len(exts) > 50 or not all(_EXT.match(e) for e in exts):
            raise Invalid("policy.allowed_extensions: up to 50 plain extensions such as pdf, docx")
    for name in ("retention_days", "review_interval_days"):
        v = p.get(name)
        if v is not None and (isinstance(v, bool) or not isinstance(v, int) or not 1 <= v <= 36500):
            raise Invalid(f"policy.{name}: whole number of days between 1 and 36500, or empty")
    if p.get("expiry_action", "archive") != "archive":
        raise Invalid("policy.expiry_action: only 'archive' (deletion needs a separate approval)")
    days = p.get("reminder_days") or []
    if (
        not isinstance(days, list)
        or len(days) > 10
        or not all(isinstance(d, int) and not isinstance(d, bool) and 0 <= d <= 365 for d in days)
    ):
        raise Invalid("policy.reminder_days: up to 10 whole numbers of days between 0 and 365")
    steps = p.get("approval_steps") or []
    if not isinstance(steps, list) or len(steps) > MAX_APPROVAL_STEPS:
        raise Invalid(f"policy.approval_steps: at most {MAX_APPROVAL_STEPS} steps")
    clean_steps = []
    for step in steps:
        kind = step.get("type") if isinstance(step, dict) else None
        ref = step.get("ref") if isinstance(step, dict) else None
        if kind not in STEP_TYPES or (kind == "department_manager") != (ref is None):
            raise Invalid(
                "policy.approval_steps: each step is {type: user|role, ref: id} or "
                "{type: department_manager}"
            )
        clean_steps.append({"type": kind, "ref": str(ref) if ref else None})
    if clean_steps and not p.get("approval_required", False):
        raise Invalid("policy.approval_steps: only valid when approval_required is true")
    return {
        "approval_steps": clean_steps,
        "approval_required": bool(p.get("approval_required", False)),
        "required_dimensions": sorted(set(dims)),
        "allowed_extensions": sorted(set(exts)) if exts is not None else None,
        "retention_days": p.get("retention_days"),
        "review_interval_days": p.get("review_interval_days"),
        "expiry_action": "archive",
        "reminder_days": sorted(set(days), reverse=True),
    }


def validate_approval_steps(db: Session, tenant_id, steps: list[dict]) -> None:
    """Reviewer references must be real, active members/roles of this organization."""
    from app.db.models import Role, TenantMembership

    for step in steps:
        if step["type"] == "user":
            m = db.get(TenantMembership, uuid.UUID(step["ref"]))
            if m is None or m.tenant_id != tenant_id or m.status != "active":
                raise Invalid("policy.approval_steps: reviewer must be an active employee")
        elif step["type"] == "role":
            r = db.get(Role, uuid.UUID(step["ref"]))
            if r is None or r.tenant_id != tenant_id or r.status != "active":
                raise Invalid("policy.approval_steps: role must be an active role")


# ---- categories -------------------------------------------------------------------------


def _all(db: Session, tenant_id) -> dict:
    return {c.id: c for c in db.scalars(select(Category).where(Category.tenant_id == tenant_id))}


def _chain(cat: Category, everything: dict) -> list[Category]:
    chain, node, guard = [], cat, 0
    while node is not None and guard < 100:
        chain.append(node)
        node = everything.get(node.parent_id)
        guard += 1
    return list(reversed(chain))  # root first


def describe(cat: Category, everything: dict) -> dict[str, Any]:
    chain = _chain(cat, everything)
    return {"category": cat, "path": " > ".join(c.name for c in chain), "depth": len(chain)}


def _subtree_height(cat_id, everything: dict) -> int:
    children = [c for c in everything.values() if c.parent_id == cat_id]
    return 1 + max((_subtree_height(c.id, everything) for c in children), default=0)


def _check_placement(everything: dict, tenant_id, name: str, parent_id, self_id=None) -> None:
    max_depth = get_settings().CATEGORY_MAX_DEPTH
    parent = None
    if parent_id is not None:
        parent = everything.get(parent_id)
        if parent is None or parent.tenant_id != tenant_id or parent.status != "active":
            raise Invalid("parent_id: must be an active category")
        if self_id is not None and self_id in {c.id for c in _chain(parent, everything)}:
            raise Invalid("parent_id: would place a category under itself")
    parent_depth = len(_chain(parent, everything)) if parent else 0
    height = _subtree_height(self_id, everything) if self_id else 1
    if parent_depth + height > max_depth:
        raise Invalid(f"categories can be at most {max_depth} levels deep")
    clash = any(
        c.parent_id == parent_id and c.id != self_id and c.name.lower() == name.lower()
        for c in everything.values()
    )
    if clash:
        raise Conflict("A category with that name already exists at this level")


def _write_version(db, tenant_id, actor_id, cat: Category, number: int, policy, fields):
    version = CategoryVersion(
        tenant_id=tenant_id,
        category_id=cat.id,
        version_number=number,
        created_by_user_id=actor_id,
        **policy,
    )
    db.add(version)
    db.flush()
    for field in fields:
        db.add(
            MetadataFieldDefinition(tenant_id=tenant_id, category_version_id=version.id, **field)
        )
    db.flush()
    return version


def create_category(
    db: Session,
    tenant_id,
    actor_id,
    *,
    name,
    parent_id=None,
    default_classification="internal",
    policy=None,
    fields=None,
):
    name = _clean_name(name, "name", 200)
    if default_classification not in CLASSIFICATIONS:
        raise Invalid(f"default_classification: use one of {', '.join(CLASSIFICATIONS)}")
    normalized = normalize_policy(policy)
    field_set = validate_field_set(list(fields or []))  # raises MetadataInvalid
    validate_approval_steps(db, tenant_id, normalized["approval_steps"])
    everything = _all(db, tenant_id)
    _check_placement(everything, tenant_id, name, parent_id)
    cat = Category(
        tenant_id=tenant_id,
        parent_id=parent_id,
        name=name,
        default_classification=default_classification,
        current_version_number=1,
    )
    db.add(cat)
    db.flush()
    _write_version(db, tenant_id, actor_id, cat, 1, normalized, field_set)
    audit.record(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_id,
        action="taxonomy.category.created",
        resource_type="category",
        resource_id=cat.id,
        details={"name": name},
    )
    return cat


def update_category(db: Session, tenant_id, actor_id, category_id, data: dict[str, Any]):
    cat = db.get(Category, category_id)
    if cat is None or cat.tenant_id != tenant_id:
        raise NotFound("category")
    unknown = set(data) - {"name", "parent_id", "default_classification", "status"}
    if unknown:
        raise Invalid(f"unsupported field(s): {', '.join(sorted(unknown))}")
    everything = _all(db, tenant_id)
    changed: list[str] = []
    new_name = _clean_name(data["name"], "name", 200) if "name" in data else cat.name
    new_parent = data.get("parent_id", cat.parent_id)
    if new_name != cat.name or new_parent != cat.parent_id:
        _check_placement(everything, tenant_id, new_name, new_parent, self_id=cat.id)
    if new_name != cat.name:
        cat.name = new_name
        changed.append("name")
    if new_parent != cat.parent_id:
        cat.parent_id = new_parent
        changed.append("parent_id")
    if (
        "default_classification" in data
        and data["default_classification"] != cat.default_classification
    ):
        if data["default_classification"] not in CLASSIFICATIONS:
            raise Invalid(f"default_classification: use one of {', '.join(CLASSIFICATIONS)}")
        cat.default_classification = data["default_classification"]
        changed.append("default_classification")
    if changed:
        audit.record(
            db,
            tenant_id=tenant_id,
            actor_user_id=actor_id,
            action="taxonomy.category.updated",
            resource_type="category",
            resource_id=cat.id,
            details={"changed": sorted(changed)},
        )
    status = data.get("status")
    if status is not None and status != cat.status:
        if status not in ("active", "inactive"):
            raise Invalid("status: must be 'active' or 'inactive'")
        if status == "inactive" and any(
            c.parent_id == cat.id and c.status == "active" for c in everything.values()
        ):
            raise Conflict("Deactivate or move the sub-categories first")
        if status == "active" and cat.parent_id and everything[cat.parent_id].status != "active":
            raise Conflict("Reactivate the parent category first")
        cat.status = status
        audit.record(
            db,
            tenant_id=tenant_id,
            actor_user_id=actor_id,
            action=f"taxonomy.category.{'reactivated' if status == 'active' else 'deactivated'}",
            resource_type="category",
            resource_id=cat.id,
            details={"name": cat.name},
        )
    db.flush()
    return cat


def list_categories(db: Session, tenant_id, status=None, limit=50, offset=0):
    limit, offset = _page(limit, offset)
    everything = _all(db, tenant_id)
    rows = sorted(
        everything.values(), key=lambda c: (describe(c, everything)["path"].lower(), str(c.id))
    )
    if status:
        rows = [c for c in rows if c.status == status]
    return [describe(c, everything) for c in rows[offset : offset + limit]]


def get_category(db: Session, tenant_id, category_id):
    everything = _all(db, tenant_id)
    cat = everything.get(category_id)
    if cat is None:
        raise NotFound("category")
    return describe(cat, everything)


def get_version(db: Session, tenant_id, category_id, number: int | None = None):
    cat = db.get(Category, category_id)
    if cat is None or cat.tenant_id != tenant_id:
        raise NotFound("category")
    number = number or cat.current_version_number
    version = db.scalars(
        select(CategoryVersion).where(
            CategoryVersion.category_id == category_id, CategoryVersion.version_number == number
        )
    ).first()
    if version is None:
        raise NotFound("version")
    fields = list(
        db.scalars(
            select(MetadataFieldDefinition)
            .where(MetadataFieldDefinition.category_version_id == version.id)
            .order_by(MetadataFieldDefinition.display_order, MetadataFieldDefinition.key)
        )
    )
    return version, fields


def list_versions(db: Session, tenant_id, category_id):
    cat = db.get(Category, category_id)
    if cat is None or cat.tenant_id != tenant_id:
        raise NotFound("category")
    return list(
        db.scalars(
            select(CategoryVersion)
            .where(CategoryVersion.category_id == category_id)
            .order_by(CategoryVersion.version_number.desc())
        )
    )


def create_version(db: Session, tenant_id, actor_id, category_id, *, policy, fields):
    cat = db.get(Category, category_id)
    if cat is None or cat.tenant_id != tenant_id:
        raise NotFound("category")
    if cat.status != "active":
        raise Conflict("Reactivate the category before changing its configuration")
    normalized = normalize_policy(policy)
    field_set = validate_field_set(list(fields or []))
    validate_approval_steps(db, tenant_id, normalized["approval_steps"])
    number = cat.current_version_number + 1
    _write_version(db, tenant_id, actor_id, cat, number, normalized, field_set)
    cat.current_version_number = number
    audit.record(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_id,
        action="taxonomy.category.version_created",
        resource_type="category",
        resource_id=cat.id,
        details={"version": number, "fields": len(field_set)},
    )
    return get_version(db, tenant_id, category_id, number)


# ---- tags -------------------------------------------------------------------------------


def seed_system_tags(db: Session, tenant_id) -> None:
    existing = {t.name.lower() for t in db.scalars(select(Tag).where(Tag.tenant_id == tenant_id))}
    for name in SYSTEM_TAGS:
        if name.lower() not in existing:
            db.add(Tag(tenant_id=tenant_id, name=name, kind="system"))
    db.flush()


def list_tags(db: Session, tenant_id, kind=None, status=None, limit=50, offset=0):
    limit, offset = _page(limit, offset)
    stmt = select(Tag).where(Tag.tenant_id == tenant_id)
    if kind:
        stmt = stmt.where(Tag.kind == kind)
    if status:
        stmt = stmt.where(Tag.status == status)
    return list(db.scalars(stmt.order_by(Tag.name, Tag.id).limit(limit).offset(offset)))


def create_tag(db: Session, tenant_id, actor_id, name: str, kind: str) -> tuple[Tag, bool]:
    """Returns (tag, created). An existing active tag with the same name (any case) is reused,
    so people converge on one label instead of near-duplicates."""
    if kind not in ("standard", "employee"):
        raise Invalid("kind: 'standard' or 'employee' (system tags are built in)")
    name = _clean_name(name, "name", 80)
    existing = db.scalars(
        select(Tag).where(Tag.tenant_id == tenant_id, Tag.name.ilike(name.replace("%", r"\%")))
    ).first()
    if existing is not None and existing.name.lower() == name.lower():
        if existing.status != "active":
            raise Conflict("That tag exists but is switched off; ask an administrator")
        return existing, False
    if kind == "employee" and not db.get(Tenant, tenant_id).allow_employee_tags:
        raise Conflict("This organization does not allow employee-created tags")
    tag = Tag(tenant_id=tenant_id, name=name, kind=kind, created_by_user_id=actor_id)
    db.add(tag)
    db.flush()
    audit.record(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_id,
        action="taxonomy.tag.created",
        resource_type="tag",
        resource_id=tag.id,
        details={"name": name, "kind": kind},
    )
    return tag, True


def update_tag(db: Session, tenant_id, actor_id, tag_id, data: dict[str, Any]) -> Tag:
    tag = db.get(Tag, tag_id)
    if tag is None or tag.tenant_id != tenant_id:
        raise NotFound("tag")
    if tag.kind == "system":
        raise Invalid("System tags cannot be changed")
    unknown = set(data) - {"name", "status"}
    if unknown:
        raise Invalid(f"unsupported field(s): {', '.join(sorted(unknown))}")
    if "name" in data:
        name = _clean_name(data["name"], "name", 80)
        clash = db.scalars(select(Tag).where(Tag.tenant_id == tenant_id, Tag.id != tag.id)).all()
        if any(t.name.lower() == name.lower() for t in clash):
            raise Conflict("A tag with that name already exists")
        if name != tag.name:
            tag.name = name
            audit.record(
                db,
                tenant_id=tenant_id,
                actor_user_id=actor_id,
                action="taxonomy.tag.updated",
                resource_type="tag",
                resource_id=tag.id,
                details={"name": name},
            )
    status = data.get("status")
    if status is not None and status != tag.status:
        if status not in ("active", "inactive"):
            raise Invalid("status: must be 'active' or 'inactive'")
        tag.status = status
        audit.record(
            db,
            tenant_id=tenant_id,
            actor_user_id=actor_id,
            action=f"taxonomy.tag.{'reactivated' if status == 'active' else 'deactivated'}",
            resource_type="tag",
            resource_id=tag.id,
            details={"name": tag.name},
        )
    db.flush()
    return tag


def set_tag_policy(db: Session, tenant_id, actor_id, allow_employee_tags: bool) -> bool:
    tenant = db.get(Tenant, tenant_id)
    if tenant.allow_employee_tags != allow_employee_tags:
        tenant.allow_employee_tags = allow_employee_tags
        audit.record(
            db,
            tenant_id=tenant_id,
            actor_user_id=actor_id,
            action="tenant.settings.updated",
            resource_type="tenant",
            resource_id=tenant_id,
            details={"allow_employee_tags": allow_employee_tags},
        )
    return tenant.allow_employee_tags


__all__ = ["Conflict", "Invalid", "MetadataInvalid", "NotFound"]
