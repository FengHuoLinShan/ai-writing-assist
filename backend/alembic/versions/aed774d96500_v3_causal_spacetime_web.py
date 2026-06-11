"""v3: 因果时空网 — 核心实体重构

- world_entities → core_entities (rename)
- characters — 去除 id，world_entity_id → entity_id PK+FK
- 新建 events / entity_relations / entity_revisions / imported_chapters
- 删除 timeline_events / relationships / entity_candidates / entity_aliases

Revision ID: aed774d96500
Revises: aed774d964ff
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "aed774d96500"
down_revision: str | None = "aed774d964ff"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ---------------------------------------------------------------
    # 0. CharacterKnowledge FK 迁移：character_id → characters.world_entity_id
    #    先更新 FK 值，再删除旧 FK
    # ---------------------------------------------------------------
    op.execute("""
        UPDATE character_knowledge ck
        SET character_id = c.world_entity_id
        FROM characters c
        WHERE ck.character_id = c.id
          AND c.world_entity_id IS NOT NULL
    """)
    op.drop_constraint(
        "character_knowledge_character_id_fkey",
        "character_knowledge",
        type_="foreignkey",
    )

    # ---------------------------------------------------------------
    # 1. world_entities → core_entities (PG 自动更新相关 FK)
    # ---------------------------------------------------------------
    op.rename_table("world_entities", "core_entities")

    # ---------------------------------------------------------------
    # 2. characters：drop id → rename world_entity_id → PK + FK
    # ---------------------------------------------------------------
    # 2a. 为 world_entity_id=NULL 的行创建 core_entities 占位记录
    op.execute("""
        INSERT INTO core_entities (id, novel_id, entity_type, name, status, created_at, updated_at)
        SELECT gen_random_uuid(), c.novel_id, 'character_ref', c.name, c.status, c.created_at, c.updated_at
        FROM characters c
        WHERE c.world_entity_id IS NULL
    """)
    op.execute("""
        UPDATE characters c
        SET world_entity_id = ce.id
        FROM core_entities ce
        WHERE c.world_entity_id IS NULL
          AND ce.name = c.name
          AND ce.novel_id = c.novel_id
          AND ce.entity_type = 'character_ref'
    """)

    # 2b. 删除旧 PK 和 id 列 (CASCADE 自动丢弃依赖)
    op.drop_column("characters", "id")

    # 2c. 重命名列
    op.alter_column(
        "characters",
        "world_entity_id",
        new_column_name="entity_id",
        existing_type=sa.UUID(),
        nullable=False,
    )

    # 2d. 添加新 PK
    op.create_primary_key("pk_characters", "characters", ["entity_id"])

    # 2e. 添加新 FK → core_entities
    op.create_foreign_key(
        "fk_characters_entity",
        "characters",
        "core_entities",
        ["entity_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # ---------------------------------------------------------------
    # 3. Re-add character_knowledge FK → characters(entity_id)
    # ---------------------------------------------------------------
    op.create_foreign_key(
        "fk_character_knowledge_character",
        "character_knowledge",
        "characters",
        ["character_id"],
        ["entity_id"],
        ondelete="CASCADE",
    )

    # ---------------------------------------------------------------
    # 4. 新建 imported_chapters 表（被 events/entity_relations 引用，需先建）
    # ---------------------------------------------------------------
    op.create_table(
        "imported_chapters",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "novel_id",
            sa.UUID(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "import_record_id",
            sa.UUID(),
            sa.ForeignKey("import_records.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("chapter_index", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "is_analyzed", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
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
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        comment="已导入的章节内容",
    )
    op.create_index(
        "ix_imported_chapters_novel",
        "imported_chapters",
        ["novel_id", "chapter_index"],
    )

    # ---------------------------------------------------------------
    # 5. 新建 events 表
    # ---------------------------------------------------------------
    op.create_table(
        "events",
        sa.Column("entity_id", sa.UUID(), primary_key=True),
        sa.Column(
            "novel_id",
            sa.UUID(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "source_chapter_id",
            sa.UUID(),
            sa.ForeignKey("imported_chapters.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "location_entity_id",
            sa.UUID(),
            sa.ForeignKey("core_entities.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("timeline_order", sa.Integer(), nullable=False),
        sa.Column("occurrence_time_label", sa.String(100), nullable=True),
        sa.ForeignKeyConstraint(
            ["entity_id"],
            ["core_entities.id"],
            ondelete="CASCADE",
        ),
        comment="事件扩展表 (entity_id PK+FK → core_entities)",
    )
    op.create_index(
        "ix_events_timeline_order",
        "events",
        ["timeline_order"],
    )

    # ---------------------------------------------------------------
    # 6. 新建 entity_relations 表
    # ---------------------------------------------------------------
    op.create_table(
        "entity_relations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "novel_id",
            sa.UUID(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "source_id",
            sa.UUID(),
            sa.ForeignKey("core_entities.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "target_id",
            sa.UUID(),
            sa.ForeignKey("core_entities.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("relation_type", sa.String(64), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("strength", sa.Float(), nullable=False, server_default="0.5"),
        sa.Column(
            "source_chapter_id",
            sa.UUID(),
            sa.ForeignKey("imported_chapters.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "caused_by_event_id",
            sa.UUID(),
            sa.ForeignKey("core_entities.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("quote", sa.Text(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="canonical"),
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
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        comment="实体关系边 (UUID FK → core_entities + 追溯字段)",
    )
    op.create_index("ix_entity_relations_source", "entity_relations", ["source_id"])
    op.create_index("ix_entity_relations_target", "entity_relations", ["target_id"])

    # ---------------------------------------------------------------
    # 7. 新建 entity_revisions 表
    # ---------------------------------------------------------------
    op.create_table(
        "entity_revisions",
        sa.Column("id", sa.UUID(), nullable=False),
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
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column(
            "source_chapter_id",
            sa.UUID(),
            sa.ForeignKey("imported_chapters.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "revision_reason", sa.String(32), nullable=False, server_default="ai_import"
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("timezone('utc', now())"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        comment="实体快照版本表",
    )
    op.create_index("ix_entity_revisions_entity", "entity_revisions", ["entity_id"])

    # ---------------------------------------------------------------
    # 8. 删除废弃表
    # ---------------------------------------------------------------
    op.drop_table("timeline_events")
    op.drop_table("relationships")
    op.drop_table("entity_candidates")
    op.drop_table("entity_aliases")


def downgrade() -> None:
    # ---------------------------------------------------------------
    # 逆向：重建废弃表
    # ---------------------------------------------------------------
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
            sa.ForeignKey("core_entities.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("alias", sa.String(255), nullable=False),
        sa.Column("alias_type", sa.String(20), nullable=False, server_default="name"),
        sa.Column("source_chapter_index", sa.Integer(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0.8"),
        sa.Column("status", sa.String(32), nullable=False, server_default="confirmed"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        comment="世界对象别名",
    )
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
        sa.Column("embedding", sa.Text(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        comment="世界对象候选池",
    )
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
        sa.Column("source_id", sa.String(36), nullable=False),
        sa.Column("target_type", sa.String(32), nullable=False),
        sa.Column("target_id", sa.String(36), nullable=False),
        sa.Column("relation_type", sa.String(32), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "visibility", sa.String(20), nullable=False, server_default="author_only"
        ),
        sa.Column("strength", sa.Float(), nullable=False, server_default="0.5"),
        sa.Column("status", sa.String(32), nullable=False, server_default="canonical"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        comment="对象间关系边",
    )
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
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        comment="轻量时间线事件",
    )

    # ---------------------------------------------------------------
    # 删除新建表
    # ---------------------------------------------------------------
    op.drop_table("entity_revisions")
    op.drop_table("entity_relations")
    op.drop_table("events")
    op.drop_table("imported_chapters")

    # ---------------------------------------------------------------
    # 恢复 characters
    # ---------------------------------------------------------------
    op.drop_constraint("fk_characters_entity", "characters", type_="foreignkey")
    op.drop_constraint("pk_characters", "characters", type_="primary")
    op.alter_column(
        "characters",
        "entity_id",
        new_column_name="world_entity_id",
        existing_type=sa.UUID(),
        nullable=True,
    )
    op.add_column(
        "characters",
        sa.Column("id", sa.UUID(), nullable=False),
    )
    op.create_primary_key("pk_characters", "characters", ["id"])

    # ---------------------------------------------------------------
    # 恢复 FK
    # ---------------------------------------------------------------
    op.drop_constraint(
        "fk_character_knowledge_character",
        "character_knowledge",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "character_knowledge_character_id_fkey",
        "character_knowledge",
        "characters",
        ["character_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "characters_world_entity_id_fkey",
        "characters",
        "core_entities",
        ["world_entity_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # core_entities → world_entities
    op.rename_table("core_entities", "world_entities")
