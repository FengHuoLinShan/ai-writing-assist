"""Add execution_mode to evolution runs (shadow isolation, V4 E07.b)."""

import sqlalchemy as sa

from alembic import op

revision = "20260921_evolution_shadow"
down_revision = "20260921_evolution_tables"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    columns = {
        column["name"] for column in inspector.get_columns("evolution_runs")
    }
    if "execution_mode" not in columns:
        op.add_column(
            "evolution_runs",
            sa.Column(
                "execution_mode",
                sa.String(16),
                nullable=False,
                server_default="live",
            ),
        )


def downgrade():
    op.drop_column("evolution_runs", "execution_mode")
