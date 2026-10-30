"""tenant isolation: dms_app role and row-level security

Revision ID: 0002
Revises: 0001

The dms_app role is cluster-wide, so downgrade revokes privileges but does not drop the role.
`users` is a global table and is intentionally not granted to dms_app yet (auth sprint).
"""

from alembic import op

from app.db.rls import APP_ROLE, disable_tenant_rls_sql, enable_tenant_rls_sql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        f"""
        DO $$ BEGIN
          IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
            CREATE ROLE {APP_ROLE} NOLOGIN;
          END IF;
        END $$
        """
    )
    op.execute(f"GRANT {APP_ROLE} TO CURRENT_USER")
    op.execute(f"GRANT USAGE ON SCHEMA public TO {APP_ROLE}")
    # No DELETE on memberships: deactivate instead of delete (PRD ORG-008).
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON tenant_memberships TO {APP_ROLE}")
    op.execute(f"GRANT SELECT ON tenants TO {APP_ROLE}")
    for stmt in enable_tenant_rls_sql("tenant_memberships"):
        op.execute(stmt)
    for stmt in enable_tenant_rls_sql("tenants", column="id"):
        op.execute(stmt)


def downgrade() -> None:
    for table in ("tenants", "tenant_memberships"):
        for stmt in disable_tenant_rls_sql(table):
            op.execute(stmt)
    op.execute(f"REVOKE ALL ON tenants, tenant_memberships FROM {APP_ROLE}")
    op.execute(f"REVOKE USAGE ON SCHEMA public FROM {APP_ROLE}")
