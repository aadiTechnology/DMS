import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.core.tenancy import Principal, get_principal, get_tenant_db, require_permission
from app.db.models import UiTemplate
from app.services.org import Conflict, Invalid, NotFound
from app.ui import service

router = APIRouter(prefix="/api/v1", tags=["appearance"])
ProductCode = Query(service.PRODUCT_CODE, pattern="^[a-z0-9-]{2,32}$")


class TemplateCard(BaseModel):
    id: uuid.UUID
    key: str
    name: str
    description: str
    version: str
    scope: str
    preview_image_url: str | None
    is_selected: bool
    is_default: bool


class TemplateDetail(TemplateCard):
    config: dict[str, Any]


class EffectiveOut(BaseModel):
    source: str  # user | tenant | product | system
    template: TemplateDetail | None


class PreferenceOut(BaseModel):
    product_code: str
    selected_template_id: uuid.UUID | None
    updated_at: datetime | None
    effective: EffectiveOut


class PreferenceIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    template_id: uuid.UUID | None = None  # null resets to the default


def _card(t: UiTemplate, selected_id, default_id) -> dict[str, Any]:
    return {
        "id": t.id, "key": t.template_key, "name": t.template_name, "description": t.description,
        "version": t.version, "scope": t.scope, "preview_image_url": t.preview_image_url,
        "is_selected": t.id == selected_id, "is_default": t.id == default_id,
    }  # fmt: skip


def _mapped(exc: Exception) -> HTTPException:
    if isinstance(exc, NotFound):
        return HTTPException(status.HTTP_404_NOT_FOUND, detail="template not found")
    if isinstance(exc, Conflict):
        return HTTPException(status.HTTP_409_CONFLICT, detail=str(exc))
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc))


def _preference_out(db: Session, principal: Principal, product: str) -> PreferenceOut:
    pref = service.get_preference(db, principal.tenant_id, principal.user_id, product)
    resolved = service.resolve(db, principal.tenant_id, principal.user_id, product)
    selected = pref.template_id if pref else None
    tenant_default = service.get_tenant_default(db, principal.tenant_id, product)
    default_id = tenant_default.template_id if tenant_default else None
    effective = None
    if resolved.template is not None:
        t = resolved.template
        effective = TemplateDetail(**_card(t, selected, default_id), config=t.config_json)
    return PreferenceOut(
        product_code=product, selected_template_id=selected, updated_at=pref.updated_at if pref else None,
        effective=EffectiveOut(source=resolved.source, template=effective),
    )  # fmt: skip


@router.get("/ui-templates/available", response_model=list[TemplateCard])
def available_templates(
    product_code: str = ProductCode,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_tenant_db),
):
    """Designs you can choose: published platform templates and your organization's own."""
    pref = service.get_preference(db, principal.tenant_id, principal.user_id, product_code)
    default = service.get_tenant_default(db, principal.tenant_id, product_code)
    selected, default_id = (
        (pref.template_id if pref else None),
        (default.template_id if default else None),
    )
    return [
        _card(t, selected, default_id)
        for t in service.list_available(db, principal.tenant_id, product_code)
    ]


@router.get("/ui-templates/available/{template_id}", response_model=TemplateDetail)
def available_template(
    template_id: uuid.UUID,
    product_code: str = ProductCode,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_tenant_db),
):
    """One design with its full configuration, for previewing before applying."""
    try:
        t = service.get_available(db, principal.tenant_id, template_id, product_code)
    except NotFound as exc:
        raise _mapped(exc) from None
    return TemplateDetail(**_card(t, None, None), config=t.config_json)


@router.get("/me/ui-preferences", response_model=PreferenceOut)
def my_preference(
    product_code: str = ProductCode,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_tenant_db),
):
    """Your saved choice and the design that applies to you now (your choice, your organization's
    default, the product default, or the built-in theme)."""
    return _preference_out(db, principal, product_code)


@router.put("/me/ui-preferences", response_model=PreferenceOut)
def set_my_preference(
    body: PreferenceIn,
    product_code: str = ProductCode,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_tenant_db),
):
    """Choose a design (or null to reset). Only affects your own account."""
    try:
        service.set_preference(
            db, principal.tenant_id, principal.user_id, body.template_id, product_code
        )
    except (NotFound, Invalid, Conflict) as exc:
        raise _mapped(exc) from None
    return _preference_out(db, principal, product_code)


class TenantDefaultIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    template_id: uuid.UUID | None = None


class TenantDefaultOut(BaseModel):
    product_code: str
    template_id: uuid.UUID | None


@router.get("/ui-templates/tenant-default", response_model=TenantDefaultOut)
def get_tenant_default(
    product_code: str = ProductCode,
    principal: Principal = Depends(require_permission("admin.manage_organization")),
    db: Session = Depends(get_tenant_db),
):
    row = service.get_tenant_default(db, principal.tenant_id, product_code)
    return TenantDefaultOut(product_code=product_code, template_id=row.template_id if row else None)


@router.put("/ui-templates/tenant-default", response_model=TenantDefaultOut)
def set_tenant_default(
    body: TenantDefaultIn,
    product_code: str = ProductCode,
    principal: Principal = Depends(require_permission("admin.manage_organization")),
    db: Session = Depends(get_tenant_db),
):
    """The organization's default design for people who have not chosen their own."""
    try:
        row = service.set_tenant_default(
            db, principal.tenant_id, principal.user_id, body.template_id, product_code
        )
    except (NotFound, Invalid, Conflict) as exc:
        raise _mapped(exc) from None
    return TenantDefaultOut(product_code=product_code, template_id=row.template_id)
