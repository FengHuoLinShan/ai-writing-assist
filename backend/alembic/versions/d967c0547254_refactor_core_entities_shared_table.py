"""refactor: core_entities shared table + extension table pattern

Replace world_entities + entity_aliases with a single core_entities table
using JSONB aliases. Characters and geo_locations become 1:1 extension tables
with entity_id as PK+FK (ON DELETE CASCADE).

Revision ID: d967c0547254
Revises: aed774d964ff
Create Date: 2026-05-30
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

revision: str = "d967c0547254"
down_revision: Union[str, None] = "aed774d964ff"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ---------------------------------------------------------------
    # Phase 1: Drop tables that depend on tables we need to change
    # ---------------------------------------------------------------

    # entity_aliases is replaced by core_entities.aliases JSONB
    op.drop_table("entity_aliases")

    # character_knowledge depends on characters.id (PK changing)
    op.drop_table("character_knowledge")

    # geo_edges depends on geo_locations.id (PK changing)
    op.drop_table("geo_edges")

    # ---------------------------------------------------------------
    # Phase 2: Drop tables whose PKs are changing
    # ---------------------------------------------------------------

    # characters: id → entity_id (PK+FK → core_entities)
    op.drop_table("characters")

    # geo_locations: id → entity_id (PK+FK → core_entities)
    op.drop_table("geo_locations")

    # world_entities is replaced by core_entities
    op.drop_table("world_entities")

    # ---------------------------------------------------------------
    # Phase 3: Create new tables
    # ---------------------------------------------------------------

    # 3a. core_entities — shared core table
    op.create_table(
        "core_entities",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("novel_id", sa.UUID(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("entity_type", sa.String(32), nullable=False, index=True,
                  comment="对象类型：character/location/faction/item/concept/event/creature/skill/rule/other"),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("aliases", sa.JSON(), nullable=False, server_default=sa.text("'[]'"),
                  comment="别名列表 JSONB [{alias: str, type: str}]"),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("public_info", sa.Text(), nullable=True),
        sa.Column("hidden_truth", sa.Text(), nullable=True),
        sa.Column("content_json", sa.JSON(), nullable=True, server_default=sa.text("'{}'")),
        sa.Column("importance", sa.Float(), nullable=False, server_default=sa.text("0.5")),
        sa.Column("importance_level", sa.String(16), nullable=False, server_default="normal"),
        sa.Column("reveal_level", sa.String(16), nullable=False, server_default="author_only"),
        sa.Column("embedding_text", sa.Text(), nullable=True),
        sa.Column("embedding", Vector(1024), nullable=True),
        sa.Column("created_by", sa.String(64), nullable=True),
        sa.Column("approved_by", sa.String(64), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="draft", index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        comment="共享核心实体表",
    )
    op.create_index("ix_core_entities_novel_id", "core_entities", ["novel_id"])
    op.create_index("ix_core_entities_name", "core_entities", ["name"])

    # 3b. characters — extension table (entity_id is PK + FK)
    op.create_table(
        "characters",
        sa.Column("entity_id", sa.UUID(), sa.ForeignKey("core_entities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("novel_id", sa.UUID(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(64), nullable=True),
        sa.Column("appearance", sa.Text(), nullable=True),
        sa.Column("personality", sa.Text(), nullable=True),
        sa.Column("desire", sa.Text(), nullable=True),
        sa.Column("fear", sa.Text(), nullable=True),
        sa.Column("secret", sa.Text(), nullable=True),
        sa.Column("weakness", sa.Text(), nullable=True),
        sa.Column("current_goal", sa.Text(), nullable=True),
        sa.Column("current_state", sa.Text(), nullable=True),
        sa.Column("current_emotion", sa.String(64), nullable=True),
        sa.Column("stance", sa.Text(), nullable=True),
        sa.Column("voice_style", sa.Text(), nullable=True),
        sa.Column("behavior_rules", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("relationship_summary", sa.Text(), nullable=True),
        sa.Column("meta", sa.JSON(), nullable=False, server_default=sa.text("'{}'"),
                  comment="扩展元数据（AI 抽取建议等）"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.PrimaryKeyConstraint("entity_id"),
        comment="人物档案扩展表",
    )
    op.create_index("ix_characters_novel_id", "characters", ["novel_id"])

    # 3c. character_knowledge — FK → core_entities.id (via characters PK)
    op.create_table(
        "character_knowledge",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("novel_id", sa.UUID(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("character_id", sa.UUID(), sa.ForeignKey("core_entities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("target_type", sa.String(64), nullable=False),
        sa.Column("target_id", sa.UUID(), nullable=False),
        sa.Column("knowledge_level", sa.String(32), nullable=False, server_default="unknown"),
        sa.Column("known_content", sa.Text(), nullable=True),
        sa.Column("misconception", sa.Text(), nullable=True),
        sa.Column("source_chapter_index", sa.Integer(), nullable=True),
        sa.Column("source_memory_id", sa.UUID(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="canonical"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        comment="人物知识边界",
    )
    op.create_index("ix_character_knowledge_novel_id", "character_knowledge", ["novel_id"])
    op.create_index("ix_character_knowledge_char_id", "character_knowledge", ["character_id"])

    # 3d. geo_locations — extension table (entity_id is PK + FK)
    op.create_table(
        "geo_locations",
        sa.Column("entity_id", sa.UUID(), sa.ForeignKey("core_entities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("novel_id", sa.UUID(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("location_level", sa.String(32), nullable=False, index=True),
        sa.Column("parent_location_id", sa.UUID(), sa.ForeignKey("core_entities.id", ondelete="SET NULL"), nullable=True),
        sa.Column("x", sa.Float(), nullable=True),
        sa.Column("y", sa.Float(), nullable=True),
        sa.Column("position_label", sa.String(128), nullable=True),
        sa.Column("scale_label", sa.String(64), nullable=True),
        sa.Column("terrain", sa.String(64), nullable=True),
        sa.Column("climate", sa.String(64), nullable=True),
        sa.Column("access_level", sa.String(32), nullable=False, server_default="normal"),
        sa.Column("content_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'"),
                  comment="扩展信息，可包含 era_states 历史时期状态"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.PrimaryKeyConstraint("entity_id"),
        comment="地理地点扩展表",
    )
    op.create_index("ix_geo_locations_novel_id", "geo_locations", ["novel_id"])
    op.create_index("ix_geo_locations_parent", "geo_locations", ["parent_location_id"])

    # 3e. geo_edges — FK → core_entities.id
    op.create_table(
        "geo_edges",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("novel_id", sa.UUID(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_location_id", sa.UUID(), sa.ForeignKey("core_entities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("target_location_id", sa.UUID(), sa.ForeignKey("core_entities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("relation_type", sa.String(32), nullable=False, index=True),
        sa.Column("direction_label", sa.String(64), nullable=True),
        sa.Column("distance_label", sa.String(64), nullable=True),
        sa.Column("travel_time", sa.String(64), nullable=True),
        sa.Column("difficulty", sa.String(32), nullable=True),
        sa.Column("visibility", sa.String(32), nullable=False, server_default="public"),
        sa.Column("condition_text", sa.Text(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="canonical", index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        comment="地理关系边",
    )
    op.create_index("ix_geo_edges_novel_id", "geo_edges", ["novel_id"])
    op.create_index("ix_geo_edges_source", "geo_edges", ["source_location_id"])
    op.create_index("ix_geo_edges_target", "geo_edges", ["target_location_id"])


def downgrade() -> None:
    """Revert to pre-core_entities schema."""
    op.drop_table("geo_edges")
    op.drop_table("geo_locations")
    op.drop_table("character_knowledge")
    op.drop_table("characters")
    op.drop_table("core_entities")

    # Recreate old tables in original order
    op.create_table(
        "world_entities",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("novel_id", sa.UUID(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("entity_type", sa.String(32), nullable=False, index=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("public_info", sa.Text(), nullable=True),
        sa.Column("hidden_truth", sa.Text(), nullable=True),
        sa.Column("content_json", sa.JSON(), nullable=True, server_default="{}"),
        sa.Column("importance", sa.Float(), nullable=False, server_default="0.5"),
        sa.Column("importance_level", sa.String(16), nullable=False, server_default="normal"),
        sa.Column("reveal_level", sa.String(16), nullable=False, server_default="author_only"),
        sa.Column("embedding_text", sa.Text(), nullable=True),
        sa.Column("embedding", Vector(1024), nullable=True),
        sa.Column("created_by", sa.String(64), nullable=True),
        sa.Column("approved_by", sa.String(64), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="draft", index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_world_entities_novel_id", "world_entities", ["novel_id"])

    op.create_table(
        "entity_aliases",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("novel_id", sa.UUID(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("entity_id", sa.UUID(), sa.ForeignKey("world_entities.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("alias", sa.String(255), nullable=False),
        sa.Column("alias_type", sa.String(20), nullable=False, server_default="name"),
        sa.Column("source_chapter_index", sa.Integer(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0.8"),
        sa.Column("status", sa.String(32), nullable=False, server_default="confirmed"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_entity_aliases_novel_id", "entity_aliases", ["novel_id"])

    op.create_table(
        "characters",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("novel_id", sa.UUID(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("world_entity_id", sa.UUID(), sa.ForeignKey("world_entities.id", ondelete="SET NULL"), nullable=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("aliases", sa.JSON(), nullable=True, server_default="[]"),
        sa.Column("role", sa.String(64), nullable=True),
        sa.Column("appearance", sa.Text(), nullable=True),
        sa.Column("personality", sa.Text(), nullable=True),
        sa.Column("desire", sa.Text(), nullable=True),
        sa.Column("fear", sa.Text(), nullable=True),
        sa.Column("secret", sa.Text(), nullable=True),
        sa.Column("weakness", sa.Text(), nullable=True),
        sa.Column("current_goal", sa.Text(), nullable=True),
        sa.Column("current_state", sa.Text(), nullable=True),
        sa.Column("current_emotion", sa.String(64), nullable=True),
        sa.Column("stance", sa.Text(), nullable=True),
        sa.Column("voice_style", sa.Text(), nullable=True),
        sa.Column("behavior_rules", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("relationship_summary", sa.Text(), nullable=True),
        sa.Column("meta", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("status", sa.String(32), nullable=False, server_default="canonical"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_characters_novel_id", "characters", ["novel_id"])

    op.create_table(
        "character_knowledge",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("novel_id", sa.UUID(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("character_id", sa.UUID(), sa.ForeignKey("characters.id", ondelete="CASCADE"), nullable=False),
        sa.Column("target_type", sa.String(64), nullable=False),
        sa.Column("target_id", sa.UUID(), nullable=False),
        sa.Column("knowledge_level", sa.String(32), nullable=False, server_default="unknown"),
        sa.Column("known_content", sa.Text(), nullable=True),
        sa.Column("misconception", sa.Text(), nullable=True),
        sa.Column("source_chapter_index", sa.Integer(), nullable=True),
        sa.Column("source_memory_id", sa.UUID(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="canonical"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_character_knowledge_novel_id", "character_knowledge", ["novel_id"])
    op.create_index("ix_character_knowledge_char_id", "character_knowledge", ["character_id"])

    op.create_table(
        "geo_locations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("novel_id", sa.UUID(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("world_entity_id", sa.UUID(), sa.ForeignKey("world_entities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("location_level", sa.String(32), nullable=False),
        sa.Column("parent_location_id", sa.UUID(), sa.ForeignKey("geo_locations.id", ondelete="SET NULL"), nullable=True),
        sa.Column("x", sa.Float(), nullable=True),
        sa.Column("y", sa.Float(), nullable=True),
        sa.Column("position_label", sa.String(128), nullable=True),
        sa.Column("scale_label", sa.String(64), nullable=True),
        sa.Column("terrain", sa.String(64), nullable=True),
        sa.Column("climate", sa.String(64), nullable=True),
        sa.Column("access_level", sa.String(32), nullable=False, server_default="normal"),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("content_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("status", sa.String(32), nullable=False, server_default="canonical"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_geo_locations_novel_id", "geo_locations", ["novel_id"])
    op.create_index("ix_geo_locations_parent", "geo_locations", ["parent_location_id"])

    op.create_table(
        "geo_edges",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("novel_id", sa.UUID(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_location_id", sa.UUID(), sa.ForeignKey("geo_locations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("target_location_id", sa.UUID(), sa.ForeignKey("geo_locations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("relation_type", sa.String(32), nullable=False),
        sa.Column("direction_label", sa.String(64), nullable=True),
        sa.Column("distance_label", sa.String(64), nullable=True),
        sa.Column("travel_time", sa.String(64), nullable=True),
        sa.Column("difficulty", sa.String(32), nullable=True),
        sa.Column("visibility", sa.String(20), nullable=False, server_default="public"),
        sa.Column("condition_text", sa.Text(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="canonical"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_geo_edges_novel_id", "geo_edges", ["novel_id"])
    op.create_index("ix_geo_edges_source", "geo_edges", ["source_location_id"])
    op.create_index("ix_geo_edges_target", "geo_edges", ["target_location_id"])
