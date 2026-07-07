"""
Embedding 缓存

LRU 内存缓存，key = hash(text + is_query_flag)，带 TTL。
用于减少对同一文本的重复 embedding 计算。
"""

from __future__ import annotations

import hashlib
import threading
import time
from collections import OrderedDict


class EmbeddingCache:
    """线程安全的 LRU embedding 缓存，支持 TTL"""

    def __init__(self, max_size: int = 10000, ttl: float = 3600.0) -> None:
        self._max_size = max_size
        self._ttl = ttl
        self._cache: OrderedDict[str, tuple[float, list[float]]] = OrderedDict()
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0

    @staticmethod
    def _key(text: str, is_query: bool) -> str:
        raw = f"{text}|query={is_query}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def get(self, text: str, *, is_query: bool = False) -> list[float] | None:
        key = self._key(text, is_query)
        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                self._misses += 1
                return None
            ts, embedding = entry
            if time.monotonic() - ts > self._ttl:
                del self._cache[key]
                self._misses += 1
                return None
            self._hits += 1
            self._cache.move_to_end(key)
            return embedding.copy()

    def set(self, text: str, embedding: list[float], *, is_query: bool = False) -> None:
        key = self._key(text, is_query)
        with self._lock:
            if key in self._cache:
                self._cache[key] = (time.monotonic(), embedding.copy())
                self._cache.move_to_end(key)
                return
            if len(self._cache) >= self._max_size:
                self._cache.popitem(last=False)
            self._cache[key] = (time.monotonic(), embedding.copy())

    @property
    def hit_rate(self) -> float:
        total = self._hits + self._misses
        if total == 0:
            return 0.0
        return self._hits / total

    @property
    def stats(self) -> dict:
        return {
            "size": len(self._cache),
            "max_size": self._max_size,
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": round(self.hit_rate, 4),
        }

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()
            self._hits = 0
            self._misses = 0
