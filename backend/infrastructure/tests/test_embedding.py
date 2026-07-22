"""
TB1: Embedding provider — generate_embedding() 测试
"""

from __future__ import annotations

import asyncio
import logging
import threading
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from infrastructure.embedding.client import (
    BgeEmbeddingClient,
    EmbeddingBatchQueueClosedError,
    prewarm_embedding_worker,
)
from infrastructure.embedding.worker import BgeOnnxWorker
from infrastructure.llm.client import LLMClient
from infrastructure.llm.providers import OpenAIProvider


@pytest.mark.asyncio
async def test_prewarm_failure_redacts_runtime_warning() -> None:
    secret = "private-token-value"
    client = AsyncMock()
    client.generate_embedding.side_effect = RuntimeError(
        f"Authorization: Bearer {secret} api_key={secret}"
    )
    settings = SimpleNamespace(
        embedding_provider="bge_onnx",
        embedding_model="test-model",
    )

    with (
        patch(
            "infrastructure.embedding.client.get_settings",
            return_value=settings,
            autospec=True,
        ),
        patch.object(
            BgeEmbeddingClient,
            "get_instance",
            autospec=True,
            return_value=client,
        ),
    ):
        with pytest.raises(RuntimeError, match="prewarm failed"):
            await prewarm_embedding_worker()

    warning = BgeEmbeddingClient.runtime_snapshot()["last_prewarm"]["warning"]
    assert secret not in warning


@pytest.fixture
def mock_openai_client():
    """返回一个 mock AsyncOpenAI client"""
    with patch("infrastructure.llm.providers.AsyncOpenAI", autospec=True) as mock:
        client = MagicMock()
        client.embeddings = MagicMock()
        client.embeddings.create = AsyncMock()
        mock.return_value = client
        yield client


@pytest.fixture
def provider(mock_openai_client) -> OpenAIProvider:
    """初始化 provider（使用 mock client）"""
    # 使用测试专用配置，避免读取真实 .env
    return OpenAIProvider(
        api_key="test-key",
        base_url="http://test",
        default_model="text-embedding-3-large",
    )


@pytest.mark.asyncio
async def test_generate_embedding_single(provider, mock_openai_client):
    """RED: 单文本应返回单个向量（list[float]）"""
    # mock embedding API 返回
    mock_openai_client.embeddings.create.return_value = MagicMock(
        data=[MagicMock(embedding=[0.1, 0.2, 0.3])],
        model="text-embedding-3-large",
        usage=MagicMock(prompt_tokens=4, total_tokens=4),
    )

    result = await provider.generate_embedding("测试文本")
    assert isinstance(result, list), "应返回 list[float]"
    assert len(result) > 0, "向量不应为空"
    assert isinstance(result[0], float), "元素应为 float"

    # 验证调用参数
    mock_openai_client.embeddings.create.assert_called_once()
    kwargs = mock_openai_client.embeddings.create.call_args[1]
    assert kwargs["input"] == "测试文本"
    assert kwargs["model"] is not None  # 使用配置中的 embedding_model


@pytest.mark.asyncio
async def test_generate_embedding_batch(provider, mock_openai_client):
    """RED: 批量文本应返回多个向量（list[list[float]]）"""
    mock_openai_client.embeddings.create.return_value = MagicMock(
        data=[
            MagicMock(embedding=[0.1, 0.2]),
            MagicMock(embedding=[0.3, 0.4]),
        ],
        model="text-embedding-3-large",
        usage=MagicMock(prompt_tokens=8, total_tokens=8),
    )

    texts = ["第一段", "第二段"]
    results = await provider.generate_embedding(texts)
    assert isinstance(results, list), "应返回 list"
    assert len(results) == 2, "应有 2 个向量"
    for vec in results:
        assert isinstance(vec, list), "每个元素应为 list[float]"
        assert isinstance(vec[0], float), "元素应为 float"


@pytest.mark.asyncio
async def test_generate_embedding_empty_text(provider, mock_openai_client):
    """RED: 空字符串应抛出 ValueError"""
    with pytest.raises(ValueError, match="empty"):
        await provider.generate_embedding("")

    with pytest.raises(ValueError, match="empty"):
        await provider.generate_embedding([])


@pytest.mark.asyncio
async def test_generate_embedding_custom_model(provider, mock_openai_client):
    """RED: 支持指定不同的 embedding model"""
    mock_openai_client.embeddings.create.return_value = MagicMock(
        data=[MagicMock(embedding=[0.1, 0.2, 0.3])],
        model="text-embedding-3-small",
        usage=MagicMock(prompt_tokens=4, total_tokens=4),
    )

    await provider.generate_embedding("测试", model="text-embedding-3-small")
    kwargs = mock_openai_client.embeddings.create.call_args[1]
    assert kwargs["model"] == "text-embedding-3-small"


@pytest.mark.asyncio
async def test_llm_client_generate_embedding_delegates_to_provider():
    """LLMClient 应公开 embedding 方法并委托 provider。"""
    with patch("infrastructure.llm.client.get_provider", autospec=True) as get_provider:
        provider = AsyncMock()
        provider.generate_embedding = AsyncMock(return_value=[0.1, 0.2])
        get_provider.return_value = provider

        client = LLMClient()
        result = await client.generate_embedding("测试文本")

    assert result == [0.1, 0.2]
    provider.generate_embedding.assert_called_once()
    assert provider.generate_embedding.call_args.kwargs == {
        "text": "测试文本",
        "model": None,
    }


class RecordingBgeWorker:
    def __init__(self) -> None:
        self.calls: list[tuple[list[str], bool]] = []
        self.started = False
        self.stopped = False
        self.error: Exception | None = None
        self.encode_started = threading.Event()

    @property
    def healthy(self) -> bool:
        return self.started and not self.stopped

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True

    def encode(
        self,
        texts: list[str],
        *,
        is_query: bool = False,
    ) -> list[list[float]]:
        self.encode_started.set()
        self.calls.append((list(texts), is_query))
        if self.error is not None:
            raise self.error
        query_marker = 1.0 if is_query else 0.0
        return [
            [float(len(text)), float(index), query_marker]
            for index, text in enumerate(texts)
        ]


@asynccontextmanager
async def bge_client_context(
    *,
    delay_ms: int = 20,
    max_items: int = 64,
    worker: RecordingBgeWorker | None = None,
):
    worker = worker or RecordingBgeWorker()
    settings = SimpleNamespace(
        bge_onnx_model_path="test-model",
        bge_onnx_device="cpu",
        bge_onnx_quantization="int8",
        inference_worker_max_batch=64,
        inference_worker_timeout=30.0,
        inference_worker_startup_timeout=300.0,
        inference_worker_queue_maxsize=200,
        embedding_batch_queue_delay_ms=delay_ms,
        embedding_batch_queue_max_items=max_items,
    )
    with (
        patch(
            "infrastructure.embedding.client.get_settings",
            return_value=settings,
            autospec=True,
        ),
        patch(
            "infrastructure.embedding.client.BgeOnnxWorker",
            return_value=worker,
            autospec=True,
        ),
    ):
        client = BgeEmbeddingClient()

    await client.start()
    try:
        yield client, worker
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_bge_embedding_batches_concurrent_uncached_document_requests():
    async with bge_client_context(delay_ms=25) as (client, worker):
        single_a, single_b, batch = await asyncio.gather(
            client.generate_embedding("alpha"),
            client.generate_embedding("beta"),
            client.generate_embedding(["gamma", "delta"]),
        )

    assert worker.calls == [(["alpha", "beta", "gamma", "delta"], False)]
    assert single_a == [5.0, 0.0, 0.0]
    assert single_b == [4.0, 1.0, 0.0]
    assert batch == [[5.0, 2.0, 0.0], [5.0, 3.0, 0.0]]


@pytest.mark.asyncio
async def test_bge_embedding_never_mixes_query_and_document_batches():
    async with bge_client_context(delay_ms=25) as (client, worker):
        query_result, document_result = await asyncio.gather(
            client.generate_embedding("search text", is_query=True),
            client.generate_embedding("stored text", is_query=False),
        )

    assert sorted(worker.calls, key=lambda call: call[1]) == [
        (["stored text"], False),
        (["search text"], True),
    ]
    assert query_result == [11.0, 0.0, 1.0]
    assert document_result == [11.0, 0.0, 0.0]


@pytest.mark.asyncio
async def test_bge_embedding_cache_hit_does_not_enter_batch_queue():
    async with bge_client_context(delay_ms=1) as (client, worker):
        first = await client.generate_embedding("cached text")
        second = await client.generate_embedding("cached text")

    assert first == second
    assert worker.calls == [(["cached text"], False)]


@pytest.mark.asyncio
async def test_bge_embedding_worker_exception_fails_entire_batch(caplog):
    worker = RecordingBgeWorker()
    secret = "private-token-value"
    worker.error = RuntimeError(
        f"encode exploded Authorization: Bearer {secret} api_key={secret}"
    )

    with caplog.at_level(logging.ERROR, logger="infrastructure.embedding.client"):
        async with bge_client_context(delay_ms=25, worker=worker) as (client, _worker):
            results = await asyncio.gather(
                client.generate_embedding("one"),
                client.generate_embedding("two"),
                return_exceptions=True,
            )

    assert worker.calls == [(["one", "two"], False)]
    assert secret not in caplog.text
    assert [str(result) for result in results] == [str(worker.error)] * 2


@pytest.mark.asyncio
async def test_bge_embedding_close_fails_pending_queue_requests():
    async with bge_client_context(delay_ms=1000) as (client, worker):
        task = asyncio.create_task(client.generate_embedding("pending"))
        await asyncio.sleep(0.01)

        await client.close()

        with pytest.raises(EmbeddingBatchQueueClosedError, match="batch queue closed"):
            await task

    assert worker.calls == []


@pytest.mark.asyncio
async def test_bge_embedding_single_call_cancellation_does_not_cancel_batch():
    async with bge_client_context(delay_ms=25) as (client, worker):
        canceled = asyncio.create_task(client.generate_embedding("cancel me"))
        kept = asyncio.create_task(client.generate_embedding("keep me"))
        await asyncio.sleep(0)

        canceled.cancel()

        with pytest.raises(asyncio.CancelledError):
            await canceled
        kept_result = await kept

    assert worker.calls == [(["cancel me", "keep me"], False)]
    assert kept_result == [7.0, 1.0, 0.0]


def test_bge_worker_serializes_shared_result_queue_exchanges() -> None:
    class AliveProcess:
        @staticmethod
        def is_alive() -> bool:
            return True

    class TaskQueue:
        def __init__(self) -> None:
            self.items: list[tuple[list[str], bool, str]] = []
            self.put_called = threading.Event()

        def put(self, item, *, timeout: float) -> None:
            _ = timeout
            self.items.append(item)
            self.put_called.set()

    class ResultQueue:
        def __init__(self, task_queue: TaskQueue) -> None:
            self.task_queue = task_queue
            self.index = 0

        def get(self, *, timeout: float):
            _ = timeout
            task = self.task_queue.items[self.index]
            self.index += 1
            return task[2], [[float(len(task[0][0]))]]

    worker = object.__new__(BgeOnnxWorker)
    task_queue = TaskQueue()
    worker._process = AliveProcess()
    worker._task_queue = task_queue
    worker._result_queue = ResultQueue(task_queue)
    worker._healthy = True
    worker._request_counter = 0
    worker._request_lock = threading.Lock()
    worker._timeout = 1.0

    worker._request_lock.acquire()
    result: list[list[list[float]]] = []
    started = threading.Event()

    def encode() -> None:
        started.set()
        result.append(worker.encode(["serialized"]))

    thread = threading.Thread(target=encode)
    thread.start()
    assert started.wait(timeout=1.0)
    assert not task_queue.put_called.wait(timeout=0.05)

    worker._request_lock.release()
    thread.join(timeout=1.0)

    assert not thread.is_alive()
    assert result == [[[10.0]]]
    assert len(task_queue.items) == 1


def test_bge_worker_discards_late_result_after_previous_timeout() -> None:
    class AliveProcess:
        @staticmethod
        def is_alive() -> bool:
            return True

    class TaskQueue:
        def __init__(self) -> None:
            self.items: list[tuple[list[str], bool, str]] = []

        def put(self, item, *, timeout: float) -> None:
            _ = timeout
            self.items.append(item)

    class ResultQueue:
        def get(self, *, timeout: float):
            _ = timeout
            if not getattr(self, "returned_stale", False):
                self.returned_stale = True
                return "emb-1", [[1.0]]
            return "emb-2", [[2.0]]

    worker = object.__new__(BgeOnnxWorker)
    worker._process = AliveProcess()
    worker._task_queue = TaskQueue()
    worker._result_queue = ResultQueue()
    worker._healthy = True
    worker._request_counter = 1
    worker._request_lock = threading.Lock()
    worker._timeout = 1.0

    assert worker.encode(["fresh request"]) == [[2.0]]


def test_bge_worker_healthcheck_discards_late_embedding_result() -> None:
    class AliveProcess:
        @staticmethod
        def is_alive() -> bool:
            return True

    class TaskQueue:
        def put(self, item, *, timeout: float) -> None:
            _ = item, timeout

    class ResultQueue:
        def get(self, *, timeout: float):
            _ = timeout
            if not getattr(self, "returned_stale", False):
                self.returned_stale = True
                return "emb-1", [[1.0]]
            return "health-2", "ok"

    worker = object.__new__(BgeOnnxWorker)
    worker._process = AliveProcess()
    worker._task_queue = TaskQueue()
    worker._result_queue = ResultQueue()
    worker._healthy = False
    worker._request_counter = 1
    worker._request_lock = threading.Lock()

    assert worker.healthcheck() is True
    assert worker.healthy is True
