"""Archive independent map assets and add reversible visual revisions.

Revision ID: 20260722_map_visual_history
Revises: 20260722_map_fact_observation
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260722_map_visual_history"
down_revision = "20260722_map_fact_observation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("map_visual_revisions"):
        return
    for table_name in ("map_terrain_layers", "map_markers"):
        op.add_column(
            table_name,
            sa.Column(
                "status",
                sa.String(length=16),
                nullable=False,
                server_default="active",
            ),
        )
        op.add_column(
            table_name,
            sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index(
            f"ix_{table_name}_status",
            table_name,
            ["status"],
            unique=False,
        )

    guid_type = sa.CHAR(36).with_variant(
        postgresql.UUID(as_uuid=True),
        "postgresql",
    )
    json_type = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
    op.create_table(
        "map_visual_revisions",
        sa.Column("map_id", guid_type, nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("operation", sa.String(length=64), nullable=False),
        sa.Column("restored_from_revision", sa.Integer(), nullable=True),
        sa.Column("forward_changes", json_type, nullable=False),
        sa.Column("reverse_changes", json_type, nullable=False),
        sa.Column("state_json", json_type, nullable=False),
        sa.Column("id", guid_type, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.timezone("utc", sa.func.now()),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.timezone("utc", sa.func.now()),
        ),
        sa.Column("novel_id", guid_type, nullable=False),
        sa.ForeignKeyConstraint(
            ["map_id"],
            ["map_configs.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["novel_id"],
            ["projects.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "map_id",
            "revision_number",
            name="uq_map_visual_revision_map_number",
        ),
        comment="不可变地图视觉 revision 与正反变更",
    )
    op.create_index(
        "ix_map_visual_revisions_map_id",
        "map_visual_revisions",
        ["map_id"],
        unique=False,
    )
    op.create_index(
        "ix_map_visual_revisions_novel_id",
        "map_visual_revisions",
        ["novel_id"],
        unique=False,
    )
    op.create_index(
        "ix_map_visual_revision_novel_map_number",
        "map_visual_revisions",
        ["novel_id", "map_id", "revision_number"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_map_visual_revision_novel_map_number",
        table_name="map_visual_revisions",
    )
    op.drop_index(
        "ix_map_visual_revisions_novel_id",
        table_name="map_visual_revisions",
    )
    op.drop_index(
        "ix_map_visual_revisions_map_id",
        table_name="map_visual_revisions",
    )
    op.drop_table("map_visual_revisions")
    for table_name in ("map_markers", "map_terrain_layers"):
        op.drop_index(f"ix_{table_name}_status", table_name=table_name)
        op.drop_column(table_name, "archived_at")
        op.drop_column(table_name, "status")
