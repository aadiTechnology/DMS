"""onboarding: tenant slug/self-registration flag, auth_tokens, registration_requests

Revision ID: 0006
Revises: 0005
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

from app.db.rls import APP_ROLE, AUTH_ROLE, disable_tenant_rls_sql, enable_tenant_rls_sql

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

PK = sa.text("gen_random_uuid()")


def upgrade() -> None:
    op.add_column("tenants", sa.Column("slug", sa.String(63), nullable=True))
    op.create_unique_constraint("uq_tenants_slug", "tenants", ["slug"])
    op.add_column(
        "tenants",
        sa.Column(
            "self_registration_enabled", sa.Boolean(), server_default="false", nullable=False
        ),
    )
    op.create_table(
        "auth_tokens",
        sa.Column("id", UUID(as_uuid=True), server_default=PK, nullable=False),
        sa.Column("purpose", sa.String(30), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=True),
        sa.Column("membership_id", UUID(as_uuid=True), nullable=True),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_auth_tokens"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_auth_tokens_user_id_users", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_auth_tokens_tenant_id_tenants",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["membership_id"],
            ["tenant_memberships.id"],
            name="fk_auth_tokens_membership_id_tenant_memberships",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("token_hash", name="uq_auth_tokens_token_hash"),
        sa.CheckConstraint("purpose IN ('invite','password_reset')", name="ck_auth_tokens_purpose"),
    )
    op.create_index("ix_auth_tokens_user_id", "auth_tokens", ["user_id"])
    op.create_table(
        "registration_requests",
        sa.Column("id", UUID(as_uuid=True), server_default=PK, nullable=False),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("full_name", sa.String(200), nullable=False),
        sa.Column("status", sa.String(20), server_default="pending", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_by_user_id", UUID(as_uuid=True), nullable=True),
        sa.Column("decision_note", sa.String(300), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_registration_requests"),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_registration_requests_tenant_id_tenants",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["decided_by_user_id"],
            ["users.id"],
            name="fk_registration_requests_decided_by_user_id_users",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "status IN ('pending','approved','rejected')", name="ck_registration_requests_status"
        ),
    )
    op.create_index(
        "uq_registration_requests_pending_email",
        "registration_requests",
        ["tenant_id", sa.text("lower(email)")],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )
    for stmt in enable_tenant_rls_sql("registration_requests"):
        op.execute(stmt)
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON registration_requests TO {APP_ROLE}")
    op.execute(f"GRANT UPDATE (self_registration_enabled) ON tenants TO {APP_ROLE}")
    # Authentication role: creates invited users, manages emailed tokens.
    op.execute(f"GRANT INSERT ON users TO {AUTH_ROLE}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON auth_tokens TO {AUTH_ROLE}")


def downgrade() -> None:
    op.execute(f"REVOKE ALL ON auth_tokens FROM {AUTH_ROLE}")
    op.execute(f"REVOKE INSERT ON users FROM {AUTH_ROLE}")
    op.execute(f"REVOKE UPDATE (self_registration_enabled) ON tenants FROM {APP_ROLE}")
    op.execute(f"REVOKE ALL ON registration_requests FROM {APP_ROLE}")
    for stmt in disable_tenant_rls_sql("registration_requests"):
        op.execute(stmt)
    op.drop_table("registration_requests")
    op.drop_table("auth_tokens")
    op.drop_column("tenants", "self_registration_enabled")
    op.drop_constraint("uq_tenants_slug", "tenants", type_="unique")
    op.drop_column("tenants", "slug")
