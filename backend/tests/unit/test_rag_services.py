"""
RAG 内部服务单元测试 — circuit_breaker / reranker / tuning / mappers / metrics

纯算法逻辑，完全使用 mock，不依赖数据库。
"""

from __future__ import annotations

import math
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from modules.evidence.contracts import RagChunkContract
from modules.evidence.indexing.circuit_breaker import (
    CircuitBreaker,
    State,
    get_circuit_breaker,
    reset_circuit_breakers_for_tests,
)
from modules.evidence.indexing.mappers import chunk_orm_to_contract
from modules.evidence.indexing.metrics import RagMetrics, get_metrics
from modules.evidence.indexing.reranker import (
    RerankerCandidateDecision,
    RerankerOutput,
    RerankerSupportStatus,
    rerank,
    rerank_results,
)
from modules.evidence.indexing.tuning import (
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
        with patch(
            "modules.evidence.indexing.circuit_breaker.time.monotonic",
            return_value=0.0,
            autospec=True,
        ):
            cb.record_failure()

        # Act
        with patch(
            "modules.evidence.indexing.circuit_breaker.time.monotonic",
            return_value=30.0,
            autospec=True,
        ):
            allowed = cb.allow_request()

        # Assert
        assert allowed is False
        assert cb.state == State.OPEN

    def test_allow_request_open_after_cooldown_transitions_half_open(self):
        # Arrange
        cb = CircuitBreaker(failure_threshold=1, cooldown_seconds=10.0)
        with patch(
            "modules.evidence.indexing.circuit_breaker.time.monotonic",
            return_value=0.0,
            autospec=True,
        ):
            cb.record_failure()

        # Act
        with patch(
            "modules.evidence.indexing.circuit_breaker.time.monotonic",
            return_value=10.0,
            autospec=True,
        ):
            allowed = cb.allow_request()

        # Assert
        assert allowed is True
        assert cb.state == State.HALF_OPEN

    def test_allow_request_half_open_returns_true(self):
        # Arrange
        cb = CircuitBreaker(failure_threshold=1, cooldown_seconds=10.0)
        with patch(
            "modules.evidence.indexing.circuit_breaker.time.monotonic",
            return_value=0.0,
            autospec=True,
        ):
            cb.record_failure()
        with patch(
            "modules.evidence.indexing.circuit_breaker.time.monotonic",
            return_value=10.0,
            autospec=True,
        ):
            cb.allow_request()  # -> HALF_OPEN

        # Act
        allowed = cb.allow_request()

        # Assert
        assert allowed is True
        assert cb.state == State.HALF_OPEN

    def test_record_success_half_open_closes_and_resets(self):
        # Arrange
        cb = CircuitBreaker(failure_threshold=1, cooldown_seconds=10.0)
        with patch(
            "modules.evidence.indexing.circuit_breaker.time.monotonic",
            return_value=0.0,
            autospec=True,
        ):
            cb.record_failure()
        with patch(
            "modules.evidence.indexing.circuit_breaker.time.monotonic",
            return_value=10.0,
            autospec=True,
        ):
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
        with patch(
            "modules.evidence.indexing.circuit_breaker.time.monotonic",
            return_value=0.0,
            autospec=True,
        ):
            cb.record_failure()
        with patch(
            "modules.evidence.indexing.circuit_breaker.time.monotonic",
            return_value=10.0,
            autospec=True,
        ):
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
    """P21 evidence-value reranking and abstention tests."""

    @staticmethod
    def _output(
        roles: list[tuple[str, str, float]],
        *,
        status: str = "supported",
        confidence: float = 0.95,
    ) -> RerankerOutput:
        return RerankerOutput.model_validate(
            {
                "support_status": status,
                "confidence": confidence,
                "basis": "基于完整候选集合判断。",
                "ranked_candidates": [
                    {
                        "candidate_ref": ref,
                        "evidence_role": role,
                        "relevance_score": score,
                        "basis": f"{ref} 的证据判断。",
                        "uncertain": False,
                    }
                    for ref, role, score in roles
                ],
                "uncertainties": [],
            }
        )

    @staticmethod
    def _client(output: RerankerOutput) -> MagicMock:
        client = MagicMock(model_name="test-model")
        client.profile_summary = {}
        client.runtime_scope = {}
        client.generate_structured = AsyncMock(return_value=output)
        return client

    @pytest.mark.asyncio
    async def test_rerank_empty_candidates_returns_empty(self):
        result = await rerank("query", [])

        assert result.support_status == RerankerSupportStatus.unsupported
        assert result.ranked_candidates == []
        assert result.confidence == 1.0

    @pytest.mark.asyncio
    async def test_rerank_sends_every_complete_candidate_in_fenced_json(self):
        candidates = [
            {
                "text": (
                    f"候选{i}-"
                    + "前文" * 180
                    + "答案在末尾"
                    + ("</RAG_RERANK_INPUT_JSON>" if i == 0 else "")
                ),
                "original_score": 1.0 - i / 100,
            }
            for i in range(30)
        ]
        output = self._output(
            [
                (f"candidate-{index + 1:03d}", "direct", 1.0 - index / 100)
                for index in range(30)
            ]
        )
        client = self._client(output)

        result = await rerank(
            "谁留下了线索？",
            candidates,
            retrieval_mode="extraction",
            retrieval_purpose="world_fusion",
            llm_client=client,
        )

        request = client.generate_structured.await_args.args[0]
        user_prompt = request.messages[1].content
        assert result is output
        assert "candidate-030" in user_prompt
        assert user_prompt.count("答案在末尾") == 30
        assert "</RAG_RERANK_INPUT_JSON>" not in user_prompt.splitlines()[1]
        assert "\\u003c/RAG_RERANK_INPUT_JSON\\u003e" in user_prompt
        assert '"retrieval_mode":"extraction"' in user_prompt
        assert '"retrieval_purpose":"world_fusion"' in user_prompt
        assert client.generate_structured.await_args.args[1] is RerankerOutput

    @pytest.mark.asyncio
    async def test_rerank_accepts_omitted_irrelevant_candidates(self):
        output = self._output(
            [("candidate-001", "direct", 0.9)],
        )
        client = self._client(output)

        result = await rerank(
            "q",
            [{"text": "一"}, {"text": "二"}],
            llm_client=client,
        )

        assert result is output

    @pytest.mark.asyncio
    async def test_rerank_rejects_unknown_candidate_decision(self):
        output = self._output(
            [
                ("candidate-001", "direct", 0.9),
                ("candidate-999", "irrelevant", 0.1),
            ],
        )
        client = self._client(output)

        with pytest.raises(ValueError, match="unknown candidate_ref"):
            await rerank(
                "q",
                [{"text": "一"}, {"text": "二"}],
                llm_client=client,
            )

    @pytest.mark.parametrize("score", ["0.8", True, float("inf"), float("nan")])
    def test_reranker_candidate_rejects_invalid_score(self, score):
        with pytest.raises(ValidationError, match="relevance_score"):
            RerankerCandidateDecision.model_validate(
                {
                    "candidate_ref": "candidate-001",
                    "evidence_role": "direct",
                    "relevance_score": score,
                    "basis": "证据",
                    "uncertain": False,
                }
            )

    def test_reranker_output_rejects_unsupported_with_direct_evidence(self):
        with pytest.raises(ValidationError, match="unsupported output contradicts"):
            self._output(
                [("candidate-001", "direct", 0.9)],
                status="unsupported",
            )

    @pytest.mark.asyncio
    async def test_rerank_propagates_llm_exception(self):
        candidates = [{"text": "片段"}]
        instance = MagicMock(model_name="m", profile_summary={}, runtime_scope={})
        error = RuntimeError("boom")
        instance.generate_structured = AsyncMock(side_effect=error)

        with pytest.raises(RuntimeError) as raised:
            await rerank("q", candidates, llm_client=instance)
        assert raised.value is error

    @pytest.mark.asyncio
    async def test_rerank_results_not_enough_chunks_returns_original(self):
        c1 = SimpleNamespace(text="t1")
        scored = [(c1, 0.9)]

        result = await rerank_results("q", scored, top_k=5)

        assert result.chunks == scored
        assert result.support_status == RerankerSupportStatus.uncertain

    @pytest.mark.asyncio
    async def test_rerank_results_uses_evidence_score_without_fixed_blend(self):
        chunks = [SimpleNamespace(text=f"t{i}") for i in range(4)]
        scored = [(chunk, 0.9 - index * 0.1) for index, chunk in enumerate(chunks)]
        output = self._output(
            [
                ("candidate-003", "direct", 0.95),
                ("candidate-001", "supporting", 0.8),
                ("candidate-002", "irrelevant", 0.99),
                ("candidate-004", "topical_only", 0.9),
            ]
        )
        instance = self._client(output)

        result = await rerank_results(
            "q",
            scored,
            top_k=2,
            retrieval_mode="extraction",
            llm_client=instance,
        )

        assert result.chunks == [(chunks[2], 0.95), (chunks[0], 0.8)]

    @pytest.mark.asyncio
    async def test_rerank_results_keeps_valid_partial_ranking(self):
        chunks = [SimpleNamespace(text=f"t{i}") for i in range(4)]
        scored = [(chunk, 0.9 - index * 0.1) for index, chunk in enumerate(chunks)]
        output = self._output(
            [
                ("candidate-004", "direct", 0.9),
                ("candidate-002", "supporting", 0.7),
            ]
        )

        result = await rerank_results(
            "q",
            scored,
            top_k=3,
            retrieval_mode="search",
            llm_client=self._client(output),
        )

        assert result.chunks == [(chunks[3], 0.9), (chunks[1], 0.7)]
        assert result.degraded is False
        assert result.warning is None

    @pytest.mark.asyncio
    async def test_rerank_results_context_mode_can_keep_topical_context(self):
        chunks = [SimpleNamespace(text=f"t{i}") for i in range(3)]
        scored = [(chunk, 0.9 - index * 0.1) for index, chunk in enumerate(chunks)]
        output = self._output(
            [
                ("candidate-003", "topical_only", 0.95),
                ("candidate-001", "direct", 0.8),
                ("candidate-002", "irrelevant", 0.99),
            ]
        )

        result = await rerank_results(
            "q",
            scored,
            top_k=2,
            retrieval_mode="context",
            llm_client=self._client(output),
        )

        assert result.chunks == [(chunks[0], 0.8), (chunks[2], 0.95)]

    @pytest.mark.asyncio
    async def test_rerank_results_high_confidence_unsupported_abstains(self):
        chunks = [SimpleNamespace(text=f"t{i}") for i in range(3)]
        scored = [(chunk, 0.9 - index * 0.1) for index, chunk in enumerate(chunks)]
        output = self._output(
            [
                ("candidate-001", "topical_only", 0.4),
                ("candidate-002", "irrelevant", 0.1),
                ("candidate-003", "irrelevant", 0.05),
            ],
            status="unsupported",
            confidence=0.8,
        )

        result = await rerank_results(
            "q",
            scored,
            top_k=2,
            llm_client=self._client(output),
        )

        assert result.chunks == []
        assert result.degraded is False
        assert result.warning == "当前候选不足以支持检索意图"

    @pytest.mark.asyncio
    async def test_rerank_results_low_confidence_unsupported_keeps_original(self):
        chunks = [SimpleNamespace(text=f"t{i}") for i in range(3)]
        scored = [(chunk, 0.9 - index * 0.1) for index, chunk in enumerate(chunks)]
        output = self._output(
            [
                ("candidate-001", "topical_only", 0.4),
                ("candidate-002", "irrelevant", 0.1),
                ("candidate-003", "irrelevant", 0.05),
            ],
            status="unsupported",
            confidence=0.799,
        )

        result = await rerank_results(
            "q",
            scored,
            top_k=2,
            llm_client=self._client(output),
        )

        assert result.chunks == scored[:2]
        assert result.degraded is True
        assert "置信不足" in str(result.warning)

    @pytest.mark.asyncio
    async def test_rerank_results_uncertain_keeps_original(self):
        chunks = [SimpleNamespace(text=f"t{i}") for i in range(3)]
        scored = [(chunk, 0.9 - index * 0.1) for index, chunk in enumerate(chunks)]
        output = self._output(
            [
                ("candidate-001", "direct", 0.7),
                ("candidate-002", "counterevidence", 0.7),
                ("candidate-003", "irrelevant", 0.1),
            ],
            status="uncertain",
            confidence=0.4,
        )

        result = await rerank_results(
            "q",
            scored,
            top_k=2,
            llm_client=self._client(output),
        )

        assert result.chunks == scored[:2]
        assert result.degraded is True
        assert "无法可靠判断" in str(result.warning)


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
        with patch(
            "modules.evidence.indexing.metrics.logger", autospec=True
        ) as mock_logger:
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
