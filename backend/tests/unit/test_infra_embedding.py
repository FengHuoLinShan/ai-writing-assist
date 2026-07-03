"""
Infrastructure: Embedding 模块单元测试

覆盖:
- embedding/cache.py — EmbeddingCache (纯逻辑，无外部依赖)
- embedding/client.py — BgeEmbeddingClient (通过 mock 隔离 Worker 和 Cache)
- embedding/worker.py — _l2_normalize, _resolve_model_id, BgeOnnxWorker
"""

from __future__ import annotations

import asyncio
import math
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ============================================================
# embedding/cache.py — EmbeddingCache
# ============================================================


class TestEmbeddingCacheKey:
    """EmbeddingCache._key 单元测试"""

    def test_key_deterministic(self) -> None:
        """GREEN: 相同输入产生相同 key"""
        from infrastructure.embedding.cache import EmbeddingCache

        cache = EmbeddingCache()
        k1 = cache._key("hello", is_query=False)
        k2 = cache._key("hello", is_query=False)
        assert k1 == k2

    def test_key_differs_by_query_flag(self) -> None:
        """GREEN: query flag 不同导致 key 不同"""
        from infrastructure.embedding.cache import EmbeddingCache

        cache = EmbeddingCache()
        k1 = cache._key("hello", is_query=False)
        k2 = cache._key("hello", is_query=True)
        assert k1 != k2

    def test_key_differs_by_text(self) -> None:
        """GREEN: 不同文本产生不同 key"""
        from infrastructure.embedding.cache import EmbeddingCache

        cache = EmbeddingCache()
        k1 = cache._key("hello", is_query=False)
        k2 = cache._key("world", is_query=False)
        assert k1 != k2

    def test_key_is_sha256_hex(self) -> None:
        """GREEN: key 是 64 字符 hex 字符串 (SHA256)"""
        from infrastructure.embedding.cache import EmbeddingCache

        cache = EmbeddingCache()
        key = cache._key("test", is_query=True)
        assert len(key) == 64
        assert all(c in "0123456789abcdef" for c in key)


class TestEmbeddingCacheGetSet:
    """EmbeddingCache.get/set 单元测试"""

    def test_set_and_get(self) -> None:
        """GREEN: set 后可以 get 到相同的 embedding"""
        from infrastructure.embedding.cache import EmbeddingCache

        cache = EmbeddingCache()
        embedding = [0.1, 0.2, 0.3]

        cache.set("hello", embedding, is_query=False)
        result = cache.get("hello", is_query=False)

        assert result == embedding

    def test_get_returns_copy(self) -> None:
        """GREEN: get 返回副本，修改不影响缓存"""
        from infrastructure.embedding.cache import EmbeddingCache

        cache = EmbeddingCache()
        embedding = [0.1, 0.2, 0.3]

        cache.set("hello", embedding, is_query=False)
        result = cache.get("hello", is_query=False)

        # 修改返回的列表
        result.append(0.4)

        # 缓存中的原值不应受影响
        cached_again = cache.get("hello", is_query=False)
        assert cached_again == [0.1, 0.2, 0.3]

    def test_get_miss(self) -> None:
        """GREEN: 未缓存的文本返回 None"""
        from infrastructure.embedding.cache import EmbeddingCache

        cache = EmbeddingCache()
        result = cache.get("nonexistent", is_query=False)
        assert result is None

    def test_get_query_flag_mismatch(self) -> None:
        """GREEN: query flag 不同导致 miss"""
        from infrastructure.embedding.cache import EmbeddingCache

        cache = EmbeddingCache()
        embedding = [0.1, 0.2, 0.3]

        cache.set("hello", embedding, is_query=True)
        result = cache.get("hello", is_query=False)

        assert result is None

    def test_set_stores_copy(self) -> None:
        """GREEN: set 存储副本，后续修改原列表不影响缓存"""
        from infrastructure.embedding.cache import EmbeddingCache

        cache = EmbeddingCache()
        embedding = [0.1, 0.2, 0.3]

        cache.set("hello", embedding, is_query=False)

        # 修改原列表
        embedding[0] = 999.0

        # 缓存中的值不应受影响
        result = cache.get("hello", is_query=False)
        assert result == [0.1, 0.2, 0.3]


class TestEmbeddingCacheTTL:
    """EmbeddingCache TTL 单元测试"""

    def test_expired_entry_returns_none(self) -> None:
        """GREEN: TTL 过期后返回 None"""
        from infrastructure.embedding.cache import EmbeddingCache

        cache = EmbeddingCache(ttl=0.0)  # TTL = 0，立即过期
        cache.set("hello", [0.1, 0.2], is_query=False)
        result = cache.get("hello", is_query=False)
        assert result is None

    def test_expired_entry_removed_from_cache(self) -> None:
        """GREEN: 过期条目被从缓存删除"""
        from infrastructure.embedding.cache import EmbeddingCache

        cache = EmbeddingCache(ttl=0.0)
        cache.set("hello", [0.1, 0.2], is_query=False)
        cache.get("hello", is_query=False)  # 触发过期删除
        assert len(cache._cache) == 0


class TestEmbeddingCacheLRUEviction:
    """EmbeddingCache LRU 淘汰"""

    def test_evict_oldest_when_full(self) -> None:
        """GREEN: 缓存满时淘汰最旧条目"""
        from infrastructure.embedding.cache import EmbeddingCache

        cache = EmbeddingCache(max_size=3)

        cache.set("a", [0.1], is_query=False)
        cache.set("b", [0.2], is_query=False)
        cache.set("c", [0.3], is_query=False)

        # 再插入一个，淘汰最旧的 "a"
        cache.set("d", [0.4], is_query=False)

        assert cache.get("a", is_query=False) is None  # 被淘汰
        assert cache.get("b", is_query=False) == [0.2]
        assert cache.get("c", is_query=False) == [0.3]
        assert cache.get("d", is_query=False) == [0.4]

    def test_no_eviction_when_under_limit(self) -> None:
        """GREEN: 未超上限时不淘汰"""
        from infrastructure.embedding.cache import EmbeddingCache

        cache = EmbeddingCache(max_size=10)

        for i in range(10):
            cache.set(f"k{i}", [float(i)], is_query=False)

        for i in range(10):
            assert cache.get(f"k{i}", is_query=False) == [float(i)]


class TestEmbeddingCacheStats:
    """EmbeddingCache 统计信息"""

    def test_hit_rate_zero_initially(self) -> None:
        """GREEN: 初始命中率为 0"""
        from infrastructure.embedding.cache import EmbeddingCache

        cache = EmbeddingCache()
        assert cache.hit_rate == 0.0

    def test_hit_rate_after_hits_and_misses(self) -> None:
        """GREEN: 计算命中率"""
        from infrastructure.embedding.cache import EmbeddingCache

        cache = EmbeddingCache()

        # 3次 miss
        cache.get("a")
        cache.get("b")
        cache.get("c")

        # 1次 hit
        cache.set("a", [0.1])
        cache.get("a")

        # hit_rate = 1/4 = 0.25
        assert cache.hit_rate == 0.25

    def test_stats_dict(self) -> None:
        """GREEN: stats 返回正确的统计字典"""
        from infrastructure.embedding.cache import EmbeddingCache

        cache = EmbeddingCache(max_size=5000, ttl=1800.0)
        cache.set("x", [0.5])
        cache.get("x")  # hit
        cache.get("y")  # miss

        stats = cache.stats
        assert stats["size"] == 1
        assert stats["max_size"] == 5000
        assert stats["hits"] == 1
        assert stats["misses"] == 1
        assert stats["hit_rate"] == 0.5

    def test_clear_resets_everything(self) -> None:
        """GREEN: clear 清空缓存并重置统计"""
        from infrastructure.embedding.cache import EmbeddingCache

        cache = EmbeddingCache()
        cache.set("a", [0.1])
        cache.set("b", [0.2])
        cache.get("a")  # hit
        cache.get("c")  # miss

        cache.clear()

        # 立即检查统计已重置
        stats = cache.stats
        assert stats["size"] == 0
        assert stats["hits"] == 0
        assert stats["misses"] == 0

        # clear 后 get 是新的 miss
        assert cache.get("a") is None
        assert cache.stats["misses"] == 1


# ============================================================
# embedding/worker.py — 纯函数
# ============================================================


class TestL2Normalize:
    """_l2_normalize 单元测试"""

    def test_normalize_positive_vector(self) -> None:
        """GREEN: 正向量归一化"""
        from infrastructure.embedding.worker import _l2_normalize

        vec = [3.0, 4.0]
        result = _l2_normalize(vec)

        expected_norm = math.sqrt(3**2 + 4**2)
        expected = [3.0 / expected_norm, 4.0 / expected_norm]
        assert result == expected

    def test_normalized_vector_has_unit_length(self) -> None:
        """GREEN: 归一化后长度为 1"""
        from infrastructure.embedding.worker import _l2_normalize

        vec = [1.0, 2.0, 3.0, 4.0, 5.0]
        result = _l2_normalize(vec)

        norm = math.sqrt(sum(v * v for v in result))
        assert abs(norm - 1.0) < 1e-12

    def test_zero_vector_returns_original(self) -> None:
        """GREEN: 零向量返回原向量（避免除零）"""
        from infrastructure.embedding.worker import _l2_normalize

        vec = [0.0, 0.0, 0.0]
        result = _l2_normalize(vec)
        assert result == vec

    def test_near_zero_vector_returns_original(self) -> None:
        """GREEN: 接近零的向量返回原向量"""
        from infrastructure.embedding.worker import _l2_normalize

        vec = [1e-13, 1e-14]
        result = _l2_normalize(vec)
        assert result == vec

    def test_negative_values(self) -> None:
        """GREEN: 负值向量归一化"""
        from infrastructure.embedding.worker import _l2_normalize

        vec = [-1.0, 0.0, 1.0]
        result = _l2_normalize(vec)

        norm = math.sqrt(sum(v * v for v in result))
        assert abs(norm - 1.0) < 1e-12

    def test_does_not_mutate_input(self) -> None:
        """GREEN: 不修改输入向量"""
        from infrastructure.embedding.worker import _l2_normalize

        vec = [3.0, 4.0]
        original = list(vec)
        _l2_normalize(vec)
        assert vec == original


class TestResolveModelId:
    """_resolve_model_id 单元测试"""

    def test_short_name_bge_base(self) -> None:
        """GREEN: 'bge-base-zh-v1.5' 映射为 HF ID"""
        from infrastructure.embedding.worker import _resolve_model_id

        result = _resolve_model_id("bge-base-zh-v1.5")
        assert result == "BAAI/bge-base-zh-v1.5"

    def test_short_name_bge_small(self) -> None:
        """GREEN: 'bge-small-zh-v1.5' 映射为 HF ID"""
        from infrastructure.embedding.worker import _resolve_model_id

        result = _resolve_model_id("bge-small-zh-v1.5")
        assert result == "BAAI/bge-small-zh-v1.5"

    def test_short_name_bge_large(self) -> None:
        """GREEN: 'bge-large-zh-v1.5' 映射为 HF ID"""
        from infrastructure.embedding.worker import _resolve_model_id

        result = _resolve_model_id("bge-large-zh-v1.5")
        assert result == "BAAI/bge-large-zh-v1.5"

    def test_unknown_name_passed_through(self) -> None:
        """GREEN: 未知名称原样返回"""
        from infrastructure.embedding.worker import _resolve_model_id

        result = _resolve_model_id("custom-model-name")
        assert result == "custom-model-name"

    def test_full_hf_id_passed_through(self) -> None:
        """GREEN: 完整 HF ID 原样返回"""
        from infrastructure.embedding.worker import _resolve_model_id

        result = _resolve_model_id("BAAI/bge-base-zh-v1.5")
        assert result == "BAAI/bge-base-zh-v1.5"


# ============================================================
# embedding/worker.py — BgeOnnxWorker
# ============================================================


class TestBgeOnnxWorkerInit:
    """BgeOnnxWorker 初始化"""

    def test_init_sets_defaults(self) -> None:
        """GREEN: 默认初始化"""
        from infrastructure.embedding.worker import BgeOnnxWorker

        worker = BgeOnnxWorker(model_path="test-model")

        assert worker._model_path == "test-model"
        assert worker._device == "cpu"
        assert worker._quantization == "int8"
        assert worker._max_batch == 64
        assert worker._timeout == 5.0
        assert worker._healthy is False
        assert worker._request_counter == 0

    def test_init_custom_params(self) -> None:
        """GREEN: 自定义参数初始化"""
        from infrastructure.embedding.worker import BgeOnnxWorker

        worker = BgeOnnxWorker(
            model_path="my-model",
            device="cuda",
            quantization="fp16",
            max_batch=128,
            timeout=30.0,
        )

        assert worker._device == "cuda"
        assert worker._quantization == "fp16"
        assert worker._max_batch == 128
        assert worker._timeout == 30.0

    def test_healthy_when_no_process(self) -> None:
        """GREEN: 无进程时 healthy 返回 False"""
        from infrastructure.embedding.worker import BgeOnnxWorker

        worker = BgeOnnxWorker(model_path="test")
        assert worker.healthy is False

    def test_healthy_dead_process(self) -> None:
        """GREEN: 进程已死时 healthy 返回 False"""
        from infrastructure.embedding.worker import BgeOnnxWorker

        worker = BgeOnnxWorker(model_path="test")
        process_mock = MagicMock()
        process_mock.is_alive.return_value = False
        worker._process = process_mock
        worker._healthy = True  # 即使标记为健康，但进程死了也应返回 False

        assert worker.healthy is False

    def test_healthy_alive_process(self) -> None:
        """GREEN: 进程存活且标记健康时返回 True"""
        from infrastructure.embedding.worker import BgeOnnxWorker

        worker = BgeOnnxWorker(model_path="test")
        process_mock = MagicMock()
        process_mock.is_alive.return_value = True
        worker._process = process_mock
        worker._healthy = True

        assert worker.healthy is True


class TestBgeOnnxWorkerStart:
    """BgeOnnxWorker.start 单元测试"""

    @pytest.mark.asyncio
    async def test_start_already_running_skips(self) -> None:
        """GREEN: 已在运行时 start 不重复启动"""
        # 直接测试 start 方法进程存在时的短路逻辑
        from infrastructure.embedding.worker import BgeOnnxWorker

        worker = BgeOnnxWorker(model_path="test")
        worker._process = MagicMock()
        worker._process.is_alive.return_value = True
        worker._healthy = True

        original_process = worker._process
        worker.start()  # 应直接返回，不替换 _process
        assert worker._process is original_process

    def test_start_worker_init_failure_raises(self) -> None:
        """RED: worker 初始化失败时抛出 RuntimeError"""
        from unittest.mock import patch

        from infrastructure.embedding.worker import BgeOnnxWorker

        worker = BgeOnnxWorker(model_path="test")
        worker._result_queue = MagicMock()
        worker._result_queue.get.return_value = (
            "__error__",
            RuntimeError("model not found"),
        )

        process_mock = MagicMock()
        with patch(
            "infrastructure.embedding.worker.mp.Process",
            return_value=process_mock,
        ):
            with pytest.raises(RuntimeError, match="failed to initialize"):
                worker.start()

        assert worker._healthy is False

    def test_start_worker_unexpected_message_raises(self) -> None:
        """RED: worker 返回意外消息时抛出 RuntimeError"""
        from unittest.mock import patch

        from infrastructure.embedding.worker import BgeOnnxWorker

        worker = BgeOnnxWorker(model_path="test")
        worker._result_queue = MagicMock()
        worker._result_queue.get.return_value = ("weird_msg", None)

        process_mock = MagicMock()
        with patch(
            "infrastructure.embedding.worker.mp.Process",
            return_value=process_mock,
        ):
            with pytest.raises(RuntimeError, match="unexpected init message"):
                worker.start()

        assert worker._healthy is False

    def test_start_worker_timeout_raises(self) -> None:
        """RED: worker 启动超时时抛出 RuntimeError"""
        from unittest.mock import patch

        from infrastructure.embedding.worker import BgeOnnxWorker

        worker = BgeOnnxWorker(model_path="test")
        worker._result_queue = MagicMock()
        worker._result_queue.get.side_effect = Exception("timeout")

        process_mock = MagicMock()
        with patch(
            "infrastructure.embedding.worker.mp.Process",
            return_value=process_mock,
        ):
            with pytest.raises(RuntimeError, match="failed to start"):
                worker.start()

        assert worker._healthy is False


class TestBgeOnnxWorkerEncode:
    """BgeOnnxWorker.encode 单元测试"""

    def test_encode_success(self) -> None:
        """GREEN: encode 正常返回 embedding"""
        from infrastructure.embedding.worker import BgeOnnxWorker

        process_mock = MagicMock()
        process_mock.is_alive.return_value = True

        worker = BgeOnnxWorker(model_path="test")

        # 直接设置 mock 队列和进程
        worker._task_queue = MagicMock()
        worker._result_queue = MagicMock()
        worker._process = process_mock
        worker._healthy = True
        worker._request_counter = 0

        embeddings = [[0.1, 0.2], [0.3, 0.4]]
        worker._result_queue.get.return_value = ("emb-1", embeddings)

        result = worker.encode(["text1", "text2"], is_query=False)

        assert result == embeddings
        worker._task_queue.put.assert_called_once()
        put_args = worker._task_queue.put.call_args[0]
        assert put_args[0][0] == ["text1", "text2"]
        assert put_args[0][1] is False  # is_query
        assert put_args[0][2] == "emb-1"  # request_id

    def test_encode_mismatched_request_id(self) -> None:
        """RED: request_id 不匹配时抛出 RuntimeError"""
        from infrastructure.embedding.worker import BgeOnnxWorker

        process_mock = MagicMock()
        process_mock.is_alive.return_value = True

        worker = BgeOnnxWorker(model_path="test")
        worker._task_queue = MagicMock()
        worker._result_queue = MagicMock()
        worker._process = process_mock
        worker._healthy = True
        worker._request_counter = 0

        # 返回不同的 request_id
        worker._result_queue.get.return_value = ("emb-999", [[0.1]])

        with pytest.raises(RuntimeError, match="response mismatch"):
            worker.encode(["text1"], is_query=False)

    def test_encode_worker_not_running(self) -> None:
        """RED: worker 进程未运行时抛出 RuntimeError"""
        from infrastructure.embedding.worker import BgeOnnxWorker

        process_mock = MagicMock()
        process_mock.is_alive.return_value = False

        worker = BgeOnnxWorker(model_path="test")
        worker._process = process_mock

        with pytest.raises(RuntimeError, match="not running"):
            worker.encode(["text1"], is_query=False)

    def test_encode_timeout(self) -> None:
        """RED: 超时时抛出 TimeoutError"""
        from infrastructure.embedding.worker import BgeOnnxWorker

        process_mock = MagicMock()
        process_mock.is_alive.return_value = True

        worker = BgeOnnxWorker(model_path="test")
        worker._task_queue = MagicMock()
        worker._result_queue = MagicMock()
        worker._process = process_mock
        worker._healthy = True
        worker._request_counter = 0

        # result_queue.get 抛出异常模拟超时
        worker._result_queue.get.side_effect = Exception("timeout")

        with pytest.raises(TimeoutError, match="timed out"):
            worker.encode(["text1"], is_query=False, timeout=0.5)

    def test_encode_returns_exception(self) -> None:
        """RED: worker 返回 Exception 时抛出"""
        from infrastructure.embedding.worker import BgeOnnxWorker

        process_mock = MagicMock()
        process_mock.is_alive.return_value = True

        worker = BgeOnnxWorker(model_path="test")
        worker._task_queue = MagicMock()
        worker._result_queue = MagicMock()
        worker._process = process_mock
        worker._healthy = True
        worker._request_counter = 0

        worker._result_queue.get.return_value = (
            "emb-1",
            RuntimeError("OOM error"),
        )

        with pytest.raises(RuntimeError, match="OOM error"):
            worker.encode(["text1"], is_query=False)

    def test_encode_custom_timeout(self) -> None:
        """GREEN: 使用自定义 timeout"""
        from infrastructure.embedding.worker import BgeOnnxWorker

        process_mock = MagicMock()
        process_mock.is_alive.return_value = True

        worker = BgeOnnxWorker(model_path="test", timeout=5.0)
        worker._task_queue = MagicMock()
        worker._result_queue = MagicMock()
        worker._process = process_mock
        worker._healthy = True
        worker._request_counter = 0

        worker._result_queue.get.return_value = ("emb-1", [[0.1]])

        worker.encode(["text1"], is_query=False, timeout=10.0)

        # 验证使用了自定义 timeout
        _, kwargs = worker._result_queue.get.call_args
        assert kwargs["timeout"] == 10.0


class TestBgeOnnxWorkerHealthcheck:
    """BgeOnnxWorker.healthcheck 单元测试"""

    def test_healthcheck_ok(self) -> None:
        """GREEN: healthcheck 返回 True"""
        from infrastructure.embedding.worker import BgeOnnxWorker

        process_mock = MagicMock()
        process_mock.is_alive.return_value = True

        worker = BgeOnnxWorker(model_path="test")
        worker._task_queue = MagicMock()
        worker._result_queue = MagicMock()
        worker._process = process_mock
        worker._healthy = True
        worker._request_counter = 0

        worker._result_queue.get.return_value = ("health-1", "ok")

        assert worker.healthcheck() is True
        assert worker._healthy is True

    def test_healthcheck_fails(self) -> None:
        """RED: healthcheck 失败返回 False"""
        from infrastructure.embedding.worker import BgeOnnxWorker

        process_mock = MagicMock()
        process_mock.is_alive.return_value = True

        worker = BgeOnnxWorker(model_path="test")
        worker._task_queue = MagicMock()
        worker._result_queue = MagicMock()
        worker._process = process_mock
        worker._healthy = True
        worker._request_counter = 0

        worker._result_queue.get.return_value = ("health-1", "not_ok")

        assert worker.healthcheck() is False

    def test_healthcheck_process_dead(self) -> None:
        """RED: 进程已死时 healthcheck 返回 False"""
        from infrastructure.embedding.worker import BgeOnnxWorker

        process_mock = MagicMock()
        process_mock.is_alive.return_value = False

        worker = BgeOnnxWorker(model_path="test")
        worker._process = process_mock

        assert worker.healthcheck() is False


class TestBgeOnnxWorkerStop:
    """BgeOnnxWorker.stop 单元测试"""

    def test_stop_alive_process(self) -> None:
        """GREEN: 停止存活进程"""
        from infrastructure.embedding.worker import BgeOnnxWorker

        process_mock = MagicMock()
        process_mock.is_alive.return_value = True

        worker = BgeOnnxWorker(model_path="test")
        worker._task_queue = MagicMock()
        worker._process = process_mock

        worker.stop(timeout=2.0)

        worker._task_queue.put.assert_called_once()
        # verify shutdown signal sent
        assert worker._task_queue.put.call_args[0][0] == "__SHUTDOWN__"
        process_mock.join.assert_called()
        assert worker._healthy is False

    def test_stop_no_process(self) -> None:
        """GREEN: 无进程时 stop 不报错"""
        from infrastructure.embedding.worker import BgeOnnxWorker

        worker = BgeOnnxWorker(model_path="test")
        worker.stop()  # should not raise

    def test_stop_terminates_if_not_joined(self) -> None:
        """GREEN: join 超时时 terminate 进程"""
        from infrastructure.embedding.worker import BgeOnnxWorker

        process_mock = MagicMock()
        process_mock.is_alive.side_effect = [True, True, False]  # alive after join

        worker = BgeOnnxWorker(model_path="test")
        worker._task_queue = MagicMock()
        worker._process = process_mock

        worker.stop(timeout=1.0)

        process_mock.terminate.assert_called_once()


# ============================================================
# embedding/client.py — BgeEmbeddingClient
# 注意: BgeEmbeddingClient 使用单例模式，测试时需完全隔离
# ============================================================


class TestBgeEmbeddingClientSingleton:
    """BgeEmbeddingClient 单例模式"""

    @pytest.mark.asyncio
    async def test_get_instance_creates_singleton(self) -> None:
        """GREEN: get_instance 返回同一实例"""
        from infrastructure.embedding.client import BgeEmbeddingClient

        # 重置单例
        BgeEmbeddingClient._instance = None

        with (
            patch("infrastructure.embedding.client.get_settings"),
            patch("infrastructure.embedding.client.BgeOnnxWorker"),
            patch.object(BgeEmbeddingClient, "start", return_value=None),
        ):
            instance1 = await BgeEmbeddingClient.get_instance()
            instance2 = await BgeEmbeddingClient.get_instance()

        assert instance1 is instance2

    @pytest.mark.asyncio
    async def test_get_instance_starts_if_not_started(self) -> None:
        """GREEN: get_instance 在未启动时自动启动"""
        from infrastructure.embedding.client import BgeEmbeddingClient

        BgeEmbeddingClient._instance = None

        start_mock = AsyncMock()

        with (
            patch("infrastructure.embedding.client.get_settings"),
            patch("infrastructure.embedding.client.BgeOnnxWorker"),
        ):
            instance = BgeEmbeddingClient()
            instance._started = False
            instance.start = start_mock
            BgeEmbeddingClient._instance = instance

            result = await BgeEmbeddingClient.get_instance()

        assert result is instance
        start_mock.assert_awaited_once()


class TestBgeEmbeddingClientStartClose:
    """BgeEmbeddingClient.start/close"""

    @pytest.mark.asyncio
    async def test_start_already_started(self) -> None:
        """GREEN: 已启动时 start 不重复执行"""
        from infrastructure.embedding.client import BgeEmbeddingClient

        with (
            patch("infrastructure.embedding.client.get_settings"),
            patch("infrastructure.embedding.client.BgeOnnxWorker"),
        ):
            client = BgeEmbeddingClient()
            client._started = True
            client._worker = MagicMock()

            await client.start()

            # worker.start 不应被调用
            client._worker.start.assert_not_called()

    @pytest.mark.asyncio
    async def test_start_normal(self) -> None:
        """GREEN: start 启动 worker"""
        from infrastructure.embedding.client import BgeEmbeddingClient

        with (
            patch("infrastructure.embedding.client.get_settings"),
            patch("infrastructure.embedding.client.BgeOnnxWorker"),
        ):
            client = BgeEmbeddingClient()
            client._started = False
            client._worker = MagicMock()

            await client.start()

            assert client._started is True
            client._worker.start.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_normal(self) -> None:
        """GREEN: close 停止 worker 并清空缓存"""
        from infrastructure.embedding.client import BgeEmbeddingClient

        with (
            patch("infrastructure.embedding.client.get_settings"),
            patch("infrastructure.embedding.client.BgeOnnxWorker"),
        ):
            client = BgeEmbeddingClient()
            client._started = True
            client._worker = MagicMock()
            client._cache = MagicMock()

            await client.close()

            assert client._started is False
            client._worker.stop.assert_called_once()
            client._cache.clear.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_not_started(self) -> None:
        """GREEN: 未启动时 close 不执行"""
        from infrastructure.embedding.client import BgeEmbeddingClient

        with (
            patch("infrastructure.embedding.client.get_settings"),
            patch("infrastructure.embedding.client.BgeOnnxWorker"),
        ):
            client = BgeEmbeddingClient()
            client._started = False
            client._worker = MagicMock()
            client._cache = MagicMock()

            await client.close()

            client._worker.stop.assert_not_called()


class TestBgeEmbeddingClientProperties:
    """BgeEmbeddingClient 属性"""

    def test_healthy_delegates(self) -> None:
        """GREEN: healthy 委托给 worker"""
        from infrastructure.embedding.client import BgeEmbeddingClient

        with (
            patch("infrastructure.embedding.client.get_settings"),
            patch("infrastructure.embedding.client.BgeOnnxWorker"),
        ):
            client = BgeEmbeddingClient()
            client._worker = MagicMock()
            client._worker.healthy = True
            client._started = True

            assert client.healthy is True

    def test_healthy_not_started(self) -> None:
        """GREEN: 未启动时 healthy 为 False"""
        from infrastructure.embedding.client import BgeEmbeddingClient

        with (
            patch("infrastructure.embedding.client.get_settings"),
            patch("infrastructure.embedding.client.BgeOnnxWorker"),
        ):
            client = BgeEmbeddingClient()
            client._started = False

            assert client.healthy is False

    def test_cache_stats_delegates(self) -> None:
        """GREEN: cache_stats 委托给 _cache"""
        from infrastructure.embedding.client import BgeEmbeddingClient

        with (
            patch("infrastructure.embedding.client.get_settings"),
            patch("infrastructure.embedding.client.BgeOnnxWorker"),
        ):
            client = BgeEmbeddingClient()
            client._cache = MagicMock()
            client._cache.stats = {"size": 5, "hits": 10}

            assert client.cache_stats == {"size": 5, "hits": 10}


class TestBgeEmbeddingClientGenerateEmbedding:
    """BgeEmbeddingClient.generate_embedding 单元测试"""

    @pytest.mark.asyncio
    async def test_single_text(self) -> None:
        """GREEN: 单文本返回 list[float]"""
        from infrastructure.embedding.client import BgeEmbeddingClient

        with (
            patch("infrastructure.embedding.client.get_settings"),
            patch("infrastructure.embedding.client.BgeOnnxWorker"),
        ):
            client = BgeEmbeddingClient()
            client._cache = MagicMock()
            client._cache.get.return_value = None  # miss
            client._worker = MagicMock()
            client._worker.encode.return_value = [[0.1, 0.2, 0.3]]

            result = await client.generate_embedding("测试文本")

        assert isinstance(result, list)
        assert result == [0.1, 0.2, 0.3]
        client._worker.encode.assert_called_once_with(["测试文本"], is_query=False)

    @pytest.mark.asyncio
    async def test_batch_texts(self) -> None:
        """GREEN: 批量文本返回 list[list[float]]"""
        from infrastructure.embedding.client import BgeEmbeddingClient

        with (
            patch("infrastructure.embedding.client.get_settings"),
            patch("infrastructure.embedding.client.BgeOnnxWorker"),
        ):
            client = BgeEmbeddingClient()
            client._cache = MagicMock()
            client._cache.get.return_value = None  # all miss
            client._worker = MagicMock()
            client._worker.encode.return_value = [[0.1], [0.2]]

            result = await client.generate_embedding(["文本A", "文本B"])

        assert isinstance(result, list)
        assert len(result) == 2
        assert result == [[0.1], [0.2]]

    @pytest.mark.asyncio
    async def test_empty_text_raises(self) -> None:
        """RED: 空列表抛出 ValueError（空字符串当作单文本处理，不抛）"""
        from infrastructure.embedding.client import BgeEmbeddingClient

        with (
            patch("infrastructure.embedding.client.get_settings"),
            patch("infrastructure.embedding.client.BgeOnnxWorker"),
        ):
            client = BgeEmbeddingClient()
            client._cache = MagicMock()
            client._cache.get.return_value = None
            client._worker = MagicMock()
            client._worker.encode.return_value = [[0.1]]

            # 空字符串被视为单文本输入，不会抛 ValueError
            result = await client.generate_embedding("")
            assert result == [0.1]

            # 空列表被视为无输入，抛 ValueError
            with pytest.raises(ValueError, match="empty"):
                await client.generate_embedding([])

    @pytest.mark.asyncio
    async def test_all_cached_no_worker_call(self) -> None:
        """GREEN: 全部命中缓存时不下发 worker"""
        from infrastructure.embedding.client import BgeEmbeddingClient

        with (
            patch("infrastructure.embedding.client.get_settings"),
            patch("infrastructure.embedding.client.BgeOnnxWorker"),
        ):
            client = BgeEmbeddingClient()
            client._cache = MagicMock()
            client._cache.get.return_value = [0.5, 0.6]  # always hit
            client._worker = MagicMock()

            result = await client.generate_embedding("cached_text")

        assert result == [0.5, 0.6]
        client._worker.encode.assert_not_called()

    @pytest.mark.asyncio
    async def test_partial_cache(self) -> None:
        """GREEN: 部分缓存, 仅未缓存文本发送到 worker"""
        from infrastructure.embedding.client import BgeEmbeddingClient

        with (
            patch("infrastructure.embedding.client.get_settings"),
            patch("infrastructure.embedding.client.BgeOnnxWorker"),
        ):
            client = BgeEmbeddingClient()
            client._cache = MagicMock()
            # text_a 命中, text_b 未命中
            client._cache.get.side_effect = lambda t, **kw: (
                [0.1] if t == "text_a" else None
            )
            client._worker = MagicMock()
            client._worker.encode.return_value = [[0.2]]

            result = await client.generate_embedding(["text_a", "text_b"])

        assert result == [[0.1], [0.2]]
        # 只有 text_b 发送到 worker
        client._worker.encode.assert_called_once_with(["text_b"], is_query=False)

    @pytest.mark.asyncio
    async def test_concurrent_uncached_calls_are_serialized(self) -> None:
        """共享 BGE worker 的 result queue 只能串行消费。"""
        from infrastructure.embedding.client import BgeEmbeddingClient

        active_calls = 0

        def _encode(texts, *, is_query=False):
            nonlocal active_calls
            active_calls += 1
            try:
                if active_calls > 1:
                    raise RuntimeError("overlapping worker encode")
                time.sleep(0.02)
                return [[float(len(texts[0]))]]
            finally:
                active_calls -= 1

        with (
            patch("infrastructure.embedding.client.get_settings"),
            patch("infrastructure.embedding.client.BgeOnnxWorker"),
        ):
            client = BgeEmbeddingClient()
            client._cache = MagicMock()
            client._cache.get.return_value = None
            client._worker = MagicMock()
            client._worker.encode.side_effect = _encode

            result_a, result_b = await asyncio.gather(
                client.generate_embedding("alpha"),
                client.generate_embedding("beta"),
            )

        assert result_a == [5.0]
        assert result_b == [4.0]
        assert client._worker.encode.call_count == 2

    @pytest.mark.asyncio
    async def test_worker_error_propagates(self) -> None:
        """RED: worker 异常向上传递"""
        from infrastructure.embedding.client import BgeEmbeddingClient

        with (
            patch("infrastructure.embedding.client.get_settings"),
            patch("infrastructure.embedding.client.BgeOnnxWorker"),
        ):
            client = BgeEmbeddingClient()
            client._cache = MagicMock()
            client._cache.get.return_value = None
            client._worker = MagicMock()
            client._worker.encode.side_effect = RuntimeError("worker crash")

            with pytest.raises(RuntimeError, match="worker crash"):
                await client.generate_embedding("test")

    @pytest.mark.asyncio
    async def test_is_query_passed_to_worker(self) -> None:
        """GREEN: is_query 参数传递给 worker"""
        from infrastructure.embedding.client import BgeEmbeddingClient

        with (
            patch("infrastructure.embedding.client.get_settings"),
            patch("infrastructure.embedding.client.BgeOnnxWorker"),
        ):
            client = BgeEmbeddingClient()
            client._cache = MagicMock()
            client._cache.get.return_value = None
            client._worker = MagicMock()
            client._worker.encode.return_value = [[0.1]]

            await client.generate_embedding("test", is_query=True)

            client._worker.encode.assert_called_once_with(["test"], is_query=True)

    @pytest.mark.asyncio
    async def test_cache_set_after_encode(self) -> None:
        """GREEN: encode 后自动缓存结果"""
        from infrastructure.embedding.client import BgeEmbeddingClient

        with (
            patch("infrastructure.embedding.client.get_settings"),
            patch("infrastructure.embedding.client.BgeOnnxWorker"),
        ):
            client = BgeEmbeddingClient()
            client._cache = MagicMock()
            client._cache.get.return_value = None  # miss
            client._worker = MagicMock()
            client._worker.encode.return_value = [[0.1, 0.2]]

            await client.generate_embedding("new_text")

            # 验证 set 被调用
            client._cache.set.assert_called_once()
            args = client._cache.set.call_args
            assert args[0][0] == "new_text"  # text
            assert args[0][1] == [0.1, 0.2]  # embedding
