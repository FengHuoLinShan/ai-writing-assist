"""refactor: core_entities shared table + extension table pattern

Replace world_entities + entity_aliases with a single core_entities table
using JSONB aliases. Characters and geo_locations become 1:1 extension tables
with entity_id as PK+FK (ON DELETE CASCADE).

Revision ID: d967c0547254
Revises: aed774d964ff
Create Date: 2026-05-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

from alembic import op

revision: str = "d967c0547254"
down_revision: str | None = "aed774d964ff"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ---------------------------------------------------------------
    # Phase 1: Create new core table while legacy tables are intact.
    # ---------------------------------------------------------------
    op.create_table(
        "core_entities",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "novel_id",
            sa.UUID(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "entity_type",
            sa.String(32),
            nullable=False,
            index=True,
            comment="对象类型：character/location/faction/item/concept/event/creature/skill/rule/other",
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column(
            "aliases",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'"),
            comment="别名列表 JSONB [{alias: str, type: str}]",
        ),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("public_info", sa.Text(), nullable=True),
        sa.Column("hidden_truth", sa.Text(), nullable=True),
        sa.Column(
            "content_json", sa.JSON(), nullable=True, server_default=sa.text("'{}'")
        ),
        sa.Column(
            "importance", sa.Float(), nullable=False, server_default=sa.text("0.5")
        ),
        sa.Column(
            "importance_level", sa.String(16), nullable=False, server_default="normal"
        ),
        sa.Column(
            "reveal_level", sa.String(16), nullable=False, server_default="author_only"
        ),
        sa.Column("embedding_text", sa.Text(), nullable=True),
        sa.Column("embedding", Vector(1024), nullable=True),
        sa.Column("created_by", sa.String(64), nullable=True),
        sa.Column("approved_by", sa.String(64), nullable=True),
        sa.Column(
            "status", sa.String(32), nullable=False, server_default="draft", index=True
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
        comment="共享核心实体表",
    )
    op.create_index("ix_core_entities_novel_id", "core_entities", ["novel_id"])
    op.create_index("ix_core_entities_name", "core_entities", ["name"])

    # Copy world_entities and fold entity_aliases into aliases JSON.
    # Deprecated aliases (status = 'deprecated') are intentionally excluded:
    # they represent LLM extraction errors or user-rejected candidates and
    # have no ongoing value in the unified aliases JSONB.
    op.execute(
        sa.text("""
        INSERT INTO core_entities (
            id, novel_id, entity_type, name, aliases, summary,
            public_info, hidden_truth, content_json, importance,
            importance_level, reveal_level, embedding_text, embedding,
            created_by, approved_by, status, created_at, updated_at
        )
        SELECT
            we.id,
            we.novel_id,
            CASE
                WHEN we.entity_type = 'character_ref' THEN 'character'
                ELSE we.entity_type
            END,
            we.name,
            COALESCE((
                SELECT json_agg(json_build_object(
                    'alias', ea.alias,
                    'type', ea.alias_type,
                    'source_chapter_index', ea.source_chapter_index,
                    'confidence', ea.confidence
                ))
                FROM entity_aliases ea
                WHERE ea.entity_id = we.id
                  AND ea.status != 'deprecated'
            ), '[]'::json),
            we.summary,
            we.public_info,
            we.hidden_truth,
            COALESCE(we.content_json, '{}'::json),
            we.importance,
            we.importance_level,
            we.reveal_level,
            we.embedding_text,
            we.embedding,
            we.created_by,
            we.approved_by,
            we.status,
            we.created_at,
            we.updated_at
        FROM world_entities we
    """)
    )

    # Characters that were not linked to world_entities still need a core row.
    op.execute(
        sa.text("""
        INSERT INTO core_entities (
            id, novel_id, entity_type, name, aliases, summary,
            content_json, importance, importance_level, reveal_level,
            status, created_at, updated_at
        )
        SELECT
            c.id,
            c.novel_id,
            'character',
            c.name,
            COALESCE((
                SELECT json_agg(
                    CASE
                        WHEN json_typeof(alias_item) = 'object'
                            THEN alias_item
                        ELSE json_build_object(
                            'alias', alias_item #>> '{}',
                            'type', 'legacy'
                        )
                    END
                )
                FROM json_array_elements(COALESCE(c.aliases, '[]'::json)) alias_item
            ), '[]'::json),
            c.current_state,
            COALESCE(c.meta, '{}'::json),
            0.5,
            'normal',
            'author_only',
            c.status,
            c.created_at,
            c.updated_at
        FROM characters c
        WHERE c.world_entity_id IS NULL
    """)
    )

    # Legacy extension rows determine the canonical subtype of linked core rows.
    op.execute(
        sa.text("""
        UPDATE core_entities ce
        SET entity_type = 'character'
        FROM characters c
        WHERE c.world_entity_id = ce.id
    """)
    )
    op.execute(
        sa.text("""
        UPDATE core_entities ce
        SET entity_type = 'location',
            summary = COALESCE(ce.summary, gl.summary)
        FROM geo_locations gl
        WHERE gl.world_entity_id = ce.id
    """)
    )

    # ---------------------------------------------------------------
    # Phase 2: Create temporary extension tables and copy legacy data.
    # ---------------------------------------------------------------
    op.create_table(
        "characters_new",
        sa.Column(
            "entity_id",
            sa.UUID(),
            sa.ForeignKey("core_entities.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "novel_id",
            sa.UUID(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("aliases", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
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
        sa.Column(
            "behavior_rules", sa.JSON(), nullable=False, server_default=sa.text("'[]'")
        ),
        sa.Column("relationship_summary", sa.Text(), nullable=True),
        sa.Column(
            "meta",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
            comment="扩展元数据（AI 抽取建议等）",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
        ),
        sa.Column(
            "status",
            sa.String(32),
            nullable=False,
            server_default="draft",
            index=True,
        ),
        sa.PrimaryKeyConstraint("entity_id"),
        comment="人物档案扩展表",
    )

    op.create_table(
        "character_knowledge_new",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "novel_id",
            sa.UUID(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "character_id",
            sa.UUID(),
            sa.ForeignKey("core_entities.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("target_type", sa.String(64), nullable=False),
        sa.Column("target_id", sa.UUID(), nullable=False),
        sa.Column(
            "knowledge_level", sa.String(32), nullable=False, server_default="unknown"
        ),
        sa.Column("known_content", sa.Text(), nullable=True),
        sa.Column("misconception", sa.Text(), nullable=True),
        sa.Column("source_chapter_index", sa.Integer(), nullable=True),
        sa.Column("source_memory_id", sa.UUID(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="canonical"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
        comment="人物知识边界",
    )

    op.create_table(
        "geo_locations_new",
        sa.Column(
            "entity_id",
            sa.UUID(),
            sa.ForeignKey("core_entities.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "novel_id",
            sa.UUID(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("location_level", sa.String(32), nullable=False, index=True),
        sa.Column(
            "parent_location_id",
            sa.UUID(),
            sa.ForeignKey("core_entities.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("x", sa.Float(), nullable=True),
        sa.Column("y", sa.Float(), nullable=True),
        sa.Column("position_label", sa.String(128), nullable=True),
        sa.Column("scale_label", sa.String(64), nullable=True),
        sa.Column("terrain", sa.String(64), nullable=True),
        sa.Column("climate", sa.String(64), nullable=True),
        sa.Column("access_level", sa.String(32), nullable=False, server_default="normal"),
        sa.Column(
            "content_json",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
            comment="扩展信息，可包含 era_states 历史时期状态",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("entity_id"),
        comment="地理地点扩展表",
    )

    op.create_table(
        "geo_edges_new",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "novel_id",
            sa.UUID(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "source_location_id",
            sa.UUID(),
            sa.ForeignKey("core_entities.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "target_location_id",
            sa.UUID(),
            sa.ForeignKey("core_entities.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("relation_type", sa.String(32), nullable=False, index=True),
        sa.Column("direction_label", sa.String(64), nullable=True),
        sa.Column("distance_label", sa.String(64), nullable=True),
        sa.Column("travel_time", sa.String(64), nullable=True),
        sa.Column("difficulty", sa.String(32), nullable=True),
        sa.Column("visibility", sa.String(32), nullable=False, server_default="public"),
        sa.Column("condition_text", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.String(32),
            nullable=False,
            server_default="canonical",
            index=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
        comment="地理关系边",
    )

    op.execute(
        sa.text("""
        INSERT INTO characters_new (
            entity_id, novel_id, name, aliases, role, appearance, personality,
            desire, fear, secret, weakness, current_goal, current_state,
            current_emotion, stance, voice_style, behavior_rules,
            relationship_summary, meta, created_at, updated_at, status
        )
        SELECT
            COALESCE(c.world_entity_id, c.id),
            c.novel_id,
            c.name,
            COALESCE(c.aliases, '[]'::json),
            c.role,
            c.appearance,
            c.personality,
            c.desire,
            c.fear,
            c.secret,
            c.weakness,
            c.current_goal,
            c.current_state,
            c.current_emotion,
            c.stance,
            c.voice_style,
            COALESCE(c.behavior_rules, '[]'::json),
            c.relationship_summary,
            COALESCE(c.meta, '{}'::json),
            c.created_at,
            c.updated_at,
            c.status
        FROM characters c
    """)
    )

    # target_id may reference legacy characters.id or geo_locations.id,
    # so we LEFT JOIN both extension tables to resolve the canonical core entity ID.
    op.execute(
        sa.text("""
        INSERT INTO character_knowledge_new (
            id, novel_id, character_id, target_type, target_id,
            knowledge_level, known_content, misconception,
            source_chapter_index, source_memory_id, status,
            created_at, updated_at
        )
        SELECT
            ck.id,
            ck.novel_id,
            COALESCE(c.world_entity_id, c.id),
            ck.target_type,
            COALESCE(
                target_char.world_entity_id,
                target_char.id,
                target_geo.world_entity_id,
                ck.target_id
            ),
            ck.knowledge_level,
            ck.known_content,
            ck.misconception,
            ck.source_chapter_index,
            ck.source_memory_id,
            ck.status,
            ck.created_at,
            ck.updated_at
        FROM character_knowledge ck
        JOIN characters c ON c.id = ck.character_id
        LEFT JOIN characters target_char ON target_char.id = ck.target_id
        LEFT JOIN geo_locations target_geo ON target_geo.id = ck.target_id
    """)
    )

    op.execute(
        sa.text("""
        INSERT INTO geo_locations_new (
            entity_id, novel_id, location_level, parent_location_id,
            x, y, position_label, scale_label, terrain, climate,
            access_level, content_json, created_at, updated_at
        )
        SELECT
            gl.world_entity_id,
            gl.novel_id,
            gl.location_level,
            parent.world_entity_id,
            gl.x,
            gl.y,
            gl.position_label,
            gl.scale_label,
            gl.terrain,
            gl.climate,
            gl.access_level,
            COALESCE(gl.content_json, '{}'::json),
            gl.created_at,
            gl.updated_at
        FROM geo_locations gl
        LEFT JOIN geo_locations parent ON parent.id = gl.parent_location_id
    """)
    )

    # Edges referencing geo_locations without a world_entity_id are orphaned
    # data (legacy cleanup leftovers) and are intentionally dropped here.
    op.execute(
        sa.text("""
        INSERT INTO geo_edges_new (
            id, novel_id, source_location_id, target_location_id,
            relation_type, direction_label, distance_label, travel_time,
            difficulty, visibility, condition_text, status,
            created_at, updated_at
        )
        SELECT
            ge.id,
            ge.novel_id,
            source.world_entity_id,
            target.world_entity_id,
            ge.relation_type,
            ge.direction_label,
            ge.distance_label,
            ge.travel_time,
            ge.difficulty,
            ge.visibility,
            ge.condition_text,
            ge.status,
            ge.created_at,
            ge.updated_at
        FROM geo_edges ge
        LEFT JOIN geo_locations source ON source.id = ge.source_location_id
        LEFT JOIN geo_locations target ON target.id = ge.target_location_id
        WHERE source.world_entity_id IS NOT NULL
          AND target.world_entity_id IS NOT NULL
    """)
    )

    # ---------------------------------------------------------------
    # Phase 3: Drop legacy tables after the data copy, then promote
    # temporary tables to their final names and create final indexes.
    # ---------------------------------------------------------------
    op.drop_table("character_knowledge")
    op.drop_table("geo_edges")
    op.drop_table("characters")
    op.drop_table("geo_locations")
    op.drop_table("entity_aliases")
    op.drop_table("world_entities")

    op.rename_table("characters_new", "characters")
    op.rename_table("character_knowledge_new", "character_knowledge")
    op.rename_table("geo_locations_new", "geo_locations")
    op.rename_table("geo_edges_new", "geo_edges")

    op.create_index("ix_characters_novel_id", "characters", ["novel_id"])
    op.create_index(
        "ix_character_knowledge_novel_id", "character_knowledge", ["novel_id"]
    )
    op.create_index(
        "ix_character_knowledge_char_id", "character_knowledge", ["character_id"]
    )
    op.create_index("ix_geo_locations_novel_id", "geo_locations", ["novel_id"])
    op.create_index("ix_geo_locations_parent", "geo_locations", ["parent_location_id"])
    op.create_index("ix_geo_edges_novel_id", "geo_edges", ["novel_id"])
    op.create_index("ix_geo_edges_source", "geo_edges", ["source_location_id"])
    op.create_index("ix_geo_edges_target", "geo_edges", ["target_location_id"])


def downgrade() -> None:
    """Revert to pre-core_entities schema.

    WARNING: This downgrade does NOT preserve data — it drops the new tables
    and recreates empty legacy tables. Use only for development rollback.
    Production downgrades require a separate data-backfill script.
    """
    op.drop_table("geo_edges")
    op.drop_table("geo_locations")
    op.drop_table("character_knowledge")
    op.drop_table("characters")
    op.drop_table("core_entities")

    # Recreate old tables in original order
    op.create_table(
        "world_entities",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "novel_id",
            sa.UUID(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("entity_type", sa.String(32), nullable=False, index=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("public_info", sa.Text(), nullable=True),
        sa.Column("hidden_truth", sa.Text(), nullable=True),
        sa.Column("content_json", sa.JSON(), nullable=True, server_default="{}"),
        sa.Column("importance", sa.Float(), nullable=False, server_default="0.5"),
        sa.Column(
            "importance_level", sa.String(16), nullable=False, server_default="normal"
        ),
        sa.Column(
            "reveal_level", sa.String(16), nullable=False, server_default="author_only"
        ),
        sa.Column("embedding_text", sa.Text(), nullable=True),
        sa.Column("embedding", Vector(1024), nullable=True),
        sa.Column("created_by", sa.String(64), nullable=True),
        sa.Column("approved_by", sa.String(64), nullable=True),
        sa.Column(
            "status", sa.String(32), nullable=False, server_default="draft", index=True
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_world_entities_novel_id", "world_entities", ["novel_id"])

    op.create_table(
        "entity_aliases",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "novel_id",
            sa.UUID(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "entity_id",
            sa.UUID(),
            sa.ForeignKey("world_entities.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("alias", sa.String(255), nullable=False),
        sa.Column("alias_type", sa.String(20), nullable=False, server_default="name"),
        sa.Column("source_chapter_index", sa.Integer(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0.8"),
        sa.Column("status", sa.String(32), nullable=False, server_default="confirmed"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_entity_aliases_novel_id", "entity_aliases", ["novel_id"])

    op.create_table(
        "characters",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "novel_id",
            sa.UUID(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "world_entity_id",
            sa.UUID(),
            sa.ForeignKey("world_entities.id", ondelete="SET NULL"),
            nullable=True,
        ),
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
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_characters_novel_id", "characters", ["novel_id"])

    op.create_table(
        "character_knowledge",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "novel_id",
            sa.UUID(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "character_id",
            sa.UUID(),
            sa.ForeignKey("characters.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("target_type", sa.String(64), nullable=False),
        sa.Column("target_id", sa.UUID(), nullable=False),
        sa.Column(
            "knowledge_level", sa.String(32), nullable=False, server_default="unknown"
        ),
        sa.Column("known_content", sa.Text(), nullable=True),
        sa.Column("misconception", sa.Text(), nullable=True),
        sa.Column("source_chapter_index", sa.Integer(), nullable=True),
        sa.Column("source_memory_id", sa.UUID(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="canonical"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_character_knowledge_novel_id", "character_knowledge", ["novel_id"]
    )
    op.create_index(
        "ix_character_knowledge_char_id", "character_knowledge", ["character_id"]
    )

    op.create_table(
        "geo_locations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "novel_id",
            sa.UUID(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "world_entity_id",
            sa.UUID(),
            sa.ForeignKey("world_entities.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("location_level", sa.String(32), nullable=False),
        sa.Column(
            "parent_location_id",
            sa.UUID(),
            sa.ForeignKey("geo_locations.id", ondelete="SET NULL"),
            nullable=True,
        ),
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
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_geo_locations_novel_id", "geo_locations", ["novel_id"])
    op.create_index("ix_geo_locations_parent", "geo_locations", ["parent_location_id"])

    op.create_table(
        "geo_edges",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "novel_id",
            sa.UUID(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "source_location_id",
            sa.UUID(),
            sa.ForeignKey("geo_locations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "target_location_id",
            sa.UUID(),
            sa.ForeignKey("geo_locations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("relation_type", sa.String(32), nullable=False),
        sa.Column("direction_label", sa.String(64), nullable=True),
        sa.Column("distance_label", sa.String(64), nullable=True),
        sa.Column("travel_time", sa.String(64), nullable=True),
        sa.Column("difficulty", sa.String(32), nullable=True),
        sa.Column("visibility", sa.String(20), nullable=False, server_default="public"),
        sa.Column("condition_text", sa.Text(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="canonical"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_geo_edges_novel_id", "geo_edges", ["novel_id"])
    op.create_index("ix_geo_edges_source", "geo_edges", ["source_location_id"])
    op.create_index("ix_geo_edges_target", "geo_edges", ["target_location_id"])
