import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, created_at_col, uuid_pk


class Tenant(Base):
    """Customer boundary (PRD section 4)."""

    __tablename__ = "tenants"
    __table_args__ = (
        CheckConstraint("status IN ('active','suspended','deactivated')", name="status"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="active")
    default_language: Mapped[str] = mapped_column(String(10), nullable=False, server_default="en")
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, server_default="Asia/Kolkata")
    data_region: Mapped[str] = mapped_column(String(32), nullable=False, server_default="india")
    plan_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = created_at_col()
    slug: Mapped[str | None] = mapped_column(String(63), nullable=True, unique=True)
    self_registration_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    allow_employee_tags: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true"
    )


class User(Base):
    """Global identity. Credentials and IdP links arrive in the auth sprints."""

    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("status IN ('active','disabled')", name="status"),
        Index("uq_users_email_lower", text("lower(email)"), unique=True),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    preferred_language: Mapped[str] = mapped_column(String(10), nullable=False, server_default="en")
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="active")
    created_at: Mapped[datetime] = created_at_col()
    password_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    failed_login_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    mfa_secret_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    mfa_last_used_step: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")


class UserSession(Base):
    """One signed-in session bound to a tenant. Refresh tokens rotate; only hashes are stored.

    Revoking a session (logout, reuse detection, deactivation) invalidates its access tokens on
    the next request because every request checks this row (PRD 7.4 session revocation).
    """

    __tablename__ = "user_sessions"
    __table_args__ = (
        UniqueConstraint("refresh_hash"),
        Index("ix_user_sessions_user_id", "user_id"),
        Index("ix_user_sessions_prev_refresh_hash", "prev_refresh_hash"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False
    )
    refresh_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    prev_refresh_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = created_at_col()
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_reason: Mapped[str | None] = mapped_column(String(40), nullable=True)


class TenantMembership(Base):
    """Employee identity within a tenant. Historical rows are never hard-deleted (ORG-008)."""

    __tablename__ = "tenant_memberships"
    __table_args__ = (
        UniqueConstraint("tenant_id", "user_id"),
        CheckConstraint("status IN ('invited','active','inactive')", name="status"),
        Index("ix_tenant_memberships_user_id", "user_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="invited")
    employee_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Role(Base):
    """Data-driven role (PRD section 3). System roles are seeded per tenant from templates."""

    __tablename__ = "roles"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name"),
        CheckConstraint("status IN ('active','inactive')", name="status"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(String(300), nullable=True)
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="active")
    created_at: Mapped[datetime] = created_at_col()


class RolePermission(Base):
    __tablename__ = "role_permissions"
    __table_args__ = (UniqueConstraint("role_id", "permission_code"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False
    )
    role_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("roles.id", ondelete="CASCADE"), nullable=False
    )
    permission_code: Mapped[str] = mapped_column(String(80), nullable=False)


class UserRoleAssignment(Base):
    """A membership holding a role. Revoked rows are kept as history."""

    __tablename__ = "user_role_assignments"
    __table_args__ = (
        Index(
            "uq_user_role_assignments_active",
            "membership_id",
            "role_id",
            unique=True,
            postgresql_where=text("revoked_at IS NULL"),
        ),
        Index("ix_user_role_assignments_membership_id", "membership_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False
    )
    membership_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant_memberships.id", ondelete="RESTRICT"), nullable=False
    )
    role_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("roles.id", ondelete="RESTRICT"), nullable=False
    )
    assigned_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    created_at: Mapped[datetime] = created_at_col()
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )


class AuditEvent(Base):
    """Append-only (the app role has no UPDATE/DELETE). Never put secrets or file content in details."""

    __tablename__ = "audit_events"
    __table_args__ = (
        CheckConstraint("outcome IN ('success','denied','failure')", name="outcome"),
        Index("ix_audit_events_tenant_id_occurred_at", "tenant_id", "occurred_at"),
        Index("ix_audit_events_tenant_id_action", "tenant_id", "action"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    occurred_at: Mapped[datetime] = created_at_col()
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(60), nullable=False)
    resource_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    outcome: Mapped[str] = mapped_column(String(20), nullable=False, server_default="success")
    privileged: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    details: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))


def _tenant_fk() -> Mapped[uuid.UUID]:
    return mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False
    )


def _membership_fk(nullable: bool = True, fk_name: str | None = None) -> Mapped[uuid.UUID | None]:
    return mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenant_memberships.id", ondelete="RESTRICT", name=fk_name),
        nullable=nullable,
    )


_ORG_STATUS = "status IN ('active','inactive')"


class Department(Base):
    """Deactivated, never deleted, so historical document references stay valid (ORG-008)."""

    __tablename__ = "departments"
    __table_args__ = (
        UniqueConstraint("tenant_id", "code"),
        UniqueConstraint("tenant_id", "name"),
        CheckConstraint(_ORG_STATUS, name="status"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="active")
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("departments.id", ondelete="RESTRICT"), nullable=True
    )
    manager_membership_id: Mapped[uuid.UUID | None] = _membership_fk()
    created_at: Mapped[datetime] = created_at_col()


class Branch(Base):
    __tablename__ = "branches"
    __table_args__ = (
        UniqueConstraint("tenant_id", "code"),
        UniqueConstraint("tenant_id", "name"),
        CheckConstraint(_ORG_STATUS, name="status"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="active")
    created_at: Mapped[datetime] = created_at_col()


class Project(Base):
    __tablename__ = "projects"
    __table_args__ = (
        UniqueConstraint("tenant_id", "code"),
        UniqueConstraint("tenant_id", "name"),
        CheckConstraint(_ORG_STATUS, name="status"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="active")
    manager_membership_id: Mapped[uuid.UUID | None] = _membership_fk()
    created_at: Mapped[datetime] = created_at_col()


class Designation(Base):
    __tablename__ = "designations"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name"),
        CheckConstraint(_ORG_STATUS, name="status"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="active")
    created_at: Mapped[datetime] = created_at_col()


class EmployeeProfile(Base):
    """Organizational attributes of a membership. Display name and work email live here (tenant
    data) so tenant code never needs to read the global users table."""

    __tablename__ = "employee_profiles"
    __table_args__ = (
        UniqueConstraint("membership_id"),
        CheckConstraint(
            "employment_status IN ('active','on_leave','exited')", name="employment_status"
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    membership_id: Mapped[uuid.UUID] = _membership_fk(nullable=False)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    work_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    department_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("departments.id", ondelete="RESTRICT"), nullable=True
    )
    branch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("branches.id", ondelete="RESTRICT"), nullable=True
    )
    designation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("designations.id", ondelete="RESTRICT"), nullable=True
    )
    reporting_manager_membership_id: Mapped[uuid.UUID | None] = _membership_fk(
        fk_name="fk_employee_profiles_reporting_manager"
    )
    employment_status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="active"
    )
    updated_at: Mapped[datetime] = created_at_col()


class ProjectMembership(Base):
    """Many-to-many (ORG-006). Removal sets ends_on, keeping history."""

    __tablename__ = "project_memberships"
    __table_args__ = (UniqueConstraint("project_id", "membership_id"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    membership_id: Mapped[uuid.UUID] = _membership_fk(nullable=False)
    project_role: Mapped[str] = mapped_column(String(60), nullable=False, server_default="member")
    starts_on: Mapped[date] = mapped_column(
        Date, nullable=False, server_default=func.current_date()
    )
    ends_on: Mapped[date | None] = mapped_column(Date, nullable=True)


class AuthToken(Base):
    """Single-use emailed tokens (invitation, password reset). Only SHA-256 hashes are stored.
    Readable only by the authentication role."""

    __tablename__ = "auth_tokens"
    __table_args__ = (
        UniqueConstraint("token_hash"),
        CheckConstraint("purpose IN ('invite','password_reset')", name="purpose"),
        Index("ix_auth_tokens_user_id", "user_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    purpose: Mapped[str] = mapped_column(String(30), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=True
    )
    membership_id: Mapped[uuid.UUID | None] = _membership_fk()
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = created_at_col()


class RegistrationRequest(Base):
    """Self-registration awaiting admin approval (PRD App.A #13)."""

    __tablename__ = "registration_requests"
    __table_args__ = (
        CheckConstraint("status IN ('pending','approved','rejected')", name="status"),
        Index(
            "uq_registration_requests_pending_email",
            "tenant_id",
            text("lower(email)"),
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="pending")
    created_at: Mapped[datetime] = created_at_col()
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    decision_note: Mapped[str | None] = mapped_column(String(300), nullable=True)


class IdentityLink(Base):
    """Binds a user to an external identity (provider + stable subject), never to an email."""

    __tablename__ = "identity_links"
    __table_args__ = (
        UniqueConstraint("provider", "subject"),
        UniqueConstraint("user_id", "provider"),
        CheckConstraint("provider IN ('google','microsoft')", name="provider"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    email_at_link: Mapped[str] = mapped_column(String(320), nullable=False)
    created_at: Mapped[datetime] = created_at_col()
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class MfaRecoveryCode(Base):
    __tablename__ = "mfa_recovery_codes"
    __table_args__ = (
        UniqueConstraint("code_hash"),
        Index("ix_mfa_recovery_codes_user_id", "user_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = created_at_col()


_CLASSIFICATIONS = "('public','internal','confidential','highly_confidential')"
_ZERO_UUID = "'00000000-0000-0000-0000-000000000000'::uuid"


class Category(Base):
    """Node of the configurable category tree (PRD 6.1). Deactivated, never deleted."""

    __tablename__ = "categories"
    __table_args__ = (
        CheckConstraint(_ORG_STATUS, name="status"),
        CheckConstraint(
            f"default_classification IN {_CLASSIFICATIONS}", name="default_classification"
        ),
        Index(
            "uq_categories_tenant_parent_name",
            "tenant_id",
            text(f"coalesce(parent_id, {_ZERO_UUID})"),
            text("lower(name)"),
            unique=True,
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("categories.id", ondelete="RESTRICT"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="active")
    default_classification: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default="internal"
    )
    current_version_number: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    created_at: Mapped[datetime] = created_at_col()


class CategoryVersion(Base):
    """Immutable snapshot of a category's policy (the app role can INSERT but never UPDATE).
    Documents keep pointing at the version they were created under (CAT-004)."""

    __tablename__ = "category_versions"
    __table_args__ = (
        UniqueConstraint("category_id", "version_number"),
        CheckConstraint("expiry_action IN ('archive')", name="expiry_action"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    category_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("categories.id", ondelete="RESTRICT"), nullable=False
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    approval_required: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    required_dimensions: Mapped[list[str]] = mapped_column(
        ARRAY(String(20)), nullable=False, server_default=text("'{}'")
    )
    allowed_extensions: Mapped[list[str] | None] = mapped_column(ARRAY(String(10)), nullable=True)
    retention_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    review_interval_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    expiry_action: Mapped[str] = mapped_column(String(20), nullable=False, server_default="archive")
    reminder_days: Mapped[list[int]] = mapped_column(
        ARRAY(Integer), nullable=False, server_default=text("'{}'")
    )
    created_at: Mapped[datetime] = created_at_col()
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )


class MetadataFieldDefinition(Base):
    __tablename__ = "metadata_field_definitions"
    __table_args__ = (UniqueConstraint("category_version_id", "key"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    category_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("category_versions.id", ondelete="RESTRICT", name="fk_mfd_category_version"),
        nullable=False,
    )
    key: Mapped[str] = mapped_column(String(40), nullable=False)
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    field_type: Mapped[str] = mapped_column(String(30), nullable=False)
    required: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    searchable: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    default_value: Mapped[Any] = mapped_column(JSONB, nullable=True)
    validation: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )


class Tag(Base):
    """Discovery label, never a security control (PRD 6). Kinds: standard (admin), employee
    (policy-controlled), system (lifecycle, immutable)."""

    __tablename__ = "tags"
    __table_args__ = (
        CheckConstraint("kind IN ('standard','employee','system')", name="kind"),
        CheckConstraint(_ORG_STATUS, name="status"),
        Index("uq_tags_tenant_name", "tenant_id", text("lower(name)"), unique=True),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="active")
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    created_at: Mapped[datetime] = created_at_col()


LIFECYCLE_STATES = "('draft','submitted','under_review','approved','rejected','archived')"
VERSION_STATUSES = "('pending','receiving','available','quarantined','rejected','abandoned')"


class Document(Base):
    """Stable logical document (PRD 8.3). Bytes live in immutable `document_versions`."""

    __tablename__ = "documents"
    __table_args__ = (
        CheckConstraint(f"classification IN {_CLASSIFICATIONS}", name="classification"),
        CheckConstraint(f"lifecycle_state IN {LIFECYCLE_STATES}", name="lifecycle_state"),
        Index("ix_documents_tenant_id_category_id", "tenant_id", "category_id"),
        Index("ix_documents_tenant_id_created_by_user_id", "tenant_id", "created_by_user_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    category_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("categories.id", ondelete="RESTRICT"), nullable=False
    )
    category_version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    classification: Mapped[str] = mapped_column(String(30), nullable=False)
    lifecycle_state: Mapped[str] = mapped_column(String(20), nullable=False, server_default="draft")
    owner_membership_id: Mapped[uuid.UUID] = _membership_fk(nullable=False)
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    current_version_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    metadata_values: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    row_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = created_at_col()


class DocumentAssociation(Base):
    """One row per organizational association (ORG-004), independently queryable."""

    __tablename__ = "document_associations"
    __table_args__ = (
        UniqueConstraint("document_id", "dimension", "ref_id"),
        CheckConstraint(
            "dimension IN ('department','branch','project','employee')", name="dimension"
        ),
        Index(
            "ix_document_associations_tenant_id_dimension_ref_id",
            "tenant_id",
            "dimension",
            "ref_id",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="RESTRICT"), nullable=False
    )
    dimension: Mapped[str] = mapped_column(String(20), nullable=False)
    ref_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)


class DocumentTag(Base):
    __tablename__ = "document_tags"
    __table_args__ = (UniqueConstraint("document_id", "tag_id"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="RESTRICT"), nullable=False
    )
    tag_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tags.id", ondelete="RESTRICT"), nullable=False
    )


class DocumentVersion(Base):
    """One uploaded file. Becomes `available` only after validation, scan and storage succeed."""

    __tablename__ = "document_versions"
    __table_args__ = (
        UniqueConstraint("document_id", "version_number"),
        UniqueConstraint("object_key"),
        CheckConstraint(f"status IN {VERSION_STATUSES}", name="status"),
        CheckConstraint(
            "scan_status IN ('pending','clean','infected','failed')", name="scan_status"
        ),
        Index(
            "uq_document_versions_idempotency",
            "tenant_id",
            "uploaded_by_user_id",
            "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="RESTRICT"), nullable=False
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="pending")
    original_filename: Mapped[str] = mapped_column(String(300), nullable=False)
    declared_content_type: Mapped[str] = mapped_column(String(150), nullable=False)
    declared_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    content_type: Mapped[str | None] = mapped_column(String(150), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    sha1: Mapped[str | None] = mapped_column(String(40), nullable=True)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    object_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    storage_file_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    scan_status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="pending")
    scan_detail: Mapped[str | None] = mapped_column(String(200), nullable=True)
    reject_reason: Mapped[str | None] = mapped_column(String(60), nullable=True)
    comment: Mapped[str | None] = mapped_column(String(300), nullable=True)
    uploaded_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    idempotency_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = created_at_col()
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
