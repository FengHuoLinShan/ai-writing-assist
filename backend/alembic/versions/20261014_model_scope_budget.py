"""Allow explicit scope-authorized Evolution budgets without changing old rows."""

import sqlalchemy as sa

from alembic import op

revision = "20261014_model_scope_budget"
down_revision = "20261013_delta_category_text"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column(
        "evolution_runs", "budget_total", existing_type=sa.Integer(), nullable=True
    )
    op.alter_column(
        "evolution_runs", "budget_remaining", existing_type=sa.Integer(), nullable=True
    )
    op.create_check_constraint(
        "ck_evolution_scope_budget_pair",
        "evolution_runs",
        "(budget_total IS NULL) = (budget_remaining IS NULL)",
    )


def downgrade():
    if (
        op.get_bind()
        .execute(
            sa.text("SELECT 1 FROM evolution_runs WHERE budget_total IS NULL LIMIT 1")
        )
        .first()
    ):
        raise RuntimeError("Scope-authorized runs must be retained; downgrade refused")
    op.drop_constraint("ck_evolution_scope_budget_pair", "evolution_runs", type_="check")
    op.alter_column(
        "evolution_runs", "budget_total", existing_type=sa.Integer(), nullable=False
    )
    op.alter_column(
        "evolution_runs", "budget_remaining", existing_type=sa.Integer(), nullable=False
    )
