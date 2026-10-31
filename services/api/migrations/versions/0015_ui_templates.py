"""UI templates: template catalogue, version history, per-user preference, tenant default

Revision ID: 0015
Revises: 0014

Platform templates have no tenant (tenant_id NULL) and are written only by the `dms_platform`
role. Tenants read published platform templates and their own tenant templates. Tenants never
see drafts or archived platform templates. A user's preference is a row per tenant, user and
product; template_id NULL means "use the default" (so no DELETE grant is needed).
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.db.rls import (
    APP_ROLE,
    PLATFORM_ROLE,
    disable_tenant_rls_sql,
    enable_tenant_rls_sql,
    tenant_predicate,
)

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None

PK = sa.text("gen_random_uuid()")
STATUSES = "('draft','published','archived')"


def _ts(name, nullable=False):
    return sa.Column(
        name,
        sa.DateTime(timezone=True),
        server_default=None if nullable else sa.func.now(),
        nullable=nullable,
    )


def upgrade() -> None:
    op.execute(
        f"""
        DO $$ BEGIN
          IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{PLATFORM_ROLE}') THEN
            CREATE ROLE {PLATFORM_ROLE} NOLOGIN;
          END IF;
        END $$
        """
    )
    op.execute(f"GRANT {PLATFORM_ROLE} TO CURRENT_USER")
    op.execute(f"GRANT USAGE ON SCHEMA public TO {PLATFORM_ROLE}")

    op.create_table(
        "ui_templates",
        sa.Column("id", UUID(as_uuid=True), server_default=PK, nullable=False),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=True),
        sa.Column("product_code", sa.String(32), nullable=False),
        sa.Column("template_key", sa.String(64), nullable=False),
        sa.Column("template_name", sa.String(80), nullable=False),
        sa.Column("description", sa.String(300), nullable=False, server_default=""),
        sa.Column("config_json", JSONB(), nullable=False),
        sa.Column("preview_image_url", sa.String(300), nullable=True),
        sa.Column("version", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), server_default="draft", nullable=False),
        sa.Column("scope", sa.String(20), server_default="platform", nullable=False),
        sa.Column("created_by", UUID(as_uuid=True), nullable=True),
        _ts("created_at"),
        _ts("updated_at"),
        sa.PrimaryKeyConstraint("id", name="pk_ui_templates"),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_ui_templates_tenant_id_tenants",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name="fk_ui_templates_created_by_users",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(f"status IN {STATUSES}", name="ck_ui_templates_status"),
        sa.CheckConstraint(
            "(scope = 'platform' AND tenant_id IS NULL) OR (scope = 'tenant' AND tenant_id IS NOT NULL)",
            name="ck_ui_templates_scope",
        ),
    )
    op.create_index(
        "uq_ui_templates_platform_key", "ui_templates", ["product_code", "template_key"],
        unique=True, postgresql_where=sa.text("tenant_id IS NULL"),
    )  # fmt: skip
    op.create_index(
        "uq_ui_templates_tenant_key", "ui_templates", ["tenant_id", "product_code", "template_key"],
        unique=True, postgresql_where=sa.text("tenant_id IS NOT NULL"),
    )  # fmt: skip
    op.create_index(
        "ix_ui_templates_product_code_status", "ui_templates", ["product_code", "status"]
    )

    op.create_table(
        "ui_template_versions",
        sa.Column("id", UUID(as_uuid=True), server_default=PK, nullable=False),
        sa.Column("template_id", UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.String(20), nullable=False),
        sa.Column("config_json", JSONB(), nullable=False),
        _ts("created_at"),
        _ts("published_at", nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_ui_template_versions"),
        sa.ForeignKeyConstraint(
            ["template_id"],
            ["ui_templates.id"],
            name="fk_ui_template_versions_template_id_ui_templates",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "template_id", "version", name="uq_ui_template_versions_template_id_version"
        ),
    )

    op.create_table(
        "user_ui_preferences",
        sa.Column("id", UUID(as_uuid=True), server_default=PK, nullable=False),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), nullable=False),
        sa.Column("product_code", sa.String(32), nullable=False),
        sa.Column("template_id", UUID(as_uuid=True), nullable=True),
        _ts("updated_at"),
        sa.PrimaryKeyConstraint("id", name="pk_user_ui_preferences"),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_user_ui_preferences_tenant_id_tenants",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_user_ui_preferences_user_id_users",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["template_id"],
            ["ui_templates.id"],
            name="fk_user_ui_preferences_template_id_ui_templates",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "user_id",
            "product_code",
            name="uq_user_ui_preferences_tenant_id_user_id_product_code",
        ),
    )

    op.create_table(
        "tenant_ui_defaults",
        sa.Column("id", UUID(as_uuid=True), server_default=PK, nullable=False),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("product_code", sa.String(32), nullable=False),
        sa.Column("template_id", UUID(as_uuid=True), nullable=True),
        sa.Column("set_by_user_id", UUID(as_uuid=True), nullable=True),
        _ts("updated_at"),
        sa.PrimaryKeyConstraint("id", name="pk_tenant_ui_defaults"),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_tenant_ui_defaults_tenant_id_tenants",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["template_id"],
            ["ui_templates.id"],
            name="fk_tenant_ui_defaults_template_id_ui_templates",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["set_by_user_id"],
            ["users.id"],
            name="fk_tenant_ui_defaults_set_by_user_id_users",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "tenant_id", "product_code", name="uq_tenant_ui_defaults_tenant_id_product_code"
        ),
    )

    for table in ("user_ui_preferences", "tenant_ui_defaults"):
        for stmt in enable_tenant_rls_sql(table):
            op.execute(stmt)
    op.execute(
        f"GRANT SELECT, INSERT, UPDATE ON user_ui_preferences, tenant_ui_defaults TO {APP_ROLE}"
    )

    op.execute("ALTER TABLE ui_templates ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE ui_templates FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY app_read ON ui_templates FOR SELECT TO {APP_ROLE} "
        f"USING ((tenant_id IS NULL AND status = 'published') OR tenant_id = {tenant_predicate()})"
    )
    op.execute(
        f"CREATE POLICY platform_all ON ui_templates FOR ALL TO {PLATFORM_ROLE} USING (true) WITH CHECK (true)"
    )
    op.execute(f"GRANT SELECT ON ui_templates TO {APP_ROLE}")
    op.execute("ALTER TABLE ui_template_versions ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE ui_template_versions FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY platform_all ON ui_template_versions FOR ALL TO {PLATFORM_ROLE} USING (true) WITH CHECK (true)"
    )
    op.execute(
        f"GRANT SELECT, INSERT, UPDATE ON ui_templates, ui_template_versions TO {PLATFORM_ROLE}"
    )


def downgrade() -> None:
    op.execute(f"REVOKE ALL ON ui_templates, ui_template_versions FROM {PLATFORM_ROLE}")
    op.execute(
        f"REVOKE ALL ON user_ui_preferences, tenant_ui_defaults, ui_templates FROM {APP_ROLE}"
    )
    for table in ("tenant_ui_defaults", "user_ui_preferences"):
        for stmt in disable_tenant_rls_sql(table):
            op.execute(stmt)
        op.drop_table(table)
    op.drop_table("ui_template_versions")
    op.execute("DROP POLICY IF EXISTS app_read ON ui_templates")
    op.execute("DROP POLICY IF EXISTS platform_all ON ui_templates")
    op.drop_table("ui_templates")
    op.execute(f"REVOKE USAGE ON SCHEMA public FROM {PLATFORM_ROLE}")
