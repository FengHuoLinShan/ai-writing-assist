"""add scene spans and rag reader-progress fields

Revision ID: 20260709_scene_spans_rag_visibility
Revises: 20260708_security_performance_indexes
"""

import json
import uuid
from typing import Any

import sqlalchemy as sa

from alembic import op
from core.base import UUIDType

revision = "20260709_scene_spans_rag_visibility"
down_revision = "20260708_security_performance_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "scene_spans" not in tables:
        op.create_table(
            "scene_spans",
            sa.Column("id", UUIDType, primary_key=True),
            sa.Column(
                "novel_id",
                UUIDType,
                sa.ForeignKey("projects.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "scene_id",
                UUIDType,
                sa.ForeignKey("scenes.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("chapter_index", sa.Integer(), nullable=False),
            sa.Column("start_offset", sa.Integer(), nullable=True),
            sa.Column("end_offset", sa.Integer(), nullable=True),
            sa.Column("start_paragraph", sa.Integer(), nullable=True),
            sa.Column("end_paragraph", sa.Integer(), nullable=True),
            sa.Column("part_no", sa.Integer(), nullable=False),
            sa.Column("source", sa.String(32), nullable=False),
            sa.Column("status", sa.String(32), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.timezone("utc", sa.func.now()),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.timezone("utc", sa.func.now()),
            ),
            sa.UniqueConstraint(
                "novel_id",
                "scene_id",
                "part_no",
                name="uq_scene_spans_novel_scene_part",
            ),
        )

    rag_columns = {column["name"] for column in inspector.get_columns("rag_chunks")}
    if "scene_span_id" not in rag_columns:
        op.add_column(
            "rag_chunks",
            sa.Column("scene_span_id", UUIDType, nullable=True),
        )

    inspector = sa.inspect(bind)
    scene_span_indexes = {index["name"] for index in inspector.get_indexes("scene_spans")}
    rag_indexes = {index["name"] for index in inspector.get_indexes("rag_chunks")}

    if "ix_scene_spans_novel_id" not in scene_span_indexes:
        op.create_index("ix_scene_spans_novel_id", "scene_spans", ["novel_id"])
    if "ix_scene_spans_scene_id" not in scene_span_indexes:
        op.create_index("ix_scene_spans_scene_id", "scene_spans", ["scene_id"])
    if "ix_scene_spans_scene" not in scene_span_indexes:
        op.create_index("ix_scene_spans_scene", "scene_spans", ["scene_id"])
    if "ix_scene_spans_novel_chapter" not in scene_span_indexes:
        op.create_index(
            "ix_scene_spans_novel_chapter",
            "scene_spans",
            ["novel_id", "chapter_index", "part_no"],
        )
    if "ix_rag_chunks_scene_span_id" not in rag_indexes:
        op.create_index(
            "ix_rag_chunks_scene_span_id",
            "rag_chunks",
            ["scene_span_id"],
        )

    _backfill_scene_spans_if_empty(bind)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "rag_chunks" in tables:
        rag_indexes = {index["name"] for index in inspector.get_indexes("rag_chunks")}
        if "ix_rag_chunks_scene_span_id" in rag_indexes:
            op.drop_index("ix_rag_chunks_scene_span_id", table_name="rag_chunks")
        rag_columns = {column["name"] for column in inspector.get_columns("rag_chunks")}
        if "scene_span_id" in rag_columns:
            op.drop_column("rag_chunks", "scene_span_id")

    if "scene_spans" in tables:
        op.drop_table("scene_spans")


def _backfill_scene_spans_if_empty(bind) -> None:  # type: ignore[no-untyped-def]
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "scenes" not in tables or "scene_spans" not in tables:
        return
    existing = bind.execute(sa.text("SELECT COUNT(*) FROM scene_spans")).scalar() or 0
    if existing:
        return

    rows = bind.execute(
        sa.text(
            "SELECT id, novel_id, scene_chunks, source, status "
            "FROM scenes WHERE scene_chunks IS NOT NULL"
        )
    ).mappings()
    insert_rows: list[dict[str, Any]] = []
    for scene in rows:
        chunks = _coerce_chunks(scene["scene_chunks"])
        parts: list[dict[str, Any]] = []
        for raw_order, chunk in enumerate(chunks):
            if not isinstance(chunk, dict):
                continue
            chapter_index = _first_int(chunk, ("chapter_index", "chapter_id"))
            if chapter_index is None:
                continue
            parts.append(
                {
                    "chapter_index": chapter_index,
                    "start_offset": _first_int(chunk, ("start_offset", "start_pos")),
                    "end_offset": _first_int(chunk, ("end_offset", "end_pos")),
                    "start_paragraph": _first_int(chunk, ("start_paragraph",)),
                    "end_paragraph": _first_int(chunk, ("end_paragraph",)),
                    "raw_order": raw_order,
                }
            )
        parts.sort(
            key=lambda part: (
                part["chapter_index"],
                part["start_offset"] if part["start_offset"] is not None else 10**12,
                (
                    part["start_paragraph"]
                    if part["start_paragraph"] is not None
                    else 10**12
                ),
                part["raw_order"],
            )
        )
        for part_no, part in enumerate(parts):
            insert_rows.append(
                {
                    "id": str(uuid.uuid4()),
                    "novel_id": str(scene["novel_id"]),
                    "scene_id": str(scene["id"]),
                    "chapter_index": part["chapter_index"],
                    "start_offset": part["start_offset"],
                    "end_offset": part["end_offset"],
                    "start_paragraph": part["start_paragraph"],
                    "end_paragraph": part["end_paragraph"],
                    "part_no": part_no,
                    "source": scene["source"] or "manual",
                    "status": scene["status"] or "draft",
                }
            )
    if not insert_rows:
        return
    bind.execute(
        sa.text(
            """
            INSERT INTO scene_spans (
                id, novel_id, scene_id, chapter_index,
                start_offset, end_offset, start_paragraph, end_paragraph,
                part_no, source, status
            )
            VALUES (
                :id, :novel_id, :scene_id, :chapter_index,
                :start_offset, :end_offset, :start_paragraph, :end_paragraph,
                :part_no, :source, :status
            )
            """
        ),
        insert_rows,
    )


def _coerce_chunks(value: Any) -> list:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return []
        return parsed if isinstance(parsed, list) else []
    return []


def _first_int(chunk: dict[str, Any], keys: tuple[str, ...]) -> int | None:
    for key in keys:
        value = chunk.get(key)
        if value is None:
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return None
