"""add rebuildable RAG entity appearances

Revision ID: 20260716_rag_entity_appearances
Revises: 20260716_story_outline
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision = "20260716_rag_entity_appearances"
down_revision = "20260716_story_outline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "rag_entity_appearances" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "rag_entity_appearances",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "novel_id",
            UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("entity_id", UUID(as_uuid=True), nullable=False),
        sa.Column("content_mode", sa.String(16), nullable=False),
        sa.Column("chapter_index", sa.Integer(), nullable=False),
        sa.Column("scene_id", UUID(as_uuid=True), nullable=True),
        sa.Column("occurrence_key", sa.String(80), nullable=False),
        sa.Column("source_content_hash", sa.String(64), nullable=False),
        sa.Column("chunk_count", sa.Integer(), nullable=False, server_default="1"),
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
        sa.UniqueConstraint(
            "novel_id",
            "content_mode",
            "entity_id",
            "occurrence_key",
            name="uq_rag_entity_appearance_occurrence",
        ),
    )
    op.create_index(
        "ix_rag_entity_appearances_novel_id",
        "rag_entity_appearances",
        ["novel_id"],
    )
    op.create_index(
        "ix_rag_entity_appearances_source_content_hash",
        "rag_entity_appearances",
        ["source_content_hash"],
    )
    op.create_index(
        "ix_rag_entity_appearances_entity_chapter",
        "rag_entity_appearances",
        ["novel_id", "entity_id", "chapter_index"],
    )
    op.create_index(
        "ix_rag_entity_appearances_mode_chapter",
        "rag_entity_appearances",
        ["novel_id", "content_mode", "chapter_index"],
    )
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if {"projects", "async_tasks"}.issubset(tables):
        project_rows = op.get_bind().execute(
            sa.text("SELECT id FROM projects WHERE deleted_at IS NULL")
        )
        tasks = sa.table(
            "async_tasks",
            sa.column("id", UUID(as_uuid=True)),
            sa.column("task_type", sa.String()),
            sa.column("status", sa.String()),
            sa.column("progress", sa.Float()),
            sa.column("meta", sa.JSON()),
            sa.column("result", sa.JSON()),
            sa.column("attempt", sa.Integer()),
            sa.column("max_attempts", sa.Integer()),
            sa.column("recovery_policy", sa.String()),
        )
        for project_id in project_rows.scalars():
            op.get_bind().execute(
                tasks.insert().values(
                    id=uuid.uuid4(),
                    task_type="rag_reannotate_entities",
                    status="pending",
                    progress=0.0,
                    meta={"novel_id": str(project_id)},
                    result={},
                    attempt=0,
                    max_attempts=2,
                    recovery_policy="auto_requeue",
                )
            )


def downgrade() -> None:
    if "async_tasks" in sa.inspect(op.get_bind()).get_table_names():
        op.execute(
            sa.text(
                "DELETE FROM async_tasks "
                "WHERE task_type = 'rag_reannotate_entities' "
                "AND status IN ('pending', 'running')"
            )
        )
    op.drop_table("rag_entity_appearances")
