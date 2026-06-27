"""initial: create all 22 tables

Revision ID: 0001
Revises:
Create Date: 2026-05-24 17:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Enable extensions
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    # -----------------------------------------------------------
    # 1. projects
    # -----------------------------------------------------------
    op.create_table(
        "projects",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("genre", sa.String(64), nullable=True),
        sa.Column("tone", sa.String(64), nullable=True),
        sa.Column("language", sa.String(16), server_default="zh", nullable=False),
        sa.Column("target_length", sa.String(32), nullable=True),
        sa.Column("current_stage", sa.String(32), nullable=True),
        sa.Column(
            "default_reveal_policy",
            sa.String(32),
            server_default="author_safe",
            nullable=False,
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
        comment="小说项目",
    )

    # -----------------------------------------------------------
    # 2. world_entities
    # -----------------------------------------------------------
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
        comment="世界对象正史库",
    )
    op.create_index("ix_world_entities_novel_id", "world_entities", ["novel_id"])

    # -----------------------------------------------------------
    # 3. relationships
    # -----------------------------------------------------------
    op.create_table(
        "relationships",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "novel_id",
            sa.UUID(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_type", sa.String(32), nullable=False),
        sa.Column("source_id", sa.String(36), nullable=False, index=True),
        sa.Column("target_type", sa.String(32), nullable=False),
        sa.Column("target_id", sa.String(36), nullable=False, index=True),
        sa.Column("relation_type", sa.String(32), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "visibility", sa.String(20), nullable=False, server_default="author_only"
        ),
        sa.Column("strength", sa.Float(), nullable=False, server_default="0.5"),
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
        comment="对象间关系边",
    )
    op.create_index("ix_relationships_novel_id", "relationships", ["novel_id"])

    # -----------------------------------------------------------
    # 4. entity_aliases
    # -----------------------------------------------------------
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
        comment="世界对象别名",
    )
    op.create_index("ix_entity_aliases_novel_id", "entity_aliases", ["novel_id"])

    # -----------------------------------------------------------
    # 5. entity_candidates
    # -----------------------------------------------------------
    op.create_table(
        "entity_candidates",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "novel_id",
            sa.UUID(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("entity_type", sa.String(32), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("source_text", sa.Text(), nullable=True),
        sa.Column("source_chapter_index", sa.Integer(), nullable=True),
        sa.Column("importance_score", sa.Float(), nullable=False, server_default="0.5"),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0.5"),
        sa.Column("candidate_reason", sa.Text(), nullable=True),
        sa.Column(
            "suggested_action",
            sa.String(32),
            nullable=False,
            server_default="needs_user_decision",
        ),
        sa.Column("suggested_existing_entity_id", sa.String(36), nullable=True),
        sa.Column("embedding_text", sa.Text(), nullable=True),
        sa.Column("embedding", Vector(1024), nullable=True),
        sa.Column(
            "status", sa.String(32), nullable=False, server_default="pending", index=True
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
        comment="世界对象候选池",
    )
    op.create_index("ix_entity_candidates_novel_id", "entity_candidates", ["novel_id"])

    # -----------------------------------------------------------
    # 6. characters
    # -----------------------------------------------------------
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
        sa.Column("current_emotion", sa.Text(), nullable=True),
        sa.Column("stance", sa.String(32), nullable=True),
        sa.Column("voice_style", sa.Text(), nullable=True),
        sa.Column("behavior_rules", sa.JSON(), nullable=True, server_default="[]"),
        sa.Column("relationship_summary", sa.Text(), nullable=True),
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
        comment="人物档案",
    )
    op.create_index("ix_characters_novel_id", "characters", ["novel_id"])

    # -----------------------------------------------------------
    # 7. character_knowledge
    # -----------------------------------------------------------
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
        sa.Column("target_type", sa.String(32), nullable=False),
        sa.Column("target_id", sa.UUID(), nullable=False),
        sa.Column("knowledge_level", sa.String(20), nullable=False),
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
        sa.PrimaryKeyConstraint("id"),
        comment="人物知识边界",
    )
    op.create_index(
        "ix_character_knowledge_novel_id", "character_knowledge", ["novel_id"]
    )
    op.create_index(
        "ix_character_knowledge_char_id", "character_knowledge", ["character_id"]
    )

    # -----------------------------------------------------------
    # 8. geo_locations
    # -----------------------------------------------------------
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
        sa.Column("content_json", sa.JSON(), nullable=True, server_default="{}"),
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
        comment="地理地点",
    )
    op.create_index("ix_geo_locations_novel_id", "geo_locations", ["novel_id"])
    op.create_index("ix_geo_locations_parent", "geo_locations", ["parent_location_id"])

    # -----------------------------------------------------------
    # 9. geo_edges
    # -----------------------------------------------------------
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
        comment="地理关系边",
    )
    op.create_index("ix_geo_edges_novel_id", "geo_edges", ["novel_id"])
    op.create_index("ix_geo_edges_source", "geo_edges", ["source_location_id"])
    op.create_index("ix_geo_edges_target", "geo_edges", ["target_location_id"])

    # -----------------------------------------------------------
    # 10. geo_eras
    # -----------------------------------------------------------
    op.create_table(
        "geo_eras",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "novel_id",
            sa.UUID(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("order_index", sa.Integer(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("start_event_id", sa.UUID(), nullable=True),
        sa.Column("end_event_id", sa.UUID(), nullable=True),
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
        comment="历史时期",
    )
    op.create_index("ix_geo_eras_novel_id", "geo_eras", ["novel_id"])

    # -----------------------------------------------------------
    # 11. memory_records
    # -----------------------------------------------------------
    op.create_table(
        "memory_records",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "novel_id",
            sa.UUID(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("memory_type", sa.String(32), nullable=False),
        sa.Column("target_type", sa.String(32), nullable=True),
        sa.Column("target_id", sa.UUID(), nullable=True),
        sa.Column("chapter_index", sa.Integer(), nullable=True),
        sa.Column("title", sa.String(255), nullable=True),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("content_json", sa.JSON(), nullable=True, server_default="{}"),
        sa.Column(
            "visibility", sa.String(20), nullable=False, server_default="reader_known"
        ),
        sa.Column(
            "known_by_character_ids", sa.JSON(), nullable=True, server_default="[]"
        ),
        sa.Column("related_entity_ids", sa.JSON(), nullable=True, server_default="[]"),
        sa.Column("related_character_ids", sa.JSON(), nullable=True, server_default="[]"),
        sa.Column("related_thread_ids", sa.JSON(), nullable=True, server_default="[]"),
        sa.Column("importance", sa.Float(), nullable=False, server_default="0.5"),
        sa.Column("status", sa.String(32), nullable=False, server_default="canonical"),
        sa.Column("source_text_excerpt", sa.Text(), nullable=True),
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
        comment="长期记忆记录",
    )
    op.create_index("ix_memory_records_novel_id", "memory_records", ["novel_id"])
    op.create_index("ix_memory_records_chapter", "memory_records", ["chapter_index"])

    # -----------------------------------------------------------
    # 12. memory_update_proposals
    # -----------------------------------------------------------
    op.create_table(
        "memory_update_proposals",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "novel_id",
            sa.UUID(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("chapter_id", sa.UUID(), nullable=True),
        sa.Column("chapter_index", sa.Integer(), nullable=True),
        sa.Column("proposal_type", sa.String(32), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0.5"),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("source_text_excerpt", sa.Text(), nullable=True),
        sa.Column("decision", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("decided_by", sa.String(64), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
        comment="记忆更新提案",
    )
    op.create_index(
        "ix_memory_proposals_novel_id", "memory_update_proposals", ["novel_id"]
    )
    op.create_index(
        "ix_memory_proposals_decision", "memory_update_proposals", ["decision"]
    )

    # -----------------------------------------------------------
    # 13. timeline_events
    # -----------------------------------------------------------
    op.create_table(
        "timeline_events",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "novel_id",
            sa.UUID(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("order_index", sa.Integer(), nullable=False),
        sa.Column("chapter_index", sa.Integer(), nullable=True),
        sa.Column("event_type", sa.String(32), nullable=True),
        sa.Column("related_character_ids", sa.JSON(), nullable=True, server_default="[]"),
        sa.Column("related_entity_ids", sa.JSON(), nullable=True, server_default="[]"),
        sa.Column("related_thread_ids", sa.JSON(), nullable=True, server_default="[]"),
        sa.Column("related_location_ids", sa.JSON(), nullable=True, server_default="[]"),
        sa.Column("geo_effects", sa.JSON(), nullable=True, server_default="[]"),
        sa.Column(
            "visibility", sa.String(20), nullable=False, server_default="author_only"
        ),
        sa.Column(
            "known_by_character_ids", sa.JSON(), nullable=True, server_default="[]"
        ),
        sa.Column("status", sa.String(32), nullable=False, server_default="candidate"),
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
        comment="轻量时间线事件",
    )
    op.create_index("ix_timeline_events_novel_id", "timeline_events", ["novel_id"])
    op.create_index("ix_timeline_events_order", "timeline_events", ["order_index"])

    # -----------------------------------------------------------
    # 14. plot_threads
    # -----------------------------------------------------------
    op.create_table(
        "plot_threads",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "novel_id",
            sa.UUID(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("thread_type", sa.String(32), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("visible_goal", sa.Text(), nullable=True),
        sa.Column("hidden_truth", sa.Text(), nullable=True),
        sa.Column("start_chapter", sa.Integer(), nullable=True),
        sa.Column("planned_payoff_chapter", sa.Integer(), nullable=True),
        sa.Column("current_stage", sa.String(32), nullable=True),
        sa.Column("related_character_ids", sa.JSON(), nullable=True, server_default="[]"),
        sa.Column("related_entity_ids", sa.JSON(), nullable=True, server_default="[]"),
        sa.Column("related_memory_ids", sa.JSON(), nullable=True, server_default="[]"),
        sa.Column("reader_known_state", sa.Text(), nullable=True),
        sa.Column("author_known_state", sa.Text(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
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
        comment="剧情线",
    )
    op.create_index("ix_plot_threads_novel_id", "plot_threads", ["novel_id"])

    # -----------------------------------------------------------
    # 15. outline_arcs
    # -----------------------------------------------------------
    op.create_table(
        "outline_arcs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "novel_id",
            sa.UUID(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("arc_index", sa.Integer(), nullable=True),
        sa.Column("start_chapter", sa.Integer(), nullable=True),
        sa.Column("end_chapter", sa.Integer(), nullable=True),
        sa.Column("arc_goal", sa.Text(), nullable=True),
        sa.Column("core_conflict", sa.Text(), nullable=True),
        sa.Column("main_opposition", sa.Text(), nullable=True),
        sa.Column("entry_hook", sa.Text(), nullable=True),
        sa.Column("midpoint_turn", sa.Text(), nullable=True),
        sa.Column("climax", sa.Text(), nullable=True),
        sa.Column("result", sa.Text(), nullable=True),
        sa.Column("next_hook", sa.Text(), nullable=True),
        sa.Column("related_thread_ids", sa.JSON(), nullable=True, server_default="[]"),
        sa.Column("related_character_ids", sa.JSON(), nullable=True, server_default="[]"),
        sa.Column("related_entity_ids", sa.JSON(), nullable=True, server_default="[]"),
        sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
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
        comment="篇章纲",
    )
    op.create_index("ix_outline_arcs_novel_id", "outline_arcs", ["novel_id"])

    # -----------------------------------------------------------
    # 16. chapter_cards
    # -----------------------------------------------------------
    op.create_table(
        "chapter_cards",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "novel_id",
            sa.UUID(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("chapter_index", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(255), nullable=True),
        sa.Column(
            "arc_id",
            sa.UUID(),
            sa.ForeignKey("outline_arcs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("chapter_goal", sa.Text(), nullable=False),
        sa.Column("main_conflict", sa.Text(), nullable=False),
        sa.Column("emotional_point", sa.Text(), nullable=True),
        sa.Column("plot_function", sa.String(32), nullable=True),
        sa.Column("must_happen", sa.JSON(), nullable=True, server_default="[]"),
        sa.Column("must_not_happen", sa.JSON(), nullable=True, server_default="[]"),
        sa.Column(
            "involved_character_ids", sa.JSON(), nullable=True, server_default="[]"
        ),
        sa.Column("involved_entity_ids", sa.JSON(), nullable=True, server_default="[]"),
        sa.Column("related_thread_ids", sa.JSON(), nullable=True, server_default="[]"),
        sa.Column("visible_progress", sa.JSON(), nullable=True, server_default="[]"),
        sa.Column("hidden_progress", sa.JSON(), nullable=True, server_default="[]"),
        sa.Column("offscreen_progress", sa.JSON(), nullable=True, server_default="[]"),
        sa.Column("foreshadowing_actions", sa.JSON(), nullable=True, server_default="[]"),
        sa.Column("ending_hook", sa.Text(), nullable=True),
        sa.Column("scene_cards", sa.JSON(), nullable=True, server_default="[]"),
        sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
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
        comment="章节卡",
    )
    op.create_index("ix_chapter_cards_novel_id", "chapter_cards", ["novel_id"])
    op.create_index(
        "ix_chapter_cards_chapter", "chapter_cards", ["chapter_index"], unique=True
    )

    # -----------------------------------------------------------
    # 17. foreshadowing_plans
    # -----------------------------------------------------------
    op.create_table(
        "foreshadowing_plans",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "novel_id",
            sa.UUID(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("surface_meaning", sa.Text(), nullable=True),
        sa.Column("hidden_meaning", sa.Text(), nullable=True),
        sa.Column("planned_seed_chapter", sa.Integer(), nullable=True),
        sa.Column(
            "planned_reinforce_chapters", sa.JSON(), nullable=True, server_default="[]"
        ),
        sa.Column("planned_payoff_chapter", sa.Integer(), nullable=True),
        sa.Column("related_entity_ids", sa.JSON(), nullable=True, server_default="[]"),
        sa.Column("related_thread_ids", sa.JSON(), nullable=True, server_default="[]"),
        sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
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
        comment="伏笔计划",
    )
    op.create_index("ix_foreshadowing_novel_id", "foreshadowing_plans", ["novel_id"])

    # -----------------------------------------------------------
    # 18. reveal_plans
    # -----------------------------------------------------------
    op.create_table(
        "reveal_plans",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "novel_id",
            sa.UUID(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("target_type", sa.String(32), nullable=False),
        sa.Column("target_id", sa.UUID(), nullable=False),
        sa.Column("secret_summary", sa.Text(), nullable=False),
        sa.Column("reveal_stages", sa.JSON(), nullable=True, server_default="[]"),
        sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
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
        comment="信息揭示计划",
    )
    op.create_index("ix_reveal_plans_novel_id", "reveal_plans", ["novel_id"])

    # -----------------------------------------------------------
    # 19. rag_chunks
    # -----------------------------------------------------------
    op.create_table(
        "rag_chunks",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "novel_id",
            sa.UUID(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_type", sa.String(32), nullable=False),
        sa.Column("source_id", sa.UUID(), nullable=True),
        sa.Column("chapter_index", sa.Integer(), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("entity_ids", sa.JSON(), nullable=True, server_default="[]"),
        sa.Column("character_ids", sa.JSON(), nullable=True, server_default="[]"),
        sa.Column("thread_ids", sa.JSON(), nullable=True, server_default="[]"),
        sa.Column(
            "visibility", sa.String(20), nullable=False, server_default="author_only"
        ),
        sa.Column("importance", sa.Float(), nullable=False, server_default="0.5"),
        sa.Column("embedding", Vector(1024), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=True, server_default="{}"),
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
        comment="RAG 分块",
    )
    op.create_index("ix_rag_chunks_novel_id", "rag_chunks", ["novel_id"])
    op.create_index("ix_rag_chunks_source", "rag_chunks", ["source_type", "source_id"])

    # -----------------------------------------------------------
    # 20. review_reports
    # -----------------------------------------------------------
    op.create_table(
        "review_reports",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "novel_id",
            sa.UUID(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("target_type", sa.String(32), nullable=False),
        sa.Column("target_id", sa.UUID(), nullable=True),
        sa.Column("decision", sa.String(20), nullable=False),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("problems", sa.JSON(), nullable=True, server_default="[]"),
        sa.Column("conflict_warnings", sa.JSON(), nullable=True, server_default="[]"),
        sa.Column("early_reveal_warnings", sa.JSON(), nullable=True, server_default="[]"),
        sa.Column(
            "character_knowledge_warnings", sa.JSON(), nullable=True, server_default="[]"
        ),
        sa.Column(
            "duplicate_entity_warnings", sa.JSON(), nullable=True, server_default="[]"
        ),
        sa.Column("geo_warnings", sa.JSON(), nullable=True, server_default="[]"),
        sa.Column("revision_instructions", sa.JSON(), nullable=True, server_default="[]"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
        comment="结构复查报告",
    )
    op.create_index("ix_review_reports_novel_id", "review_reports", ["novel_id"])

    # -----------------------------------------------------------
    # 21. writing_drafts
    # -----------------------------------------------------------
    op.create_table(
        "writing_drafts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "novel_id",
            sa.UUID(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("chapter_index", sa.Integer(), nullable=False),
        sa.Column(
            "chapter_card_id",
            sa.UUID(),
            sa.ForeignKey("chapter_cards.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("title", sa.String(255), nullable=True),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("version_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
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
        comment="正文草稿",
    )
    op.create_index("ix_writing_drafts_novel_id", "writing_drafts", ["novel_id"])
    op.create_index(
        "ix_writing_drafts_chapter", "writing_drafts", ["novel_id", "chapter_index"]
    )

    # -----------------------------------------------------------
    # 22. async_tasks
    # -----------------------------------------------------------
    op.create_table(
        "async_tasks",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("task_type", sa.String(64), nullable=False),
        sa.Column(
            "status", sa.String(16), nullable=False, server_default="pending", index=True
        ),
        sa.Column("progress", sa.Float(), nullable=False, server_default="0"),
        sa.Column("meta", sa.JSON(), nullable=True, server_default="{}"),
        sa.Column("result", sa.JSON(), nullable=True, server_default="{}"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
        comment="异步任务队列",
    )


def downgrade() -> None:
    """按依赖顺序倒序删除所有表"""
    op.drop_table("async_tasks")
    op.drop_table("writing_drafts")
    op.drop_table("review_reports")
    op.drop_table("rag_chunks")
    op.drop_table("reveal_plans")
    op.drop_table("foreshadowing_plans")
    op.drop_table("chapter_cards")
    op.drop_table("outline_arcs")
    op.drop_table("plot_threads")
    op.drop_table("timeline_events")
    op.drop_table("memory_update_proposals")
    op.drop_table("memory_records")
    op.drop_table("geo_eras")
    op.drop_table("geo_edges")
    op.drop_table("geo_locations")
    op.drop_table("character_knowledge")
    op.drop_table("characters")
    op.drop_table("entity_candidates")
    op.drop_table("entity_aliases")
    op.drop_table("relationships")
    op.drop_table("world_entities")
    op.drop_table("projects")
