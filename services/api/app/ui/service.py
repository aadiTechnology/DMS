"""UI template catalogue: import and lifecycle (platform side), availability, per-user preference,
tenant default and the fallback chain (tenant side).

Resolution order for what a person sees: their own valid choice, then the organization's approved
default, then the product default, then the built-in system theme (returned as `None`; the web
engine owns that theme). A template that is not published, not available to the organization or no
longer valid is skipped, never applied. Choosing a design changes appearance only: it touches no
data, permission or workflow.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import TenantUiDefault, UiTemplate, UiTemplateVersion, UserUiPreference
from app.services import audit
from app.services.org import Conflict, Invalid, NotFound
from app.ui.templates import validate_template

PRODUCT_CODE = "dms"


def _now() -> datetime:
    return datetime.now(UTC)


def _version_tuple(version: str) -> tuple[int, ...]:
    return tuple(int(p) for p in version.split("."))


# ---- platform side (run inside a platform_session) --------------------------------------


def import_platform_template(
    db: Session, raw: Any, *, product_code: str = PRODUCT_CODE, actor_user_id=None, publish: bool = False
) -> UiTemplate:  # fmt: skip
    """Validate and store a template as a draft (or published). A new version of an existing key
    replaces its current content and keeps the old one in the history; the same or an older
    version is refused."""
    result = validate_template(raw)
    if not result.valid:
        raise Invalid("Invalid template: " + "; ".join(result.errors[:5]))
    config = result.template
    existing = db.scalars(
        select(UiTemplate).where(
            UiTemplate.tenant_id.is_(None),
            UiTemplate.product_code == product_code,
            UiTemplate.template_key == config["key"],
        )
    ).first()
    now = _now()
    if existing is None:
        template = UiTemplate(
            product_code=product_code, template_key=config["key"], scope="platform",
            template_name=config["name"], description=config["description"], config_json=config,
            preview_image_url=config.get("previewImage"), version=config["version"],
            status="draft", created_by=actor_user_id,
        )  # fmt: skip
        db.add(template)
        db.flush()
    else:
        if _version_tuple(config["version"]) <= _version_tuple(existing.version):
            raise Conflict(
                f"Version {config['version']} of '{config['key']}' already exists or is older than {existing.version}"
            )
        template = existing
        template.template_name, template.description = config["name"], config["description"]
        template.config_json, template.version = config, config["version"]
        template.preview_image_url = config.get("previewImage")
        template.updated_at = now
        if (
            template.status == "published"
        ):  # a new version is reviewed before it replaces the live one
            template.status = "draft"
    db.add(
        UiTemplateVersion(template_id=template.id, version=config["version"], config_json=config)
    )
    db.flush()
    if publish:
        publish_template(db, template)
    return template


def publish_template(db: Session, template: UiTemplate) -> UiTemplate:
    if template.status == "archived":
        raise Conflict("An archived template cannot be published; import a new version instead")
    if not validate_template(
        template.config_json
    ).valid:  # defence in depth: never publish bad data
        raise Invalid("The stored template no longer passes validation")
    template.status, template.updated_at = "published", _now()
    db.execute(
        UiTemplateVersion.__table__.update()
        .where(
            UiTemplateVersion.template_id == template.id,
            UiTemplateVersion.version == template.version,
        )
        .values(published_at=_now())
    )
    db.flush()
    return template


def archive_template(db: Session, template: UiTemplate) -> UiTemplate:
    template.status, template.updated_at = "archived", _now()
    db.flush()
    return template


# ---- tenant side ------------------------------------------------------------------------


def list_available(db: Session, tenant_id, product_code: str = PRODUCT_CODE) -> list[UiTemplate]:
    """Published templates this organization may choose (row-level security already hides drafts)."""
    return list(
        db.scalars(
            select(UiTemplate)
            .where(
                UiTemplate.product_code == product_code,
                UiTemplate.status == "published",
                or_(UiTemplate.tenant_id.is_(None), UiTemplate.tenant_id == tenant_id),
            )
            .order_by(UiTemplate.template_name, UiTemplate.id)
        )
    )


def get_available(
    db: Session, tenant_id, template_id, product_code: str = PRODUCT_CODE
) -> UiTemplate:
    template = db.get(UiTemplate, template_id)
    if (
        template is None
        or template.product_code != product_code
        or template.status != "published"
        or template.tenant_id not in (None, tenant_id)
    ):
        raise NotFound("template")
    return template


def _usable(template: UiTemplate | None, tenant_id, product_code: str) -> bool:
    return (
        template is not None
        and template.product_code == product_code
        and template.status == "published"
        and template.tenant_id in (None, tenant_id)
        and validate_template(template.config_json).valid
    )


@dataclass
class Resolved:
    source: str  # user | tenant | product | system
    template: UiTemplate | None


def get_preference(
    db: Session, tenant_id, user_id, product_code: str = PRODUCT_CODE
) -> UserUiPreference | None:
    return db.scalars(
        select(UserUiPreference).where(
            UserUiPreference.tenant_id == tenant_id,
            UserUiPreference.user_id == user_id,
            UserUiPreference.product_code == product_code,
        )
    ).first()


def get_tenant_default(
    db: Session, tenant_id, product_code: str = PRODUCT_CODE
) -> TenantUiDefault | None:
    return db.scalars(
        select(TenantUiDefault).where(
            TenantUiDefault.tenant_id == tenant_id, TenantUiDefault.product_code == product_code
        )
    ).first()


def resolve(db: Session, tenant_id, user_id, product_code: str = PRODUCT_CODE) -> Resolved:
    pref = get_preference(db, tenant_id, user_id, product_code)
    if pref is not None and pref.template_id is not None:
        template = db.get(UiTemplate, pref.template_id)
        if _usable(template, tenant_id, product_code):
            return Resolved("user", template)
    default = get_tenant_default(db, tenant_id, product_code)
    if default is not None and default.template_id is not None:
        template = db.get(UiTemplate, default.template_id)
        if _usable(template, tenant_id, product_code):
            return Resolved("tenant", template)
    key = get_settings().UI_DEFAULT_TEMPLATE_KEY
    template = db.scalars(
        select(UiTemplate).where(
            UiTemplate.tenant_id.is_(None),
            UiTemplate.product_code == product_code,
            UiTemplate.template_key == key,
            UiTemplate.status == "published",
        )
    ).first()
    if _usable(template, tenant_id, product_code):
        return Resolved("product", template)
    return Resolved("system", None)


def set_preference(
    db: Session, tenant_id, user_id, template_id: uuid.UUID | None, product_code: str = PRODUCT_CODE
) -> UserUiPreference:  # fmt: skip
    """Save one person's choice (None resets to the default). Only a published, available and
    valid template can be chosen."""
    if template_id is not None:
        template = get_available(db, tenant_id, template_id, product_code)
        if not _usable(template, tenant_id, product_code):
            raise Invalid("That template is not available")
    pref = get_preference(db, tenant_id, user_id, product_code)
    if pref is None:
        pref = UserUiPreference(tenant_id=tenant_id, user_id=user_id, product_code=product_code)
        db.add(pref)
    pref.template_id, pref.updated_at = template_id, _now()
    db.flush()
    audit.record(
        db, tenant_id=tenant_id, actor_user_id=user_id, action="ui.preference_changed",
        resource_type="ui_template", resource_id=template_id,
        details={"product": product_code, "reset": template_id is None},
    )  # fmt: skip
    return pref


def set_tenant_default(
    db: Session, tenant_id, actor_id, template_id: uuid.UUID | None, product_code: str = PRODUCT_CODE
) -> TenantUiDefault:  # fmt: skip
    if template_id is not None:
        get_available(db, tenant_id, template_id, product_code)
    row = get_tenant_default(db, tenant_id, product_code)
    if row is None:
        row = TenantUiDefault(tenant_id=tenant_id, product_code=product_code)
        db.add(row)
    row.template_id, row.set_by_user_id, row.updated_at = template_id, actor_id, _now()
    db.flush()
    audit.record(
        db, tenant_id=tenant_id, actor_user_id=actor_id, action="ui.tenant_default_changed",
        resource_type="ui_template", resource_id=template_id,
        details={"product": product_code, "cleared": template_id is None},
    )  # fmt: skip
    return row
