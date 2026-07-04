"""
RAG 章节索引

IndexingService 负责把章节正文处理为 RAG chunk 并生成 embedding，
包括读取草稿、分块、角色/实体匹配、去重创建和批量 embedding 的全流程。
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable

from sqlalchemy.ext.asyncio import AsyncSession

from modules.rag.chunk_annotation import build_chunk_create
from modules.rag.chunking import ChineseNovelChunk, ChunkingService
from modules.rag.contracts import RagIndexReport
from modules.rag.embedding_writer import EmbeddingWriter
from modules.rag.models import RagChunk
from modules.rag.repositories import RagChunkRepository
from modules.rag.source_collection import (
    collect_annotation_sources,
    collect_chapter_sources,
)


class IndexingService:
    """章节索引服务。

    构造函数注入 repo 与 chunking；默认自行实例化以保持现有调用方式兼容。
    """

    def __init__(
        self,
        repo: RagChunkRepository | None = None,
        chunking: ChunkingService | None = None,
    ) -> None:
        self._repo = repo or RagChunkRepository()
        self._chunking = chunking or ChunkingService()

    async def index_chapter(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        chapter_index: int,
    ) -> int:
        """索引指定章节的正文到 RAG 库，返回创建的 chunk 数。"""
        report = await self.index_chapter_with_report(db, novel_id, chapter_index)
        return report.chunks_created

    async def index_chapter_with_report(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        chapter_index: int,
    ) -> RagIndexReport:
        """索引指定章节并返回诊断报告。"""
        started_at = time.monotonic()
        sources = await collect_chapter_sources(db, novel_id, chapter_index)
        if sources is None:
            return RagIndexReport(chapter_index=chapter_index, chunks_created=0)

        chunks = self._chunking.split_chinese_novel(sources.content)
        if not chunks:
            return RagIndexReport(chapter_index=chapter_index, chunks_created=0)

        await self._repo.delete_by_chapter(db, novel_id, "chapter_text", chapter_index)

        chunk_items = [
            build_chunk_create(
                cn_chunk,
                chapter_index=chapter_index,
                chunking=self._chunking,
                project_terms=sources.project_terms,
                entity_importance_map=sources.entity_importance_map,
                scenes_for_chapter=sources.scenes_for_chapter,
            )
            for cn_chunk in chunks
        ]
        created_chunks = await self._repo.create_many(db, novel_id, chunk_items)

        await db.flush()
        embedding_result = await EmbeddingWriter(self._repo).write_batch(
            db,
            created_chunks,
            warning_prefix="章节 embedding 失败",
        )

        from modules.rag.metrics import get_metrics

        get_metrics().record_indexing(
            chunks_created=len(created_chunks),
            embedding_failed_count=embedding_result.failed_count,
            latency_ms=(time.monotonic() - started_at) * 1000,
        )

        return RagIndexReport(
            chapter_index=chapter_index,
            chunks_created=len(created_chunks),
            warnings=embedding_result.warnings,
            embedding_failed_count=embedding_result.failed_count,
            chunks_created_ids=[str(c.id) for c in created_chunks],
        )

    async def index_chapter_incremental(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        chapter_index: int,
        old_content: str,
        new_content: str,
    ) -> RagIndexReport:
        """增量索引：仅重建变更区域的 chunk。

        使用 difflib.SequenceMatcher 识别文本变更，保留未变区域的已有 chunk。
        变更率 >= 30% 时自动回退到全量重建，避免大量碎片。
        """
        import difflib

        warnings: list[str] = []

        change_ratio = len(new_content) / max(len(old_content), 1)
        if change_ratio > 1.3 or change_ratio < 0.7:
            warnings.append(
                f"文本变更率 {abs(1 - change_ratio):.0%} >= 30%，自动回退全量重建"
            )
            return await self.index_chapter_with_report(db, novel_id, chapter_index)

        matcher = difflib.SequenceMatcher(None, old_content, new_content)
        opcodes = matcher.get_opcodes()

        old_chunks = await self._repo.find_by_chapter(db, novel_id, chapter_index)
        old_by_offset: dict[tuple[int, int], RagChunk] = {}
        for c in old_chunks:
            if c.start_offset is not None and c.end_offset is not None:
                old_by_offset[(c.start_offset, c.end_offset)] = c

        scenes_for_chapter, project_terms, entity_importance_map = (
            await collect_annotation_sources(db, novel_id, chapter_index)
        )

        created_chunks: list[RagChunk] = []
        reused_old_ids: set[uuid.UUID] = set()
        embedding_failed_count = 0

        for tag, i1, i2, j1, j2 in opcodes:
            if tag == "equal":
                for (start, end), chunk in list(old_by_offset.items()):
                    if start >= i1 and end <= i2:
                        created_chunks.append(chunk)
                        reused_old_ids.add(chunk.id)
                        old_by_offset.pop((start, end), None)

            elif tag in ("replace", "insert"):
                new_text = new_content[j1:j2]
                if not new_text.strip():
                    continue

                cn_chunks = self._chunking.split_chinese_novel(new_text)
                for cn_chunk in cn_chunks:
                    adjusted_chunk = ChineseNovelChunk(
                        chunk_index=cn_chunk.chunk_index,
                        text=cn_chunk.text,
                        start_offset=j1 + cn_chunk.start_offset,
                        end_offset=j1 + cn_chunk.end_offset,
                        char_count=cn_chunk.char_count,
                    )
                    chunk_data = build_chunk_create(
                        adjusted_chunk,
                        chapter_index=chapter_index,
                        chunking=self._chunking,
                        project_terms=project_terms,
                        entity_importance_map=entity_importance_map,
                        scenes_for_chapter=scenes_for_chapter,
                        chunk_index=len(created_chunks),
                    )
                    chunk = await self._repo.create(db, novel_id, chunk_data)
                    created_chunks.append(chunk)

        stale_chunk_ids = [
            chunk.id
            for chunk in old_by_offset.values()
            if chunk.id not in reused_old_ids
        ]
        if stale_chunk_ids:
            await self._repo.delete_many(db, stale_chunk_ids)

        await db.flush()

        new_chunks = [c for c in created_chunks if c.embedding_status == "pending"]
        if new_chunks:
            embedding_result = await EmbeddingWriter(self._repo).write_batch(
                db,
                new_chunks,
                warning_prefix="增量 embedding 失败",
            )
            warnings.extend(embedding_result.warnings)
            embedding_failed_count = embedding_result.failed_count

        return RagIndexReport(
            chapter_index=chapter_index,
            chunks_created=len(created_chunks),
            warnings=warnings,
            embedding_failed_count=embedding_failed_count,
            chunks_created_ids=[str(c.id) for c in created_chunks],
        )

    async def retry_embeddings(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        *,
        start_chapter: int | None = None,
        end_chapter: int | None = None,
        statuses: list[str] | None = None,
        progress_callback: Callable[[float], None] | None = None,
    ) -> dict:
        """Retry failed or pending chunk embeddings for one novel."""
        started_at = time.monotonic()
        allowed_statuses = {"failed", "pending_vectorization"}
        retry_statuses = [
            status for status in (statuses or ["failed", "pending_vectorization"])
            if status in allowed_statuses
        ]
        if not retry_statuses:
            retry_statuses = ["failed", "pending_vectorization"]

        initial_total = await self._repo.count_retryable_embeddings(
            db,
            novel_id,
            statuses=retry_statuses,
            start_chapter=start_chapter,
            end_chapter=end_chapter,
        )

        total = initial_total
        succeeded = 0
        failed = 0
        warnings: list[str] = []

        from modules.rag.metrics import get_metrics

        if initial_total == 0:
            if progress_callback is not None:
                progress_callback(1.0)
            await db.flush()
            get_metrics().record_embedding_retry(
                total=0,
                failed=0,
                latency_ms=(time.monotonic() - started_at) * 1000,
            )
            return {
                "total": 0,
                "succeeded": 0,
                "failed": 0,
                "remaining_retryable_count": 0,
                "warnings": [],
            }

        embedding_writer = EmbeddingWriter(self._repo)
        while True:
            candidates = await self._repo.find_embedding_retry_candidates(
                db,
                novel_id,
                statuses=retry_statuses,
                start_chapter=start_chapter,
                end_chapter=end_chapter,
            )
            if not candidates:
                break

            embedding_result = await embedding_writer.write_batch(
                db,
                candidates,
                warning_prefix="embedding 重试失败",
            )
            if embedding_result.failed_count == 0:
                succeeded += len(candidates)
                if progress_callback is not None:
                    progress_callback(min(1.0, succeeded / max(initial_total, 1)))
                continue
            failed += embedding_result.failed_count
            warnings.extend(embedding_result.warnings)
            break

        remaining_retryable_count = await self._repo.count_retryable_embeddings(
            db,
            novel_id,
            statuses=retry_statuses,
            start_chapter=start_chapter,
            end_chapter=end_chapter,
        )
        if remaining_retryable_count == 0:
            if progress_callback is not None:
                progress_callback(1.0)
            await db.flush()

        get_metrics().record_embedding_retry(
            total=total,
            failed=failed,
            latency_ms=(time.monotonic() - started_at) * 1000,
        )

        return {
            "total": total,
            "succeeded": succeeded,
            "failed": failed,
            "remaining_retryable_count": remaining_retryable_count,
            "warnings": warnings,
        }
