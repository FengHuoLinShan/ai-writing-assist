"""Add project-level single live writer index to evolution runs (V4 R5).

部分唯一索引：同项目同时至多一个 active live run——count-then-insert
竞态在数据库层只有一赢者（E07.c 单写者门禁的数据库不变量）。
"""

import sqlalchemy as sa

from alembic import op

revision = "20260921_evolution_single_writer"
down_revision = "20260921_evolution_shadow"
branch_labels = None
depends_on = None

_PREDICATE = "execution_mode = 'live' AND status = 'active'"


def upgrade():
    op.create_index(
        "uq_evolution_run_single_live_writer",
        "evolution_runs",
        ["novel_id"],
        unique=True,
        postgresql_where=sa.text(_PREDICATE),
        sqlite_where=sa.text(_PREDICATE),
    )


def downgrade():
    op.drop_index(
        "uq_evolution_run_single_live_writer",
        table_name="evolution_runs",
    )
