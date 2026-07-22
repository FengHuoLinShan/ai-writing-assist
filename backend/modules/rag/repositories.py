"""
RAG 数据访问层

封装 rag_chunks 表的所有数据库操作和多种检索方式。
提供精确检索、关键词检索和向量检索（预留接口）。
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Sequence

from sqlalchemy import Float, and_, case, delete, exists, func, or_, select, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer
from sqlalchemy.sql.elements import ColumnElement

from infrastructure.llm.redaction import redact_diagnostic
from modules.rag.models import RagChunk, RagEntityAppearance, RagIndexState
from modules.rag.schemas import RagChunkCreate
from modules.rag.scoring import keyword_query_terms
from shared.constants import DEFAULT_PAGE_SIZE


class RagChunkRepository:
    def _json_array_contains_all(
        self,
        db: AsyncSession,
        column: ColumnElement,
        values: list[str],
    ) -> ColumnElement[bool]:
        if not values:
            from sqlalchemy import true

            return true()
        bind = db.get_bind()
        if bind.dialect.name == "postgresql":
            return column.cast(JSONB).contains(values)
        return and_(*(column.contains(value) for value in values))

    @staticmethod
    def _parse_scene_id(scene_id: str | None) -> uuid.UUID | None:
        return uuid.UUID(str(scene_id)) if scene_id else None

    @staticmethod
    def _parse_optional_uuid(value: str | None) -> uuid.UUID | None:
        return uuid.UUID(str(value)) if value else None

    @staticmethod
    def _append_visible_until_filter(
        conditions: list[ColumnElement[bool]],
        visible_until_chapter: int | None,
    ) -> None:
        if visible_until_chapter is None:
            return
        conditions.append(
            or_(
                RagChunk.chapter_index <= visible_until_chapter,
                RagChunk.chapter_index.is_(None),
            )
        )

    # ============================================================
    # 基础 CRUD
    # ============================================================

    async def create(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        data: RagChunkCreate,
    ) -> RagChunk:
        """创建 RAG 片段"""
        chunk = self._build_chunk(novel_id, data)
        db.add(chunk)
        await db.flush()
        return chunk

    async def create_many(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        items: Sequence[RagChunkCreate],
    ) -> list[RagChunk]:
        """批量创建 RAG 片段，并用一次 flush 分配主键。"""
        chunks = [self._build_chunk(novel_id, data) for data in items]
        if not chunks:
            return []
        db.add_all(chunks)
        await db.flush()
        return chunks

    async def replace_chapter_chunks(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        *,
        source_type: str,
        chapter_index: int,
        items: Sequence[RagChunkCreate],
        content_mode: str = "canonical",
    ) -> list[RagChunk]:
        """Replace one chapter/source chunk stream with idempotent keyed upserts."""
        if not items:
            await self.delete_by_chapter(
                db,
                novel_id,
                source_type,
                chapter_index,
                content_mode=content_mode,
            )
            return []

        for item in items:
            if item.source_type != source_type:
                raise ValueError(
                    "RAG chunk source_type must match replacement source_type"
                )
            if item.chapter_index != chapter_index:
                raise ValueError("RAG chunk chapter_index must match replacement chapter")
            if item.chunk_index is None:
                raise ValueError(
                    "RAG chunk chunk_index is required for idempotent replace"
                )
            if not item.index_version.strip():
                raise ValueError("RAG chunk index_version is required")
            if item.content_mode != items[0].content_mode:
                raise ValueError(
                    "RAG chapter replacement requires one content_mode"
                )

        source_hashes = {
            item.source_content_hash for item in items if item.source_content_hash
        }
        if len(source_hashes) > 1:
            raise ValueError(
                "RAG chapter replacement requires one source_content_hash"
            )
        current_source_hash = next(iter(source_hashes), None)

        await self._lock_chapter_chunks(db, novel_id, source_type, chapter_index)

        old_scene_ids = (
            await self._list_chapter_scene_ids(
                db,
                novel_id,
                source_type=source_type,
                chapter_index=chapter_index,
                content_mode=items[0].content_mode,
            )
            if source_type == "chapter_text"
            else set()
        )

        rows = [self._chunk_row(novel_id, item) for item in items]
        await self._upsert_chapter_chunk_rows(db, rows)

        current_chunk_indices = list(
            dict.fromkeys(int(item.chunk_index or 0) for item in items)
        )
        index_versions = list(dict.fromkeys(item.index_version for item in items))
        stale_stmt = delete(RagChunk).where(
            RagChunk.novel_id == novel_id,
            RagChunk.source_type == source_type,
            RagChunk.chapter_index == chapter_index,
            RagChunk.content_mode == items[0].content_mode,
            or_(
                RagChunk.index_version.notin_(index_versions),
                RagChunk.chunk_index.is_(None),
                RagChunk.chunk_index.notin_(current_chunk_indices),
            ),
        )
        await db.execute(stale_stmt)
        if source_type == "chapter_text":
            await self.replace_entity_appearances(
                db,
                novel_id,
                chapter_index=chapter_index,
                content_mode=items[0].content_mode,
                chunks=items,
                affected_scene_ids=old_scene_ids,
                current_source_hash=current_source_hash,
            )
        await db.flush()
        return await self.find_by_chapter(
            db,
            novel_id,
            chapter_index,
            source_type=source_type,
            content_mode=items[0].content_mode,
        )

    def _build_chunk(
        self,
        novel_id: uuid.UUID,
        data: RagChunkCreate,
    ) -> RagChunk:
        return RagChunk(**self._chunk_row(novel_id, data))

    def _chunk_row(
        self,
        novel_id: uuid.UUID,
        data: RagChunkCreate,
    ) -> dict:
        return {
            "novel_id": novel_id,
            "source_type": data.source_type,
            "source_id": uuid.UUID(hex=data.source_id) if data.source_id else None,
            "content_mode": data.content_mode,
            "source_content_hash": data.source_content_hash,
            "chapter_index": data.chapter_index,
            "chunk_index": data.chunk_index,
            "start_offset": data.start_offset,
            "end_offset": data.end_offset,
            "char_count": data.char_count,
            "text": data.text,
            "summary": data.summary,
            "entity_ids": data.entity_ids or [],
            "character_ids": data.character_ids or [],
            "thread_ids": data.thread_ids or [],
            "scene_id": self._parse_optional_uuid(data.scene_id),
            "scene_span_id": self._parse_optional_uuid(data.scene_span_id),
            "visibility": data.visibility or "author_only",
            "importance": data.importance if data.importance is not None else 0.5,
            "index_version": data.index_version,
            "embedding_status": data.embedding_status or "pending",
            "embedding_error": data.embedding_error,
            "index_warnings": data.index_warnings or [],
            "meta": data.meta or {},
        }

    async def _lock_chapter_chunks(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        source_type: str,
        chapter_index: int,
    ) -> None:
        bind = db.get_bind()
        if bind is not None and bind.dialect.name == "postgresql":
            await db.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                {"key": f"rag_chunks:{novel_id}:{source_type}:{chapter_index}"},
            )

    async def lock_chapter_chunks(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        chapter_index: int,
    ) -> None:
        """Share the chapter replacement fence with lightweight reannotation."""
        await self._lock_chapter_chunks(
            db,
            novel_id,
            "chapter_text",
            chapter_index,
        )

    async def _list_chapter_scene_ids(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        *,
        source_type: str,
        chapter_index: int,
        content_mode: str,
    ) -> set[uuid.UUID]:
        result = await db.execute(
            select(RagChunk.scene_id)
            .where(
                RagChunk.novel_id == novel_id,
                RagChunk.source_type == source_type,
                RagChunk.chapter_index == chapter_index,
                RagChunk.content_mode == content_mode,
                RagChunk.scene_id.is_not(None),
            )
            .distinct()
        )
        return {scene_id for scene_id in result.scalars().all() if scene_id is not None}

    async def _upsert_chapter_chunk_rows(
        self,
        db: AsyncSession,
        rows: list[dict],
    ) -> None:
        bind = db.get_bind()
        dialect_name = bind.dialect.name if bind is not None else ""
        if dialect_name == "postgresql":
            # Some demo/dev databases predate the partial unique indexes required
            # by ON CONFLICT. The caller already holds a per-chapter advisory lock,
            # so a manual upsert is safe and keeps publish_chapter recoverable.
            await self._manual_upsert_chapter_chunk_rows(db, rows)
            return
        if dialect_name == "sqlite":
            await self._manual_upsert_chapter_chunk_rows(db, rows)
            return
        await self._manual_upsert_chapter_chunk_rows(db, rows)

    async def _manual_upsert_chapter_chunk_rows(
        self,
        db: AsyncSession,
        rows: list[dict],
    ) -> None:
        if not rows:
            return

        # Preserve the old row-by-row/autoflush behavior for duplicate input
        # keys: the last item updates the row created or matched by the first.
        rows_by_key: dict[tuple, dict] = {}
        for row in rows:
            rows_by_key[self._manual_upsert_key_from_row(row)] = row

        stmt = select(RagChunk).where(
            RagChunk.novel_id.in_({row["novel_id"] for row in rows}),
            RagChunk.source_type.in_({row["source_type"] for row in rows}),
            RagChunk.chapter_index.in_({row["chapter_index"] for row in rows}),
            RagChunk.index_version.in_({row["index_version"] for row in rows}),
            RagChunk.content_mode.in_({row["content_mode"] for row in rows}),
        )
        result = await db.execute(stmt)
        existing_by_key: dict[tuple, list[RagChunk]] = defaultdict(list)
        for chunk in result.scalars().all():
            existing_by_key[self._manual_upsert_key_from_chunk(chunk)].append(chunk)

        duplicate_ids: list[uuid.UUID] = []
        for key, row in rows_by_key.items():
            matches = existing_by_key.pop(key, [])
            if not matches:
                db.add(RagChunk(**row))
                continue
            existing = matches[0]
            for field, value in row.items():
                if field != "id":
                    setattr(existing, field, value)
            duplicate_ids.extend(chunk.id for chunk in matches[1:])
        if duplicate_ids:
            await db.execute(delete(RagChunk).where(RagChunk.id.in_(duplicate_ids)))

    @staticmethod
    def _manual_upsert_key_from_row(row: dict) -> tuple:
        source_id = row["source_id"] if row["source_type"] != "chapter_text" else None
        return (
            row["novel_id"],
            row["source_type"],
            source_id,
            row["chapter_index"],
            row["chunk_index"],
            row["index_version"],
            row["content_mode"],
        )

    @classmethod
    def _manual_upsert_key_from_chunk(cls, chunk: RagChunk) -> tuple:
        return cls._manual_upsert_key_from_row(
            {
                "novel_id": chunk.novel_id,
                "source_type": chunk.source_type,
                "source_id": chunk.source_id,
                "chapter_index": chunk.chapter_index,
                "chunk_index": chunk.chunk_index,
                "index_version": chunk.index_version,
                "content_mode": chunk.content_mode,
            }
        )

    async def get(
        self,
        db: AsyncSession,
        chunk_id: uuid.UUID,
    ) -> RagChunk | None:
        """根据 ID 获取片段"""
        stmt = select(RagChunk).where(RagChunk.id == chunk_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_multi(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        skip: int = 0,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> tuple[list[RagChunk], int]:
        """获取片段列表（分页），返回 (items, total)"""
        # 获取总数
        count_stmt = select(func.count(RagChunk.id)).where(RagChunk.novel_id == novel_id)
        count_result = await db.execute(count_stmt)
        total = count_result.scalar_one()

        # 获取分页数据
        stmt = (
            select(RagChunk)
            .where(RagChunk.novel_id == novel_id)
            .offset(skip)
            .limit(limit)
            .order_by(RagChunk.created_at.desc(), RagChunk.id.desc())
        )
        result = await db.execute(stmt)
        items: Sequence[RagChunk] = result.scalars().all()
        return list(items), total

    async def update_embedding(
        self,
        db: AsyncSession,
        chunk_id: uuid.UUID,
        embedding: list[float],
    ) -> bool:
        """更新片段的 embedding 向量

        Args:
            db: 数据库 session
            chunk_id: 片段 ID
            embedding: 浮点数向量

        Returns:
            bool — 是否成功更新
        """
        chunk = await self.get(db, chunk_id)
        if chunk is None:
            return False
        chunk.embedding = embedding  # type: ignore[assignment]
        return True

    async def mark_embedding_failed(
        self,
        db: AsyncSession,
        chunk_id: uuid.UUID,
        error: str,
    ) -> bool:
        """标记 chunk embedding 失败并截断错误信息。"""
        chunk = await self.get(db, chunk_id)
        if chunk is None:
            return False
        safe_error = redact_diagnostic(error, limit=1000)
        chunk.embedding = None
        chunk.embedding_status = "failed"
        chunk.embedding_error = safe_error
        chunk.index_warnings = [f"embedding 生成失败: {safe_error}"]
        return True

    async def delete(
        self,
        db: AsyncSession,
        chunk_id: uuid.UUID,
    ) -> bool:
        """删除片段，返回是否成功删除"""
        stmt = delete(RagChunk).where(RagChunk.id == chunk_id)
        result = await db.execute(stmt)
        await db.flush()
        return result.rowcount > 0

    async def delete_many(
        self,
        db: AsyncSession,
        chunk_ids: Sequence[uuid.UUID],
    ) -> int:
        """批量删除片段，返回删除数"""
        unique_ids = list(dict.fromkeys(chunk_ids))
        if not unique_ids:
            return 0
        stmt = delete(RagChunk).where(RagChunk.id.in_(unique_ids))
        result = await db.execute(stmt)
        await db.flush()
        return result.rowcount

    async def delete_by_novel(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
    ) -> int:
        """删除小说项目的所有片段，返回删除数"""
        stmt = delete(RagChunk).where(RagChunk.novel_id == novel_id)
        result = await db.execute(stmt)
        await db.flush()
        return result.rowcount

    async def delete_by_chapter(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        source_type: str,
        chapter_index: int,
        *,
        content_mode: str | None = None,
    ) -> int:
        """删除指定章节和来源类型的全部片段，返回删除数"""
        conditions = [
            RagChunk.novel_id == novel_id,
            RagChunk.source_type == source_type,
            RagChunk.chapter_index == chapter_index,
        ]
        if content_mode is not None:
            conditions.append(RagChunk.content_mode == content_mode)
        stmt = delete(RagChunk).where(*conditions)
        result = await db.execute(stmt)
        if source_type == "chapter_text":
            appearance_conditions = [
                RagEntityAppearance.novel_id == novel_id,
                RagEntityAppearance.chapter_index == chapter_index,
            ]
            if content_mode is not None:
                appearance_conditions.append(
                    RagEntityAppearance.content_mode == content_mode
                )
            await db.execute(
                delete(RagEntityAppearance).where(*appearance_conditions)
            )
        await db.flush()
        return result.rowcount

    async def replace_entity_appearances(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        *,
        chapter_index: int,
        content_mode: str,
        chunks: Sequence[RagChunkCreate] | Sequence[RagChunk],
        affected_scene_ids: set[uuid.UUID] | None = None,
        current_source_hash: str | None = None,
    ) -> None:
        """Replace one chapter fallback plus globally deduplicated affected Scenes."""
        source_hashes = {
            str(getattr(chunk, "source_content_hash", "") or "") for chunk in chunks
        }
        source_hashes.discard("")
        if current_source_hash is None:
            if len(source_hashes) > 1:
                raise ValueError(
                    "RAG appearance replacement requires one source_content_hash"
                )
            current_source_hash = next(iter(source_hashes), "")

        scene_ids = set(affected_scene_ids or set())
        for chunk in chunks:
            raw_scene_id = getattr(chunk, "scene_id", None)
            try:
                if raw_scene_id:
                    scene_ids.add(uuid.UUID(str(raw_scene_id)))
            except (TypeError, ValueError):
                continue

        await db.execute(
            delete(RagEntityAppearance).where(
                RagEntityAppearance.novel_id == novel_id,
                RagEntityAppearance.chapter_index == chapter_index,
                RagEntityAppearance.content_mode == content_mode,
                RagEntityAppearance.scene_id.is_(None),
            )
        )
        selected_chunks: list[RagChunkCreate | RagChunk] = [
            chunk
            for chunk in chunks
            if str(getattr(chunk, "source_content_hash", "") or "")
            == current_source_hash
        ]
        if scene_ids:
            await db.execute(
                delete(RagEntityAppearance).where(
                    RagEntityAppearance.novel_id == novel_id,
                    RagEntityAppearance.content_mode == content_mode,
                    RagEntityAppearance.scene_id.in_(scene_ids),
                )
            )
            fresh_hashes = await self.list_fresh_index_hashes(
                db,
                novel_id,
                content_mode=content_mode,
            )
            fresh_hashes[(chapter_index, content_mode)] = current_source_hash
            scene_chunks = await self._list_chunks_for_scenes(
                db,
                novel_id,
                content_mode=content_mode,
                scene_ids=scene_ids,
            )
            selected_chunks.extend(
                chunk
                for chunk in scene_chunks
                if chunk.chapter_index is not None
                and chunk.chapter_index != chapter_index
                and chunk.source_content_hash
                == fresh_hashes.get((chunk.chapter_index, content_mode))
            )
        self._add_entity_appearance_rows(db, novel_id, selected_chunks)
        await db.flush()

    async def replace_project_entity_appearances(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        *,
        chunks: Sequence[RagChunk],
    ) -> None:
        """Atomically replace a project's global Scene/chapter occurrence index."""
        await db.execute(
            delete(RagEntityAppearance).where(
                RagEntityAppearance.novel_id == novel_id
            )
        )
        self._add_entity_appearance_rows(db, novel_id, chunks)
        await db.flush()

    @staticmethod
    def _add_entity_appearance_rows(
        db: AsyncSession,
        novel_id: uuid.UUID,
        chunks: Sequence[RagChunkCreate] | Sequence[RagChunk],
    ) -> None:
        grouped: dict[tuple[str, uuid.UUID, str], dict] = {}
        for chunk in chunks:
            source_hash = str(getattr(chunk, "source_content_hash", "") or "")
            raw_chapter_index = getattr(chunk, "chapter_index", None)
            content_mode = str(getattr(chunk, "content_mode", "") or "")
            if not source_hash or raw_chapter_index is None or not content_mode:
                continue
            chapter_index = int(raw_chapter_index)
            raw_scene_id = getattr(chunk, "scene_id", None)
            try:
                scene_id = uuid.UUID(str(raw_scene_id)) if raw_scene_id else None
            except (TypeError, ValueError):
                scene_id = None
            occurrence_key = (
                f"scene:{scene_id}" if scene_id else f"chapter:{chapter_index}"
            )
            entity_ids = [
                *(getattr(chunk, "entity_ids", None) or []),
                *(getattr(chunk, "character_ids", None) or []),
            ]
            for raw_entity_id in dict.fromkeys(str(item) for item in entity_ids):
                try:
                    entity_id = uuid.UUID(raw_entity_id)
                except (TypeError, ValueError):
                    continue
                key = (content_mode, entity_id, occurrence_key)
                row = grouped.get(key)
                if row is None:
                    grouped[key] = {
                        "entity_id": entity_id,
                        "content_mode": content_mode,
                        "chapter_index": chapter_index,
                        "scene_id": scene_id,
                        "occurrence_key": occurrence_key,
                        "source_content_hash": source_hash,
                        "chunk_count": 1,
                    }
                    continue
                row["chunk_count"] += 1
                if chapter_index > row["chapter_index"]:
                    row["chapter_index"] = chapter_index
                    row["source_content_hash"] = source_hash
        if grouped:
            db.add_all(
                [
                    RagEntityAppearance(novel_id=novel_id, **row)
                    for row in grouped.values()
                ]
            )

    async def _list_chunks_for_scenes(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        *,
        content_mode: str,
        scene_ids: set[uuid.UUID],
    ) -> list[RagChunk]:
        if not scene_ids:
            return []
        result = await db.execute(
            select(RagChunk)
            .options(defer(RagChunk.embedding))
            .where(
                RagChunk.novel_id == novel_id,
                RagChunk.source_type == "chapter_text",
                RagChunk.content_mode == content_mode,
                RagChunk.scene_id.in_(scene_ids),
                RagChunk.chapter_index.is_not(None),
            )
            .order_by(RagChunk.chapter_index, RagChunk.chunk_index, RagChunk.id)
        )
        return list(result.scalars().all())

    async def list_fresh_index_hashes(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        *,
        content_mode: str | None = None,
    ) -> dict[tuple[int, str], str]:
        conditions = [
            RagIndexState.novel_id == novel_id,
            RagIndexState.status == "succeeded",
            RagIndexState.indexed_hash.is_not(None),
            RagIndexState.indexed_hash == RagIndexState.requested_hash,
        ]
        if content_mode is not None:
            conditions.append(RagIndexState.content_mode == content_mode)
        rows = (
            await db.execute(
                select(
                    RagIndexState.chapter_index,
                    RagIndexState.content_mode,
                    RagIndexState.indexed_hash,
                ).where(*conditions)
            )
        ).all()
        return {
            (chapter_index, mode): indexed_hash
            for chapter_index, mode, indexed_hash in rows
            if indexed_hash
        }

    async def list_entity_activity_rows(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
    ) -> tuple[list[RagEntityAppearance], list[RagIndexState]]:
        appearances = list(
            (
                await db.execute(
                    select(RagEntityAppearance)
                    .where(RagEntityAppearance.novel_id == novel_id)
                    .order_by(
                        RagEntityAppearance.chapter_index,
                        RagEntityAppearance.entity_id,
                        RagEntityAppearance.occurrence_key,
                    )
                )
            )
            .scalars()
            .all()
        )
        states = list(
            (
                await db.execute(
                    select(RagIndexState)
                    .where(RagIndexState.novel_id == novel_id)
                    .order_by(RagIndexState.chapter_index, RagIndexState.content_mode)
                )
            )
            .scalars()
            .all()
        )
        return appearances, states

    async def list_chapter_chunks_for_reannotation(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        *,
        chapter_index: int | None = None,
        content_mode: str | None = None,
        source_content_hash: str | None = None,
    ) -> list[RagChunk]:
        """Load chapter chunks without touching their embedding payload."""
        conditions = [
            RagChunk.novel_id == novel_id,
            RagChunk.source_type == "chapter_text",
            RagChunk.chapter_index.is_not(None),
        ]
        if chapter_index is not None:
            conditions.append(RagChunk.chapter_index == chapter_index)
        if content_mode is not None:
            conditions.append(RagChunk.content_mode == content_mode)
        if source_content_hash is not None:
            conditions.append(RagChunk.source_content_hash == source_content_hash)
        return list(
            (
                await db.execute(
                    select(RagChunk)
                    .options(defer(RagChunk.embedding))
                    .where(*conditions)
                    .order_by(
                        RagChunk.chapter_index,
                        RagChunk.content_mode,
                        RagChunk.chunk_index,
                    )
                )
            )
            .scalars()
            .all()
        )

    async def list_reannotation_keys(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
    ) -> list[tuple[int, str]]:
        rows = (
            await db.execute(
                select(RagChunk.chapter_index, RagChunk.content_mode)
                .where(
                    RagChunk.novel_id == novel_id,
                    RagChunk.source_type == "chapter_text",
                    RagChunk.chapter_index.is_not(None),
                )
                .distinct()
                .order_by(RagChunk.chapter_index, RagChunk.content_mode)
            )
        ).all()
        return [
            (int(chapter_index), str(content_mode))
            for chapter_index, content_mode in rows
        ]

    # ============================================================
    # 精确检索
    # ============================================================

    async def find_by_source(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        source_type: str,
        source_id: uuid.UUID | None = None,
    ) -> list[RagChunk]:
        """按来源类型和 ID 精确检索"""
        conditions = [
            RagChunk.novel_id == novel_id,
            RagChunk.source_type == source_type,
        ]
        if source_id is not None:
            conditions.append(RagChunk.source_id == source_id)

        stmt = select(RagChunk).where(and_(*conditions))
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def find_by_entity(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        entity_id: str,
        *,
        visibility: str | None = None,
    ) -> list[RagChunk]:
        """按关联的世界对象 ID 检索"""
        conditions = [
            RagChunk.novel_id == novel_id,
            self._json_array_contains_all(db, RagChunk.entity_ids, [entity_id]),
        ]
        if visibility is not None:
            conditions.append(RagChunk.visibility == visibility)

        stmt = (
            select(RagChunk)
            .where(and_(*conditions))
            .order_by(
                RagChunk.chapter_index.asc(),
                RagChunk.chunk_index.asc(),
                RagChunk.id.asc(),
            )
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def find_by_chapter_range(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        start_chapter: int,
        end_chapter: int,
        *,
        source_type: str = "chapter_text",
        visibility: str | None = None,
        content_mode: str = "canonical",
    ) -> list[RagChunk]:
        """按章节范围读取有序 chunk。"""
        conditions = [
            RagChunk.novel_id == novel_id,
            RagChunk.source_type == source_type,
            RagChunk.chapter_index >= start_chapter,
            RagChunk.chapter_index <= end_chapter,
            RagChunk.content_mode == content_mode,
        ]
        if visibility is not None:
            conditions.append(RagChunk.visibility == visibility)

        stmt = (
            select(RagChunk)
            .where(and_(*conditions))
            .order_by(
                RagChunk.chapter_index.asc(),
                RagChunk.chunk_index.asc(),
                RagChunk.id.asc(),
            )
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def find_by_character(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        character_id: str,
        *,
        visibility: str | None = None,
    ) -> list[RagChunk]:
        """按关联的人物 ID 检索"""
        conditions = [
            RagChunk.novel_id == novel_id,
            self._json_array_contains_all(db, RagChunk.character_ids, [character_id]),
        ]
        if visibility is not None:
            conditions.append(RagChunk.visibility == visibility)

        stmt = (
            select(RagChunk)
            .where(and_(*conditions))
            .order_by(
                RagChunk.importance.desc(),
                RagChunk.id.asc(),
            )
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def find_by_thread(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        thread_id: str,
        *,
        visibility: str | None = None,
    ) -> list[RagChunk]:
        """按关联的剧情线 ID 检索"""
        conditions = [
            RagChunk.novel_id == novel_id,
            self._json_array_contains_all(db, RagChunk.thread_ids, [thread_id]),
        ]
        if visibility is not None:
            conditions.append(RagChunk.visibility == visibility)

        stmt = (
            select(RagChunk)
            .where(and_(*conditions))
            .order_by(
                RagChunk.importance.desc(),
                RagChunk.id.asc(),
            )
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def find_by_chapter(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        chapter_index: int,
        *,
        source_type: str | None = None,
        visibility: str | None = None,
        content_mode: str | None = None,
    ) -> list[RagChunk]:
        """按章节索引检索"""
        conditions = [
            RagChunk.novel_id == novel_id,
            RagChunk.chapter_index == chapter_index,
        ]
        if source_type is not None:
            conditions.append(RagChunk.source_type == source_type)
        if visibility is not None:
            conditions.append(RagChunk.visibility == visibility)
        if content_mode is not None:
            conditions.append(RagChunk.content_mode == content_mode)

        stmt = (
            select(RagChunk)
            .where(and_(*conditions))
            .order_by(
                RagChunk.importance.desc(),
                RagChunk.chapter_index.asc(),
                RagChunk.chunk_index.asc(),
                RagChunk.id.asc(),
            )
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    # ============================================================
    # 关键词检索（文本匹配）
    # ============================================================

    async def keyword_search(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        query: str,
        *,
        entity_ids: list[str] | None = None,
        character_ids: list[str] | None = None,
        thread_ids: list[str] | None = None,
        chapter_index: int | None = None,
        scene_id: str | None = None,
        strict_scene_filter: bool = False,
        visibility: str | None = None,
        visible_until_chapter: int | None = None,
        content_mode: str = "canonical",
        limit: int = 20,
    ) -> list[RagChunk]:
        """关键词检索 — 使用简单的 SQL LIKE 文本匹配

        不依赖 PostgreSQL full-text search，保持 SQLite 兼容。
        返回按匹配度粗略排序的结果。
        """
        conditions = [
            RagChunk.novel_id == novel_id,
            RagChunk.content_mode == content_mode,
        ]

        # 构建关键词条件（OR 逻辑，匹配任意关键词即返回）
        query_terms = keyword_query_terms(query)
        keyword_rank = None
        if query_terms:
            keyword_conditions = []
            for term in query_terms:
                pattern = f"%{term}%"
                keyword_conditions.append(RagChunk.text.ilike(pattern))
            keyword_rank = sum(
                case((condition, 1), else_=0) for condition in keyword_conditions
            )
            conditions.append(or_(*keyword_conditions))

        # metadata 过滤
        if entity_ids:
            conditions.append(
                self._json_array_contains_all(db, RagChunk.entity_ids, entity_ids)
            )
        if character_ids:
            conditions.append(
                self._json_array_contains_all(db, RagChunk.character_ids, character_ids)
            )
        if thread_ids:
            conditions.append(
                self._json_array_contains_all(db, RagChunk.thread_ids, thread_ids)
            )
        if chapter_index is not None:
            conditions.append(RagChunk.chapter_index == chapter_index)
        self._append_visible_until_filter(conditions, visible_until_chapter)
        scene_uuid = self._parse_scene_id(scene_id)
        if scene_uuid is not None:
            conditions.append(RagChunk.scene_id == scene_uuid)
        elif strict_scene_filter:
            conditions.append(RagChunk.scene_id.is_not(None))
        if visibility is not None:
            conditions.append(RagChunk.visibility == visibility)

        stmt = select(RagChunk).where(and_(*conditions))
        if keyword_rank is not None:
            stmt = stmt.order_by(
                keyword_rank.desc(),
                RagChunk.importance.desc(),
                RagChunk.chapter_index.asc(),
                RagChunk.chunk_index.asc(),
                RagChunk.id.asc(),
            )
        else:
            stmt = stmt.order_by(
                RagChunk.importance.desc(),
                RagChunk.chapter_index.asc(),
                RagChunk.chunk_index.asc(),
                RagChunk.id.asc(),
            )
        stmt = stmt.limit(limit)
        result = await db.execute(stmt)
        return list(result.scalars().all())

    # ============================================================
    # 向量检索（预留接口）
    # ============================================================

    async def vector_search(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        embedding: list[float],
        *,
        entity_ids: list[str] | None = None,
        character_ids: list[str] | None = None,
        thread_ids: list[str] | None = None,
        chapter_index: int | None = None,
        scene_id: str | None = None,
        strict_scene_filter: bool = False,
        visibility: str | None = None,
        visible_until_chapter: int | None = None,
        content_mode: str = "canonical",
        top_k: int = 12,
        ef_search: int = 40,
    ) -> list[tuple[RagChunk, float]]:
        """向量检索 — pgvector <#> 内积操作符 + HNSW 索引

        L2 归一化后内积等价于余弦相似度。PostgreSQL 使用 pgvector
        原生 <#> 操作符走 HNSW 索引；SQLite 回退到 Python 层计算。

        Returns:
            list[(RagChunk, score)] — 按相似度降序排列
        """
        bind = db.get_bind()
        if bind is not None and bind.dialect.name != "postgresql":
            return await self._vector_search_python(
                db,
                novel_id,
                embedding,
                entity_ids=entity_ids,
                character_ids=character_ids,
                thread_ids=thread_ids,
                chapter_index=chapter_index,
                scene_id=scene_id,
                strict_scene_filter=strict_scene_filter,
                visibility=visibility,
                visible_until_chapter=visible_until_chapter,
                content_mode=content_mode,
                top_k=top_k,
            )

        # PostgreSQL SET does not accept bind parameters in this position.
        ef_search_value = max(1, int(ef_search))
        await db.execute(text(f"SET LOCAL hnsw.ef_search = {ef_search_value}"))
        conditions = [
            RagChunk.novel_id == novel_id,
            RagChunk.embedding.is_not(None),
            RagChunk.content_mode == content_mode,
        ]
        if entity_ids:
            conditions.append(
                self._json_array_contains_all(db, RagChunk.entity_ids, entity_ids)
            )
        if character_ids:
            conditions.append(
                self._json_array_contains_all(db, RagChunk.character_ids, character_ids)
            )
        if thread_ids:
            conditions.append(
                self._json_array_contains_all(db, RagChunk.thread_ids, thread_ids)
            )
        if chapter_index is not None:
            conditions.append(RagChunk.chapter_index == chapter_index)
        self._append_visible_until_filter(conditions, visible_until_chapter)
        scene_uuid = self._parse_scene_id(scene_id)
        if scene_uuid is not None:
            conditions.append(RagChunk.scene_id == scene_uuid)
        elif strict_scene_filter:
            conditions.append(RagChunk.scene_id.is_not(None))
        if visibility is not None:
            conditions.append(RagChunk.visibility == visibility)

        stmt = (
            select(
                RagChunk,
                RagChunk.embedding.op("<#>")(embedding).cast(Float).label("score"),
            )
            .where(and_(*conditions))
            .order_by(text("score ASC"))
            .limit(top_k)
        )
        result = await db.execute(stmt)
        rows = result.all()
        return [(row[0], -float(row[1])) for row in rows]

    async def _vector_search_python(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        embedding: list[float],
        *,
        entity_ids: list[str] | None = None,
        character_ids: list[str] | None = None,
        thread_ids: list[str] | None = None,
        chapter_index: int | None = None,
        scene_id: str | None = None,
        strict_scene_filter: bool = False,
        visibility: str | None = None,
        visible_until_chapter: int | None = None,
        content_mode: str = "canonical",
        top_k: int = 12,
    ) -> list[tuple[RagChunk, float]]:
        """SQLite 回退：Python 层计算余弦相似度"""
        import math

        conditions = [
            RagChunk.novel_id == novel_id,
            RagChunk.embedding.is_not(None),
            RagChunk.content_mode == content_mode,
        ]
        if entity_ids:
            conditions.append(
                self._json_array_contains_all(db, RagChunk.entity_ids, entity_ids)
            )
        if character_ids:
            conditions.append(
                self._json_array_contains_all(db, RagChunk.character_ids, character_ids)
            )
        if thread_ids:
            conditions.append(
                self._json_array_contains_all(db, RagChunk.thread_ids, thread_ids)
            )
        if chapter_index is not None:
            conditions.append(RagChunk.chapter_index == chapter_index)
        self._append_visible_until_filter(conditions, visible_until_chapter)
        scene_uuid = self._parse_scene_id(scene_id)
        if scene_uuid is not None:
            conditions.append(RagChunk.scene_id == scene_uuid)
        elif strict_scene_filter:
            conditions.append(RagChunk.scene_id.is_not(None))
        if visibility is not None:
            conditions.append(RagChunk.visibility == visibility)

        candidate_limit = min(max(top_k * 20, 100), 1000)
        stmt = (
            select(RagChunk)
            .where(and_(*conditions))
            .order_by(
                RagChunk.importance.desc(),
                RagChunk.updated_at.desc(),
                RagChunk.id.desc(),
            )
            .limit(candidate_limit)
        )
        result = await db.execute(stmt)
        chunks: list[RagChunk] = list(result.scalars().all())

        if not chunks:
            return []

        def _dot(a: list[float], b: list[float]) -> float:
            return sum(x * y for x, y in zip(a, b))

        def _norm(a: list[float]) -> float:
            return math.sqrt(sum(x * x for x in a))

        scored: list[tuple[RagChunk, float]] = []
        norm_q = _norm(embedding)
        for c in chunks:
            chunk_emb = c.embedding
            if isinstance(chunk_emb, list) and len(chunk_emb) == len(embedding):
                norm_c = _norm(chunk_emb)
                if norm_c > 0 and norm_q > 0:
                    sim = _dot(embedding, chunk_emb) / (norm_q * norm_c)
                    scored.append((c, max(0.0, sim)))

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]

    # ============================================================
    # 统计
    # ============================================================

    async def count_by_novel(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
    ) -> int:
        """统计小说项目的片段总数"""
        stmt = select(func.count(RagChunk.id)).where(RagChunk.novel_id == novel_id)
        result = await db.execute(stmt)
        return result.scalar_one()

    async def list_scene_mapping_rows(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        *,
        content_mode: str,
    ) -> list:
        """Load only fields required by Scene mapping coverage."""
        stmt = (
            select(
                RagChunk.id,
                RagChunk.source_id,
                RagChunk.source_content_hash,
                RagChunk.chapter_index,
                RagChunk.start_offset,
                RagChunk.end_offset,
                RagChunk.scene_id,
                RagChunk.scene_span_id,
            )
            .where(
                RagChunk.novel_id == novel_id,
                RagChunk.content_mode == content_mode,
                RagChunk.source_type == "chapter_text",
            )
            .order_by(RagChunk.chapter_index, RagChunk.chunk_index, RagChunk.id)
        )
        result = await db.execute(stmt)
        return list(result.all())

    async def has_embeddings(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
    ) -> bool:
        """该项目是否已有可用 chunk embedding。"""
        stmt = select(
            exists().where(
                RagChunk.novel_id == novel_id,
                RagChunk.embedding.is_not(None),
            )
        )
        result = await db.execute(stmt)
        return bool(result.scalar_one())

    async def get_sample_embedding_dim(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
    ) -> int | None:
        """读取已索引向量的实际维度，用于诊断配置漂移。"""
        stmt = (
            select(RagChunk.embedding)
            .where(
                RagChunk.novel_id == novel_id,
                RagChunk.embedding.is_not(None),
            )
            .limit(1)
        )
        result = await db.execute(stmt)
        embedding = result.scalar_one_or_none()
        if embedding is None:
            return None
        if isinstance(embedding, (str, bytes, bytearray, memoryview)):
            return None
        if hasattr(embedding, "shape") and embedding.shape:
            return int(embedding.shape[0])
        if hasattr(embedding, "tolist"):
            embedding = embedding.tolist()
        if isinstance(embedding, Sequence):
            return len(embedding)
        return None

    async def count_embedding_failed(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
    ) -> int:
        """统计 embedding 失败的 chunk 数。"""
        stmt = select(func.count(RagChunk.id)).where(
            RagChunk.novel_id == novel_id,
            RagChunk.embedding_status == "failed",
        )
        result = await db.execute(stmt)
        return result.scalar_one() or 0

    async def count_pending_vectorization(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
    ) -> int:
        """统计待重新向量化的 chunk 数（维度迁移后）。"""
        stmt = select(func.count(RagChunk.id)).where(
            RagChunk.novel_id == novel_id,
            RagChunk.embedding_status == "pending_vectorization",
        )
        result = await db.execute(stmt)
        return result.scalar_one() or 0

    def _embedding_retry_conditions(
        self,
        novel_id: uuid.UUID,
        statuses: list[str],
        start_chapter: int | None,
        end_chapter: int | None,
    ) -> list:
        conditions = [
            RagChunk.novel_id == novel_id,
            RagChunk.embedding_status.in_(statuses),
        ]
        if start_chapter is not None:
            conditions.append(RagChunk.chapter_index >= start_chapter)
        if end_chapter is not None:
            conditions.append(RagChunk.chapter_index <= end_chapter)
        return conditions

    async def count_retryable_embeddings(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        *,
        statuses: list[str],
        start_chapter: int | None = None,
        end_chapter: int | None = None,
    ) -> int:
        """统计可重试向量化的 chunk 数。"""
        stmt = select(func.count(RagChunk.id)).where(
            and_(
                *self._embedding_retry_conditions(
                    novel_id,
                    statuses,
                    start_chapter,
                    end_chapter,
                )
            )
        )
        result = await db.execute(stmt)
        return result.scalar_one() or 0

    async def find_embedding_retry_candidates(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        *,
        statuses: list[str],
        start_chapter: int | None = None,
        end_chapter: int | None = None,
        limit: int = 500,
    ) -> list[RagChunk]:
        """读取可重试向量化的 chunk，始终按 novel_id 隔离。"""
        stmt = (
            select(RagChunk)
            .where(
                and_(
                    *self._embedding_retry_conditions(
                        novel_id,
                        statuses,
                        start_chapter,
                        end_chapter,
                    )
                )
            )
            .order_by(
                RagChunk.chapter_index.asc(),
                RagChunk.chunk_index.asc(),
                RagChunk.id.asc(),
            )
            .limit(limit)
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def find_embedding_retry_candidate_values(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        *,
        statuses: list[str],
        start_chapter: int | None = None,
        end_chapter: int | None = None,
        limit: int = 500,
    ) -> list:
        """Read the scalar fields needed by task-only embedding retry plans.

        Returning row projections keeps the plan independent of the session
        identity map after the task checkpoint and avoids loading stale vectors
        or unrelated JSON metadata for provider calls.
        """
        stmt = (
            select(
                RagChunk.id,
                RagChunk.novel_id,
                RagChunk.text,
                RagChunk.embedding_status,
                RagChunk.source_type,
                RagChunk.source_id,
                RagChunk.source_content_hash,
                RagChunk.content_mode,
                RagChunk.chapter_index,
                RagChunk.chunk_index,
                RagChunk.index_version,
            )
            .where(
                and_(
                    *self._embedding_retry_conditions(
                        novel_id,
                        statuses,
                        start_chapter,
                        end_chapter,
                    )
                )
            )
            .order_by(
                RagChunk.chapter_index.asc(),
                RagChunk.chunk_index.asc(),
                RagChunk.id.asc(),
            )
            .limit(limit)
        )
        result = await db.execute(stmt)
        return list(result.all())

    async def find_embedding_retry_rows_by_ids_for_update(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        chunk_ids: Sequence[uuid.UUID],
    ) -> list[RagChunk]:
        """Reload one retry batch under same-novel row locks before write-back."""
        unique_ids = sorted(set(chunk_ids), key=str)
        if not unique_ids:
            return []
        stmt = (
            select(RagChunk)
            .where(
                RagChunk.novel_id == novel_id,
                RagChunk.id.in_(unique_ids),
            )
            .order_by(RagChunk.id.asc())
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())
