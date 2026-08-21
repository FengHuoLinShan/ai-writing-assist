"""
RAG 检索质量指标

运行时单例，追踪查询数量、降级率、延迟、空结果率、缓存命中率。
每 100 次查询自动输出聚合 JSON 日志。通过 /api/rag/metrics 暴露。
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

_LOG_INTERVAL = 100  # 每 N 次查询输出一次聚合日志


@dataclass
class RagMetrics:
    query_count: int = 0
    degraded_count: int = 0
    empty_result_count: int = 0
    meaningful_match_fail_count: int = 0
    total_latency_ms: float = 0.0
    embedding_latency_ms: float = 0.0
    embedding_latency_count: int = 0
    search_latency_ms: float = 0.0
    search_latency_count: int = 0
    rerank_latency_ms: float = 0.0
    rerank_latency_count: int = 0
    indexed_chunks_count: int = 0
    indexing_failed_embedding_count: int = 0
    indexing_latency_ms: float = 0.0
    indexing_count: int = 0
    embedding_retry_count: int = 0
    embedding_retry_failed_count: int = 0
    embedding_retry_latency_ms: float = 0.0
    _lock: threading.RLock = field(default_factory=threading.RLock)

    def record(
        self,
        *,
        latency_ms: float,
        degraded: bool = False,
        empty: bool = False,
        meaningful_match_fail: bool = False,
        embedding_ms: float | None = None,
        search_ms: float | None = None,
        rerank_ms: float | None = None,
    ) -> None:
        with self._lock:
            self.query_count += 1
            self.total_latency_ms += latency_ms
            if degraded:
                self.degraded_count += 1
            if empty:
                self.empty_result_count += 1
            if meaningful_match_fail:
                self.meaningful_match_fail_count += 1
            if embedding_ms is not None:
                self.embedding_latency_ms += embedding_ms
                self.embedding_latency_count += 1
            if search_ms is not None:
                self.search_latency_ms += search_ms
                self.search_latency_count += 1
            if rerank_ms is not None:
                self.rerank_latency_ms += rerank_ms
                self.rerank_latency_count += 1

            if self.query_count % _LOG_INTERVAL == 0:
                self._log_summary()

    def record_indexing(
        self,
        *,
        chunks_created: int,
        embedding_failed_count: int,
        latency_ms: float,
    ) -> None:
        with self._lock:
            self.indexed_chunks_count += chunks_created
            self.indexing_failed_embedding_count += embedding_failed_count
            self.indexing_latency_ms += latency_ms
            self.indexing_count += 1

    def record_embedding_retry(
        self,
        *,
        total: int,
        failed: int,
        latency_ms: float,
    ) -> None:
        with self._lock:
            self.embedding_retry_count += total
            self.embedding_retry_failed_count += failed
            self.embedding_retry_latency_ms += latency_ms

    def _log_summary(self) -> None:
        s = self.snapshot
        logger.info(
            "RAG metrics [%d queries]: avg_latency=%.1fms degraded=%.1f%% "
            "empty=%.1f%% meaningful_fail=%d",
            s["query_count"],
            s["avg_latency_ms"],
            s["degraded_rate"] * 100,
            s["empty_rate"] * 100,
            s["meaningful_match_fail_count"],
        )

    @property
    def snapshot(self) -> dict:
        with self._lock:
            n = max(self.query_count, 1)
            embedding_n = max(self.embedding_latency_count, 1)
            search_n = max(self.search_latency_count, 1)
            rerank_n = max(self.rerank_latency_count, 1)
            indexing_n = max(self.indexing_count, 1)
            retry_n = max(self.embedding_retry_count, 1)
            return {
                "query_count": self.query_count,
                "degraded_count": self.degraded_count,
                "degraded_rate": round(self.degraded_count / n, 4),
                "empty_result_count": self.empty_result_count,
                "empty_rate": round(self.empty_result_count / n, 4),
                "avg_latency_ms": round(self.total_latency_ms / n, 1),
                "embedding_avg_ms": round(self.embedding_latency_ms / embedding_n, 1),
                "search_avg_ms": round(self.search_latency_ms / search_n, 1),
                "rerank_avg_ms": round(self.rerank_latency_ms / rerank_n, 1),
                "meaningful_match_fail_count": self.meaningful_match_fail_count,
                "indexed_chunks_count": self.indexed_chunks_count,
                "indexing_failed_embedding_count": (self.indexing_failed_embedding_count),
                "indexing_avg_ms": round(self.indexing_latency_ms / indexing_n, 1),
                "embedding_retry_count": self.embedding_retry_count,
                "embedding_retry_failed_count": self.embedding_retry_failed_count,
                "embedding_retry_failed_rate": round(
                    self.embedding_retry_failed_count / retry_n, 4
                ),
                "embedding_retry_avg_ms": round(
                    self.embedding_retry_latency_ms / retry_n, 1
                ),
            }

    def reset(self) -> None:
        with self._lock:
            self.query_count = 0
            self.degraded_count = 0
            self.empty_result_count = 0
            self.meaningful_match_fail_count = 0
            self.total_latency_ms = 0.0
            self.embedding_latency_ms = 0.0
            self.embedding_latency_count = 0
            self.search_latency_ms = 0.0
            self.search_latency_count = 0
            self.rerank_latency_ms = 0.0
            self.rerank_latency_count = 0
            self.indexed_chunks_count = 0
            self.indexing_failed_embedding_count = 0
            self.indexing_latency_ms = 0.0
            self.indexing_count = 0
            self.embedding_retry_count = 0
            self.embedding_retry_failed_count = 0
            self.embedding_retry_latency_ms = 0.0


# 全局单例
_metrics = RagMetrics()


def get_metrics() -> RagMetrics:
    return _metrics
