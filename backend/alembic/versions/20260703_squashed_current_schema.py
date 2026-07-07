"""squashed current demo schema

Revision ID: 20260703_scene_chapter_links
Revises:
Create Date: 2026-07-03

This project is still in demo-stage schema development. The historical
step-by-step migrations were intentionally squashed into this current-schema
initializer. Intermediate demo databases should be recreated instead of
upgraded through removed historical revisions.
"""

from collections.abc import Sequence

import infrastructure.tasks.models  # noqa: F401
import modules.context.models  # noqa: F401
import modules.imports.models  # noqa: F401
import modules.memory.models  # noqa: F401
import modules.outline.models  # noqa: F401
import modules.project.models  # noqa: F401
import modules.rag.models  # noqa: F401
import modules.world.map_models  # noqa: F401
import modules.world.models  # noqa: F401
import modules.writing.models  # noqa: F401
from alembic import op
from core.base import Base
from core.config import Settings

revision: str = "20260703_scene_chapter_links"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ALLOWED_VECTOR_INDEX_TYPES = {"hnsw", "ivfflat"}
_ALLOWED_VECTOR_INDEX_TARGETS = {
    (
        "ix_rag_chunks_embedding",
        "rag_chunks",
        "embedding",
        "vector_ip_ops",
    ),
    (
        "ix_core_entities_embedding",
        "core_entities",
        "embedding",
        "vector_cosine_ops",
    ),
}


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")
        op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    Base.metadata.create_all(bind=bind)

    if bind.dialect.name == "postgresql":
        _create_postgresql_only_indexes()


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)

    if bind.dialect.name == "postgresql":
        op.execute("DROP EXTENSION IF EXISTS pg_trgm")
        op.execute("DROP EXTENSION IF EXISTS vector")


def _create_postgresql_only_indexes() -> None:
    _assert_no_postgresql_duplicate_keys()
    op.execute(
        _create_vector_index_sql(
            "ix_rag_chunks_embedding",
            "rag_chunks",
            "embedding",
            "vector_ip_ops",
        )
    )
    op.execute(
        _create_vector_index_sql(
            "ix_core_entities_embedding",
            "core_entities",
            "embedding",
            "vector_cosine_ops",
        )
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_core_entities_search_trgm
        ON core_entities USING gin (search_text gin_trgm_ops)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_core_entities_auto_ingested_recent
        ON core_entities (novel_id, created_at DESC, id DESC)
        WHERE status = 'canonical'
          AND (CAST(((content_json -> '_meta') ->> 'auto_ingested') AS BOOLEAN) IS TRUE)
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS ix_map_binding_center
        ON map_location_bindings (map_id, location_entity_id)
        WHERE is_center = true
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_entity_relations_canonical_edge
        ON entity_relations (novel_id, source_id, target_id, relation_type)
        WHERE status = 'canonical'
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_map_config_top_level_name
        ON map_configs (novel_id, name)
        WHERE parent_map_id IS NULL
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_rag_chunks_chapter_text_key
        ON rag_chunks (
            novel_id,
            source_type,
            chapter_index,
            chunk_index,
            index_version
        )
        WHERE source_type = 'chapter_text'
          AND chapter_index IS NOT NULL
          AND chunk_index IS NOT NULL
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_rag_chunks_object_source_key
        ON rag_chunks (
            novel_id,
            source_type,
            source_id,
            chapter_index,
            chunk_index,
            index_version
        )
        WHERE source_id IS NOT NULL
          AND chunk_index IS NOT NULL
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_reader_reveal_null_chapter
        ON reader_reveal_policies (novel_id, target_hash)
        WHERE reveal_chapter_index IS NULL
        """
    )


def _vector_index_type(settings: Settings | None = None) -> str:
    configured = (settings or Settings()).vector_index_type.strip().lower()
    if configured not in _ALLOWED_VECTOR_INDEX_TYPES:
        raise ValueError("VECTOR_INDEX_TYPE must be one of: hnsw, ivfflat")
    return configured


def _create_vector_index_sql(
    index_base_name: str,
    table: str,
    column: str,
    opclass: str,
    *,
    settings: Settings | None = None,
) -> str:
    target = (index_base_name, table, column, opclass)
    if target not in _ALLOWED_VECTOR_INDEX_TARGETS:
        raise ValueError("Unsupported vector index target")
    index_type = _vector_index_type(settings)
    index_name = f"{index_base_name}_{index_type}"
    return f"""
        CREATE INDEX IF NOT EXISTS {index_name}
        ON {table} USING {index_type} ({column} {opclass})
        """


def _assert_no_postgresql_duplicate_keys() -> None:
    duplicate_checks = {
        "canonical entity relations": """
            SELECT novel_id, source_id, target_id, relation_type, COUNT(*) AS n
            FROM entity_relations
            WHERE status = 'canonical'
            GROUP BY novel_id, source_id, target_id, relation_type
            HAVING COUNT(*) > 1
            LIMIT 5
        """,
        "top-level map names": """
            SELECT novel_id, name, COUNT(*) AS n
            FROM map_configs
            WHERE parent_map_id IS NULL
            GROUP BY novel_id, name
            HAVING COUNT(*) > 1
            LIMIT 5
        """,
        "chapter text rag chunks": """
            SELECT novel_id, source_type, chapter_index, chunk_index, index_version,
                   COUNT(*) AS n
            FROM rag_chunks
            WHERE source_type = 'chapter_text'
              AND chapter_index IS NOT NULL
              AND chunk_index IS NOT NULL
            GROUP BY novel_id, source_type, chapter_index, chunk_index, index_version
            HAVING COUNT(*) > 1
            LIMIT 5
        """,
        "object source rag chunks": """
            SELECT novel_id, source_type, source_id, chapter_index, chunk_index,
                   index_version, COUNT(*) AS n
            FROM rag_chunks
            WHERE source_id IS NOT NULL
              AND chunk_index IS NOT NULL
            GROUP BY novel_id, source_type, source_id, chapter_index, chunk_index,
                     index_version
            HAVING COUNT(*) > 1
            LIMIT 5
        """,
    }
    bind = op.get_bind()
    for label, sql in duplicate_checks.items():
        rows = bind.exec_driver_sql(sql).fetchall()
        if rows:
            sample = "; ".join(str(tuple(row)) for row in rows)
            raise RuntimeError(
                f"Cannot create unique indexes: duplicate {label} remain: {sample}"
            )
