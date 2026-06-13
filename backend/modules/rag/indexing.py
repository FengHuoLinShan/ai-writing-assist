"""
RAG 章节索引

IndexingService 负责把章节正文处理为 RAG chunk 并生成 embedding，
包括读取草稿、分块、角色/实体匹配、去重创建和批量 embedding 的全流程。
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from core.container import get as _container_get
from modules.rag.chunking import ChunkingService
from modules.rag.contracts import RagIndexReport
from modules.rag.models import RagChunk
from modules.rag.query_expansion import _load_project_terms, _match_project_terms
from modules.rag.repositories import RagChunkRepository
from modules.rag.schemas import RagChunkCreate

RAG_INDEX_VERSION = "cn-novel-v1"


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
        _get_latest_draft = _container_get("writing.get_latest_draft_for_chapter")

        draft = await _get_latest_draft(db, str(novel_id), chapter_index)
        if not draft or not draft.content:
            return RagIndexReport(chapter_index=chapter_index, chunks_created=0)

        chunks = self._chunking.split_chinese_novel(draft.content)
        if not chunks:
            return RagIndexReport(chapter_index=chapter_index, chunks_created=0)

        project_terms = await _load_project_terms(db, novel_id)
        await self._repo.delete_by_chapter(db, novel_id, "chapter_text", chapter_index)

        entity_importance_map: dict[str, dict[str, object]] = {}
        try:
            _get_importance_map = _container_get("world.get_entity_importance_map")
            entity_importance_map = await _get_importance_map(db, str(novel_id))
        except Exception:
            pass

        created_chunks: list[RagChunk] = []
        warnings: list[str] = []

        for cn_chunk in chunks:
            character_ids, entity_ids, thread_ids = _match_project_terms(
                cn_chunk.text,
                project_terms,
            )

            chunk_importance = 0.5
            if entity_ids and entity_importance_map:
                max_imp = 0.5
                has_core = False
                for eid in entity_ids:
                    info = entity_importance_map.get(eid)
                    if info:
                        imp_val = float(info["importance"])
                        if imp_val > max_imp:
                            max_imp = imp_val
                        if info.get("importance_level") == "core":
                            has_core = True
                chunk_importance = min(1.0, max_imp + (0.2 if has_core else 0.0))

            chunk_data = RagChunkCreate(
                source_type="chapter_text",
                chapter_index=chapter_index,
                chunk_index=cn_chunk.chunk_index,
                start_offset=cn_chunk.start_offset,
                end_offset=cn_chunk.end_offset,
                char_count=cn_chunk.char_count,
                text=cn_chunk.text,
                summary=self._chunking.extract_summary(cn_chunk.text),
                entity_ids=entity_ids,
                character_ids=character_ids,
                thread_ids=thread_ids,
                visibility="author_only",
                importance=chunk_importance,
                index_version=RAG_INDEX_VERSION,
                embedding_status="pending",
                meta={
                    "chapter_index": chapter_index,
                    "chunk_index": cn_chunk.chunk_index,
                },
            )
            chunk = await self._repo.create(db, novel_id, chunk_data)
            created_chunks.append(chunk)

        await db.flush()

        embedding_failed_count = 0
        if created_chunks:
            from infrastructure.llm.client import LLMClient

            llm = LLMClient()

            for chunk in created_chunks:
                try:
                    embedding = await llm.generate_embedding(chunk.text)
                    if (
                        isinstance(embedding, list)
                        and embedding
                        and isinstance(embedding[0], float)
                    ):
                        await self._repo.update_embedding(db, chunk.id, embedding)
                        chunk.embedding_status = "succeeded"
                    else:
                        raise ValueError("embedding 返回格式异常")
                except Exception as exc:
                    chunk.embedding_status = "failed"
                    chunk.embedding_error = str(exc)[:1000]
                    chunk.index_warnings = [f"embedding 生成失败: {exc}"]
                    embedding_failed_count += 1

            await db.flush()

            if embedding_failed_count > 0:
                warnings.append(
                    f"本章 {embedding_failed_count}/{len(created_chunks)} "
                    "个片段 embedding 失败，检索将降级为关键词匹配",
                )

        return RagIndexReport(
            chapter_index=chapter_index,
            chunks_created=len(created_chunks),
            warnings=warnings,
            embedding_failed_count=embedding_failed_count,
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

        project_terms = await _load_project_terms(db, novel_id)
        created_chunks: list[RagChunk] = []
        embedding_failed_count = 0

        for tag, i1, i2, j1, j2 in opcodes:
            if tag == "equal":
                for (start, end), chunk in old_by_offset.items():
                    if start >= i1 and end <= i2:
                        created_chunks.append(chunk)
                        del old_by_offset[(start, end)]

            elif tag in ("replace", "insert"):
                new_text = new_content[j1:j2]
                if not new_text.strip():
                    continue

                cn_chunks = self._chunking.split_chinese_novel(new_text)
                for cn_chunk in cn_chunks:
                    character_ids, entity_ids, thread_ids = _match_project_terms(
                        cn_chunk.text,
                        project_terms,
                    )
                    chunk_data = RagChunkCreate(
                        source_type="chapter_text",
                        chapter_index=chapter_index,
                        chunk_index=len(created_chunks),
                        start_offset=j1 + cn_chunk.start_offset,
                        end_offset=j1 + cn_chunk.end_offset,
                        char_count=cn_chunk.char_count,
                        text=cn_chunk.text,
                        summary=self._chunking.extract_summary(cn_chunk.text),
                        entity_ids=entity_ids,
                        character_ids=character_ids,
                        thread_ids=thread_ids,
                        visibility="author_only",
                        importance=0.5,
                        index_version=RAG_INDEX_VERSION,
                        embedding_status="pending",
                    )
                    chunk = await self._repo.create(db, novel_id, chunk_data)
                    created_chunks.append(chunk)

        for (start, end), chunk in old_by_offset.items():
            if chunk.id not in {c.id for c in created_chunks}:
                await self._repo.delete(db, chunk.id)

        await db.flush()

        new_chunks = [c for c in created_chunks if c.embedding_status == "pending"]
        if new_chunks:
            try:
                from infrastructure.llm.client import LLMClient

                texts = [c.text for c in new_chunks]
                embeddings = await LLMClient().generate_embedding(texts)
                if isinstance(embeddings, list) and len(embeddings) == len(new_chunks):
                    for chunk, emb in zip(new_chunks, embeddings):
                        await self._repo.update_embedding(db, chunk.id, emb)
                        chunk.embedding_status = "succeeded"
                    await db.flush()
            except Exception as exc:
                warning = f"增量 embedding 失败: {exc}"
                warnings.append(warning)
                embedding_failed_count = len(new_chunks)
                for chunk in new_chunks:
                    chunk.embedding_status = "failed"
                    chunk.embedding_error = str(exc)[:1000]
                await db.flush()

        return RagIndexReport(
            chapter_index=chapter_index,
            chunks_created=len(created_chunks),
            warnings=warnings,
            embedding_failed_count=embedding_failed_count,
            chunks_created_ids=[str(c.id) for c in created_chunks],
        )
