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

revision: str = "20260703_scene_chapter_links"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


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
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_rag_chunks_embedding_hnsw
        ON rag_chunks USING hnsw (embedding vector_ip_ops)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_core_entities_embedding_hnsw
        ON core_entities USING hnsw (embedding vector_ip_ops)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_core_entities_search_trgm
        ON core_entities USING gin (search_text gin_trgm_ops)
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS ix_map_binding_center
        ON map_location_bindings (map_id, location_entity_id)
        WHERE is_center = true
        """
    )
