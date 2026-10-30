"""approval workflow: requests, step assignments, insert-only events; category approval steps

Revision ID: 0013
Revises: 0012

No backfill: versions that were waiting before this migration (development data only) have no
request and can only be released by re-uploading.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.db.rls import APP_ROLE, disable_tenant_rls_sql, enable_tenant_rls_sql

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None

PK = sa.text("gen_random_uuid()")
TABLES = ("approval_requests", "approval_assignments", "approval_events")


def _fk(col, ref, name):
    return sa.ForeignKeyConstraint([col], [ref], name=name, ondelete="RESTRICT")


def _base():
    return [
        sa.Column("id", UUID(as_uuid=True), server_default=PK, nullable=False),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
    ]


def _ts(name, nullable=False):
    return sa.Column(
        name,
        sa.DateTime(timezone=True),
        server_default=None if nullable else sa.func.now(),
        nullable=nullable,
    )


def upgrade() -> None:
    op.add_column(
        "category_versions",
        sa.Column("approval_steps", JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
    )
    op.create_table(
        "approval_requests",
        *_base(),
        sa.Column("document_id", UUID(as_uuid=True), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), server_default="pending", nullable=False),
        sa.Column("current_step", sa.Integer(), server_default="1", nullable=False),
        sa.Column("steps", JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("submitted_by_user_id", UUID(as_uuid=True), nullable=False),
        sa.Column("resubmission_of", UUID(as_uuid=True), nullable=True),
        _ts("submitted_at"),
        _ts("decided_at", nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_approval_requests"),
        _fk("tenant_id", "tenants.id", "fk_approval_requests_tenant_id_tenants"),
        _fk("document_id", "documents.id", "fk_approval_requests_document_id_documents"),
        _fk("submitted_by_user_id", "users.id", "fk_approval_requests_submitted_by_user_id_users"),
        _fk("resubmission_of", "approval_requests.id", "fk_approval_requests_resub"),
        sa.CheckConstraint(
            "status IN ('pending','approved','rejected','cancelled')",
            name="ck_approval_requests_status",
        ),
    )
    op.create_index(
        "uq_approval_requests_pending_document",
        "approval_requests",
        ["document_id"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index(
        "ix_approval_requests_tenant_id_status", "approval_requests", ["tenant_id", "status"]
    )
    op.create_table(
        "approval_assignments",
        *_base(),
        sa.Column("request_id", UUID(as_uuid=True), nullable=False),
        sa.Column("step_number", sa.Integer(), nullable=False),
        sa.Column("membership_id", UUID(as_uuid=True), nullable=False),
        _ts("created_at"),
        sa.PrimaryKeyConstraint("id", name="pk_approval_assignments"),
        _fk("tenant_id", "tenants.id", "fk_approval_assignments_tenant_id_tenants"),
        _fk(
            "request_id",
            "approval_requests.id",
            "fk_approval_assignments_request_id_approval_requests",
        ),
        _fk(
            "membership_id",
            "tenant_memberships.id",
            "fk_approval_assignments_membership_id_tenant_memberships",
        ),
        sa.UniqueConstraint(
            "request_id",
            "step_number",
            "membership_id",
            name="uq_approval_assignments_request_id_step_number_membership_id",
        ),
    )
    op.create_table(
        "approval_events",
        *_base(),
        sa.Column("request_id", UUID(as_uuid=True), nullable=False),
        sa.Column("step_number", sa.Integer(), nullable=True),
        sa.Column("actor_user_id", UUID(as_uuid=True), nullable=True),
        sa.Column("action", sa.String(20), nullable=False),
        sa.Column("comment", sa.String(1000), nullable=True),
        sa.Column("privileged", sa.Boolean(), server_default="false", nullable=False),
        _ts("created_at"),
        sa.PrimaryKeyConstraint("id", name="pk_approval_events"),
        _fk("tenant_id", "tenants.id", "fk_approval_events_tenant_id_tenants"),
        _fk(
            "request_id", "approval_requests.id", "fk_approval_events_request_id_approval_requests"
        ),
        _fk("actor_user_id", "users.id", "fk_approval_events_actor_user_id_users"),
        sa.CheckConstraint(
            "action IN ('submitted','step_started','approved','rejected','commented','resubmitted')",
            name="ck_approval_events_action",
        ),
    )
    op.create_index(
        "uq_approval_events_decision",
        "approval_events",
        ["request_id", "step_number", "actor_user_id", "action"],
        unique=True,
        postgresql_where=sa.text("action IN ('approved','rejected')"),
    )
    op.create_index(
        "ix_approval_events_request_id_created_at", "approval_events", ["request_id", "created_at"]
    )
    for table in TABLES:
        for stmt in enable_tenant_rls_sql(table):
            op.execute(stmt)
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON approval_requests TO {APP_ROLE}")
    # assignments and events are history: insert-only for the application
    op.execute(f"GRANT SELECT, INSERT ON approval_assignments, approval_events TO {APP_ROLE}")


def downgrade() -> None:
    op.execute(f"REVOKE ALL ON {', '.join(TABLES)} FROM {APP_ROLE}")
    for table in reversed(TABLES):
        for stmt in disable_tenant_rls_sql(table):
            op.execute(stmt)
        op.drop_table(table)
    op.drop_column("category_versions", "approval_steps")
