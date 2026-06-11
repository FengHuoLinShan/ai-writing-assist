"""add search_text generated column for pg_trgm dedup

Add a GENERATED ALWAYS column that concatenates name and content_json->>'aliases'
into a single text field, then create a GIN trigram index on it for fast fuzzy
dedup matching.

Revision ID: d967c0547255
Revises: d967c0547254
Create Date: 2026-05-31
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d967c0547255"
down_revision: str | None = "d967c0547254"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Ensure pg_trgm extension is available (it was created in 0001 but may not exist in test DBs)
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    # Add generated column that aggregates name + aliases for full-text fuzzy search
    op.execute("""
        ALTER TABLE core_entities
        ADD COLUMN search_text text
        GENERATED ALWAYS AS (
            name || ' ' || COALESCE(content_json->>'aliases', '')
        ) STORED
    """)

    # GIN trigram index for fast similarity() queries
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_core_entities_search_trgm
        ON core_entities USING GIN (search_text gin_trgm_ops)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_core_entities_search_trgm")
    op.execute("ALTER TABLE core_entities DROP COLUMN IF EXISTS search_text")
