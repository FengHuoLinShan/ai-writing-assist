"""Add versioned RP source context bindings.

Revision ID: 20260901_rp_source_context
Revises: 20260827_project_author_tasks
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260901_rp_source_context"
down_revision = "20260827_project_author_tasks"
branch_labels = None
depends_on = None


def _uuid():
    return sa.CHAR(36).with_variant(postgresql.UUID(as_uuid=True), "postgresql")


def _json():
    return sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    guid = _uuid()
    op.execute("DROP INDEX IF EXISTS uq_rag_chunks_chapter_text_key")
    op.execute(
        """
        CREATE UNIQUE INDEX uq_rag_chunks_chapter_text_key
        ON rag_chunks (
            novel_id, source_type, content_mode, source_id,
            chapter_index, chunk_index, index_version
        )
        WHERE source_type = 'chapter_text'
          AND source_id IS NOT NULL
          AND chapter_index IS NOT NULL
          AND chunk_index IS NOT NULL
        """
    )
    op.add_column(
        "import_records",
        sa.Column(
            "import_kind",
            sa.String(32),
            nullable=False,
            server_default="manuscript",
        ),
    )
    op.create_check_constraint(
        "ck_import_records_import_kind",
        "import_records",
        "import_kind IN ('manuscript', 'source_revision')",
    )
    op.drop_index("uq_import_records_done_file_name", table_name="import_records")
    op.create_index(
        "uq_import_records_done_file_name",
        "import_records",
        ["novel_id", "file_name"],
        unique=True,
        postgresql_where=sa.text("status = 'done' AND import_kind = 'manuscript'"),
        sqlite_where=sa.text("status = 'done' AND import_kind = 'manuscript'"),
    )
    op.create_table(
        "interaction_source_revisions",
        sa.Column("id", guid, nullable=False),
        sa.Column("source_novel_id", guid, nullable=False),
        sa.Column("owner_id", guid, nullable=False),
        sa.Column("parent_revision_id", guid, nullable=True),
        sa.Column("import_record_id", guid, nullable=True),
        sa.Column("workflow_id", guid, nullable=True),
        sa.Column("task_id", guid, nullable=True),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("source_manifest", _json(), nullable=False),
        sa.Column("anchor_manifest", _json(), nullable=False),
        sa.Column("reference_manifest", _json(), nullable=False),
        sa.Column("ambiguities", _json(), nullable=False),
        sa.Column("resolutions", _json(), nullable=False),
        sa.Column("readiness_summary", _json(), nullable=False),
        sa.Column("manifest_hash", sa.String(64), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=True),
        sa.Column("ready_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=True,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "status IN ('organizing', 'needs_confirmation', 'ready', 'failed')",
            name="ck_interaction_source_revision_status",
        ),
        sa.CheckConstraint(
            "status != 'ready' OR fingerprint IS NOT NULL",
            name="ck_interaction_source_ready_fingerprint",
        ),
        sa.ForeignKeyConstraint(["source_novel_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["parent_revision_id"],
            ["interaction_source_revisions.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["import_record_id"], ["import_records.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["workflow_id"], ["import_workflow_runs.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["task_id"], ["async_tasks.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_novel_id",
            "version_number",
            name="uq_interaction_source_revision_version",
        ),
        sa.UniqueConstraint(
            "source_novel_id",
            "manifest_hash",
            name="uq_interaction_source_revision_manifest",
        ),
    )
    op.create_index(
        "ix_interaction_source_revision_owner_status",
        "interaction_source_revisions",
        ["owner_id", "status", "created_at"],
    )
    for column in ("source_novel_id", "owner_id", "task_id", "status"):
        op.create_index(
            f"ix_interaction_source_revisions_{column}",
            "interaction_source_revisions",
            [column],
        )

    op.add_column(
        "interaction_journeys", sa.Column("source_revision_id", guid, nullable=True)
    )
    op.add_column("interaction_journeys", sa.Column("source_anchor_key", sa.String(64)))
    for column in ("source_anchor", "player_identity", "reference_policy"):
        op.add_column(
            "interaction_journeys",
            sa.Column(column, _json(), nullable=False, server_default="{}"),
        )
    op.add_column(
        "interaction_journeys",
        sa.Column(
            "source_context_epoch", sa.Integer(), nullable=False, server_default="0"
        ),
    )
    op.create_foreign_key(
        "fk_interaction_journey_source_revision",
        "interaction_journeys",
        "interaction_source_revisions",
        ["source_revision_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_interaction_journeys_source_revision_id",
        "interaction_journeys",
        ["source_revision_id"],
    )

    op.add_column(
        "interaction_generation_attempts",
        sa.Column("source_revision_id", guid, nullable=True),
    )
    op.add_column(
        "interaction_generation_attempts",
        sa.Column(
            "started_source_context_epoch",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "interaction_generation_attempts",
        sa.Column("source_context_snapshot_id", guid, nullable=True),
    )
    op.add_column(
        "interaction_generation_attempts",
        sa.Column("source_context_fingerprint", sa.String(64), nullable=True),
    )
    op.add_column(
        "interaction_generation_attempts",
        sa.Column("reference_trace", _json(), nullable=False, server_default="[]"),
    )
    op.create_foreign_key(
        "fk_interaction_attempt_source_revision",
        "interaction_generation_attempts",
        "interaction_source_revisions",
        ["source_revision_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_interaction_attempt_context_snapshot",
        "interaction_generation_attempts",
        "context_snapshots",
        ["source_context_snapshot_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_interaction_attempts_source_revision_id",
        "interaction_generation_attempts",
        ["source_revision_id"],
    )

    op.add_column(
        "context_snapshots", sa.Column("consumer_novel_id", guid, nullable=True)
    )
    op.create_foreign_key(
        "fk_context_snapshots_consumer_project",
        "context_snapshots",
        "projects",
        ["consumer_novel_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_context_snapshots_consumer_novel_id",
        "context_snapshots",
        ["consumer_novel_id"],
    )
    op.create_index(
        "ix_context_snapshots_consumer_task",
        "context_snapshots",
        ["consumer_novel_id", "task_id"],
    )
    op.create_index(
        "ix_rag_chunks_novel_draft_chapter_order",
        "rag_chunks",
        ["novel_id", "source_id", "chapter_index", "chunk_index", "content_mode"],
    )


def downgrade() -> None:
    op.drop_index("ix_rag_chunks_novel_draft_chapter_order", table_name="rag_chunks")
    op.execute("DROP INDEX IF EXISTS uq_rag_chunks_chapter_text_key")
    # 旧唯一键不含 source_id,而本版本之后同一章节会按 draft 并存多份 chunk;
    # 迁移层无法安全判定哪一份是当前稿,存在并存数据时明确失败而不是盲删。
    duplicate_drafts = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT 1 FROM rag_chunks "
                "WHERE source_type = 'chapter_text' "
                "  AND chapter_index IS NOT NULL "
                "  AND chunk_index IS NOT NULL "
                "GROUP BY novel_id, source_type, content_mode, "
                "  chapter_index, chunk_index, index_version "
                "HAVING COUNT(*) > 1 LIMIT 1"
            )
        )
        .first()
    )
    if duplicate_drafts:
        raise RuntimeError(
            "multiple chapter_text draft versions coexist in rag_chunks; "
            "rebuild the search index before downgrading this migration"
        )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_rag_chunks_chapter_text_key
        ON rag_chunks (
            novel_id, source_type, content_mode,
            chapter_index, chunk_index, index_version
        )
        WHERE source_type = 'chapter_text'
          AND chapter_index IS NOT NULL
          AND chunk_index IS NOT NULL
        """
    )
    op.drop_index("ix_context_snapshots_consumer_task", table_name="context_snapshots")
    op.drop_index(
        "ix_context_snapshots_consumer_novel_id", table_name="context_snapshots"
    )
    op.drop_constraint(
        "fk_context_snapshots_consumer_project",
        "context_snapshots",
        type_="foreignkey",
    )
    op.drop_column("context_snapshots", "consumer_novel_id")

    op.drop_constraint(
        "fk_interaction_attempt_context_snapshot",
        "interaction_generation_attempts",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_interaction_attempt_source_revision",
        "interaction_generation_attempts",
        type_="foreignkey",
    )
    op.drop_index(
        "ix_interaction_attempts_source_revision_id",
        table_name="interaction_generation_attempts",
    )
    for column in (
        "reference_trace",
        "source_context_fingerprint",
        "source_context_snapshot_id",
        "started_source_context_epoch",
        "source_revision_id",
    ):
        op.drop_column("interaction_generation_attempts", column)

    op.drop_constraint(
        "fk_interaction_journey_source_revision",
        "interaction_journeys",
        type_="foreignkey",
    )
    op.drop_index(
        "ix_interaction_journeys_source_revision_id",
        table_name="interaction_journeys",
    )
    for column in (
        "source_context_epoch",
        "reference_policy",
        "player_identity",
        "source_anchor",
        "source_anchor_key",
        "source_revision_id",
    ):
        op.drop_column("interaction_journeys", column)

    for column in ("status", "task_id", "owner_id", "source_novel_id"):
        op.drop_index(
            f"ix_interaction_source_revisions_{column}",
            table_name="interaction_source_revisions",
        )
    op.drop_index(
        "ix_interaction_source_revision_owner_status",
        table_name="interaction_source_revisions",
    )
    op.drop_table("interaction_source_revisions")
    op.drop_index("uq_import_records_done_file_name", table_name="import_records")
    # source_revision 记录是本特性的内部记账,随 downgrade 一并移除,
    # 否则旧谓词(不含 import_kind)的唯一索引会被同 file_name 的重复行卡住。
    op.execute(
        sa.text(
            "DELETE FROM import_records "
            "WHERE status = 'done' AND import_kind = 'source_revision'"
        )
    )
    op.create_index(
        "uq_import_records_done_file_name",
        "import_records",
        ["novel_id", "file_name"],
        unique=True,
        postgresql_where=sa.text("status = 'done'"),
        sqlite_where=sa.text("status = 'done'"),
    )
    op.drop_constraint("ck_import_records_import_kind", "import_records", type_="check")
    op.drop_column("import_records", "import_kind")
