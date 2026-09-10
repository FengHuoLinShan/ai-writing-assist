"""Shared PostgreSQL schema comparison policy for Alembic and upgrade tests."""

from typing import Any

from sqlalchemy import JSON, inspect
from sqlalchemy.dialects.postgresql import JSONB

# These PostgreSQL-only indexes are intentionally owned by explicit migrations.
# Alembic cannot faithfully reconstruct expression, partial, trigram, or vector
# indexes from the portable ORM metadata, so comparison validates their presence
# separately and excludes only these known names from remove-index suggestions.
MIGRATION_MANAGED_INDEXES: dict[str, set[str]] = {
    "core_entities": {
        "ix_core_entities_auto_ingested_recent",
        "ix_core_entities_embedding_hnsw",
        "ix_core_entities_name",
        "ix_core_entities_search_trgm",
    },
    "delta_log": {"ix_delta_log_scene_index"},
    "entity_relations": {"uq_entity_relations_canonical_edge"},
    "events": {"ix_events_timeline_order"},
    "imported_chapters": {"ix_imported_chapters_novel"},
    "memory_events": {"ix_memory_events_novel_chapter"},
    "memory_snapshots": {"ix_memory_snapshots_novel_chapter"},
    "projects": {"ix_projects_deleted_at"},
    "rag_chunks": {
        "ix_rag_chunks_chapter_order",
        "ix_rag_chunks_embedding_hnsw",
        "ix_rag_chunks_source",
        "uq_rag_chunks_chapter_text_key",
        "uq_rag_chunks_object_source_key",
    },
    "reader_reveal_policies": {"ix_reader_reveal_null_chapter"},
    "text_archive": {"ix_text_archive_scene"},
    "writing_conflict_items": {"ix_writing_conflict_items_check"},
    "writing_drafts": {"ix_writing_drafts_chapter"},
}


def _include_schema_object(
    obj: Any,
    name: str | None,
    type_: str,
    reflected: bool,
    compare_to: Any,
) -> bool:
    del compare_to
    if type_ != "index" or not reflected or not name:
        return True
    table_name = getattr(getattr(obj, "table", None), "name", None)
    return name not in MIGRATION_MANAGED_INDEXES.get(str(table_name), set())


def _compare_schema_type(
    context: Any,
    inspected_column: Any,
    metadata_column: Any,
    inspected_type: Any,
    metadata_type: Any,
) -> bool | None:
    del context, inspected_column, metadata_column
    if isinstance(inspected_type, JSON | JSONB) and isinstance(
        metadata_type,
        JSON | JSONB,
    ):
        return False
    return None


def _validate_migration_managed_indexes(connection: Any) -> None:
    inspector = inspect(connection)
    tables = set(inspector.get_table_names())
    missing: list[str] = []
    for table_name, expected in MIGRATION_MANAGED_INDEXES.items():
        if table_name not in tables:
            continue
        actual = {index["name"] for index in inspector.get_indexes(table_name)}
        missing.extend(
            f"{table_name}.{index_name}" for index_name in sorted(expected - actual)
        )
    if missing:
        raise RuntimeError(
            "Missing migration-managed PostgreSQL indexes: " + ", ".join(missing)
        )
