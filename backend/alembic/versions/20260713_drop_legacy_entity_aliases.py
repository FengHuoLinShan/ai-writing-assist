"""drop the unused legacy core_entities.aliases column

Revision ID: 20260713_drop_legacy_entity_aliases
Revises: 20260713_schema_reconciliation
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260713_drop_legacy_entity_aliases"
down_revision = "20260713_schema_reconciliation"
branch_labels = None
depends_on = None


def _has_aliases_column() -> bool:
    inspector = sa.inspect(op.get_bind())
    if "core_entities" not in set(inspector.get_table_names()):
        return False
    return "aliases" in {
        column["name"] for column in inspector.get_columns("core_entities")
    }


def upgrade() -> None:
    if not _has_aliases_column():
        return
    non_empty = op.get_bind().execute(
        sa.text(
            "SELECT COUNT(*) FROM core_entities "
            "WHERE aliases IS NOT NULL "
            "AND aliases::text NOT IN ('[]', 'null')"
        )
    ).scalar_one()
    if non_empty:
        raise RuntimeError(
            "core_entities.aliases still contains data; migrate it into "
            "content_json.aliases before dropping the legacy column"
        )
    op.drop_column("core_entities", "aliases")


def downgrade() -> None:
    if _has_aliases_column():
        return
    op.add_column(
        "core_entities",
        sa.Column(
            "aliases",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'::json"),
            comment="别名列表 JSONB [{alias: str, type: str}]",
        ),
    )
