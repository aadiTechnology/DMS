"""authentication: password columns, user_sessions, dms_auth role

Revision ID: 0003
Revises: 0002

dms_auth is the only role (besides the owner) that can read users and write sessions. It may
read tenants and memberships across tenants (needed to resolve which tenant a login belongs to);
dms_app, used for tenant request work, still cannot touch users or sessions.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

AUTH_ROLE = "dms_auth"


def upgrade() -> None:
    op.add_column("users", sa.Column("password_hash", sa.Text(), nullable=True))
    op.add_column(
        "users",
        sa.Column("failed_login_count", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column("users", sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True))

    op.create_table(
        "user_sessions",
        sa.Column(
            "id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("user_id", UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("refresh_hash", sa.String(64), nullable=False),
        sa.Column("prev_refresh_hash", sa.String(64), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_reason", sa.String(40), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_user_sessions"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_user_sessions_user_id_users", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_user_sessions_tenant_id_tenants",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("refresh_hash", name="uq_user_sessions_refresh_hash"),
    )
    op.create_index("ix_user_sessions_user_id", "user_sessions", ["user_id"])
    op.create_index("ix_user_sessions_prev_refresh_hash", "user_sessions", ["prev_refresh_hash"])

    op.execute(
        f"""
        DO $$ BEGIN
          IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{AUTH_ROLE}') THEN
            CREATE ROLE {AUTH_ROLE} NOLOGIN;
          END IF;
        END $$
        """
    )
    op.execute(f"GRANT {AUTH_ROLE} TO CURRENT_USER")
    op.execute(f"GRANT USAGE ON SCHEMA public TO {AUTH_ROLE}")
    op.execute(f"GRANT SELECT, UPDATE ON users TO {AUTH_ROLE}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON user_sessions TO {AUTH_ROLE}")
    op.execute(f"GRANT SELECT ON tenants, tenant_memberships TO {AUTH_ROLE}")
    for table in ("tenants", "tenant_memberships"):
        op.execute(f"CREATE POLICY auth_read ON {table} FOR SELECT TO {AUTH_ROLE} USING (true)")


def downgrade() -> None:
    for table in ("tenants", "tenant_memberships"):
        op.execute(f"DROP POLICY IF EXISTS auth_read ON {table}")
    op.execute(f"REVOKE ALL ON users, user_sessions, tenants, tenant_memberships FROM {AUTH_ROLE}")
    op.execute(f"REVOKE USAGE ON SCHEMA public FROM {AUTH_ROLE}")
    op.drop_table("user_sessions")
    for col in ("last_login_at", "locked_until", "failed_login_count", "password_hash"):
        op.drop_column("users", col)
