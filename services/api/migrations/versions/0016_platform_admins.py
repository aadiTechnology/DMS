"""platform administrators: people allowed to manage the shared UI template catalogue

Revision ID: 0016
Revises: 0015

A platform administrator is an ordinary user account listed here. The table has no tenant and no
row-level security; the sign-in role may read it to check a request, and only the owner
connection (the `python -m app.platform_admin` command) may change it. There is deliberately no
web or API path that grants the role.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

from app.db.rls import AUTH_ROLE

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "platform_admins",
        sa.Column("user_id", UUID(as_uuid=True), nullable=False),
        sa.Column("granted_by", sa.String(200), nullable=False, server_default="command"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("user_id", name="pk_platform_admins"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_platform_admins_user_id_users", ondelete="RESTRICT"
        ),
    )
    op.execute(f"GRANT SELECT ON platform_admins TO {AUTH_ROLE}")


def downgrade() -> None:
    op.execute(f"REVOKE ALL ON platform_admins FROM {AUTH_ROLE}")
    op.drop_table("platform_admins")
