"""RAG 索引诊断状态聚合。

`get_index_status` 的编排归本模块：片段计数、embedding 配置比对、
告警文案与运行时快照组装都在这里完成；facade 只做稳定委托。
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from modules.evidence.indexing.repositories import RagChunkRepository


class IndexStatusService:
    """Aggregate RAG index health for author-facing diagnostics."""

    def __init__(self, repo: RagChunkRepository | None = None) -> None:
        self._repo = repo or RagChunkRepository()

    async def status(self, db: AsyncSession, novel_id: str) -> dict:
        from core.config import get_settings
        from infrastructure.embedding.client import BgeEmbeddingClient
        from modules.evidence.indexing.circuit_breaker import get_circuit_breaker
        from modules.evidence.indexing.index_state import RagIndexStateService

        nid = uuid.UUID(hex=novel_id)
        total = await self._repo.count_by_novel(db, nid)
        embedding_failed_count = await self._repo.count_embedding_failed(db, nid)
        pending_vectorization = await self._repo.count_pending_vectorization(db, nid)
        retryable_embedding_count = await self._repo.count_retryable_embeddings(
            db,
            nid,
            statuses=["failed", "pending_vectorization"],
        )
        indexed_embedding_dim = await self._repo.get_sample_embedding_dim(db, nid)
        settings = get_settings()
        configured_embedding_dim = settings.embedding_dim
        effective_embedding_dim = indexed_embedding_dim or configured_embedding_dim
        embedding_dimension_mismatch = (
            indexed_embedding_dim is not None
            and indexed_embedding_dim != configured_embedding_dim
        )

        warnings = []
        if embedding_dimension_mismatch:
            warnings.append(
                f"已索引向量维度为 {indexed_embedding_dim}，"
                f"但配置 EMBEDDING_DIM={configured_embedding_dim}，"
                "请同步配置后重启后端"
            )
        if pending_vectorization:
            warnings.append(
                f"有 {pending_vectorization} 个片段待重新向量化（维度迁移后），"
                "检索可能暂时不准确"
            )
        if embedding_failed_count:
            warnings.append(
                f"有 {embedding_failed_count} 个片段 embedding 失败，检索和抽取可能不准确"
            )

        freshness = await RagIndexStateService().summary(db, novel_id)
        return {
            "total": total,
            "embedding_provider": settings.embedding_provider,
            "embedding_model": settings.embedding_model,
            "embedding_dim": effective_embedding_dim,
            "configured_embedding_dim": configured_embedding_dim,
            "indexed_embedding_dim": indexed_embedding_dim,
            "embedding_dimension_mismatch": embedding_dimension_mismatch,
            "embedding_failed_count": embedding_failed_count,
            "pending_vectorization": pending_vectorization,
            "retryable_embedding_count": retryable_embedding_count,
            "embedding_runtime": BgeEmbeddingClient.runtime_snapshot(),
            "degraded": (
                embedding_failed_count > 0
                or pending_vectorization > 0
                or embedding_dimension_mismatch
            ),
            "warnings": warnings,
            "circuit_breaker": get_circuit_breaker(novel_id).status["state"],
            "index_freshness": freshness,
        }
