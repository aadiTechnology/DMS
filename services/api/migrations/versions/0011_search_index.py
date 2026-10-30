"""search index: document_search (weighted metadata vector, content vector, extraction state)

Revision ID: 0011
Revises: 0010
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import TSVECTOR, UUID

from app.db.rls import APP_ROLE, disable_tenant_rls_sql, enable_tenant_rls_sql

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "document_search",
        sa.Column("document_id", UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("meta_tsv", TSVECTOR(), nullable=True),
        sa.Column("content_tsv", TSVECTOR(), nullable=True),
        sa.Column("content_version_number", sa.Integer(), nullable=True),
        sa.Column("extraction_status", sa.String(20), server_default="pending", nullable=False),
        sa.Column("failure_reason", sa.String(60), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("truncated", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("document_id", name="pk_document_search"),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name="fk_document_search_document_id_documents",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_document_search_tenant_id_tenants",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "extraction_status IN ('pending','processing','indexed','failed','unsupported')",
            name="ck_document_search_extraction_status",
        ),
    )
    op.create_index(
        "ix_document_search_meta_tsv", "document_search", ["meta_tsv"], postgresql_using="gin"
    )
    op.create_index(
        "ix_document_search_content_tsv", "document_search", ["content_tsv"], postgresql_using="gin"
    )
    op.create_index(
        "ix_document_search_tenant_id_status", "document_search", ["tenant_id", "extraction_status"]
    )
    for stmt in enable_tenant_rls_sql("document_search"):
        op.execute(stmt)
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON document_search TO {APP_ROLE}")


def downgrade() -> None:
    op.execute(f"REVOKE ALL ON document_search FROM {APP_ROLE}")
    for stmt in disable_tenant_rls_sql("document_search"):
        op.execute(stmt)
    op.drop_table("document_search")
