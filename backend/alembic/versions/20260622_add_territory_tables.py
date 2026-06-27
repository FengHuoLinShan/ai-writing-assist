"""add map_territory_tiles table

动态地图功能 P2 数据层（PRD docs/PRD-动态地图功能.md §4.4）：
- map_territory_tiles: 势力范围（组织控制区域）

Revision ID: 20260622_add_territory_tables
Revises: 20260614_add_map_tables
Create Date: 2026-06-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260622_add_territory_tables"
down_revision: str | None = "20260614_add_map_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # map_territory_tiles (P2 势力范围)
    op.create_table(
        "map_territory_tiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("novel_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("map_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("faction_entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("hex_q", sa.Integer(), nullable=False),
        sa.Column("hex_r", sa.Integer(), nullable=False),
        sa.Column("style_override", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("timezone('utc', now())"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("timezone('utc', now())"),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(["novel_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["map_id"], ["map_configs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["faction_entity_id"], ["core_entities.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "map_id",
            "faction_entity_id",
            "hex_q",
            "hex_r",
            name="uq_map_territory_map_faction_qr",
        ),
        comment="势力范围（P2）",
    )
    op.create_index(
        "ix_map_territory_map_id", "map_territory_tiles", ["map_id"], unique=False
    )
    op.create_index(
        "ix_map_territory_faction_id",
        "map_territory_tiles",
        ["faction_entity_id"],
        unique=False,
    )
    op.create_index(
        "ix_map_territory_novel_id", "map_territory_tiles", ["novel_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_map_territory_novel_id", table_name="map_territory_tiles")
    op.drop_index("ix_map_territory_faction_id", table_name="map_territory_tiles")
    op.drop_index("ix_map_territory_map_id", table_name="map_territory_tiles")
    op.drop_table("map_territory_tiles")
