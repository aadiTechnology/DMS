"""RBAC (roles, role_permissions, user_role_assignments) and append-only audit_events

Revision ID: 0004
Revises: 0003
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.db.rls import APP_ROLE, AUTH_ROLE, disable_tenant_rls_sql, enable_tenant_rls_sql

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

PK = sa.text("gen_random_uuid()")
TABLES = ("roles", "role_permissions", "user_role_assignments", "audit_events")


def _tenant_col():
    return sa.Column("tenant_id", UUID(as_uuid=True), nullable=False)


def _fk(table, col, ref, name, ondelete="RESTRICT"):
    return sa.ForeignKeyConstraint(
        [col], [ref], name=f"fk_{table}_{col}_{ref.split('.')[0]}", ondelete=ondelete
    )


def upgrade() -> None:
    now = sa.func.now()
    op.create_table(
        "roles",
        sa.Column("id", UUID(as_uuid=True), server_default=PK, nullable=False),
        _tenant_col(),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.String(300), nullable=True),
        sa.Column("is_system", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("status", sa.String(20), server_default="active", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=now, nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_roles"),
        _fk("roles", "tenant_id", "tenants.id", "roles"),
        sa.UniqueConstraint("tenant_id", "name", name="uq_roles_tenant_id_name"),
        sa.CheckConstraint("status IN ('active','inactive')", name="ck_roles_status"),
    )
    op.create_table(
        "role_permissions",
        sa.Column("id", UUID(as_uuid=True), server_default=PK, nullable=False),
        _tenant_col(),
        sa.Column("role_id", UUID(as_uuid=True), nullable=False),
        sa.Column("permission_code", sa.String(80), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_role_permissions"),
        _fk("role_permissions", "tenant_id", "tenants.id", "rp"),
        _fk("role_permissions", "role_id", "roles.id", "rp", ondelete="CASCADE"),
        sa.UniqueConstraint(
            "role_id", "permission_code", name="uq_role_permissions_role_id_permission_code"
        ),
    )
    op.create_table(
        "user_role_assignments",
        sa.Column("id", UUID(as_uuid=True), server_default=PK, nullable=False),
        _tenant_col(),
        sa.Column("membership_id", UUID(as_uuid=True), nullable=False),
        sa.Column("role_id", UUID(as_uuid=True), nullable=False),
        sa.Column("assigned_by_user_id", UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=now, nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by_user_id", UUID(as_uuid=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_user_role_assignments"),
        _fk("user_role_assignments", "tenant_id", "tenants.id", "ura"),
        _fk("user_role_assignments", "membership_id", "tenant_memberships.id", "ura"),
        _fk("user_role_assignments", "role_id", "roles.id", "ura"),
        _fk("user_role_assignments", "assigned_by_user_id", "users.id", "ura"),
        _fk("user_role_assignments", "revoked_by_user_id", "users.id", "ura"),
    )
    op.create_index(
        "uq_user_role_assignments_active",
        "user_role_assignments",
        ["membership_id", "role_id"],
        unique=True,
        postgresql_where=sa.text("revoked_at IS NULL"),
    )
    op.create_index(
        "ix_user_role_assignments_membership_id", "user_role_assignments", ["membership_id"]
    )
    op.create_table(
        "audit_events",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        _tenant_col(),
        sa.Column("actor_user_id", UUID(as_uuid=True), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=now, nullable=False),
        sa.Column("action", sa.String(80), nullable=False),
        sa.Column("resource_type", sa.String(60), nullable=False),
        sa.Column("resource_id", sa.String(64), nullable=True),
        sa.Column("outcome", sa.String(20), server_default="success", nullable=False),
        sa.Column("privileged", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("details", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_audit_events"),
        _fk("audit_events", "tenant_id", "tenants.id", "ae"),
        _fk("audit_events", "actor_user_id", "users.id", "ae"),
        sa.CheckConstraint(
            "outcome IN ('success','denied','failure')", name="ck_audit_events_outcome"
        ),
    )
    op.create_index(
        "ix_audit_events_tenant_id_occurred_at", "audit_events", ["tenant_id", "occurred_at"]
    )
    op.create_index("ix_audit_events_tenant_id_action", "audit_events", ["tenant_id", "action"])

    for table in TABLES:
        for stmt in enable_tenant_rls_sql(table):
            op.execute(stmt)
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON roles, user_role_assignments TO {APP_ROLE}")
    op.execute(f"GRANT SELECT, INSERT, DELETE ON role_permissions TO {APP_ROLE}")
    # Append-only: no UPDATE or DELETE for the application role.
    op.execute(f"GRANT SELECT, INSERT ON audit_events TO {APP_ROLE}")
    # Authentication events are written before a tenant context exists.
    op.execute(f"GRANT INSERT ON audit_events TO {AUTH_ROLE}")
    op.execute(
        f"CREATE POLICY auth_insert ON audit_events FOR INSERT TO {AUTH_ROLE} WITH CHECK (true)"
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS auth_insert ON audit_events")
    op.execute(f"REVOKE ALL ON {', '.join(TABLES)} FROM {APP_ROLE}, {AUTH_ROLE}")
    for table in reversed(TABLES):
        for stmt in disable_tenant_rls_sql(table):
            op.execute(stmt)
        op.drop_table(table)
