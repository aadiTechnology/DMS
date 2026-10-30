"""SSO identity links and TOTP MFA

Revision ID: 0007
Revises: 0006
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

from app.db.rls import AUTH_ROLE

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

PK = sa.text("gen_random_uuid()")


def upgrade() -> None:
    op.add_column(
        "users", sa.Column("mfa_enabled", sa.Boolean(), server_default="false", nullable=False)
    )
    op.add_column("users", sa.Column("mfa_secret_encrypted", sa.Text(), nullable=True))
    op.add_column(
        "users",
        sa.Column("mfa_last_used_step", sa.BigInteger(), server_default="0", nullable=False),
    )
    op.create_table(
        "identity_links",
        sa.Column("id", UUID(as_uuid=True), server_default=PK, nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(20), nullable=False),
        sa.Column("subject", sa.String(255), nullable=False),
        sa.Column("email_at_link", sa.String(320), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_identity_links"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_identity_links_user_id_users", ondelete="RESTRICT"
        ),
        sa.UniqueConstraint("provider", "subject", name="uq_identity_links_provider_subject"),
        sa.UniqueConstraint("user_id", "provider", name="uq_identity_links_user_id_provider"),
        sa.CheckConstraint("provider IN ('google','microsoft')", name="ck_identity_links_provider"),
    )
    op.create_table(
        "mfa_recovery_codes",
        sa.Column("id", UUID(as_uuid=True), server_default=PK, nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), nullable=False),
        sa.Column("code_hash", sa.String(64), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_mfa_recovery_codes"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_mfa_recovery_codes_user_id_users",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("code_hash", name="uq_mfa_recovery_codes_code_hash"),
    )
    op.create_index("ix_mfa_recovery_codes_user_id", "mfa_recovery_codes", ["user_id"])
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON identity_links TO {AUTH_ROLE}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON mfa_recovery_codes TO {AUTH_ROLE}")


def downgrade() -> None:
    op.execute(f"REVOKE ALL ON identity_links, mfa_recovery_codes FROM {AUTH_ROLE}")
    op.drop_table("mfa_recovery_codes")
    op.drop_table("identity_links")
    for col in ("mfa_last_used_step", "mfa_secret_encrypted", "mfa_enabled"):
        op.drop_column("users", col)
