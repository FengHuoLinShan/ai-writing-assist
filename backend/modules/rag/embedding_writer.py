"""Embedding persistence for RAG indexing."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from modules.rag.models import RagChunk
from modules.rag.repositories import RagChunkRepository


class EmbeddingWriteResult:
    def __init__(self, failed_count: int = 0, warnings: list[str] | None = None) -> None:
        self.failed_count = failed_count
        self.warnings = warnings or []


class EmbeddingWriter:
    def __init__(
        self,
        repo: RagChunkRepository,
        llm_client: Any | None = None,
    ) -> None:
        self._repo = repo
        if llm_client is None:
            from infrastructure.llm.client import LLMClient

            llm_client = LLMClient()
        self._llm = llm_client

    async def write_per_chunk(
        self,
        db: AsyncSession,
        chunks: list[RagChunk],
    ) -> EmbeddingWriteResult:
        failed_count = 0
        for chunk in chunks:
            try:
                embedding = await self._llm.generate_embedding(chunk.text)
                if self._is_single_embedding(embedding):
                    await self._repo.update_embedding(db, chunk.id, embedding)
                    chunk.embedding_status = "succeeded"
                else:
                    raise ValueError("embedding 返回格式异常")
            except Exception as exc:
                chunk.embedding_status = "failed"
                chunk.embedding_error = str(exc)[:1000]
                chunk.index_warnings = [f"embedding 生成失败: {exc}"]
                failed_count += 1
        await db.flush()
        warnings = []
        if failed_count > 0:
            warnings.append(
                f"本章 {failed_count}/{len(chunks)} "
                "个片段 embedding 失败，检索将降级为关键词匹配",
            )
        return EmbeddingWriteResult(failed_count=failed_count, warnings=warnings)

    async def write_batch(
        self,
        db: AsyncSession,
        chunks: list[RagChunk],
        *,
        warning_prefix: str,
    ) -> EmbeddingWriteResult:
        if not chunks:
            return EmbeddingWriteResult()
        try:
            embeddings = await self._llm.generate_embedding(
                [chunk.text for chunk in chunks]
            )
            if not isinstance(embeddings, list) or len(embeddings) != len(chunks):
                raise ValueError("embedding 返回格式异常")
            for chunk, embedding in zip(chunks, embeddings):
                if not self._is_single_embedding(embedding):
                    raise ValueError("embedding 返回格式异常")
                await self._repo.update_embedding(db, chunk.id, embedding)
                chunk.embedding_status = "succeeded"
                chunk.embedding_error = None
                chunk.index_warnings = []
            await db.flush()
            return EmbeddingWriteResult()
        except Exception as exc:
            error = str(exc)
            for chunk in chunks:
                chunk.embedding_status = "failed"
                chunk.embedding_error = error[:1000]
            await db.flush()
            return EmbeddingWriteResult(
                failed_count=len(chunks),
                warnings=[f"{warning_prefix}: {error}"],
            )

    @staticmethod
    def _is_single_embedding(value: object) -> bool:
        return (
            isinstance(value, list)
            and bool(value)
            and isinstance(value[0], float)
        )
