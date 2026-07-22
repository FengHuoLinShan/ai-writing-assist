"""Add exact context confirmation asset references.

Revision ID: 20260722_context_confirm_refs
Revises: 20260717_character_profiles
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260722_context_confirm_refs"
down_revision = "20260717_character_profiles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("context_confirmation_asset_refs"):
        return
    guid_type = sa.CHAR(36).with_variant(
        postgresql.UUID(as_uuid=True),
        "postgresql",
    )
    with op.batch_alter_table("context_confirmations") as batch_op:
        batch_op.create_unique_constraint(
            "uq_context_confirmations_id_novel",
            ["id", "novel_id"],
        )

    op.create_table(
        "context_confirmation_asset_refs",
        sa.Column("confirmation_id", guid_type, nullable=False),
        sa.Column("novel_id", guid_type, nullable=False),
        sa.Column("asset_role", sa.String(length=16), nullable=False),
        sa.Column("asset_type", sa.String(length=128), nullable=False),
        sa.Column("asset_id", sa.String(length=255), nullable=False),
        sa.ForeignKeyConstraint(
            ["confirmation_id", "novel_id"],
            ["context_confirmations.id", "context_confirmations.novel_id"],
            name="fk_context_confirmation_asset_refs_owner",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "confirmation_id",
            "asset_role",
            "asset_type",
            "asset_id",
        ),
        comment="确认记录选中及结果资产的精确失效索引",
    )
    op.create_index(
        "ix_context_confirmation_asset_refs_lookup",
        "context_confirmation_asset_refs",
        ["novel_id", "asset_type", "asset_id"],
        unique=False,
    )
    # Test projects are intentionally disposable; do not infer/backfill refs
    # from legacy JSON columns. New confirmations populate this table atomically.


def downgrade() -> None:
    op.drop_index(
        "ix_context_confirmation_asset_refs_lookup",
        table_name="context_confirmation_asset_refs",
    )
    op.drop_table("context_confirmation_asset_refs")
    with op.batch_alter_table("context_confirmations") as batch_op:
        batch_op.drop_constraint(
            "uq_context_confirmations_id_novel",
            type_="unique",
        )
