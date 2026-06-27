"""
BGE Embedding Client

封装 BgeOnnxWorker 为异步接口，提供 EmbeddingProvider 抽象基类。
通过 asyncio.to_thread 桥接同步 Worker 到 async 调用。
"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod

from core.config import get_settings
from infrastructure.embedding.cache import EmbeddingCache
from infrastructure.embedding.worker import BgeOnnxWorker

logger = logging.getLogger(__name__)


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
        )
        self._cache = EmbeddingCache()
        self._started = False

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

    async def start(self) -> None:
        if self._started:
            return
        await asyncio.to_thread(self._worker.start)
        self._started = True
        logger.info("BgeEmbeddingClient started")

    async def close(self) -> None:
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
                embeddings = await asyncio.to_thread(
                    self._worker.encode,
                    uncached_texts,
                    is_query=is_query,
                )
            except Exception:
                logger.exception("BGE encoding failed for %d texts", len(uncached_texts))
                raise

            for idx, emb in zip(uncached_indices, embeddings):
                results[idx] = emb
                self._cache.set(
                    uncached_texts[uncached_indices.index(idx)], emb, is_query=is_query
                )

        if is_single:
            return results[0]
        return results
