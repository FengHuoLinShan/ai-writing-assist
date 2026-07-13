"""reconcile active ORM schema with the PostgreSQL development database

Revision ID: 20260713_schema_reconciliation
Revises: 20260713_scene_fusion_suggestions
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260713_schema_reconciliation"
down_revision = "20260713_scene_fusion_suggestions"
branch_labels = None
depends_on = None


LEGACY_TABLES = (
    "geo_edges",
    "geo_locations",
    "geo_eras",
    "review_reports",
    "chapter_cards",
)

CREATED_AT_NOT_NULL_TABLES = (
    "async_tasks",
    "character_knowledge",
    "characters",
    "core_entities",
    "delta_log",
    "evidence_links",
    "foreshadowing_plans",
    "generation_prompt_template_revisions",
    "generation_prompt_templates",
    "global_author_preferences",
    "global_llm_defaults",
    "memory_events",
    "memory_snapshots",
    "outline_arcs",
    "plot_threads",
    "project_author_preferences",
    "projects",
    "rag_chunks",
    "rag_index_state",
    "reveal_plans",
    "scene_spans",
    "scene_summary_checkpoints",
    "scenes",
    "text_archive",
    "writing_conflict_checks",
    "writing_conflict_items",
    "writing_drafts",
)

INDEX_RENAMES = {
    "ix_character_knowledge_char_id": "ix_character_knowledge_character_id",
    "ix_characters_new_status": "ix_characters_status",
    "ix_entity_relations_source": "ix_entity_relations_source_id",
    "ix_entity_relations_target": "ix_entity_relations_target_id",
    "ix_entity_revisions_entity": "ix_entity_revisions_entity_id",
    "ix_foreshadowing_novel_id": "ix_foreshadowing_plans_novel_id",
    "ix_map_territory_faction_id": "ix_map_territory_tiles_faction_entity_id",
    "ix_map_territory_map_id": "ix_map_territory_tiles_map_id",
    "ix_map_territory_novel_id": "ix_map_territory_tiles_novel_id",
    "ix_memory_events_entity": "ix_memory_events_entity_id",
    "ix_memory_events_type": "ix_memory_events_event_type",
}

ADDED_INDEXES = {
    "async_tasks": {
        "ix_async_tasks_task_type": ["task_type"],
    },
    "character_knowledge": {
        "ix_character_knowledge_status": ["status"],
        "ix_character_knowledge_target_id": ["target_id"],
    },
    "core_entities": {
        "ix_core_entities_name": ["name"],
    },
    "context_snapshots": {
        "ix_context_snapshots_novel_id": ["novel_id"],
        "ix_context_snapshots_task_id": ["task_id"],
        "ix_context_snapshots_workflow_id": ["workflow_id"],
    },
    "delta_log": {
        "ix_delta_log_scene_index": ["novel_id", "scene_index"],
    },
    "entity_relations": {
        "ix_entity_relations_novel_id": ["novel_id"],
    },
    "events": {
        "ix_events_novel_id": ["novel_id"],
        "ix_events_timeline_order": ["timeline_order"],
    },
    "foreshadowing_plans": {
        "ix_foreshadowing_plans_status": ["status"],
    },
    "generation_prompt_templates": {
        "ix_generation_prompt_templates_status": ["status"],
    },
    "imported_chapters": {
        "ix_imported_chapters_novel_id": ["novel_id"],
        "ix_imported_chapters_novel": ["novel_id", "chapter_index"],
    },
    "map_facts": {
        "ix_map_facts_map_id": ["map_id"],
        "ix_map_facts_target_entity_id": ["target_entity_id"],
    },
    "map_location_layouts": {
        "ix_map_location_layouts_location_entity_id": ["location_entity_id"],
    },
    "map_observations": {
        "ix_map_observations_map_id": ["map_id"],
        "ix_map_observations_scene_id": ["scene_id"],
        "ix_map_observations_scene_index": ["scene_index"],
        "ix_map_observations_target_entity_id": ["target_entity_id"],
    },
    "map_terrain_bindings": {
        "ix_map_terrain_bindings_location_entity_id": ["location_entity_id"],
    },
    "memory_events": {
        "ix_memory_events_novel_chapter": [
            "novel_id",
            "chapter_index",
            "sequence",
        ],
    },
    "memory_snapshots": {
        "ix_memory_snapshots_novel_chapter": ["novel_id", "chapter_index"],
    },
    "outline_arcs": {
        "ix_outline_arcs_status": ["status"],
    },
    "plot_threads": {
        "ix_plot_threads_status": ["status"],
    },
    "projects": {
        "ix_projects_deleted_at": ["deleted_at"],
    },
    "rag_chunks": {
        "ix_rag_chunks_chapter_index": ["chapter_index"],
        "ix_rag_chunks_chapter_order": [
            "novel_id",
            "chapter_index",
            "chunk_index",
        ],
        "ix_rag_chunks_source_id": ["source_id"],
        "ix_rag_chunks_source": ["source_type", "source_id"],
    },
    "text_archive": {
        "ix_text_archive_scene": ["novel_id", "entity_id", "scene_index"],
    },
    "writing_conflict_items": {
        "ix_writing_conflict_items_check": ["check_id"],
    },
    "writing_drafts": {
        "ix_writing_drafts_chapter_index": ["chapter_index"],
        "ix_writing_drafts_chapter": ["novel_id", "chapter_index"],
    },
}


def _table_names() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _column_names(table_name: str) -> set[str]:
    return {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns(table_name)
    }


def _index_names(table_name: str) -> set[str]:
    return {
        index["name"]
        for index in sa.inspect(op.get_bind()).get_indexes(table_name)
    }


def _constraint_names(table_name: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return {
        constraint["name"]
        for constraint in inspector.get_unique_constraints(table_name)
        if constraint.get("name")
    }


def _rename_indexes() -> None:
    bind = op.get_bind()
    for old_name, new_name in INDEX_RENAMES.items():
        existing = {
            index["name"]
            for table_name in sa.inspect(bind).get_table_names()
            for index in sa.inspect(bind).get_indexes(table_name)
        }
        if old_name in existing and new_name not in existing:
            op.execute(
                sa.text(
                    f'ALTER INDEX "{old_name}" RENAME TO "{new_name}"'
                )
            )


def _create_missing_indexes() -> None:
    tables = _table_names()
    for table_name, indexes in ADDED_INDEXES.items():
        if table_name not in tables:
            continue
        existing = _index_names(table_name)
        columns = _column_names(table_name)
        for index_name, index_columns in indexes.items():
            if index_name in existing or not set(index_columns) <= columns:
                continue
            op.create_index(index_name, table_name, index_columns)
            existing.add(index_name)


def _drop_added_indexes() -> None:
    tables = _table_names()
    for table_name, indexes in ADDED_INDEXES.items():
        if table_name not in tables:
            continue
        existing = _index_names(table_name)
        for index_name in indexes:
            if index_name in existing:
                op.drop_index(index_name, table_name=table_name)


def _set_created_at_nullable(nullable: bool) -> None:
    tables = _table_names()
    for table_name in CREATED_AT_NOT_NULL_TABLES:
        if table_name not in tables or "created_at" not in _column_names(table_name):
            continue
        if not nullable:
            op.execute(
                sa.text(
                    f'UPDATE "{table_name}" '
                    "SET created_at = timezone('utc', now()) "
                    "WHERE created_at IS NULL"
                )
            )
        op.alter_column(
            table_name,
            "created_at",
            existing_type=sa.DateTime(timezone=True),
            nullable=nullable,
        )


def _upgrade_character_knowledge_fk() -> None:
    if "character_knowledge" not in _table_names():
        return
    inspector = sa.inspect(op.get_bind())
    fks = inspector.get_foreign_keys("character_knowledge")
    current = [
        fk
        for fk in fks
        if fk.get("constrained_columns") == ["character_id"]
    ]
    if any(
        fk.get("referred_table") == "characters"
        and fk.get("referred_columns") == ["entity_id"]
        for fk in current
    ):
        return
    for fk in current:
        if fk.get("name"):
            op.drop_constraint(
                fk["name"],
                "character_knowledge",
                type_="foreignkey",
            )
    op.create_foreign_key(
        "fk_character_knowledge_character_entity",
        "character_knowledge",
        "characters",
        ["character_id"],
        ["entity_id"],
        ondelete="CASCADE",
    )


def _downgrade_character_knowledge_fk() -> None:
    if "character_knowledge" not in _table_names():
        return
    inspector = sa.inspect(op.get_bind())
    for fk in inspector.get_foreign_keys("character_knowledge"):
        if (
            fk.get("constrained_columns") == ["character_id"]
            and fk.get("name")
        ):
            op.drop_constraint(
                fk["name"],
                "character_knowledge",
                type_="foreignkey",
            )
    op.create_foreign_key(
        "character_knowledge_new_character_id_fkey",
        "character_knowledge",
        "core_entities",
        ["character_id"],
        ["id"],
        ondelete="CASCADE",
    )


def upgrade() -> None:
    tables = _table_names()
    for table_name in LEGACY_TABLES:
        if table_name in tables:
            op.drop_table(table_name)

    if "async_tasks" in _table_names():
        op.alter_column(
            "async_tasks",
            "status",
            existing_type=sa.String(16),
            type_=sa.String(32),
        )
        op.alter_column(
            "async_tasks",
            "progress",
            existing_type=sa.Float(),
            nullable=True,
        )
    if "core_entities" in _table_names():
        op.alter_column(
            "core_entities",
            "entity_type",
            existing_type=sa.String(32),
            type_=sa.String(64),
        )
    if "rag_chunks" in _table_names():
        op.alter_column(
            "rag_chunks",
            "source_type",
            existing_type=sa.String(32),
            type_=sa.String(64),
        )
        op.alter_column(
            "rag_chunks",
            "visibility",
            existing_type=sa.String(20),
            type_=sa.String(32),
        )
        for column_name, fallback in (
            ("entity_ids", "[]"),
            ("character_ids", "[]"),
            ("thread_ids", "[]"),
            ("meta", "{}"),
        ):
            op.execute(
                sa.text(
                    f"UPDATE rag_chunks SET {column_name} = "
                    f"'{fallback}'::jsonb WHERE {column_name} IS NULL"
                )
            )
            op.alter_column(
                "rag_chunks",
                column_name,
                existing_type=sa.JSON(),
                nullable=False,
            )
    if "writing_drafts" in _table_names():
        op.alter_column(
            "writing_drafts",
            "title",
            existing_type=sa.String(255),
            type_=sa.Text(),
            postgresql_using="title::text",
        )
    for table_name in ("entity_relations", "imported_chapters"):
        if table_name in _table_names() and "updated_at" in _column_names(table_name):
            op.alter_column(
                table_name,
                "updated_at",
                existing_type=sa.DateTime(timezone=True),
                nullable=True,
            )

    _set_created_at_nullable(False)
    _upgrade_character_knowledge_fk()
    _rename_indexes()
    _create_missing_indexes()

    if "memory_events" in _table_names():
        constraints = _constraint_names("memory_events")
        if "uq_memory_events_novel_chapter_sequence" not in constraints:
            op.create_unique_constraint(
                "uq_memory_events_novel_chapter_sequence",
                "memory_events",
                ["novel_id", "chapter_index", "sequence"],
            )
    if "writing_drafts" in _table_names():
        constraints = _constraint_names("writing_drafts")
        if "uq_writing_draft_version" not in constraints:
            op.create_unique_constraint(
                "uq_writing_draft_version",
                "writing_drafts",
                ["novel_id", "chapter_index", "version_number"],
            )


def downgrade() -> None:
    if "writing_drafts" in _table_names():
        constraints = _constraint_names("writing_drafts")
        if "uq_writing_draft_version" in constraints:
            op.drop_constraint(
                "uq_writing_draft_version",
                "writing_drafts",
                type_="unique",
            )
    if "memory_events" in _table_names():
        constraints = _constraint_names("memory_events")
        if "uq_memory_events_novel_chapter_sequence" in constraints:
            op.drop_constraint(
                "uq_memory_events_novel_chapter_sequence",
                "memory_events",
                type_="unique",
            )

    _drop_added_indexes()
    existing_indexes = {
        index["name"]
        for table_name in _table_names()
        for index in sa.inspect(op.get_bind()).get_indexes(table_name)
    }
    for old_name, new_name in INDEX_RENAMES.items():
        if new_name in existing_indexes and old_name not in existing_indexes:
            op.execute(
                sa.text(
                    f'ALTER INDEX "{new_name}" RENAME TO "{old_name}"'
                )
            )

    _downgrade_character_knowledge_fk()
    _set_created_at_nullable(True)

    for table_name in ("entity_relations", "imported_chapters"):
        if table_name in _table_names() and "updated_at" in _column_names(table_name):
            op.execute(
                sa.text(
                    f'UPDATE "{table_name}" '
                    "SET updated_at = timezone('utc', now()) "
                    "WHERE updated_at IS NULL"
                )
            )
            op.alter_column(
                table_name,
                "updated_at",
                existing_type=sa.DateTime(timezone=True),
                nullable=False,
            )
    if "writing_drafts" in _table_names():
        op.alter_column(
            "writing_drafts",
            "title",
            existing_type=sa.Text(),
            type_=sa.String(255),
            postgresql_using="title::varchar(255)",
        )
    if "rag_chunks" in _table_names():
        for column_name in ("entity_ids", "character_ids", "thread_ids", "meta"):
            op.alter_column(
                "rag_chunks",
                column_name,
                existing_type=sa.JSON(),
                nullable=True,
            )
        op.alter_column(
            "rag_chunks",
            "visibility",
            existing_type=sa.String(32),
            type_=sa.String(20),
        )
        op.alter_column(
            "rag_chunks",
            "source_type",
            existing_type=sa.String(64),
            type_=sa.String(32),
        )
    if "core_entities" in _table_names():
        op.alter_column(
            "core_entities",
            "entity_type",
            existing_type=sa.String(64),
            type_=sa.String(32),
        )
    if "async_tasks" in _table_names():
        op.execute("UPDATE async_tasks SET progress = 0.0 WHERE progress IS NULL")
        op.alter_column(
            "async_tasks",
            "progress",
            existing_type=sa.Float(),
            nullable=False,
        )
        op.alter_column(
            "async_tasks",
            "status",
            existing_type=sa.String(32),
            type_=sa.String(16),
        )
