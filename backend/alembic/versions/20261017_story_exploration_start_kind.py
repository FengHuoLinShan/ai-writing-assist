"""Allow provisional exploration starts on the two director/progression roots.

P0 §3.2：两根表新增 source_kind（默认 'scene'），scene_id 改为可空，
组合 CHECK 保证 Scene 型根仍必填场景；新增 (novel_id, source_kind, created_at)
索引。推进根 context_confirmation_id 保持 NOT NULL：临时起点也必须有确认。

downgrade 在存在 source_kind='provisional' 行时拒绝执行，不破坏探索历史。

Revision ID: 20261017_exploration_start_kind
Revises: 20261017_wp_scope_stop
Create Date: 2026-10-17
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261017_exploration_start_kind"
down_revision: str | None = "20261017_wp_scope_stop"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ROOT_TABLES: tuple[tuple[str, str, str], ...] = (
    # (table, source_kind check, start-kind combination check)
    (
        "story_scene_director_roots",
        "ck_story_scene_director_root_source_kind",
        "ck_story_scene_director_root_start_kind_valid",
    ),
    (
        "story_world_progression_roots",
        "ck_story_world_progression_root_source_kind",
        "ck_story_world_progression_root_start_kind_valid",
    ),
)


def upgrade() -> None:
    for table, kind_check, start_check in _ROOT_TABLES:
        op.add_column(
            table,
            sa.Column(
                "source_kind",
                sa.String(length=16),
                nullable=False,
                server_default="scene",
            ),
        )
        op.create_check_constraint(
            kind_check,
            table,
            "source_kind IN ('scene', 'provisional')",
        )
        op.alter_column(table, "scene_id", existing_type=sa.UUID(), nullable=True)
        op.create_check_constraint(
            start_check,
            table,
            "(source_kind = 'scene') = (scene_id IS NOT NULL)",
        )
        op.create_index(
            f"ix_{table}_novel_source_created",
            table,
            ["novel_id", "source_kind", "created_at"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    for table, _kind_check, _start_check in _ROOT_TABLES:
        provisional_rows = bind.execute(
            sa.text(
                f"SELECT COUNT(*) FROM {table} "
                "WHERE source_kind = 'provisional'"
            )
        ).scalar_one()
        if provisional_rows:
            raise RuntimeError(
                f"表 {table} 存在 {provisional_rows} 条临时起点探索记录，"
                "拒绝破坏性降级；请先处理这些探索历史"
            )
    for table, kind_check, start_check in _ROOT_TABLES:
        op.drop_index(f"ix_{table}_novel_source_created", table_name=table)
        op.drop_constraint(start_check, table, type_="check")
        op.drop_constraint(kind_check, table, type_="check")
        op.alter_column(table, "scene_id", existing_type=sa.UUID(), nullable=False)
        op.drop_column(table, "source_kind")
