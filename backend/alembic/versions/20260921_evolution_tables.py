"""Add evolution run registry, frozen attempts and receipts."""

import sqlalchemy as sa

from alembic import op

revision = "20260921_evolution_tables"
down_revision = "20260920_creative_recovery"
branch_labels = None
depends_on = None


def _identity():
    return [
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "novel_id",
            sa.Uuid(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.timezone("utc", sa.func.now()),
            nullable=False,
        ),
    ]


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("evolution_runs"):
        op.create_table(
            "evolution_runs",
            *_identity(),
            sa.Column("run_key", sa.String(120), nullable=False),
            sa.Column("mode", sa.String(32), nullable=False),
            sa.Column("owner_epoch", sa.Integer(), nullable=False),
            sa.Column("active_engine", sa.String(64), nullable=False),
            sa.Column("status", sa.String(32), nullable=False),
            sa.Column("committed_scene_index", sa.Integer(), nullable=False),
            sa.Column("committed_source_revision", sa.Integer(), nullable=False),
            sa.Column("head_attempt_id", sa.Uuid(), nullable=True),
            sa.Column("budget_total", sa.Integer(), nullable=False),
            sa.Column("budget_remaining", sa.Integer(), nullable=False),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=True,
            ),
            sa.UniqueConstraint("novel_id", "run_key", name="uq_evolution_run_novel_key"),
            comment="演化理解运行注册表：owner epoch / 游标 / 根预算",
        )
        op.create_index("ix_evolution_runs_novel_id", "evolution_runs", ["novel_id"])
    if not inspector.has_table("evolution_frozen_attempts"):
        op.create_table(
            "evolution_frozen_attempts",
            *_identity(),
            sa.Column("run_key", sa.String(120), nullable=False),
            sa.Column("attempt_key", sa.String(120), nullable=False),
            sa.Column("owner_epoch", sa.Integer(), nullable=False),
            sa.Column("producer_version", sa.String(64), nullable=False),
            sa.Column("source_manifest_hash", sa.String(64), nullable=False),
            sa.Column("previous_receipt", sa.String(120), nullable=True),
            sa.Column("previous_prefix_json", sa.JSON(), nullable=True),
            sa.Column("payload_json", sa.JSON(), nullable=False),
            sa.Column("status", sa.String(32), nullable=False),
            sa.UniqueConstraint(
                "novel_id",
                "run_key",
                "attempt_key",
                name="uq_evolution_frozen_attempt_key",
            ),
            comment="演化窄提交冻结负载（T10 恢复基础）",
        )
        op.create_index(
            "ix_evolution_frozen_attempts_novel_id",
            "evolution_frozen_attempts",
            ["novel_id"],
        )
        op.create_index(
            "ix_evolution_frozen_attempts_run_key",
            "evolution_frozen_attempts",
            ["run_key"],
        )
    if not inspector.has_table("evolution_receipts"):
        op.create_table(
            "evolution_receipts",
            *_identity(),
            sa.Column("run_key", sa.String(120), nullable=False),
            sa.Column("attempt_key", sa.String(120), nullable=False),
            sa.Column("execution_status", sa.String(32), nullable=False),
            sa.Column("committed_scene_index", sa.Integer(), nullable=False),
            sa.Column("committed_source_revision", sa.Integer(), nullable=False),
            sa.Column("receipt_json", sa.JSON(), nullable=False),
            sa.UniqueConstraint(
                "novel_id",
                "run_key",
                "attempt_key",
                name="uq_evolution_receipt_attempt",
            ),
            comment="演化窄提交回执（T11 重放依据）",
        )
        op.create_index(
            "ix_evolution_receipts_novel_id", "evolution_receipts", ["novel_id"]
        )
        op.create_index(
            "ix_evolution_receipts_run_key", "evolution_receipts", ["run_key"]
        )


def downgrade():
    op.drop_table("evolution_receipts")
    op.drop_table("evolution_frozen_attempts")
    op.drop_table("evolution_runs")
