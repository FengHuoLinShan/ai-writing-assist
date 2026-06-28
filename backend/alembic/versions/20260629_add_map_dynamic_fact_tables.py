"""add map dynamic fact tables

Revision ID: 20260629_map_dynamic_facts
Revises: 20260628_context_snapshots
Create Date: 2026-06-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260629_map_dynamic_facts"
down_revision: str | None = "20260628_context_snapshots"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "map_observations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("novel_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("map_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("target_entity_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("target_entity_type", sa.String(length=64), nullable=True),
        sa.Column("target_name", sa.String(length=255), nullable=True),
        sa.Column("dynamic_type", sa.String(length=64), nullable=False),
        sa.Column("time_anchor", sa.JSON(), nullable=True),
        sa.Column("spatial_anchor", sa.JSON(), nullable=True),
        sa.Column("value_json", sa.JSON(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0.5"),
        sa.Column(
            "review_state",
            sa.String(length=32),
            nullable=False,
            server_default="candidate",
        ),
        sa.Column("source_ref", sa.JSON(), nullable=True),
        sa.Column("evidence_text", sa.Text(), nullable=True),
        sa.Column("scene_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("scene_index", sa.Integer(), nullable=True),
        sa.Column("source_chapter_index", sa.Integer(), nullable=True),
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
        sa.ForeignKeyConstraint(["map_id"], ["map_configs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["target_entity_id"], ["core_entities.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        comment="地图观察事实候选",
    )
    op.create_index(
        "ix_map_observation_map_review",
        "map_observations",
        ["map_id", "review_state"],
        unique=False,
    )
    op.create_index(
        "ix_map_observation_target",
        "map_observations",
        ["target_entity_id", "dynamic_type"],
        unique=False,
    )
    op.create_index(
        "ix_map_observation_scene",
        "map_observations",
        ["scene_id", "scene_index"],
        unique=False,
    )
    op.create_index(
        "ix_map_observations_novel_id",
        "map_observations",
        ["novel_id"],
        unique=False,
    )
    op.create_index(
        "ix_map_observations_dynamic_type",
        "map_observations",
        ["dynamic_type"],
        unique=False,
    )
    op.create_index(
        "ix_map_observations_review_state",
        "map_observations",
        ["review_state"],
        unique=False,
    )

    op.create_table(
        "map_facts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("novel_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("observation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("map_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("target_entity_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("target_entity_type", sa.String(length=64), nullable=True),
        sa.Column("target_name", sa.String(length=255), nullable=True),
        sa.Column("dynamic_type", sa.String(length=64), nullable=False),
        sa.Column("time_anchor", sa.JSON(), nullable=True),
        sa.Column("spatial_anchor", sa.JSON(), nullable=True),
        sa.Column("value_json", sa.JSON(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column(
            "fact_status",
            sa.String(length=32),
            nullable=False,
            server_default="confirmed",
        ),
        sa.Column("source_ref", sa.JSON(), nullable=True),
        sa.Column("evidence_text", sa.Text(), nullable=True),
        sa.Column("scene_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("scene_index", sa.Integer(), nullable=True),
        sa.Column("source_chapter_index", sa.Integer(), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["observation_id"], ["map_observations.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["map_id"], ["map_configs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["target_entity_id"], ["core_entities.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        comment="已确认时间化地图事实",
    )
    op.create_index(
        "ix_map_fact_map_status",
        "map_facts",
        ["map_id", "fact_status"],
        unique=False,
    )
    op.create_index(
        "ix_map_fact_target",
        "map_facts",
        ["target_entity_id", "dynamic_type"],
        unique=False,
    )
    op.create_index(
        "ix_map_fact_scene",
        "map_facts",
        ["scene_id", "scene_index"],
        unique=False,
    )
    op.create_index("ix_map_facts_novel_id", "map_facts", ["novel_id"], unique=False)
    op.create_index(
        "ix_map_facts_fact_status", "map_facts", ["fact_status"], unique=False
    )
    op.create_index(
        "ix_map_facts_observation_id",
        "map_facts",
        ["observation_id"],
        unique=False,
    )
    op.create_index(
        "ix_map_facts_dynamic_type", "map_facts", ["dynamic_type"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_map_facts_dynamic_type", table_name="map_facts")
    op.drop_index("ix_map_facts_observation_id", table_name="map_facts")
    op.drop_index("ix_map_facts_fact_status", table_name="map_facts")
    op.drop_index("ix_map_facts_novel_id", table_name="map_facts")
    op.drop_index("ix_map_fact_scene", table_name="map_facts")
    op.drop_index("ix_map_fact_target", table_name="map_facts")
    op.drop_index("ix_map_fact_map_status", table_name="map_facts")
    op.drop_table("map_facts")

    op.drop_index("ix_map_observations_review_state", table_name="map_observations")
    op.drop_index("ix_map_observations_dynamic_type", table_name="map_observations")
    op.drop_index("ix_map_observations_novel_id", table_name="map_observations")
    op.drop_index("ix_map_observation_scene", table_name="map_observations")
    op.drop_index("ix_map_observation_target", table_name="map_observations")
    op.drop_index("ix_map_observation_map_review", table_name="map_observations")
    op.drop_table("map_observations")
