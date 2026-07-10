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
from modules.rag.chunking import ChunkingService
from modules.rag.contracts import RagIndexReport
from modules.rag.embedding_writer import EmbeddingWriter
from modules.rag.repositories import RagChunkRepository
from modules.rag.source_collection import collect_chapter_sources


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
        *,
        content_mode: str = "canonical",
    ) -> int:
        """索引指定章节的正文到 RAG 库，返回创建的 chunk 数。"""
        report = await self.index_chapter_with_report(
            db,
            novel_id,
            chapter_index,
            content_mode=content_mode,
        )
        return report.chunks_created

    async def index_chapter_with_report(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        chapter_index: int,
        *,
        content_mode: str = "canonical",
    ) -> RagIndexReport:
        """索引指定章节并返回诊断报告。"""
        started_at = time.monotonic()
        sources = await collect_chapter_sources(
            db,
            novel_id,
            chapter_index,
            content_mode=content_mode,
        )
        if sources is None:
            await self._repo.replace_chapter_chunks(
                db,
                novel_id,
                source_type="chapter_text",
                chapter_index=chapter_index,
                items=[],
                content_mode=content_mode,
            )
            return RagIndexReport(
                chapter_index=chapter_index,
                content_mode=content_mode,
                chunks_created=0,
            )

        chunks = self._chunking.split_chinese_novel(sources.content)
        if not chunks:
            await self._repo.replace_chapter_chunks(
                db,
                novel_id,
                source_type="chapter_text",
                chapter_index=chapter_index,
                items=[],
                content_mode=content_mode,
            )
            return RagIndexReport(
                chapter_index=chapter_index,
                content_mode=content_mode,
                source_draft_id=sources.source_draft_id,
                source_content_hash=sources.source_content_hash,
                chunks_created=0,
            )

        chunk_items = [
            build_chunk_create(
                cn_chunk,
                chapter_index=chapter_index,
                content_mode=content_mode,
                source_draft_id=sources.source_draft_id,
                source_content_hash=sources.source_content_hash,
                chunking=self._chunking,
                project_terms=sources.project_terms,
                entity_importance_map=sources.entity_importance_map,
                scenes_for_chapter=sources.scenes_for_chapter,
                scene_spans_for_chapter=sources.scene_spans_for_chapter,
            )
            for cn_chunk in chunks
        ]
        created_chunks = await self._repo.replace_chapter_chunks(
            db,
            novel_id,
            source_type="chapter_text",
            chapter_index=chapter_index,
            items=chunk_items,
            content_mode=content_mode,
        )

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
            content_mode=content_mode,
            source_draft_id=sources.source_draft_id,
            source_content_hash=sources.source_content_hash,
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
        *,
        content_mode: str = "working",
    ) -> RagIndexReport:
        """Compatibility entry point that performs a version-bound full replace.

        Reusing chunks across draft IDs would make their source hash and offsets
        unverifiable. ``old_content``/``new_content`` remain accepted for wire
        compatibility, but the current concrete writing source is authoritative.
        """
        from dataclasses import replace

        del old_content, new_content
        report = await self.index_chapter_with_report(
            db,
            novel_id,
            chapter_index,
            content_mode=content_mode,
        )
        return replace(
            report,
            warnings=[
                "版本绑定索引已使用当前正文执行全量替换",
                *report.warnings,
            ],
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
            status
            for status in (statuses or ["failed", "pending_vectorization"])
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
            batch_succeeded = len(candidates) - embedding_result.failed_count
            succeeded += batch_succeeded
            warnings.extend(embedding_result.warnings)
            if progress_callback is not None:
                progress_callback(min(1.0, succeeded / max(initial_total, 1)))

            if embedding_result.failed_count == 0:
                continue
            failed += embedding_result.failed_count
            break

        remaining_retryable_count = await self._repo.count_retryable_embeddings(
            db,
            novel_id,
            statuses=retry_statuses,
            start_chapter=start_chapter,
            end_chapter=end_chapter,
        )
        if remaining_retryable_count == 0 and failed == 0:
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
