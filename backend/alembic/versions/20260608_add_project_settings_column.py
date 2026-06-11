"""add project.settings json column

Revision ID: 20260608_project_settings
Revises: e31ca9d12321
Create Date: 2026-06-08
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260608_project_settings"
down_revision: str | None = "94d6df4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column(
            "settings",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'::json"),
            comment="小说配置（JSON，如 temporary_entity_expiry_chapters）",
        ),
    )


def downgrade() -> None:
    op.drop_column("projects", "settings")
