"""Add structured revisions to the existing atlas without rewriting image assets.

Revision ID: 20260908_unified_map
Revises: 20260901_rp_source_context
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision = "20260908_unified_map"
down_revision = "20260901_rp_source_context"
branch_labels = None
depends_on = None


def upgrade():
    for fk in sa.inspect(op.get_bind()).get_foreign_keys("map_atlas_nodes"):
        if fk["constrained_columns"] == ["created_by_run_id"]:
            op.drop_constraint(fk["name"], "map_atlas_nodes", type_="foreignkey")
    op.alter_column("map_atlas_nodes", "created_by_run_id", nullable=True)
    op.create_foreign_key(
        "fk_map_node_origin_run",
        "map_atlas_nodes",
        "map_atlas_runs",
        ["created_by_run_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_unique_constraint(
        "uq_map_atlas_nodes_novel_id", "map_atlas_nodes", ["novel_id", "id"]
    )
    op.add_column("map_atlas_nodes", sa.Column("current_revision_id", UUID(as_uuid=True)))
    op.add_column("map_atlas_nodes", sa.Column("structure_task_id", UUID(as_uuid=True)))
    op.create_foreign_key(
        "fk_map_node_structure_task",
        "map_atlas_nodes",
        "async_tasks",
        ["structure_task_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_table(
        "map_atlas_revisions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "novel_id",
            UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("node_id", UUID(as_uuid=True), nullable=False),
        sa.Column("base_revision_id", UUID(as_uuid=True)),
        sa.Column("status", sa.String(16), nullable=False, server_default="candidate"),
        sa.Column("document", sa.JSON(), nullable=False),
        sa.Column("geometry_hash", sa.String(64), nullable=False),
        sa.Column("problems", sa.JSON(), nullable=False),
        sa.Column("confirmation_id", UUID(as_uuid=True)),
        sa.Column("context_fingerprint", sa.String(128)),
        sa.Column("task_id", UUID(as_uuid=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["novel_id", "node_id"],
            ["map_atlas_nodes.novel_id", "map_atlas_nodes.id"],
            ondelete="CASCADE",
            name="fk_map_revision_node",
        ),
        sa.UniqueConstraint("novel_id", "node_id", "id", name="uq_map_revision_owner"),
        sa.UniqueConstraint("task_id", "node_id", name="uq_map_revision_task_node"),
        sa.CheckConstraint(
            "status IN ('candidate', 'saved', 'rejected')", name="ck_map_revision_status"
        ),
    )
    op.create_index(
        "ix_map_atlas_revisions_novel_id", "map_atlas_revisions", ["novel_id"]
    )
    op.create_index(
        "ix_map_revision_node_created",
        "map_atlas_revisions",
        ["novel_id", "node_id", "created_at"],
    )
    op.create_foreign_key(
        "fk_map_node_current_revision",
        "map_atlas_nodes",
        "map_atlas_revisions",
        ["novel_id", "id", "current_revision_id"],
        ["novel_id", "node_id", "id"],
        deferrable=True,
        initially="DEFERRED",
    )
    op.add_column(
        "map_atlas_pages", sa.Column("source_map_revision_id", UUID(as_uuid=True))
    )
    op.add_column("map_atlas_pages", sa.Column("source_geometry_hash", sa.String(64)))
    op.create_foreign_key(
        "fk_map_page_source_revision",
        "map_atlas_pages",
        "map_atlas_revisions",
        ["source_map_revision_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.execute("""
        CREATE FUNCTION protect_map_revision_content() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
          IF ROW(NEW.novel_id, NEW.node_id, NEW.base_revision_id, NEW.document::jsonb,
                 NEW.geometry_hash, NEW.problems::jsonb, NEW.confirmation_id,
                 NEW.context_fingerprint, NEW.task_id, NEW.created_at)
             IS DISTINCT FROM
             ROW(OLD.novel_id, OLD.node_id, OLD.base_revision_id, OLD.document::jsonb,
                 OLD.geometry_hash, OLD.problems::jsonb, OLD.confirmation_id,
                 OLD.context_fingerprint, OLD.task_id, OLD.created_at) THEN
            RAISE EXCEPTION 'map revision content is immutable';
          END IF;
          RETURN NEW;
        END $$;
        CREATE TRIGGER map_revision_immutable BEFORE UPDATE ON map_atlas_revisions
        FOR EACH ROW EXECUTE FUNCTION protect_map_revision_content();
    """)


def downgrade():
    raise RuntimeError(
        "Restore a verified backup to remove map revisions without losing author work"
    )
