import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel
from sqlalchemy import select

from app.core.config import get_settings
from app.core.tenancy import Principal, get_principal
from app.db.models import PlatformAdmin, UiTemplate, UiTemplateVersion, User
from app.db.tenant_session import auth_session, platform_session, tenant_session
from app.services import audit
from app.services.org import Conflict, Invalid, NotFound
from app.ui import service
from app.ui.templates import MAX_TEMPLATE_BYTES, validate_template

router = APIRouter(prefix="/api/v1", tags=["platform"])
ProductCode = Query(service.PRODUCT_CODE, pattern="^[a-z0-9-]{2,32}$")


def _admin_state(user_id) -> tuple[bool, bool]:
    """(is an active platform administrator, has two-step verification on)."""
    with auth_session() as db:
        row = db.get(PlatformAdmin, user_id)
        user = db.get(User, user_id)
        active = (
            row is not None
            and row.revoked_at is None
            and user is not None
            and user.status == "active"
        )
        return active, bool(user and user.mfa_enabled)


def require_platform_admin(principal: Principal = Depends(get_principal)) -> Principal:
    is_admin, has_mfa = _admin_state(principal.user_id)
    if not is_admin:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, detail="Platform administrator access required"
        )
    settings = get_settings()
    required = settings.PLATFORM_ADMIN_REQUIRE_MFA
    if required is None:
        required = settings.ENVIRONMENT == "production"
    if required and not has_mfa:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="Platform administrators must turn on two-step verification first",
        )
    return principal


async def raw_json(request: Request) -> bytes:
    """The uploaded template, as received. Size is limited before anything is parsed."""
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_TEMPLATE_BYTES:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="The file is larger than 64 KB"
        )
    body = await request.body()
    if len(body) > MAX_TEMPLATE_BYTES:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="The file is larger than 64 KB"
        )
    return body


class AdminStateOut(BaseModel):
    is_platform_admin: bool


class TemplateAdminOut(BaseModel):
    id: uuid.UUID
    product_code: str
    key: str
    name: str
    description: str
    version: str
    status: str
    scope: str
    preview_image_url: str | None
    created_at: datetime
    updated_at: datetime


class TemplateAdminDetail(TemplateAdminOut):
    config: dict[str, Any]


class VersionOut(BaseModel):
    version: str
    created_at: datetime
    published_at: datetime | None


class ValidationOut(BaseModel):
    valid: bool
    errors: list[str]
    key: str | None = None
    name: str | None = None
    description: str | None = None
    version: str | None = None
    outcome: str | None = None  # new_template | new_version | conflict
    current_version: str | None = None


def _out(t: UiTemplate) -> dict[str, Any]:
    return {
        "id": t.id, "product_code": t.product_code, "key": t.template_key, "name": t.template_name,
        "description": t.description, "version": t.version, "status": t.status, "scope": t.scope,
        "preview_image_url": t.preview_image_url, "created_at": t.created_at, "updated_at": t.updated_at,
    }  # fmt: skip


def _audit(
    principal: Principal, action: str, template: UiTemplate | None, details: dict[str, Any]
) -> None:
    """Platform work has no tenant of its own, so it is recorded in the administrator's own
    organization audit log, flagged privileged."""
    with tenant_session(principal.tenant_id) as db:
        audit.record(
            db, tenant_id=principal.tenant_id, actor_user_id=principal.user_id,
            action=f"platform.ui_template.{action}", resource_type="ui_template",
            resource_id=template.id if template else None, privileged=True, details=details,
        )  # fmt: skip


def _mapped(exc: Exception) -> HTTPException:
    if isinstance(exc, NotFound):
        return HTTPException(status.HTTP_404_NOT_FOUND, detail="template not found")
    if isinstance(exc, Conflict):
        return HTTPException(status.HTTP_409_CONFLICT, detail=str(exc))
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc))


def _load(db, template_id, product_code) -> UiTemplate:
    template = db.get(UiTemplate, template_id)
    if template is None or template.tenant_id is not None or template.product_code != product_code:
        raise NotFound("template")
    return template


@router.get("/me/platform-admin", response_model=AdminStateOut)
def am_i_platform_admin(principal: Principal = Depends(get_principal)):
    """Lets the web app decide whether to show the template management screen. The real check
    happens on every platform request."""
    return AdminStateOut(is_platform_admin=_admin_state(principal.user_id)[0])


@router.post("/platform/ui-templates/validate", response_model=ValidationOut)
def validate_upload(
    body: bytes = Depends(raw_json),
    product_code: str = ProductCode,
    principal: Principal = Depends(require_platform_admin),
):
    """Check a template file without saving it: errors, its name and description, and whether
    its key and version are new."""
    result = validate_template(body)
    if not result.valid:
        return ValidationOut(valid=False, errors=result.errors)
    t = result.template
    with platform_session() as db:
        existing = db.scalars(
            select(UiTemplate).where(
                UiTemplate.tenant_id.is_(None),
                UiTemplate.product_code == product_code,
                UiTemplate.template_key == t["key"],
            )
        ).first()
    if existing is None:
        outcome = "new_template"
    elif service._version_tuple(t["version"]) > service._version_tuple(existing.version):
        outcome = "new_version"
    else:
        outcome = "conflict"
    return ValidationOut(
        valid=outcome != "conflict",
        errors=[] if outcome != "conflict" else [f"version {t['version']} already exists or is older than {existing.version}"],
        key=t["key"], name=t["name"], description=t["description"], version=t["version"],
        outcome=outcome, current_version=existing.version if existing else None,
    )  # fmt: skip


@router.post(
    "/platform/ui-templates/import",
    response_model=TemplateAdminOut,
    status_code=status.HTTP_201_CREATED,
)
def import_template(
    body: bytes = Depends(raw_json),
    publish: bool = False,
    product_code: str = ProductCode,
    principal: Principal = Depends(require_platform_admin),
):
    """Validate and save a template as a draft (publish=true also publishes it). A new version of
    an existing key keeps the earlier versions on record."""
    result = validate_template(body)
    if not result.valid:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail={"errors": result.errors})
    try:
        with platform_session() as db:
            template = service.import_platform_template(
                db,
                result.template,
                product_code=product_code,
                actor_user_id=principal.user_id,
                publish=publish,
            )
            out = _out(template)
    except (Invalid, Conflict, NotFound) as exc:
        raise _mapped(exc) from None
    _audit(
        principal,
        "imported",
        template,
        {"key": out["key"], "version": out["version"], "published": publish},
    )
    return out


@router.get("/platform/ui-templates", response_model=list[TemplateAdminOut])
def list_templates(
    status_filter: str | None = Query(None, alias="status", pattern="^(draft|published|archived)$"),
    product_code: str = ProductCode,
    principal: Principal = Depends(require_platform_admin),
):
    with platform_session() as db:
        stmt = select(UiTemplate).where(
            UiTemplate.tenant_id.is_(None), UiTemplate.product_code == product_code
        )
        if status_filter:
            stmt = stmt.where(UiTemplate.status == status_filter)
        return [_out(t) for t in db.scalars(stmt.order_by(UiTemplate.template_name, UiTemplate.id))]


@router.get("/platform/ui-templates/{template_id}", response_model=TemplateAdminDetail)
def get_template(
    template_id: uuid.UUID,
    product_code: str = ProductCode,
    principal: Principal = Depends(require_platform_admin),
):
    try:
        with platform_session() as db:
            t = _load(db, template_id, product_code)
            return {**_out(t), "config": t.config_json}
    except NotFound as exc:
        raise _mapped(exc) from None


@router.get("/platform/ui-templates/{template_id}/versions", response_model=list[VersionOut])
def template_versions(
    template_id: uuid.UUID,
    product_code: str = ProductCode,
    principal: Principal = Depends(require_platform_admin),
):
    try:
        with platform_session() as db:
            t = _load(db, template_id, product_code)
            rows = db.scalars(
                select(UiTemplateVersion)
                .where(UiTemplateVersion.template_id == t.id)
                .order_by(UiTemplateVersion.created_at.desc())
            ).all()
            return [
                {"version": v.version, "created_at": v.created_at, "published_at": v.published_at}
                for v in rows
            ]
    except NotFound as exc:
        raise _mapped(exc) from None


def _transition(template_id, product_code, principal: Principal, action: str):
    try:
        with platform_session() as db:
            t = _load(db, template_id, product_code)
            (service.publish_template if action == "published" else service.archive_template)(db, t)
            out = _out(t)
    except (Invalid, Conflict, NotFound) as exc:
        raise _mapped(exc) from None
    _audit(principal, action, t, {"key": out["key"], "version": out["version"]})
    return out


@router.post("/platform/ui-templates/{template_id}/publish", response_model=TemplateAdminOut)
def publish(
    template_id: uuid.UUID,
    product_code: str = ProductCode,
    principal: Principal = Depends(require_platform_admin),
):
    """Make the template available to every organization, without any application redeploy."""
    return _transition(template_id, product_code, principal, "published")


@router.post("/platform/ui-templates/{template_id}/archive", response_model=TemplateAdminOut)
def archive(
    template_id: uuid.UUID,
    product_code: str = ProductCode,
    principal: Principal = Depends(require_platform_admin),
):
    """Withdraw the template. People who chose it fall back to the next design in the chain."""
    return _transition(template_id, product_code, principal, "archived")
