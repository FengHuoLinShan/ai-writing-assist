"""merge: d967c0547256 HNSW + d967c0547257 memory events

Revision ID: e31ca9d12321
Revises: d967c0547256, d967c0547257
Create Date: 2026-06-01 22:10:54.090981
"""

from collections.abc import Sequence

import pgvector  # noqa: F401

# revision identifiers, used by Alembic.
revision: str = "e31ca9d12321"
down_revision: str | None = ("d967c0547256", "d967c0547257")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
