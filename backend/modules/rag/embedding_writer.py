"""Embedding persistence for RAG indexing."""

from __future__ import annotations

import asyncio
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.llm.redaction import redact_diagnostic
from modules.rag.models import RagChunk
from modules.rag.repositories import RagChunkRepository


class EmbeddingWriteResult:
    def __init__(self, failed_count: int = 0, warnings: list[str] | None = None) -> None:
        self.failed_count = failed_count
        self.warnings = warnings or []


class EmbeddingWriter:
    _FALLBACK_CONCURRENCY = 3

    def __init__(
        self,
        repo: RagChunkRepository,
        llm_client: Any | None = None,
    ) -> None:
        self._repo = repo
        self._owns_llm_client = llm_client is None
        if llm_client is None:
            from infrastructure.llm.client import LLMClient

            llm_client = LLMClient()
        self._llm = llm_client

    async def __aenter__(self) -> EmbeddingWriter:
        return self

    async def __aexit__(self, *_exc_info: object) -> None:
        await self.close()

    async def close(self) -> None:
        if not self._owns_llm_client:
            return
        await self._llm.close()
        self._owns_llm_client = False

    async def write_per_chunk(
        self,
        db: AsyncSession,
        chunks: list[RagChunk],
    ) -> EmbeddingWriteResult:
        result = await self.embed_per_chunk(chunks)
        await db.flush()
        return result

    async def embed_per_chunk(
        self,
        chunks: list[Any],
    ) -> EmbeddingWriteResult:
        """Generate and attach embeddings without opening a DB transaction."""
        failed_count = 0
        semaphore = asyncio.Semaphore(self._FALLBACK_CONCURRENCY)

        async def _generate(chunk: Any) -> tuple[Any, object, Exception | None]:
            async with semaphore:
                try:
                    return chunk, await self._llm.generate_embedding(chunk.text), None
                except Exception as exc:  # noqa: BLE001 - preserve per-chunk degradation
                    return chunk, None, exc

        for chunk, embedding, exc in await asyncio.gather(
            *(_generate(chunk) for chunk in chunks)
        ):
            try:
                if exc is not None:
                    raise exc
                if not self._is_single_embedding(embedding):
                    raise ValueError("embedding 返回格式异常")
                chunk.embedding = embedding  # type: ignore[assignment]
                chunk.embedding_status = "succeeded"
                chunk.embedding_error = None
                chunk.index_warnings = []
            except Exception as exc:
                error = redact_diagnostic(exc, limit=1000)
                chunk.embedding = None
                chunk.embedding_status = "failed"
                chunk.embedding_error = error
                chunk.index_warnings = [f"embedding 生成失败: {error}"]
                failed_count += 1
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
        result = await self.embed_batch(chunks, warning_prefix=warning_prefix)
        await db.flush()
        return result

    async def embed_batch(
        self,
        chunks: list[Any],
        *,
        warning_prefix: str,
    ) -> EmbeddingWriteResult:
        """Generate and attach a batch without touching the database session."""
        if not chunks:
            return EmbeddingWriteResult()
        try:
            embeddings = await self._llm.generate_embedding(
                [chunk.text for chunk in chunks]
            )
            if len(chunks) == 1 and self._is_single_embedding(embeddings):
                embeddings = [embeddings]
            if not isinstance(embeddings, list) or len(embeddings) != len(chunks):
                raise ValueError("embedding 返回格式异常")
            for chunk, embedding in zip(chunks, embeddings):
                if not self._is_single_embedding(embedding):
                    raise ValueError("embedding 返回格式异常")
                chunk.embedding = embedding  # type: ignore[assignment]
                chunk.embedding_status = "succeeded"
                chunk.embedding_error = None
                chunk.index_warnings = []
            return EmbeddingWriteResult()
        except Exception as exc:
            error = redact_diagnostic(exc, limit=1000)
            batch_warning = f"{warning_prefix}: {error}"
            fallback_result = await self.embed_per_chunk(chunks)
            return EmbeddingWriteResult(
                failed_count=fallback_result.failed_count,
                warnings=[batch_warning, *fallback_result.warnings],
            )

    @staticmethod
    def _is_single_embedding(value: object) -> bool:
        return (
            isinstance(value, list)
            and bool(value)
            and all(isinstance(item, float) for item in value)
        )
