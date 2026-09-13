"""Add expiry tracking for disposable anonymous RP accounts."""

import sqlalchemy as sa

from alembic import op

revision = "20260914_anonymous_rp_accounts"
down_revision = "20260913_schema_parity_repair"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "accounts",
        sa.Column("temporary_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_accounts_temporary_expires_at",
        "accounts",
        ["temporary_expires_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_accounts_temporary_expires_at", table_name="accounts")
    op.drop_column("accounts", "temporary_expires_at")
