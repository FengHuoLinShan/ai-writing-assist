"""
RAG 内部服务单元测试 — circuit_breaker / reranker / tuning / mappers / metrics

纯算法逻辑，完全使用 mock，不依赖数据库。
"""

from __future__ import annotations

import json
import math
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.rag.circuit_breaker import (
    CircuitBreaker,
    State,
    get_circuit_breaker,
    reset_circuit_breakers_for_tests,
)
from modules.rag.contracts import RagChunkContract
from modules.rag.mappers import chunk_orm_to_contract
from modules.rag.metrics import RagMetrics, get_metrics
from modules.rag.reranker import rerank, rerank_results
from modules.rag.tuning import (
    _dcg,
    _mrr,
    _ndcg,
    generate_weight_combinations,
)

# ============================================================
# CircuitBreaker
# ============================================================


class TestCircuitBreaker:
    """熔断器状态机单元测试"""

    def test_allow_request_closed_state_returns_true(self):
        # Arrange
        cb = CircuitBreaker()

        # Act
        allowed = cb.allow_request()

        # Assert
        assert allowed is True
        assert cb.state == State.CLOSED

    def test_allow_request_open_within_cooldown_returns_false(self):
        # Arrange
        cb = CircuitBreaker(failure_threshold=1, cooldown_seconds=60.0)
        with patch("modules.rag.circuit_breaker.time.monotonic", return_value=0.0):
            cb.record_failure()

        # Act
        with patch("modules.rag.circuit_breaker.time.monotonic", return_value=30.0):
            allowed = cb.allow_request()

        # Assert
        assert allowed is False
        assert cb.state == State.OPEN

    def test_allow_request_open_after_cooldown_transitions_half_open(self):
        # Arrange
        cb = CircuitBreaker(failure_threshold=1, cooldown_seconds=10.0)
        with patch("modules.rag.circuit_breaker.time.monotonic", return_value=0.0):
            cb.record_failure()

        # Act
        with patch("modules.rag.circuit_breaker.time.monotonic", return_value=10.0):
            allowed = cb.allow_request()

        # Assert
        assert allowed is True
        assert cb.state == State.HALF_OPEN

    def test_allow_request_half_open_returns_true(self):
        # Arrange
        cb = CircuitBreaker(failure_threshold=1, cooldown_seconds=10.0)
        with patch("modules.rag.circuit_breaker.time.monotonic", return_value=0.0):
            cb.record_failure()
        with patch("modules.rag.circuit_breaker.time.monotonic", return_value=10.0):
            cb.allow_request()  # -> HALF_OPEN

        # Act
        allowed = cb.allow_request()

        # Assert
        assert allowed is True
        assert cb.state == State.HALF_OPEN

    def test_record_success_half_open_closes_and_resets(self):
        # Arrange
        cb = CircuitBreaker(failure_threshold=1, cooldown_seconds=10.0)
        with patch("modules.rag.circuit_breaker.time.monotonic", return_value=0.0):
            cb.record_failure()
        with patch("modules.rag.circuit_breaker.time.monotonic", return_value=10.0):
            cb.allow_request()

        # Act
        cb.record_success()

        # Assert
        assert cb.state == State.CLOSED
        assert cb._failure_count == 0

    def test_record_success_closed_no_state_change(self):
        # Arrange
        cb = CircuitBreaker()
        cb._failure_count = 2

        # Act
        cb.record_success()

        # Assert
        assert cb.state == State.CLOSED
        assert cb._failure_count == 2

    def test_record_failure_closed_reaches_threshold_opens(self):
        # Arrange
        cb = CircuitBreaker(failure_threshold=3)

        # Act
        cb.record_failure()
        cb.record_failure()
        cb.record_failure()

        # Assert
        assert cb.state == State.OPEN
        assert cb._failure_count == 3

    def test_record_failure_half_open_returns_to_open(self):
        # Arrange
        cb = CircuitBreaker(failure_threshold=1, cooldown_seconds=10.0)
        with patch("modules.rag.circuit_breaker.time.monotonic", return_value=0.0):
            cb.record_failure()
        with patch("modules.rag.circuit_breaker.time.monotonic", return_value=10.0):
            cb.allow_request()

        # Act
        cb.record_failure()

        # Assert
        assert cb.state == State.OPEN

    def test_reset_restores_closed_and_zeroes_counters(self):
        # Arrange
        cb = CircuitBreaker(failure_threshold=1)
        cb.record_failure()
        assert cb.state == State.OPEN

        # Act
        cb.reset()

        # Assert
        assert cb.state == State.CLOSED
        assert cb._failure_count == 0
        assert cb._last_failure_time == 0.0

    def test_status_returns_snapshot_dict(self):
        # Arrange
        cb = CircuitBreaker(failure_threshold=5, cooldown_seconds=30.0)

        # Act
        st = cb.status

        # Assert
        assert st == {
            "state": "closed",
            "failure_count": 0,
            "failure_threshold": 5,
            "cooldown_seconds": 30.0,
        }

    def test_get_circuit_breaker_returns_singleton(self):
        # Act
        a = get_circuit_breaker()
        b = get_circuit_breaker()

        # Assert
        assert a is b

    def test_get_circuit_breaker_returns_same_instance_per_novel(self):
        reset_circuit_breakers_for_tests()
        novel_id = uuid.uuid4()

        a = get_circuit_breaker(novel_id)
        b = get_circuit_breaker(str(novel_id))

        assert a is b

    def test_get_circuit_breaker_isolates_state_by_novel(self):
        reset_circuit_breakers_for_tests()
        novel_a = uuid.uuid4()
        novel_b = uuid.uuid4()

        breaker_a = get_circuit_breaker(novel_a)
        breaker_b = get_circuit_breaker(novel_b)
        breaker_a._failure_threshold = 1
        breaker_a.record_failure()

        assert breaker_a is not breaker_b
        assert breaker_a.state == State.OPEN
        assert breaker_b.state == State.CLOSED


# ============================================================
# Reranker
# ============================================================


class TestReranker:
    """LLM 重排序单元测试"""

    @pytest.fixture
    def mock_llm_client(self):
        def _make(scores, model_name="test-model"):
            with patch("modules.rag.reranker.LLMClient") as mock_client:
                instance = mock_client.return_value
                instance._settings.llm_model = model_name
                instance.generate = AsyncMock(
                    return_value=MagicMock(content=json.dumps({"scores": scores}))
                )
                yield mock_client, instance

        return _make

    @pytest.mark.asyncio
    async def test_rerank_empty_candidates_returns_empty(self):
        # Arrange
        # Act
        result = await rerank("query", [])

        # Assert
        assert result == []

    @pytest.mark.asyncio
    async def test_rerank_success_returns_padded_scores(self):
        # Arrange
        candidates = [
            {"text": "片段一"},
            {"text": "片段二"},
        ]
        instance = MagicMock(model_name="m")
        instance.generate = AsyncMock(
            return_value=MagicMock(content=json.dumps({"scores": [0.8]}))
        )

        # Act
        result = await rerank("q", candidates, llm_client=instance)

        # Assert
        assert len(result) == 2
        assert result[0] == 0.8
        assert result[1] == 0.0  # padded

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "scores",
        [
            ["0.8"],
            [True],
        ],
    )
    async def test_rerank_propagates_non_json_number_scores(self, scores):
        # Arrange
        candidates = [
            {"text": "片段一"},
            {"text": "片段二"},
        ]
        instance = MagicMock(model_name="m")
        instance.generate = AsyncMock(
            return_value=MagicMock(content=json.dumps({"scores": scores}))
        )

        # Act / Assert
        with pytest.raises(ValueError, match="scores entries"):
            await rerank("q", candidates, llm_client=instance)

    @pytest.mark.asyncio
    async def test_rerank_truncates_extra_scores_to_trimmed_length(self):
        # Arrange
        candidates = [
            {"text": "片段一"},
            {"text": "片段二"},
        ]
        instance = MagicMock(model_name="m")
        instance.generate = AsyncMock(
            return_value=MagicMock(content=json.dumps({"scores": [0.2, 0.4, 0.6]}))
        )

        # Act
        result = await rerank("q", candidates, llm_client=instance)

        # Assert
        assert result == [0.2, 0.4]

    @pytest.mark.asyncio
    async def test_rerank_truncated_candidates_get_default_score(self):
        # Arrange
        candidates = [{"text": f"片段{i}"} for i in range(30)]
        instance = MagicMock(model_name="m")
        instance.generate = AsyncMock(
            return_value=MagicMock(content=json.dumps({"scores": [1.0] * 24}))
        )

        # Act
        result = await rerank(
            "q",
            candidates,
            llm_client=instance,
            max_candidates=24,
        )

        # Assert
        assert len(result) == 30
        assert all(s == 1.0 for s in result[:24])
        assert all(s == 0.3 for s in result[24:])

    @pytest.mark.asyncio
    async def test_rerank_propagates_llm_exception(self):
        # Arrange
        candidates = [{"text": "片段"}]
        instance = MagicMock(model_name="m")
        error = RuntimeError("boom")
        instance.generate = AsyncMock(side_effect=error)

        # Act / Assert
        with pytest.raises(RuntimeError) as raised:
            await rerank("q", candidates, llm_client=instance)
        assert raised.value is error

    @pytest.mark.asyncio
    async def test_rerank_scores_clamped_to_0_1(self):
        # Arrange
        candidates = [{"text": "片段"}]
        instance = MagicMock(model_name="m")
        instance.generate = AsyncMock(
            return_value=MagicMock(content=json.dumps({"scores": [-0.5, 1.5]}))
        )

        # Act
        result = await rerank("q", candidates, llm_client=instance)

        # Assert: only first candidate exists
        assert result[0] == 0.0  # clamped

    @pytest.mark.asyncio
    async def test_rerank_results_not_enough_chunks_returns_original(self):
        # Arrange
        c1 = SimpleNamespace(text="t1")
        scored = [(c1, 0.9)]

        # Act
        result = await rerank_results("q", scored, top_k=5)

        # Assert
        assert result == scored

    @pytest.mark.asyncio
    async def test_rerank_results_success_fuses_and_sorts(self):
        # Arrange
        c1 = SimpleNamespace(text="t1")
        c2 = SimpleNamespace(text="t2")
        c3 = SimpleNamespace(text="t3")
        scored = [(c1, 0.9), (c2, 0.8), (c3, 0.7)]

        instance = MagicMock(model_name="m")
        instance.generate = AsyncMock(
            return_value=MagicMock(content=json.dumps({"scores": [0.9, 0.5, 0.8]}))
        )

        # Act
        result = await rerank_results(
            "q",
            scored,
            top_k=2,
            llm_client=instance,
        )

        # Assert
        assert len(result) == 2
        # final: c1=0.3*0.9+0.7*0.9=0.90, c2=0.59, c3=0.77
        assert result[0][0] is c1
        assert result[1][0] is c3


# ============================================================
# Tuning
# ============================================================


class TestTuning:
    """调优算法单元测试"""

    def test_dcg_empty_scores_returns_zero(self):
        # Act
        result = _dcg([], 5)

        # Assert
        assert result == 0.0

    def test_dcg_calculates_correctly(self):
        # Arrange
        scores = [1.0, 1.0]

        # Act
        result = _dcg(scores, 2)

        # Assert
        expected = (2**1 - 1) / math.log2(2) + (2**1 - 1) / math.log2(3)
        assert result == pytest.approx(expected)

    def test_ndcg_no_relevant_returns_zero(self):
        # Act
        result = _ndcg(["a", "b"], set(), 2)

        # Assert
        assert result == 0.0

    def test_ndcg_perfect_ranking_returns_one(self):
        # Arrange
        predicted = ["a", "b", "c"]
        relevant = {"a", "b"}

        # Act
        result = _ndcg(predicted, relevant, 3)

        # Assert
        assert result == pytest.approx(1.0)

    def test_mrr_first_relevant_returns_one(self):
        # Arrange
        predicted = ["a", "b"]
        relevant = {"a"}

        # Act
        result = _mrr(predicted, relevant)

        # Assert
        assert result == 1.0

    def test_mrr_second_relevant_returns_half(self):
        # Arrange
        predicted = ["a", "b"]
        relevant = {"b"}

        # Act
        result = _mrr(predicted, relevant)

        # Assert
        assert result == 0.5

    def test_mrr_no_relevant_returns_zero(self):
        # Arrange
        predicted = ["a", "b"]
        relevant = {"c"}

        # Act
        result = _mrr(predicted, relevant)

        # Assert
        assert result == 0.0

    def test_generate_weight_combinations_all_sum_to_one(self):
        # Act
        combos = generate_weight_combinations()

        # Assert
        assert len(combos) > 0
        for vw, kw, rw, iw in combos:
            assert pytest.approx(vw + kw + rw + iw) == 1.0

    def test_generate_weight_combinations_within_bounds(self):
        # Act
        combos = generate_weight_combinations()

        # Assert
        for vw, kw, rw, iw in combos:
            assert 0.30 <= vw <= 0.60
            assert 0.15 <= kw <= 0.40
            assert 0.05 <= rw <= 0.25
            assert 0.05 <= iw <= 0.20


# ============================================================
# Mappers
# ============================================================


class TestMappers:
    """数据映射单元测试"""

    def test_chunk_orm_to_contract_maps_all_fields(self):
        # Arrange
        chunk = SimpleNamespace(
            id="chunk-1",
            novel_id="novel-1",
            source_type="chapter_text",
            source_id="src-1",
            chapter_index=1,
            chunk_index=0,
            start_offset=0,
            end_offset=100,
            char_count=100,
            text="测试文本",
            summary="摘要",
            entity_ids=["e1"],
            character_ids=["c1"],
            thread_ids=["t1"],
            visibility="author_only",
            importance=0.8,
            index_version="v1",
            embedding_status="succeeded",
            embedding_error=None,
            index_warnings=None,
            meta={"key": "value"},
        )

        # Act
        contract = chunk_orm_to_contract(chunk, score=0.95)

        # Assert
        assert isinstance(contract, RagChunkContract)
        assert contract.id == "chunk-1"
        assert contract.novel_id == "novel-1"
        assert contract.source_type == "chapter_text"
        assert contract.source_id == "src-1"
        assert contract.chapter_index == 1
        assert contract.chunk_index == 0
        assert contract.start_offset == 0
        assert contract.end_offset == 100
        assert contract.char_count == 100
        assert contract.text == "测试文本"
        assert contract.summary == "摘要"
        assert contract.entity_ids == ["e1"]
        assert contract.character_ids == ["c1"]
        assert contract.thread_ids == ["t1"]
        assert contract.visibility == "author_only"
        assert contract.importance == 0.8
        assert contract.index_version == "v1"
        assert contract.embedding_status == "succeeded"
        assert contract.embedding_error is None
        assert contract.index_warnings == []
        assert contract.meta == {"key": "value"}
        assert contract.score == pytest.approx(0.95)

    def test_chunk_orm_to_contract_with_score_rounds_to_4_decimals(self):
        # Arrange
        chunk = SimpleNamespace(
            id="c",
            novel_id="n",
            source_type="t",
            source_id=None,
            chapter_index=None,
            chunk_index=None,
            start_offset=None,
            end_offset=None,
            char_count=None,
            text="",
            summary=None,
            entity_ids=None,
            character_ids=None,
            thread_ids=None,
            visibility="author_only",
            importance=0.5,
            index_version="legacy",
            embedding_status="pending",
            embedding_error=None,
            index_warnings=None,
            meta=None,
        )

        # Act
        contract = chunk_orm_to_contract(chunk, score=0.12345678)

        # Assert
        assert contract.score == 0.1235

    def test_chunk_orm_to_contract_without_score_sets_none(self):
        # Arrange
        chunk = SimpleNamespace(
            id="c",
            novel_id="n",
            source_type="t",
            source_id=None,
            chapter_index=None,
            chunk_index=None,
            start_offset=None,
            end_offset=None,
            char_count=None,
            text="",
            summary=None,
            entity_ids=None,
            character_ids=None,
            thread_ids=None,
            visibility="author_only",
            importance=0.5,
            index_version="legacy",
            embedding_status="pending",
            embedding_error=None,
            index_warnings=None,
            meta=None,
        )

        # Act
        contract = chunk_orm_to_contract(chunk)

        # Assert
        assert contract.score is None

    def test_chunk_orm_to_contract_none_lists_default_empty(self):
        # Arrange
        chunk = SimpleNamespace(
            id="c",
            novel_id="n",
            source_type="t",
            source_id=None,
            chapter_index=None,
            chunk_index=None,
            start_offset=None,
            end_offset=None,
            char_count=None,
            text="",
            summary=None,
            entity_ids=None,
            character_ids=None,
            thread_ids=None,
            visibility="author_only",
            importance=0.5,
            index_version="legacy",
            embedding_status="pending",
            embedding_error=None,
            index_warnings=None,
            meta=None,
        )

        # Act
        contract = chunk_orm_to_contract(chunk)

        # Assert
        assert contract.entity_ids == []
        assert contract.character_ids == []
        assert contract.thread_ids == []
        assert contract.index_warnings == []


# ============================================================
# Metrics
# ============================================================


class TestMetrics:
    """检索指标单元测试"""

    def test_record_increments_query_count(self):
        # Arrange
        metrics = RagMetrics()

        # Act
        metrics.record(latency_ms=10.0)
        metrics.record(latency_ms=20.0)

        # Assert
        assert metrics.query_count == 2

    def test_record_degraded_increments_degraded_count(self):
        # Arrange
        metrics = RagMetrics()

        # Act
        metrics.record(latency_ms=10.0, degraded=True)
        metrics.record(latency_ms=10.0, degraded=False)

        # Assert
        assert metrics.degraded_count == 1

    def test_record_empty_increments_empty_count(self):
        # Arrange
        metrics = RagMetrics()

        # Act
        metrics.record(latency_ms=10.0, empty=True)

        # Assert
        assert metrics.empty_result_count == 1

    def test_record_meaningful_match_fail_increments(self):
        # Arrange
        metrics = RagMetrics()

        # Act
        metrics.record(latency_ms=10.0, meaningful_match_fail=True)

        # Assert
        assert metrics.meaningful_match_fail_count == 1

    def test_record_every_100_queries_logs_summary(self):
        # Arrange
        metrics = RagMetrics()
        with patch("modules.rag.metrics.logger") as mock_logger:
            # Act
            for _ in range(100):
                metrics.record(latency_ms=10.0)

            # Assert
            mock_logger.info.assert_called_once()
            call_args = mock_logger.info.call_args[0]
            assert "RAG metrics" in call_args[0]

    def test_snapshot_zero_queries_avoids_division_by_zero(self):
        # Arrange
        metrics = RagMetrics()

        # Act
        snap = metrics.snapshot

        # Assert
        assert snap["query_count"] == 0
        assert snap["degraded_rate"] == 0.0
        assert snap["empty_rate"] == 0.0
        assert snap["avg_latency_ms"] == 0.0

    def test_snapshot_calculates_rates(self):
        # Arrange
        metrics = RagMetrics()
        metrics.record(latency_ms=100.0, degraded=True, empty=True)
        metrics.record(latency_ms=300.0, degraded=False, empty=False)

        # Act
        snap = metrics.snapshot

        # Assert
        assert snap["query_count"] == 2
        assert snap["degraded_rate"] == 0.5
        assert snap["empty_rate"] == 0.5
        assert snap["avg_latency_ms"] == 200.0

    def test_reset_zeroes_all_counters(self):
        # Arrange
        metrics = RagMetrics()
        metrics.record(latency_ms=10.0, degraded=True, empty=True)
        assert metrics.query_count == 1

        # Act
        metrics.reset()

        # Assert
        assert metrics.query_count == 0
        assert metrics.degraded_count == 0
        assert metrics.empty_result_count == 0
        assert metrics.meaningful_match_fail_count == 0
        assert metrics.total_latency_ms == 0.0

    def test_get_metrics_returns_singleton(self):
        # Act
        a = get_metrics()
        b = get_metrics()

        # Assert
        assert a is b
