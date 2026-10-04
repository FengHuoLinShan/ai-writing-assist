"""Add world edit-history metadata columns and the revision notes table.

Revision ID: 20261005_world_revision_metadata
Revises: 20261004_image_reuse_spreadsheet_merge

世界编辑历史（路线图阶段 0）的数据库合同：

- entity_revisions / world_bible_page_revisions / map_atlas_revisions 三张修订表
  新增 ``writing_chapter_index``（保存时的写作进度）和 ``change_summary``
  （改动字段摘要），并补 ``(novel_id, created_at, id)`` 复合索引。
- 重建 ``protect_map_revision_content``，把两列新元数据纳入地图修订的内容保护。
- 新表 ``world_revision_notes``：实体/页面/地图修订的事后补写备注。
  ``revision_id`` 不设外键（一列按 ``target_kind`` 指向三张修订表），
  归属校验在服务层完成。
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision = "20261005_world_revision_metadata"
down_revision = "20261004_image_reuse_spreadsheet_merge"
branch_labels = None
depends_on = None

# 三张修订表共享的新列与索引。
_REVISION_TABLES = (
    "entity_revisions",
    "world_bible_page_revisions",
    "map_atlas_revisions",
)

_MAP_TRIGGER_FUNCTION = """
        CREATE FUNCTION protect_map_revision_content() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
          IF ROW(NEW.novel_id, NEW.node_id, NEW.base_revision_id, NEW.document::jsonb,
                 NEW.geometry_hash, NEW.problems::jsonb, NEW.confirmation_id,
                 NEW.context_fingerprint, NEW.task_id, NEW.created_at,
                 NEW.writing_chapter_index, NEW.change_summary::jsonb)
             IS DISTINCT FROM
             ROW(OLD.novel_id, OLD.node_id, OLD.base_revision_id, OLD.document::jsonb,
                 OLD.geometry_hash, OLD.problems::jsonb, OLD.confirmation_id,
                 OLD.context_fingerprint, OLD.task_id, OLD.created_at,
                 OLD.writing_chapter_index, OLD.change_summary::jsonb) THEN
            RAISE EXCEPTION 'map revision content is immutable';
          END IF;
          RETURN NEW;
        END $$;
"""

_MAP_TRIGGER_FUNCTION_OLD = """
        CREATE FUNCTION protect_map_revision_content() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
          IF ROW(NEW.novel_id, NEW.node_id, NEW.base_revision_id, NEW.document::jsonb,
                 NEW.geometry_hash, NEW.problems::jsonb, NEW.confirmation_id,
                 NEW.context_fingerprint, NEW.task_id, NEW.created_at)
             IS DISTINCT FROM
             ROW(OLD.novel_id, OLD.node_id, OLD.base_revision_id, OLD.document::jsonb,
                 OLD.geometry_hash, OLD.problems::jsonb, OLD.confirmation_id,
                 OLD.context_fingerprint, OLD.task_id, OLD.created_at) THEN
            RAISE EXCEPTION 'map revision content is immutable';
          END IF;
          RETURN NEW;
        END $$;
"""


def _recreate_map_trigger(function_body: str) -> None:
    op.execute("DROP TRIGGER IF EXISTS map_revision_immutable ON map_atlas_revisions")
    op.execute("DROP FUNCTION IF EXISTS protect_map_revision_content()")
    op.execute(function_body)
    op.execute(
        "CREATE TRIGGER map_revision_immutable BEFORE UPDATE ON map_atlas_revisions "
        "FOR EACH ROW EXECUTE FUNCTION protect_map_revision_content()"
    )


def upgrade() -> None:
    for table in _REVISION_TABLES:
        op.add_column(
            table,
            sa.Column(
                "writing_chapter_index",
                sa.Integer(),
                nullable=True,
                comment="保存时的写作进度（最大已有正文的章节号；0=尚无正文，NULL=旧记录）",
            ),
        )
        op.add_column(
            table,
            sa.Column(
                "change_summary",
                sa.JSON(),
                nullable=True,
                comment="改动字段摘要 JSON",
            ),
        )
        op.create_check_constraint(
            f"ck_{table}_writing_chapter_index_nonneg",
            table,
            "writing_chapter_index IS NULL OR writing_chapter_index >= 0",
        )
        op.create_index(
            f"ix_{table}_novel_created",
            table,
            ["novel_id", "created_at", "id"],
        )

    op.alter_column(
        "entity_revisions",
        "revision_reason",
        existing_type=sa.String(32),
        comment=(
            "快照原因（实际写入路径）：manual_update/manual_delete/"
            "manual_promote/focused_completion/rollback/redundant_alias_resolution/"
            "focused_completion_rollback/spreadsheet_migration_rollback；"
            "ai_import 仅为列默认值，生产代码不显式写入"
        ),
    )

    _recreate_map_trigger(_MAP_TRIGGER_FUNCTION)

    op.create_table(
        "world_revision_notes",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "novel_id",
            UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("target_kind", sa.String(16), nullable=False),
        sa.Column("revision_id", UUID(as_uuid=True), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.timezone("utc", sa.func.now()),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=True,
            server_default=sa.func.timezone("utc", sa.func.now()),
        ),
        sa.CheckConstraint(
            "target_kind IN ('entity', 'page', 'map')",
            name="ck_world_revision_notes_target_kind",
        ),
        sa.UniqueConstraint(
            "novel_id",
            "target_kind",
            "revision_id",
            name="uq_world_revision_notes_target",
        ),
        comment="世界修订备注（事后补写，不进入快照/摘要/Canon receipt）",
    )
    op.create_index(
        "ix_world_revision_notes_novel_id", "world_revision_notes", ["novel_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_world_revision_notes_novel_id", table_name="world_revision_notes")
    op.drop_table("world_revision_notes")

    _recreate_map_trigger(_MAP_TRIGGER_FUNCTION_OLD)

    op.alter_column(
        "entity_revisions",
        "revision_reason",
        existing_type=sa.String(32),
        comment="快照原因：ai_import/manual_edit/rollback/batch_update",
    )

    for table in reversed(_REVISION_TABLES):
        op.drop_index(f"ix_{table}_novel_created", table_name=table)
        op.drop_constraint(
            f"ck_{table}_writing_chapter_index_nonneg",
            table_name=table,
            type_="check",
        )
        op.drop_column(table, "change_summary")
        op.drop_column(table, "writing_chapter_index")
