"""lifecycle: retention dates, archive and deletion markers, legal holds, deletion requests

Revision ID: 0014
Revises: 0013

Existing documents keep NULL retention and review dates (no backfill; development data only).
Deleted documents stay as tombstones (metadata and history); their files are removed.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

from app.db.rls import APP_ROLE, disable_tenant_rls_sql, enable_tenant_rls_sql

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None

PK = sa.text("gen_random_uuid()")
TABLES = ("legal_holds", "deletion_requests")
OLD = "('draft','submitted','under_review','approved','rejected','archived')"
NEW = "('draft','submitted','under_review','approved','rejected','archived','deleted')"


def _base():
    return [
        sa.Column("id", UUID(as_uuid=True), server_default=PK, nullable=False),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", UUID(as_uuid=True), nullable=False),
    ]


def _fk(col, ref, name):
    return sa.ForeignKeyConstraint([col], [ref], name=name, ondelete="RESTRICT")


def _ts(name, nullable=True):
    return sa.Column(
        name,
        sa.DateTime(timezone=True),
        server_default=None if nullable else sa.func.now(),
        nullable=nullable,
    )


def upgrade() -> None:
    op.add_column("documents", sa.Column("retention_until", sa.Date(), nullable=True))
    op.add_column("documents", sa.Column("review_due_on", sa.Date(), nullable=True))
    op.add_column("documents", _ts("archived_at"))
    op.add_column("documents", _ts("deleted_at"))
    op.add_column("document_versions", _ts("purged_at"))
    op.drop_constraint("ck_documents_lifecycle_state", "documents", type_="check")
    op.create_check_constraint(
        "ck_documents_lifecycle_state", "documents", f"lifecycle_state IN {NEW}"
    )

    op.create_table(
        "legal_holds",
        *_base(),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("placed_by_user_id", UUID(as_uuid=True), nullable=False),
        _ts("placed_at", nullable=False),
        _ts("released_at"),
        sa.Column("released_by_user_id", UUID(as_uuid=True), nullable=True),
        sa.Column("release_reason", sa.String(500), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_legal_holds"),
        _fk("tenant_id", "tenants.id", "fk_legal_holds_tenant_id_tenants"),
        _fk("document_id", "documents.id", "fk_legal_holds_document_id_documents"),
        _fk("placed_by_user_id", "users.id", "fk_legal_holds_placed_by_user_id_users"),
        _fk("released_by_user_id", "users.id", "fk_legal_holds_released_by_user_id_users"),
    )
    op.create_index(
        "uq_legal_holds_active",
        "legal_holds",
        ["document_id"],
        unique=True,
        postgresql_where=sa.text("released_at IS NULL"),
    )
    op.create_table(
        "deletion_requests",
        *_base(),
        sa.Column("status", sa.String(20), server_default="pending", nullable=False),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("requested_by_user_id", UUID(as_uuid=True), nullable=False),
        _ts("requested_at", nullable=False),
        sa.Column("decided_by_user_id", UUID(as_uuid=True), nullable=True),
        sa.Column("decision_reason", sa.String(500), nullable=True),
        _ts("decided_at"),
        sa.PrimaryKeyConstraint("id", name="pk_deletion_requests"),
        _fk("tenant_id", "tenants.id", "fk_deletion_requests_tenant_id_tenants"),
        _fk("document_id", "documents.id", "fk_deletion_requests_document_id_documents"),
        _fk("requested_by_user_id", "users.id", "fk_deletion_requests_requested_by_user_id_users"),
        _fk("decided_by_user_id", "users.id", "fk_deletion_requests_decided_by_user_id_users"),
        sa.CheckConstraint(
            "status IN ('pending','approved','rejected','cancelled')",
            name="ck_deletion_requests_status",
        ),
    )
    op.create_index(
        "uq_deletion_requests_pending",
        "deletion_requests",
        ["document_id"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index(
        "ix_documents_tenant_id_retention_until", "documents", ["tenant_id", "retention_until"]
    )
    for table in TABLES:
        for stmt in enable_tenant_rls_sql(table):
            op.execute(stmt)
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON {', '.join(TABLES)} TO {APP_ROLE}")


def downgrade() -> None:
    op.execute(f"REVOKE ALL ON {', '.join(TABLES)} FROM {APP_ROLE}")
    for table in reversed(TABLES):
        for stmt in disable_tenant_rls_sql(table):
            op.execute(stmt)
        op.drop_table(table)
    op.drop_index("ix_documents_tenant_id_retention_until", table_name="documents")
    op.drop_constraint("ck_documents_lifecycle_state", "documents", type_="check")
    op.create_check_constraint(
        "ck_documents_lifecycle_state", "documents", f"lifecycle_state IN {OLD}"
    )
    op.drop_column("document_versions", "purged_at")
    for column in ("deleted_at", "archived_at", "review_due_on", "retention_until"):
        op.drop_column("documents", column)
