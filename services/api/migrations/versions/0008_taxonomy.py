"""taxonomy: categories, immutable category versions, metadata fields, tags

Revision ID: 0008
Revises: 0007
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID

from app.db.rls import APP_ROLE, disable_tenant_rls_sql, enable_tenant_rls_sql

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

PK = sa.text("gen_random_uuid()")
TABLES = ("categories", "category_versions", "metadata_field_definitions", "tags")
ZERO = "'00000000-0000-0000-0000-000000000000'::uuid"
CLASSES = "('public','internal','confidential','highly_confidential')"


def _id():
    return sa.Column("id", UUID(as_uuid=True), server_default=PK, nullable=False)


def _tenant():
    return sa.Column("tenant_id", UUID(as_uuid=True), nullable=False)


def _created():
    return sa.Column(
        "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )


def _fk(table, col, ref, name=None):
    return sa.ForeignKeyConstraint(
        [col], [ref], name=name or f"fk_{table}_{col}_{ref.split('.')[0]}", ondelete="RESTRICT"
    )


def upgrade() -> None:
    op.add_column(
        "tenants",
        sa.Column("allow_employee_tags", sa.Boolean(), server_default="true", nullable=False),
    )
    op.create_table(
        "categories",
        _id(),
        _tenant(),
        sa.Column("parent_id", UUID(as_uuid=True), nullable=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("status", sa.String(20), server_default="active", nullable=False),
        sa.Column(
            "default_classification", sa.String(30), server_default="internal", nullable=False
        ),
        sa.Column("current_version_number", sa.Integer(), server_default="1", nullable=False),
        _created(),
        sa.PrimaryKeyConstraint("id", name="pk_categories"),
        _fk("categories", "tenant_id", "tenants.id"),
        _fk("categories", "parent_id", "categories.id"),
        sa.CheckConstraint("status IN ('active','inactive')", name="ck_categories_status"),
        sa.CheckConstraint(
            f"default_classification IN {CLASSES}", name="ck_categories_default_classification"
        ),
    )
    op.create_index(
        "uq_categories_tenant_parent_name",
        "categories",
        ["tenant_id", sa.text(f"coalesce(parent_id, {ZERO})"), sa.text("lower(name)")],
        unique=True,
    )
    op.create_table(
        "category_versions",
        _id(),
        _tenant(),
        sa.Column("category_id", UUID(as_uuid=True), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("approval_required", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "required_dimensions",
            ARRAY(sa.String(20)),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column("allowed_extensions", ARRAY(sa.String(10)), nullable=True),
        sa.Column("retention_days", sa.Integer(), nullable=True),
        sa.Column("review_interval_days", sa.Integer(), nullable=True),
        sa.Column("expiry_action", sa.String(20), server_default="archive", nullable=False),
        sa.Column(
            "reminder_days", ARRAY(sa.Integer()), server_default=sa.text("'{}'"), nullable=False
        ),
        _created(),
        sa.Column("created_by_user_id", UUID(as_uuid=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_category_versions"),
        _fk("category_versions", "tenant_id", "tenants.id"),
        _fk("category_versions", "category_id", "categories.id"),
        _fk("category_versions", "created_by_user_id", "users.id"),
        sa.UniqueConstraint(
            "category_id", "version_number", name="uq_category_versions_category_id_version_number"
        ),
        sa.CheckConstraint(
            "expiry_action IN ('archive')", name="ck_category_versions_expiry_action"
        ),
    )
    op.create_table(
        "metadata_field_definitions",
        _id(),
        _tenant(),
        sa.Column("category_version_id", UUID(as_uuid=True), nullable=False),
        sa.Column("key", sa.String(40), nullable=False),
        sa.Column("label", sa.String(120), nullable=False),
        sa.Column("field_type", sa.String(30), nullable=False),
        sa.Column("required", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("searchable", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("display_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("default_value", JSONB(), nullable=True),
        sa.Column("validation", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_metadata_field_definitions"),
        _fk("metadata_field_definitions", "tenant_id", "tenants.id"),
        _fk(
            "metadata_field_definitions",
            "category_version_id",
            "category_versions.id",
            "fk_mfd_category_version",
        ),
        sa.UniqueConstraint(
            "category_version_id",
            "key",
            name="uq_metadata_field_definitions_category_version_id_key",
        ),
    )
    op.create_table(
        "tags",
        _id(),
        _tenant(),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), server_default="active", nullable=False),
        sa.Column("created_by_user_id", UUID(as_uuid=True), nullable=True),
        _created(),
        sa.PrimaryKeyConstraint("id", name="pk_tags"),
        _fk("tags", "tenant_id", "tenants.id"),
        _fk("tags", "created_by_user_id", "users.id"),
        sa.CheckConstraint("kind IN ('standard','employee','system')", name="ck_tags_kind"),
        sa.CheckConstraint("status IN ('active','inactive')", name="ck_tags_status"),
    )
    op.create_index(
        "uq_tags_tenant_name", "tags", ["tenant_id", sa.text("lower(name)")], unique=True
    )

    for table in TABLES:
        for stmt in enable_tenant_rls_sql(table):
            op.execute(stmt)
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON categories, tags TO {APP_ROLE}")
    # Versions and their fields are immutable history: INSERT only, no UPDATE, no DELETE.
    op.execute(
        f"GRANT SELECT, INSERT ON category_versions, metadata_field_definitions TO {APP_ROLE}"
    )
    op.execute(f"GRANT UPDATE (allow_employee_tags) ON tenants TO {APP_ROLE}")
    # Backfill the system lifecycle tags (TAG-003) for tenants that already exist.
    # FORCE is lifted only for this statement so a non-superuser table owner can run it.
    op.execute("ALTER TABLE tags NO FORCE ROW LEVEL SECURITY")
    op.execute(
        "INSERT INTO tags (tenant_id, name, kind) "
        "SELECT t.id, n.name, 'system' FROM tenants t "
        "CROSS JOIN (VALUES ('Pending'), ('Approved'), ('Archived')) AS n(name)"
    )
    op.execute("ALTER TABLE tags FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute(f"REVOKE UPDATE (allow_employee_tags) ON tenants FROM {APP_ROLE}")
    op.execute(f"REVOKE ALL ON {', '.join(TABLES)} FROM {APP_ROLE}")
    for table in reversed(TABLES):
        for stmt in disable_tenant_rls_sql(table):
            op.execute(stmt)
        op.drop_table(table)
    op.drop_column("tenants", "allow_employee_tags")
