import uuid
from datetime import date, datetime

from sqlalchemy import (
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
from sqlalchemy.dialects.postgresql import JSONB, UUID
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
