"""merge_heads

Revision ID: 8bb02b4b94ba
Revises: 20260609_pinyin_string, 20260622_add_territory_tables, aed774d96500
Create Date: 2026-06-25 10:04:08.348733
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import pgvector  # noqa: F401


# revision identifiers, used by Alembic.
revision: str = '8bb02b4b94ba'
down_revision: Union[str, None] = ('20260609_pinyin_string', '20260622_add_territory_tables', 'aed774d96500')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
