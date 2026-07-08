"""
BGE Embedding Client

封装 BgeOnnxWorker 为异步接口，提供 EmbeddingProvider 抽象基类。
通过 asyncio.to_thread 桥接同步 Worker 到 async 调用。
"""

from __future__ import annotations

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from collections import deque
from dataclasses import dataclass, field

from core.config import get_settings
from infrastructure.embedding.cache import EmbeddingCache
from infrastructure.embedding.worker import BgeOnnxWorker

logger = logging.getLogger(__name__)

_last_prewarm: dict | None = None


def _settings_int(settings: object, name: str, default: int) -> int:
    value = getattr(settings, name, default)
    return value if isinstance(value, int) and not isinstance(value, bool) else default


class EmbeddingBatchQueueClosedError(RuntimeError):
    """Raised for pending embedding requests when the batch queue is closed."""


@dataclass(slots=True)
class _BatchRequest:
    texts: list[str]
    future: asyncio.Future[list[list[float]]]


@dataclass(slots=True)
class _BatchQueueState:
    queue: asyncio.Queue[_BatchRequest] = field(default_factory=asyncio.Queue)
    backlog: deque[_BatchRequest] = field(default_factory=deque)
    task: asyncio.Task[None] | None = None


class EmbeddingProvider(ABC):
    """Embedding 提供者抽象基类"""

    @abstractmethod
    async def generate_embedding(
        self,
        text: str | list[str],
        *,
        is_query: bool = False,
    ) -> list[float] | list[list[float]]: ...

    @abstractmethod
    async def close(self) -> None: ...


class BgeEmbeddingClient(EmbeddingProvider):
    """本地 BGE embedding 客户端

    封装 BgeOnnxWorker 子进程管理 + LRU 缓存 + 异步桥接。
    单例模式：整个应用共享一个 worker 进程。
    """

    _instance: BgeEmbeddingClient | None = None
    _lock = asyncio.Lock()

    def __init__(self) -> None:
        settings = get_settings()
        self._worker = BgeOnnxWorker(
            model_path=settings.bge_onnx_model_path,
            device=settings.bge_onnx_device,
            quantization=settings.bge_onnx_quantization,
            max_batch=settings.inference_worker_max_batch,
            timeout=settings.inference_worker_timeout,
            queue_maxsize=settings.inference_worker_queue_maxsize,
        )
        self._cache = EmbeddingCache()
        self._started = False
        self._direct_encode_lock = asyncio.Lock()
        self._batch_delay_seconds = max(
            0,
            _settings_int(settings, "embedding_batch_queue_delay_ms", 5),
        ) / 1000
        self._batch_max_items = max(
            1,
            _settings_int(
                settings,
                "embedding_batch_queue_max_items",
                _settings_int(settings, "inference_worker_max_batch", 64),
            ),
        )
        self._batch_wait_timeout_seconds = max(
            0.1,
            float(getattr(settings, "embedding_batch_queue_timeout_seconds", 30.0)),
        )
        self._batch_queues = {
            False: _BatchQueueState(),
            True: _BatchQueueState(),
        }
        self._queue_lifecycle_lock = asyncio.Lock()
        self._closing = False

    @classmethod
    async def get_instance(cls) -> BgeEmbeddingClient:
        if cls._instance is not None and cls._instance._started:
            return cls._instance
        async with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            if not cls._instance._started:
                await cls._instance.start()
            return cls._instance

    @classmethod
    def runtime_snapshot(cls) -> dict:
        instance = cls._instance
        snapshot = {
            "started": False,
            "healthy": False,
            "cache_stats": {},
            "last_prewarm": _last_prewarm,
        }
        if instance is None:
            return snapshot
        snapshot.update(
            {
                "started": instance._started,
                "healthy": instance.healthy,
                "cache_stats": instance.cache_stats,
            }
        )
        return snapshot

    @classmethod
    async def close_instance(cls) -> None:
        if cls._instance is not None:
            await cls._instance.close()

    async def start(self) -> None:
        if self._started:
            return
        await asyncio.to_thread(self._worker.start)
        self._started = True
        self._closing = False
        self._start_batch_workers()
        logger.info("BgeEmbeddingClient started")

    async def close(self) -> None:
        close_error = EmbeddingBatchQueueClosedError(
            "BGE embedding batch queue closed during client shutdown"
        )
        async with self._queue_lifecycle_lock:
            self._closing = True
            await self._stop_batch_workers(close_error)
        if self._started:
            await asyncio.to_thread(self._worker.stop)
            self._started = False
            self._cache.clear()

    @property
    def healthy(self) -> bool:
        return self._started and self._worker.healthy

    @property
    def cache_stats(self) -> dict:
        return self._cache.stats

    def _start_batch_workers(self) -> None:
        for is_query, state in self._batch_queues.items():
            if state.task is None or state.task.done():
                state.task = asyncio.create_task(
                    self._batch_worker_loop(is_query, state),
                    name=f"bge-embedding-batch-queue-{is_query}",
                )

    async def _stop_batch_workers(self, error: Exception) -> None:
        tasks = [
            state.task
            for state in self._batch_queues.values()
            if state.task is not None and not state.task.done()
        ]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        for state in self._batch_queues.values():
            self._fail_queued_requests(state, error)
            state.task = None

    async def _batch_worker_loop(
        self,
        is_query: bool,
        state: _BatchQueueState,
    ) -> None:
        current_batch: list[_BatchRequest] = []
        try:
            while True:
                first = await self._take_next_request(state)
                current_batch = [first]
                batch_size = len(first.texts)

                if batch_size < self._batch_max_items:
                    batch_size = await self._collect_batch_requests(
                        state,
                        current_batch,
                        batch_size,
                    )

                await self._encode_batch_requests(
                    current_batch,
                    is_query=is_query,
                    batch_size=batch_size,
                )
                current_batch = []
        except asyncio.CancelledError as exc:
            error = EmbeddingBatchQueueClosedError(
                "BGE embedding batch queue closed before encoding completed"
            )
            self._fail_requests(current_batch, error)
            self._fail_queued_requests(state, error)
            raise exc

    async def _take_next_request(self, state: _BatchQueueState) -> _BatchRequest:
        if state.backlog:
            return state.backlog.popleft()
        return await state.queue.get()

    async def _collect_batch_requests(
        self,
        state: _BatchQueueState,
        batch: list[_BatchRequest],
        batch_size: int,
    ) -> int:
        deadline = time.monotonic() + self._batch_delay_seconds
        while batch_size < self._batch_max_items:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break

            try:
                if state.backlog:
                    request = state.backlog.popleft()
                else:
                    request = await asyncio.wait_for(state.queue.get(), remaining)
            except TimeoutError:
                break

            request_size = len(request.texts)
            if batch_size + request_size > self._batch_max_items and batch:
                state.backlog.appendleft(request)
                break

            batch.append(request)
            batch_size += request_size

        return batch_size

    async def _encode_batch_requests(
        self,
        batch: list[_BatchRequest],
        *,
        is_query: bool,
        batch_size: int,
    ) -> None:
        texts = [text for request in batch for text in request.texts]
        try:
            embeddings = await asyncio.to_thread(
                self._worker.encode,
                texts,
                is_query=is_query,
            )
        except Exception as exc:
            logger.exception("BGE batch encoding failed for %d texts", batch_size)
            self._fail_requests(batch, exc)
            return

        if len(embeddings) != len(texts):
            error = RuntimeError(
                "BGE worker returned "
                f"{len(embeddings)} embeddings for {len(texts)} texts"
            )
            self._fail_requests(batch, error)
            return

        offset = 0
        for request in batch:
            end = offset + len(request.texts)
            if not request.future.done():
                request.future.set_result(embeddings[offset:end])
            offset = end

    async def _encode_uncached(
        self,
        texts: list[str],
        *,
        is_query: bool,
    ) -> list[list[float]]:
        if self._closing:
            raise EmbeddingBatchQueueClosedError("BGE embedding batch queue is closed")
        if not self._started:
            async with self._direct_encode_lock:
                return await asyncio.to_thread(
                    self._worker.encode,
                    texts,
                    is_query=is_query,
                )

        loop = asyncio.get_running_loop()
        future: asyncio.Future[list[list[float]]] = loop.create_future()
        request = _BatchRequest(texts=list(texts), future=future)

        async with self._queue_lifecycle_lock:
            if not self._started or self._closing:
                raise EmbeddingBatchQueueClosedError(
                    "BGE embedding batch queue is closed"
                )
            await self._batch_queues[is_query].queue.put(request)
        try:
            return await asyncio.wait_for(
                asyncio.shield(future),
                timeout=self._batch_wait_timeout_seconds,
            )
        except TimeoutError as exc:
            future.cancel()
            raise TimeoutError("BGE embedding batch queue timed out") from exc
        except asyncio.CancelledError:
            future.cancel()
            raise

    @staticmethod
    def _fail_requests(requests: list[_BatchRequest], error: Exception) -> None:
        for request in requests:
            if not request.future.done():
                request.future.set_exception(error)

    def _fail_queued_requests(
        self,
        state: _BatchQueueState,
        error: Exception,
    ) -> None:
        queued = list(state.backlog)
        state.backlog.clear()
        while True:
            try:
                queued.append(state.queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        self._fail_requests(queued, error)

    async def generate_embedding(
        self,
        text: str | list[str],
        *,
        is_query: bool = False,
    ) -> list[float] | list[list[float]]:
        """生成文本 embedding。

        单文本 → list[float]，多文本 → list[list[float]]。
        自动通过 LRU 缓存去重，减少重复计算。
        """
        is_single = isinstance(text, str)
        texts: list[str] = [text] if is_single else list(text)

        if not texts:
            raise ValueError("Input text is empty")

        # 检查缓存
        uncached_texts: list[str] = []
        uncached_indices: list[int] = []
        results: list[list[float]] = [None] * len(texts)  # type: ignore[list-item]

        for i, t in enumerate(texts):
            cached = self._cache.get(t, is_query=is_query)
            if cached is not None:
                results[i] = cached
            else:
                uncached_texts.append(t)
                uncached_indices.append(i)

        # 批量编码未缓存文本
        if uncached_texts:
            try:
                embeddings = await self._encode_uncached(
                    uncached_texts,
                    is_query=is_query,
                )
            except Exception:
                logger.exception("BGE encoding failed for %d texts", len(uncached_texts))
                raise

            for text, idx, emb in zip(uncached_texts, uncached_indices, embeddings):
                results[idx] = emb
                self._cache.set(text, emb, is_query=is_query)

        if is_single:
            return results[0]
        return results


async def prewarm_embedding_worker() -> dict:
    """启动 BGE worker 并执行一次轻量 query embedding。"""
    global _last_prewarm

    settings = get_settings()
    started_at = time.monotonic()
    try:
        client = await BgeEmbeddingClient.get_instance()
        embedding = await client.generate_embedding("rag prewarm", is_query=True)
        if not (
            isinstance(embedding, list)
            and embedding
            and isinstance(embedding[0], float)
        ):
            raise ValueError("embedding 返回格式异常")
        latency_ms = round((time.monotonic() - started_at) * 1000, 1)
        result = {
            "status": "ready",
            "provider": settings.embedding_provider,
            "model": settings.embedding_model,
            "embedding_dim": len(embedding),
            "latency_ms": latency_ms,
            "cache_stats": client.cache_stats,
        }
        _last_prewarm = result.copy()
        return result
    except Exception as exc:
        latency_ms = round((time.monotonic() - started_at) * 1000, 1)
        result = {
            "status": "failed",
            "provider": settings.embedding_provider,
            "model": settings.embedding_model,
            "embedding_dim": None,
            "latency_ms": latency_ms,
            "cache_stats": {},
            "warning": str(exc)[:500],
        }
        _last_prewarm = result.copy()
        raise RuntimeError("embedding worker prewarm failed") from exc
