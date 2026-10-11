"""Add source-basis registration to scene memory checkpoints.

Revision ID: 20261007_scene_checkpoint_basis
Revises: 20261007_interaction_source_cache

`memory_scene_checkpoints.basis_json`（M4 契约 §3）：系统行构建时记录的环境基线
（≤ cutoff 章稿指纹切片 + 重放窗口内场景结构 + Scene memory 契约版本），
供 `get_scene_state_view` 读时确定性比对，绕过失效钩子的变更不再静默供给。
不回填；旧行按「基线缺失→degraded 待重建」语义处理。
"""

import sqlalchemy as sa

from alembic import op

revision = "20261007_scene_checkpoint_basis"
down_revision = "20261007_interaction_source_cache"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "memory_scene_checkpoints",
        sa.Column("basis_json", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("memory_scene_checkpoints", "basis_json")
