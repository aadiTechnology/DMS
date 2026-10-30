"""foundation: tenants, users, tenant_memberships

Revision ID: 0001
Revises:
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

PK = sa.text("gen_random_uuid()")


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("id", UUID(as_uuid=True), server_default=PK, nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("status", sa.String(20), server_default="active", nullable=False),
        sa.Column("default_language", sa.String(10), server_default="en", nullable=False),
        sa.Column("timezone", sa.String(64), server_default="Asia/Kolkata", nullable=False),
        sa.Column("data_region", sa.String(32), server_default="india", nullable=False),
        sa.Column("plan_id", UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_tenants"),
        sa.CheckConstraint(
            "status IN ('active','suspended','deactivated')", name="ck_tenants_status"
        ),
    )
    op.create_table(
        "users",
        sa.Column("id", UUID(as_uuid=True), server_default=PK, nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("preferred_language", sa.String(10), server_default="en", nullable=False),
        sa.Column("status", sa.String(20), server_default="active", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.CheckConstraint("status IN ('active','disabled')", name="ck_users_status"),
    )
    op.create_index("uq_users_email_lower", "users", [sa.text("lower(email)")], unique=True)
    op.create_table(
        "tenant_memberships",
        sa.Column("id", UUID(as_uuid=True), server_default=PK, nullable=False),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(20), server_default="invited", nullable=False),
        sa.Column("employee_number", sa.String(64), nullable=True),
        sa.Column(
            "joined_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_tenant_memberships"),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_tenant_memberships_tenant_id_tenants",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_tenant_memberships_user_id_users",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("tenant_id", "user_id", name="uq_tenant_memberships_tenant_id_user_id"),
        sa.CheckConstraint(
            "status IN ('invited','active','inactive')", name="ck_tenant_memberships_status"
        ),
    )
    op.create_index("ix_tenant_memberships_user_id", "tenant_memberships", ["user_id"])


def downgrade() -> None:
    op.drop_table("tenant_memberships")
    op.drop_index("uq_users_email_lower", table_name="users")
    op.drop_table("users")
    op.drop_table("tenants")
