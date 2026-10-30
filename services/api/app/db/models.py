import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
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
