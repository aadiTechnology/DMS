import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.core.tenancy import (
    Principal,
    get_principal,
    get_tenant_db,
    require_any_permission,
    require_permission,
)
from app.services import rbac, taxonomy
from app.services.metadata import FIELD_TYPES, MetadataInvalid

router = APIRouter(prefix="/api/v1", tags=["taxonomy"])
manage = require_permission("admin.manage_taxonomy")
may_tag = require_any_permission(
    "admin.manage_taxonomy", "document.upload", "document.edit_metadata"
)
Classification = Literal["public", "internal", "confidential", "highly_confidential"]


@contextmanager
def _errors() -> Iterator[None]:
    try:
        yield
    except taxonomy.NotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"{exc} not found") from None
    except taxonomy.Conflict as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from None
    except taxonomy.Invalid as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from None
    except MetadataInvalid as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, detail={"fields": exc.errors}
        ) from None


# ---- schemas ----------------------------------------------------------------------------


class ApprovalStepIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["user", "role", "department_manager"]
    ref: uuid.UUID | None = None


class PolicyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approval_steps: list[ApprovalStepIn] = []
    approval_required: bool = False
    required_dimensions: list[str] = []
    allowed_extensions: list[str] | None = None
    retention_days: int | None = None
    review_interval_days: int | None = None
    expiry_action: str = "archive"
    reminder_days: list[int] = []


class FieldIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    label: str
    field_type: str
    required: bool = False
    searchable: bool = True
    display_order: int = 0
    default_value: Any = None
    validation: dict[str, Any] = {}


class FieldOut(FieldIn):
    id: uuid.UUID


class VersionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    policy: PolicyIn = PolicyIn()
    fields: list[FieldIn] = []


class VersionOut(BaseModel):
    version_number: int
    approval_required: bool
    required_dimensions: list[str]
    allowed_extensions: list[str] | None
    retention_days: int | None
    review_interval_days: int | None
    expiry_action: str
    reminder_days: list[int]
    approval_steps: list[dict[str, Any]]
    created_at: datetime
    fields: list[FieldOut]


class CategoryIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(max_length=200)
    parent_id: uuid.UUID | None = None
    default_classification: Classification = "internal"
    policy: PolicyIn = PolicyIn()
    fields: list[FieldIn] = []


class CategoryPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(None, max_length=200)
    parent_id: uuid.UUID | None = None
    default_classification: Classification | None = None
    status: Literal["active", "inactive"] | None = None


class CategoryOut(BaseModel):
    id: uuid.UUID
    name: str
    parent_id: uuid.UUID | None
    path: str
    depth: int
    status: str
    default_classification: str
    current_version_number: int


class CategoryDetail(CategoryOut):
    version: VersionOut


def _category_out(info: dict) -> CategoryOut:
    c = info["category"]
    return CategoryOut(
        id=c.id,
        name=c.name,
        parent_id=c.parent_id,
        path=info["path"],
        depth=info["depth"],
        status=c.status,
        default_classification=c.default_classification,
        current_version_number=c.current_version_number,
    )


def _version_out(version, fields) -> VersionOut:
    return VersionOut(
        version_number=version.version_number,
        approval_required=version.approval_required,
        required_dimensions=version.required_dimensions,
        allowed_extensions=version.allowed_extensions,
        retention_days=version.retention_days,
        review_interval_days=version.review_interval_days,
        expiry_action=version.expiry_action,
        reminder_days=version.reminder_days,
        approval_steps=version.approval_steps,
        created_at=version.created_at,
        fields=[
            FieldOut(
                id=f.id,
                key=f.key,
                label=f.label,
                field_type=f.field_type,
                required=f.required,
                searchable=f.searchable,
                display_order=f.display_order,
                default_value=f.default_value,
                validation=f.validation,
            )
            for f in fields
        ],
    )


# ---- categories -------------------------------------------------------------------------


@router.get("/metadata/field-types", response_model=list[str])
def field_types(_: Principal = Depends(get_principal)):
    return list(FIELD_TYPES)


@router.get("/categories", response_model=list[CategoryOut])
def list_categories(
    status_filter: Literal["active", "inactive"] | None = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_tenant_db),
):
    """Readable by every member: upload forms and filters need the tree."""
    rows = taxonomy.list_categories(db, principal.tenant_id, status_filter, limit, offset)
    return [_category_out(r) for r in rows]


@router.post("/categories", response_model=CategoryDetail, status_code=status.HTTP_201_CREATED)
def create_category(
    body: CategoryIn,
    principal: Principal = Depends(manage),
    db: Session = Depends(get_tenant_db),
):
    with _errors():
        cat = taxonomy.create_category(
            db,
            principal.tenant_id,
            principal.user_id,
            name=body.name,
            parent_id=body.parent_id,
            default_classification=body.default_classification,
            policy=body.policy.model_dump(),
            fields=[f.model_dump() for f in body.fields],
        )
        info = taxonomy.get_category(db, principal.tenant_id, cat.id)
        version, fields = taxonomy.get_version(db, principal.tenant_id, cat.id)
    return CategoryDetail(**_category_out(info).model_dump(), version=_version_out(version, fields))


@router.get("/categories/{category_id}", response_model=CategoryDetail)
def get_category(
    category_id: uuid.UUID,
    version: int | None = Query(None, ge=1),
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_tenant_db),
):
    with _errors():
        info = taxonomy.get_category(db, principal.tenant_id, category_id)
        v, fields = taxonomy.get_version(db, principal.tenant_id, category_id, version)
    return CategoryDetail(**_category_out(info).model_dump(), version=_version_out(v, fields))


@router.patch("/categories/{category_id}", response_model=CategoryOut)
def update_category(
    category_id: uuid.UUID,
    body: CategoryPatch,
    principal: Principal = Depends(manage),
    db: Session = Depends(get_tenant_db),
):
    """Rename, move (`parent_id`, null = top level), change default classification, or
    deactivate/reactivate. There is no delete."""
    with _errors():
        taxonomy.update_category(
            db,
            principal.tenant_id,
            principal.user_id,
            category_id,
            body.model_dump(exclude_unset=True),
        )
        return _category_out(taxonomy.get_category(db, principal.tenant_id, category_id))


@router.get("/categories/{category_id}/versions", response_model=list[VersionOut])
def list_versions(
    category_id: uuid.UUID,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_tenant_db),
):
    with _errors():
        versions = taxonomy.list_versions(db, principal.tenant_id, category_id)
        return [
            _version_out(
                *taxonomy.get_version(db, principal.tenant_id, category_id, v.version_number)
            )
            for v in versions
        ]


@router.post(
    "/categories/{category_id}/versions",
    response_model=VersionOut,
    status_code=status.HTTP_201_CREATED,
)
def create_version(
    category_id: uuid.UUID,
    body: VersionIn,
    principal: Principal = Depends(manage),
    db: Session = Depends(get_tenant_db),
):
    """Publish a new immutable version of the policy and metadata fields. Existing documents keep
    the version they were created under."""
    with _errors():
        version, fields = taxonomy.create_version(
            db,
            principal.tenant_id,
            principal.user_id,
            category_id,
            policy=body.policy.model_dump(),
            fields=[f.model_dump() for f in body.fields],
        )
    return _version_out(version, fields)


# ---- tags -------------------------------------------------------------------------------


class TagIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(max_length=80)
    kind: Literal["standard", "employee"] = "employee"


class TagPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(None, max_length=80)
    status: Literal["active", "inactive"] | None = None


class TagOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    kind: str
    status: str


class TagPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    allow_employee_tags: bool


@router.get("/tags", response_model=list[TagOut])
def list_tags(
    kind: Literal["standard", "employee", "system"] | None = None,
    status_filter: Literal["active", "inactive"] | None = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_tenant_db),
):
    return taxonomy.list_tags(db, principal.tenant_id, kind, status_filter, limit, offset)


@router.get("/tags/policy", response_model=TagPolicy)
def get_tag_policy(principal: Principal = Depends(manage), db: Session = Depends(get_tenant_db)):
    from app.db.models import Tenant

    return TagPolicy(allow_employee_tags=db.get(Tenant, principal.tenant_id).allow_employee_tags)


@router.put("/tags/policy", response_model=TagPolicy)
def set_tag_policy(
    body: TagPolicy, principal: Principal = Depends(manage), db: Session = Depends(get_tenant_db)
):
    value = taxonomy.set_tag_policy(
        db, principal.tenant_id, principal.user_id, body.allow_employee_tags
    )
    return TagPolicy(allow_employee_tags=value)


@router.post("/tags", response_model=TagOut)
def create_tag(
    body: TagIn,
    response: Response,
    principal: Principal = Depends(may_tag),
    db: Session = Depends(get_tenant_db),
):
    """Standard tags need `admin.manage_taxonomy`; employee tags need upload or metadata-edit
    rights and the organization's tag policy. An existing tag with the same name is returned."""
    if body.kind == "standard" and not rbac.has_permission(
        db, principal.tenant_id, principal.user_id, "admin.manage_taxonomy"
    ):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Permission denied")
    with _errors():
        tag, created = taxonomy.create_tag(
            db, principal.tenant_id, principal.user_id, body.name, body.kind
        )
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return tag


@router.patch("/tags/{tag_id}", response_model=TagOut)
def update_tag(
    tag_id: uuid.UUID,
    body: TagPatch,
    principal: Principal = Depends(manage),
    db: Session = Depends(get_tenant_db),
):
    with _errors():
        return taxonomy.update_tag(
            db, principal.tenant_id, principal.user_id, tag_id, body.model_dump(exclude_unset=True)
        )
