"""Add map prompt review and external upload state.

Revision ID: 20260813_map_prompt_upload
Revises: 20260812_ai_map_atlas
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260813_map_prompt_upload"
down_revision = "20260812_ai_map_atlas"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("map_atlas_runs") as batch:
        batch.add_column(
            sa.Column(
                "review_image_prompts",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch.drop_constraint("ck_map_atlas_runs_kind", type_="check")
        batch.create_check_constraint(
            "ck_map_atlas_runs_kind",
            "run_kind IN ('initial','update','rebuild','edit','regenerate','upload')",
        )
        batch.drop_constraint("ck_map_atlas_runs_status", type_="check")
        batch.create_check_constraint(
            "ck_map_atlas_runs_status",
            "status IN ('planning','prompt_review','generating','review_ready',"
            "'partial','paused','failed','completed')",
        )
    with op.batch_alter_table("map_atlas_pages") as batch:
        batch.add_column(
            sa.Column(
                "generation_choice",
                sa.String(16),
                nullable=False,
                server_default="internal",
            )
        )
        batch.create_check_constraint(
            "ck_map_atlas_pages_generation_choice",
            "generation_choice IN ('internal','external')",
        )
        batch.drop_constraint("ck_map_atlas_pages_generation_status", type_="check")
        batch.create_check_constraint(
            "ck_map_atlas_pages_generation_status",
            "generation_status IN ('prepared','provider_in_flight','uploaded',"
            "'review_ready','prompt_only','failed','retry_requires_confirmation')",
        )


def downgrade() -> None:
    with op.batch_alter_table("map_atlas_pages") as batch:
        batch.drop_constraint("ck_map_atlas_pages_generation_status", type_="check")
        batch.create_check_constraint(
            "ck_map_atlas_pages_generation_status",
            "generation_status IN ('prepared','provider_in_flight','uploaded',"
            "'review_ready','failed','retry_requires_confirmation')",
        )
        batch.drop_constraint("ck_map_atlas_pages_generation_choice", type_="check")
        batch.drop_column("generation_choice")
    with op.batch_alter_table("map_atlas_runs") as batch:
        batch.drop_constraint("ck_map_atlas_runs_status", type_="check")
        batch.create_check_constraint(
            "ck_map_atlas_runs_status",
            "status IN ('planning','generating','review_ready','partial',"
            "'paused','failed','completed')",
        )
        batch.drop_constraint("ck_map_atlas_runs_kind", type_="check")
        batch.create_check_constraint(
            "ck_map_atlas_runs_kind",
            "run_kind IN ('initial','update','rebuild','edit','regenerate')",
        )
        batch.drop_column("review_image_prompts")
