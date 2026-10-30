"""document versions: review status (approval gate) and restore lineage

Revision ID: 0012
Revises: 0011
"""

import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "document_versions",
        sa.Column("review_status", sa.String(20), server_default="none", nullable=False),
    )
    op.add_column(
        "document_versions", sa.Column("restored_from_version", sa.Integer(), nullable=True)
    )
    op.create_check_constraint(
        "ck_document_versions_review_status",
        "document_versions",
        "review_status IN ('none','pending','approved','rejected')",
    )
    # Versions already waiting for approval (documents submitted before this change).
    # FORCE is lifted only for this statement so a non-superuser table owner can run it.
    op.execute("ALTER TABLE document_versions NO FORCE ROW LEVEL SECURITY")
    op.execute(
        "UPDATE document_versions v SET review_status = 'pending' FROM documents d "
        "WHERE v.document_id = d.id AND v.status = 'available' "
        "AND d.lifecycle_state IN ('submitted','under_review')"
    )
    op.execute("ALTER TABLE document_versions FORCE ROW LEVEL SECURITY")
    op.execute("GRANT DELETE ON document_tags TO dms_app")


def downgrade() -> None:
    op.execute("REVOKE DELETE ON document_tags FROM dms_app")
    op.drop_constraint("ck_document_versions_review_status", "document_versions", type_="check")
    op.drop_column("document_versions", "restored_from_version")
    op.drop_column("document_versions", "review_status")
