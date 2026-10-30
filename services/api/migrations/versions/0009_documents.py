"""documents, document versions, associations, document tags

Revision ID: 0009
Revises: 0008
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.db.rls import APP_ROLE, disable_tenant_rls_sql, enable_tenant_rls_sql

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

PK = sa.text("gen_random_uuid()")
TABLES = ("documents", "document_associations", "document_tags", "document_versions")
CLASSES = "('public','internal','confidential','highly_confidential')"
LIFECYCLE = "('draft','submitted','under_review','approved','rejected','archived')"
VERSION_STATUS = "('pending','receiving','available','quarantined','rejected','abandoned')"


def _id():
    return sa.Column("id", UUID(as_uuid=True), server_default=PK, nullable=False)


def _tenant():
    return sa.Column("tenant_id", UUID(as_uuid=True), nullable=False)


def _ts(name, nullable=False, default=True):
    return sa.Column(
        name,
        sa.DateTime(timezone=True),
        server_default=sa.func.now() if default else None,
        nullable=nullable,
    )


def _fk(table, col, ref, name=None):
    return sa.ForeignKeyConstraint(
        [col], [ref], name=name or f"fk_{table}_{col}_{ref.split('.')[0]}", ondelete="RESTRICT"
    )


def upgrade() -> None:
    op.create_table(
        "documents",
        _id(),
        _tenant(),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("category_id", UUID(as_uuid=True), nullable=False),
        sa.Column("category_version_number", sa.Integer(), nullable=False),
        sa.Column("classification", sa.String(30), nullable=False),
        sa.Column("lifecycle_state", sa.String(20), server_default="draft", nullable=False),
        sa.Column("owner_membership_id", UUID(as_uuid=True), nullable=False),
        sa.Column("created_by_user_id", UUID(as_uuid=True), nullable=False),
        sa.Column("current_version_number", sa.Integer(), nullable=True),
        sa.Column(
            "metadata_values", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column("row_version", sa.Integer(), server_default="1", nullable=False),
        _ts("created_at"),
        _ts("updated_at"),
        sa.PrimaryKeyConstraint("id", name="pk_documents"),
        _fk("documents", "tenant_id", "tenants.id"),
        _fk("documents", "category_id", "categories.id"),
        _fk("documents", "owner_membership_id", "tenant_memberships.id"),
        _fk("documents", "created_by_user_id", "users.id"),
        sa.CheckConstraint(f"classification IN {CLASSES}", name="ck_documents_classification"),
        sa.CheckConstraint(f"lifecycle_state IN {LIFECYCLE}", name="ck_documents_lifecycle_state"),
    )
    op.create_index("ix_documents_tenant_id_category_id", "documents", ["tenant_id", "category_id"])
    op.create_index(
        "ix_documents_tenant_id_created_by_user_id",
        "documents",
        ["tenant_id", "created_by_user_id"],
    )
    op.create_table(
        "document_associations",
        _id(),
        _tenant(),
        sa.Column("document_id", UUID(as_uuid=True), nullable=False),
        sa.Column("dimension", sa.String(20), nullable=False),
        sa.Column("ref_id", UUID(as_uuid=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_document_associations"),
        _fk("document_associations", "tenant_id", "tenants.id"),
        _fk("document_associations", "document_id", "documents.id"),
        sa.UniqueConstraint(
            "document_id",
            "dimension",
            "ref_id",
            name="uq_document_associations_document_id_dimension_ref_id",
        ),
        sa.CheckConstraint(
            "dimension IN ('department','branch','project','employee')",
            name="ck_document_associations_dimension",
        ),
    )
    op.create_index(
        "ix_document_associations_tenant_id_dimension_ref_id",
        "document_associations",
        ["tenant_id", "dimension", "ref_id"],
    )
    op.create_table(
        "document_tags",
        _id(),
        _tenant(),
        sa.Column("document_id", UUID(as_uuid=True), nullable=False),
        sa.Column("tag_id", UUID(as_uuid=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_document_tags"),
        _fk("document_tags", "tenant_id", "tenants.id"),
        _fk("document_tags", "document_id", "documents.id"),
        _fk("document_tags", "tag_id", "tags.id"),
        sa.UniqueConstraint("document_id", "tag_id", name="uq_document_tags_document_id_tag_id"),
    )
    op.create_table(
        "document_versions",
        _id(),
        _tenant(),
        sa.Column("document_id", UUID(as_uuid=True), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), server_default="pending", nullable=False),
        sa.Column("original_filename", sa.String(300), nullable=False),
        sa.Column("declared_content_type", sa.String(150), nullable=False),
        sa.Column("declared_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("content_type", sa.String(150), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("sha1", sa.String(40), nullable=True),
        sa.Column("sha256", sa.String(64), nullable=True),
        sa.Column("object_key", sa.String(1024), nullable=False),
        sa.Column("storage_file_id", sa.String(255), nullable=True),
        sa.Column("scan_status", sa.String(20), server_default="pending", nullable=False),
        sa.Column("scan_detail", sa.String(200), nullable=True),
        sa.Column("reject_reason", sa.String(60), nullable=True),
        sa.Column("comment", sa.String(300), nullable=True),
        sa.Column("uploaded_by_user_id", UUID(as_uuid=True), nullable=False),
        sa.Column("idempotency_key", sa.String(100), nullable=True),
        _ts("expires_at", default=False),
        _ts("created_at"),
        _ts("finalized_at", nullable=True, default=False),
        sa.PrimaryKeyConstraint("id", name="pk_document_versions"),
        _fk("document_versions", "tenant_id", "tenants.id"),
        _fk("document_versions", "document_id", "documents.id"),
        _fk("document_versions", "uploaded_by_user_id", "users.id"),
        sa.UniqueConstraint(
            "document_id", "version_number", name="uq_document_versions_document_id_version_number"
        ),
        sa.UniqueConstraint("object_key", name="uq_document_versions_object_key"),
        sa.CheckConstraint(f"status IN {VERSION_STATUS}", name="ck_document_versions_status"),
        sa.CheckConstraint(
            "scan_status IN ('pending','clean','infected','failed')",
            name="ck_document_versions_scan_status",
        ),
    )
    op.create_index(
        "uq_document_versions_idempotency",
        "document_versions",
        ["tenant_id", "uploaded_by_user_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )

    for table in TABLES:
        for stmt in enable_tenant_rls_sql(table):
            op.execute(stmt)
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON documents, document_versions TO {APP_ROLE}")
    op.execute(f"GRANT SELECT, INSERT ON document_associations, document_tags TO {APP_ROLE}")


def downgrade() -> None:
    op.execute(f"REVOKE ALL ON {', '.join(TABLES)} FROM {APP_ROLE}")
    for table in reversed(TABLES):
        for stmt in disable_tenant_rls_sql(table):
            op.execute(stmt)
        op.drop_table(table)
