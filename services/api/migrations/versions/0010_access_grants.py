"""document access grants; privileged-access permission for existing organization admins

Revision ID: 0010
Revises: 0009
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

from app.db.rls import APP_ROLE, disable_tenant_rls_sql, enable_tenant_rls_sql

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

PK = sa.text("gen_random_uuid()")


def _fk(col, ref, name):
    return sa.ForeignKeyConstraint([col], [ref], name=name, ondelete="RESTRICT")


def upgrade() -> None:
    op.create_table(
        "document_access_grants",
        sa.Column("id", UUID(as_uuid=True), server_default=PK, nullable=False),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", UUID(as_uuid=True), nullable=False),
        sa.Column("grantee_membership_id", UUID(as_uuid=True), nullable=False),
        sa.Column("can_view", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("can_download", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("granted_by_user_id", UUID(as_uuid=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by_user_id", UUID(as_uuid=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_document_access_grants"),
        _fk("tenant_id", "tenants.id", "fk_document_access_grants_tenant_id_tenants"),
        _fk("document_id", "documents.id", "fk_document_access_grants_document_id_documents"),
        _fk("grantee_membership_id", "tenant_memberships.id", "fk_dag_grantee_membership"),
        _fk("granted_by_user_id", "users.id", "fk_dag_granted_by_user"),
        _fk("revoked_by_user_id", "users.id", "fk_dag_revoked_by_user"),
        sa.CheckConstraint("can_view OR can_download", name="ck_document_access_grants_some_right"),
    )
    op.create_index(
        "uq_document_access_grants_active",
        "document_access_grants",
        ["document_id", "grantee_membership_id"],
        unique=True,
        postgresql_where=sa.text("revoked_at IS NULL"),
    )
    op.create_index(
        "ix_document_access_grants_tenant_id_grantee",
        "document_access_grants",
        ["tenant_id", "grantee_membership_id"],
    )
    for stmt in enable_tenant_rls_sql("document_access_grants"):
        op.execute(stmt)
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON document_access_grants TO {APP_ROLE}")

    # Existing organization administrators receive the new privileged-access permission.
    # FORCE is lifted only for this statement so a non-superuser table owner can run it.
    op.execute("ALTER TABLE role_permissions NO FORCE ROW LEVEL SECURITY")
    op.execute(
        "INSERT INTO role_permissions (tenant_id, role_id, permission_code) "
        "SELECT r.tenant_id, r.id, 'document.access_all' FROM roles r "
        "WHERE r.name = 'org_admin' AND r.is_system "
        "AND NOT EXISTS (SELECT 1 FROM role_permissions p "
        "WHERE p.role_id = r.id AND p.permission_code = 'document.access_all')"
    )
    op.execute("ALTER TABLE role_permissions FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("ALTER TABLE role_permissions NO FORCE ROW LEVEL SECURITY")
    op.execute("DELETE FROM role_permissions WHERE permission_code = 'document.access_all'")
    op.execute("ALTER TABLE role_permissions FORCE ROW LEVEL SECURITY")
    op.execute(f"REVOKE ALL ON document_access_grants FROM {APP_ROLE}")
    for stmt in disable_tenant_rls_sql("document_access_grants"):
        op.execute(stmt)
    op.drop_table("document_access_grants")
