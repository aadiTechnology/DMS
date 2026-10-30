"""organization structure: departments, branches, projects, designations, profiles, project members

Revision ID: 0005
Revises: 0004
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

from app.db.rls import APP_ROLE, disable_tenant_rls_sql, enable_tenant_rls_sql

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

PK = sa.text("gen_random_uuid()")
TABLES = (
    "departments",
    "branches",
    "projects",
    "designations",
    "employee_profiles",
    "project_memberships",
)
ORG_STATUS = "status IN ('active','inactive')"


def _id():
    return sa.Column("id", UUID(as_uuid=True), server_default=PK, nullable=False)


def _tenant():
    return sa.Column("tenant_id", UUID(as_uuid=True), nullable=False)


def _uuid(name, nullable=True):
    return sa.Column(name, UUID(as_uuid=True), nullable=nullable)


def _created(name="created_at"):
    return sa.Column(name, sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


def _status():
    return sa.Column("status", sa.String(20), server_default="active", nullable=False)


def _fk(table, col, ref, ondelete="RESTRICT", name=None):
    return sa.ForeignKeyConstraint(
        [col], [ref], name=name or f"fk_{table}_{col}_{ref.split('.')[0]}", ondelete=ondelete
    )


def upgrade() -> None:
    for table in ("departments", "branches", "projects"):
        cols = [
            _id(),
            _tenant(),
            sa.Column("name", sa.String(200), nullable=False),
            sa.Column("code", sa.String(40), nullable=False),
            _status(),
        ]
        extra = []
        if table == "departments":
            cols.append(_uuid("parent_id"))
            extra.append(_fk(table, "parent_id", "departments.id"))
        if table in ("departments", "projects"):
            cols.append(_uuid("manager_membership_id"))
            extra.append(_fk(table, "manager_membership_id", "tenant_memberships.id"))
        op.create_table(
            table,
            *cols,
            _created(),
            sa.PrimaryKeyConstraint("id", name=f"pk_{table}"),
            _fk(table, "tenant_id", "tenants.id"),
            *extra,
            sa.UniqueConstraint("tenant_id", "code", name=f"uq_{table}_tenant_id_code"),
            sa.UniqueConstraint("tenant_id", "name", name=f"uq_{table}_tenant_id_name"),
            sa.CheckConstraint(ORG_STATUS, name=f"ck_{table}_status"),
        )
    op.create_table(
        "designations",
        _id(),
        _tenant(),
        sa.Column("name", sa.String(200), nullable=False),
        _status(),
        _created(),
        sa.PrimaryKeyConstraint("id", name="pk_designations"),
        _fk("designations", "tenant_id", "tenants.id"),
        sa.UniqueConstraint("tenant_id", "name", name="uq_designations_tenant_id_name"),
        sa.CheckConstraint(ORG_STATUS, name="ck_designations_status"),
    )
    op.create_table(
        "employee_profiles",
        _id(),
        _tenant(),
        _uuid("membership_id", nullable=False),
        sa.Column("full_name", sa.String(200), nullable=False),
        sa.Column("work_email", sa.String(320), nullable=True),
        _uuid("department_id"),
        _uuid("branch_id"),
        _uuid("designation_id"),
        _uuid("reporting_manager_membership_id"),
        sa.Column("employment_status", sa.String(20), server_default="active", nullable=False),
        _created("updated_at"),
        sa.PrimaryKeyConstraint("id", name="pk_employee_profiles"),
        _fk("employee_profiles", "tenant_id", "tenants.id"),
        _fk("employee_profiles", "membership_id", "tenant_memberships.id"),
        _fk("employee_profiles", "department_id", "departments.id"),
        _fk("employee_profiles", "branch_id", "branches.id"),
        _fk("employee_profiles", "designation_id", "designations.id"),
        _fk(
            "employee_profiles",
            "reporting_manager_membership_id",
            "tenant_memberships.id",
            name="fk_employee_profiles_reporting_manager",
        ),
        sa.UniqueConstraint("membership_id", name="uq_employee_profiles_membership_id"),
        sa.CheckConstraint(
            "employment_status IN ('active','on_leave','exited')",
            name="ck_employee_profiles_employment_status",
        ),
    )
    op.create_table(
        "project_memberships",
        _id(),
        _tenant(),
        _uuid("project_id", nullable=False),
        _uuid("membership_id", nullable=False),
        sa.Column("project_role", sa.String(60), server_default="member", nullable=False),
        sa.Column("starts_on", sa.Date(), server_default=sa.func.current_date(), nullable=False),
        sa.Column("ends_on", sa.Date(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_project_memberships"),
        _fk("project_memberships", "tenant_id", "tenants.id"),
        _fk("project_memberships", "project_id", "projects.id"),
        _fk("project_memberships", "membership_id", "tenant_memberships.id"),
        sa.UniqueConstraint(
            "project_id", "membership_id", name="uq_project_memberships_project_id_membership_id"
        ),
    )
    for table in TABLES:
        for stmt in enable_tenant_rls_sql(table):
            op.execute(stmt)
    # No DELETE anywhere: deactivate instead (ORG-008).
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON {', '.join(TABLES)} TO {APP_ROLE}")


def downgrade() -> None:
    op.execute(f"REVOKE ALL ON {', '.join(TABLES)} FROM {APP_ROLE}")
    for table in reversed(TABLES):
        for stmt in disable_tenant_rls_sql(table):
            op.execute(stmt)
        op.drop_table(table)
