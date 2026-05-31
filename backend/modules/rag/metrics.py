"""
RAG 检索质量指标

运行时单例，追踪查询数量、降级率、延迟、空结果率、缓存命中率。
每 100 次查询自动输出聚合 JSON 日志。通过 /api/rag/metrics 暴露。
"""

from __future__ import annotations

import logging
import threading
import time
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
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def record(
        self,
        *,
        latency_ms: float,
        degraded: bool = False,
        empty: bool = False,
        meaningful_match_fail: bool = False,
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

            if self.query_count % _LOG_INTERVAL == 0:
                self._log_summary()

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
            return {
                "query_count": self.query_count,
                "degraded_count": self.degraded_count,
                "degraded_rate": round(self.degraded_count / n, 4),
                "empty_result_count": self.empty_result_count,
                "empty_rate": round(self.empty_result_count / n, 4),
                "avg_latency_ms": round(self.total_latency_ms / n, 1),
                "meaningful_match_fail_count": self.meaningful_match_fail_count,
            }

    def reset(self) -> None:
        with self._lock:
            self.query_count = 0
            self.degraded_count = 0
            self.empty_result_count = 0
            self.meaningful_match_fail_count = 0
            self.total_latency_ms = 0.0


# 全局单例
_metrics = RagMetrics()


def get_metrics() -> RagMetrics:
    return _metrics
