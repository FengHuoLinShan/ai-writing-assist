"""merge map layout terrain with scene structure heads

Revision ID: 20260630_merge_map_heads
Revises: 20260630_map_layout_terrain, f20260629e
Create Date: 2026-06-30
"""

from collections.abc import Sequence

revision: str = "20260630_merge_map_heads"
down_revision: str | tuple[str, str] | None = (
    "20260630_map_layout_terrain",
    "f20260629e",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
