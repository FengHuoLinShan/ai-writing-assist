"""Freeze world object image candidate request hash (B9).

Revision ID: 20261002_candidate_request_hash
Revises: 20261002_llm_secondary_models
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20261002_candidate_request_hash"
down_revision = "20261002_llm_secondary_models"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "world_object_image_candidates",
        sa.Column(
            "request_hash",
            sa.String(64),
            nullable=True,
            comment=(
                "入队时冻结的幂等键（B9）；完成登记复用，避免生成期间实体"
                "被编辑导致登记键漂移"
            ),
        ),
    )


def downgrade() -> None:
    op.drop_column("world_object_image_candidates", "request_hash")
