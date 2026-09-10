"""World review phase 4: review items + validation run impact/plan columns (ADR-0022).

Revision ID: 20260910_world_review_phase4
Revises: 20260909_world_cocreation_sessions
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision = "20260910_world_review_phase4"
down_revision = "20260909_world_cocreation_sessions"
branch_labels = None
depends_on = None


def upgrade():
    op.create_unique_constraint(
        "uq_world_validation_runs_novel_id",
        "world_validation_runs",
        ["novel_id", "id"],
    )
    op.add_column(
        "world_validation_runs",
        sa.Column("impact_json", sa.JSON(), nullable=False, server_default="{}"),
    )
    op.add_column(
        "world_validation_runs",
        sa.Column("plan_json", sa.JSON(), nullable=False, server_default="{}"),
    )
    op.add_column(
        "world_validation_runs",
        sa.Column("stale_reason", sa.String(64), nullable=True),
    )
    op.add_column(
        "world_validation_runs",
        sa.Column(
            "continued_count", sa.Integer(), nullable=False, server_default="0"
        ),
    )
    op.create_table(
        "world_validation_review_items",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "novel_id",
            UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("run_id", UUID(as_uuid=True), nullable=False),
        sa.Column("finding_id", sa.String(128), nullable=False),
        sa.Column("disposition", sa.String(32), nullable=False),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "finding_snapshot", sa.JSON(), nullable=False, server_default="{}"
        ),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "disposition IN ('resolved', 'acknowledged', 'deferred')",
            name="ck_world_validation_review_items_disposition",
        ),
        sa.UniqueConstraint(
            "run_id", "finding_id", name="uq_world_validation_review_items"
        ),
        sa.ForeignKeyConstraint(
            ["novel_id", "run_id"],
            ["world_validation_runs.novel_id", "world_validation_runs.id"],
            name="fk_world_validation_review_items_run",
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_world_validation_review_items_novel_run",
        "world_validation_review_items",
        ["novel_id", "run_id"],
    )


def downgrade():
    op.drop_index(
        "ix_world_validation_review_items_novel_run",
        table_name="world_validation_review_items",
    )
    op.drop_table("world_validation_review_items")
    op.drop_column("world_validation_runs", "continued_count")
    op.drop_column("world_validation_runs", "stale_reason")
    op.drop_column("world_validation_runs", "plan_json")
    op.drop_column("world_validation_runs", "impact_json")
    op.drop_constraint(
        "uq_world_validation_runs_novel_id", "world_validation_runs", type_="unique"
    )
