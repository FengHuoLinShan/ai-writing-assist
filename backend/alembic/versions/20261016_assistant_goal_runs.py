"""add isolated goal runs to assistant_runs

Revision ID: 20261016_assistant_goal_runs
Revises: 20261015_operation_trace_v2
Create Date: 2026-10-16
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261016_assistant_goal_runs"
down_revision: str | None = "20261015_operation_trace_v2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _replace_mode_constraint(sqlite: bool, *, downgrade: bool = False) -> None:
    allowed = "'author','background'" if downgrade else "'author','background','goal'"
    if sqlite:
        with op.batch_alter_table("assistant_runs", recreate="always") as batch:
            batch.drop_constraint("ck_assistant_run_mode", type_="check")
            batch.create_check_constraint(
                "ck_assistant_run_mode", f"mode IN ({allowed})"
            )
            if downgrade:
                batch.drop_constraint(
                    "ck_assistant_goal_run_without_session", type_="check"
                )
            else:
                batch.create_check_constraint(
                    "ck_assistant_goal_run_without_session",
                    "mode != 'goal' OR session_id IS NULL",
                )
        return

    op.drop_constraint("ck_assistant_run_mode", "assistant_runs", type_="check")
    op.create_check_constraint(
        "ck_assistant_run_mode", "assistant_runs", f"mode IN ({allowed})"
    )
    if downgrade:
        op.drop_constraint(
            "ck_assistant_goal_run_without_session",
            "assistant_runs",
            type_="check",
        )
    else:
        op.create_check_constraint(
            "ck_assistant_goal_run_without_session",
            "assistant_runs",
            "mode != 'goal' OR session_id IS NULL",
        )


def upgrade() -> None:
    bind = op.get_bind()
    sqlite = bind.dialect.name == "sqlite"
    _replace_mode_constraint(sqlite)
    predicate = sa.text(
        "mode = 'goal' AND status IN ('pending','running','waiting_approval')"
    )
    op.create_index(
        "uq_assistant_goal_run_active",
        "assistant_runs",
        ["novel_id"],
        unique=True,
        postgresql_where=predicate,
        sqlite_where=predicate,
    )


def downgrade() -> None:
    op.drop_index("uq_assistant_goal_run_active", table_name="assistant_runs")
    _replace_mode_constraint(
        op.get_bind().dialect.name == "sqlite", downgrade=True
    )
