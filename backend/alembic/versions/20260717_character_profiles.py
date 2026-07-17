"""backfill minimum profiles for adopted character entities

Revision ID: 20260717_character_profiles
Revises: 20260717_reveal_thread_links
"""

from __future__ import annotations

from alembic import op

revision = "20260717_character_profiles"
down_revision = "20260717_reveal_thread_links"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            """
            INSERT INTO characters (
                entity_id, novel_id, name, aliases, secret,
                behavior_rules, meta, status
            )
            SELECT
                entity.id,
                entity.novel_id,
                entity.name,
                '[]'::json,
                entity.hidden_truth,
                '[]'::json,
                json_build_object(
                    'auto_materialized', true,
                    'source', 'core_entity_backfill',
                    'core_summary', entity.summary,
                    'public_info', entity.public_info
                ),
                'canonical'
            FROM core_entities AS entity
            WHERE entity.entity_type = 'character'
              AND entity.status = 'canonical'
            ON CONFLICT (entity_id) DO NOTHING
            """
        )
        return

    op.execute(
        """
        INSERT OR IGNORE INTO characters (
            entity_id, novel_id, name, aliases, secret,
            behavior_rules, meta, status
        )
        SELECT
            entity.id,
            entity.novel_id,
            entity.name,
            '[]',
            entity.hidden_truth,
            '[]',
            json_object(
                'auto_materialized', 1,
                'source', 'core_entity_backfill',
                'core_summary', entity.summary,
                'public_info', entity.public_info
            ),
            'canonical'
        FROM core_entities AS entity
        WHERE entity.entity_type = 'character'
          AND entity.status = 'canonical'
        """
    )


def downgrade() -> None:
    # The backfilled rows may have been enriched by authors after upgrade.
    # Deleting them during downgrade would destroy user data.
    pass
