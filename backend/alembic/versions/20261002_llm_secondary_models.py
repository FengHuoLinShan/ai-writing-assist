"""Add secondary models to global LLM defaults (B5 model routing).

Revision ID: 20261002_llm_secondary_models
Revises: 20261002_image_request_reuse
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20261002_llm_secondary_models"
down_revision = "20261002_image_request_reuse"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "global_llm_defaults",
        sa.Column(
            "secondary_models",
            sa.JSON(),
            nullable=True,
            comment="同 provider 附加模型（B5 路由候选；须为能力档案 verified 档）",
        ),
    )


def downgrade() -> None:
    op.drop_column("global_llm_defaults", "secondary_models")
