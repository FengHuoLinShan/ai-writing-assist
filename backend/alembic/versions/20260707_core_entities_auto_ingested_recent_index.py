"""add recent auto-ingested core entity partial index

Revision ID: 20260707_core_entities_auto_ingested_recent_index
Revises: 20260707_writing_draft_provenance
"""

from alembic import op

revision = "20260707_core_entities_auto_ingested_recent_index"
down_revision = "20260707_writing_draft_provenance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_core_entities_auto_ingested_recent
        ON core_entities (novel_id, created_at DESC, id DESC)
        WHERE status = 'canonical'
          AND (CAST(((content_json -> '_meta') ->> 'auto_ingested') AS BOOLEAN) IS TRUE)
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute("DROP INDEX IF EXISTS ix_core_entities_auto_ingested_recent")
