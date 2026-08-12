"""
RAG 检索编排单元测试
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

import pytest

from modules.rag.query_expansion import QueryExpander
from modules.rag.repositories import RagChunkRepository
from modules.rag.reranker import (
    RERANKER_TOTAL_TIMEOUT_SECONDS,
    RerankerCandidateDecision,
    RerankerEvidenceRole,
    RerankerOutput,
    RerankerSupportStatus,
    RerankOutcome,
    rerank,
    rerank_results,
)
from modules.rag.retrieval import RetrievalOrchestrator, _is_rerank_enabled
from modules.rag.scoring import Scorer


def _rerank_test_chunk(novel_id: uuid.UUID, index: int):
    return type(
        "Chunk",
        (),
        {
            "id": uuid.uuid4(),
            "novel_id": novel_id,
            "source_type": "chapter_text",
            "source_id": None,
            "chapter_index": index + 1,
            "chunk_index": index,
            "start_offset": 0,
            "end_offset": 10,
            "char_count": 10,
            "text": f"候选 {index}",
            "summary": None,
            "entity_ids": [],
            "character_ids": [],
            "thread_ids": [],
            "visibility": "author_only",
            "importance": 0.5,
            "index_version": "cn-novel-v1",
            "embedding_status": "succeeded",
            "embedding_error": None,
            "index_warnings": [],
            "meta": {},
            "embedding": None,
        },
    )()


@pytest.fixture
def retrieval() -> RetrievalOrchestrator:
    return RetrievalOrchestrator(
        repo=RagChunkRepository(),
        scorer=Scorer(),
        query_expander=QueryExpander(),
    )


class TestRetrievalOrchestratorDedup:
    def test_deduplicate_by_embedding_keeps_larger_chunk(self) -> None:
        chunk_a = type(
            "Chunk",
            (),
            {"embedding": [1.0, 0.0], "char_count": 100},
        )()
        chunk_b = type(
            "Chunk",
            (),
            {"embedding": [1.0, 0.0], "char_count": 50},
        )()
        orch = RetrievalOrchestrator()
        result = orch._deduplicate_by_embedding([(chunk_a, 0.9), (chunk_b, 0.8)])
        assert len(result) == 1
        assert result[0][0] is chunk_a

    def test_deduplicate_skips_when_no_embedding(self) -> None:
        chunk_a = type("Chunk", (), {"embedding": None, "char_count": 100})()
        chunk_b = type("Chunk", (), {"embedding": None, "char_count": 50})()
        orch = RetrievalOrchestrator()
        result = orch._deduplicate_by_embedding([(chunk_a, 0.9), (chunk_b, 0.8)])
        assert len(result) == 2

    def test_deduplicate_limits_embedding_comparison_window(self, monkeypatch) -> None:
        calls = 0

        def _count_similarity(_a, _b):
            nonlocal calls
            calls += 1
            return 0.0

        monkeypatch.setattr("modules.rag.scoring.cosine_similarity", _count_similarity)
        chunks = [
            type(
                "Chunk",
                (),
                {
                    "embedding": [1.0 if i == j else 0.0 for j in range(80)],
                    "char_count": 100 + i,
                },
            )()
            for i in range(80)
        ]
        orch = RetrievalOrchestrator()

        result = orch._deduplicate_by_embedding(
            [(chunk, 1.0) for chunk in chunks],
            max_candidates=20,
        )

        assert len(result) == 80
        assert calls <= 190


class TestRetrievalOrchestratorInjected:
    @pytest.mark.asyncio
    async def test_reranker_drops_only_low_value_topical_noise(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        novel_id = uuid.uuid4()
        chunks = [_rerank_test_chunk(novel_id, index) for index in range(3)]

        async def fake_rerank(*_args, **_kwargs):
            return RerankerOutput(
                support_status=RerankerSupportStatus.supported,
                confidence=0.95,
                basis="直接答案与有价值背景足以支持查询。",
                ranked_candidates=[
                    RerankerCandidateDecision(
                        candidate_ref="candidate-001",
                        evidence_role=RerankerEvidenceRole.direct,
                        relevance_score=0.95,
                        basis="直接回答。",
                    ),
                    RerankerCandidateDecision(
                        candidate_ref="candidate-002",
                        evidence_role=RerankerEvidenceRole.topical_only,
                        relevance_score=0.35,
                        basis="有助于理解主题背景。",
                    ),
                    RerankerCandidateDecision(
                        candidate_ref="candidate-003",
                        evidence_role=RerankerEvidenceRole.topical_only,
                        relevance_score=0.05,
                        basis="仅提到同一专名。",
                    ),
                ],
                uncertainties=[],
            )

        monkeypatch.setattr("modules.rag.reranker.rerank", fake_rerank)

        outcome = await rerank_results(
            "从哪里知道这个事实？",
            [(chunk, 0.8 - index * 0.1) for index, chunk in enumerate(chunks)],
            top_k=2,
            retrieval_mode="search",
            llm_client=object(),  # type: ignore[arg-type]
        )

        assert [chunk.id for chunk, _score in outcome.chunks] == [
            chunks[0].id,
            chunks[1].id,
        ]
        assert [score for _chunk, score in outcome.chunks] == [0.95, 0.35]

    @pytest.mark.asyncio
    async def test_reranker_role_tier_keeps_direct_evidence_above_topical_score(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        novel_id = uuid.uuid4()
        chunks = [_rerank_test_chunk(novel_id, index) for index in range(3)]

        async def fake_rerank(*_args, **_kwargs):
            return RerankerOutput(
                support_status=RerankerSupportStatus.supported,
                confidence=0.9,
                basis="直接证据回答时间边界后的变化。",
                ranked_candidates=[
                    RerankerCandidateDecision(
                        candidate_ref="candidate-001",
                        evidence_role=RerankerEvidenceRole.topical_only,
                        relevance_score=0.95,
                        basis="只在更早阶段提到同一概念。",
                    ),
                    RerankerCandidateDecision(
                        candidate_ref="candidate-003",
                        evidence_role=RerankerEvidenceRole.direct,
                        relevance_score=0.8,
                        basis="直接展示查询所问的变化。",
                    ),
                    RerankerCandidateDecision(
                        candidate_ref="candidate-002",
                        evidence_role=RerankerEvidenceRole.direct,
                        relevance_score=0.8,
                        basis="同层同分，但模型将其排在后一位。",
                    ),
                ],
                uncertainties=[],
            )

        monkeypatch.setattr("modules.rag.reranker.rerank", fake_rerank)

        outcome = await rerank_results(
            "服药之后如何逐步理解力量边界？",
            [(chunk, 0.9 - index * 0.1) for index, chunk in enumerate(chunks)],
            top_k=2,
            retrieval_mode="search",
            llm_client=object(),  # type: ignore[arg-type]
        )

        assert [chunk.id for chunk, _score in outcome.chunks] == [
            chunks[2].id,
            chunks[1].id,
        ]

    @pytest.mark.parametrize("mode", ["search", "context", "extraction"])
    def test_enabled_reranker_supports_every_retrieval_mode(self, mode: str) -> None:
        with patch(
            "core.config.get_settings",
            return_value=type("Settings", (), {"reranker_enabled": True})(),
            autospec=True,
        ):
            assert _is_rerank_enabled(mode) is True

    def test_enabled_reranker_rejects_unknown_mode(self) -> None:
        with patch(
            "core.config.get_settings",
            return_value=type("Settings", (), {"reranker_enabled": True})(),
            autospec=True,
        ):
            assert _is_rerank_enabled("unknown") is False

    @pytest.mark.asyncio
    async def test_reranker_failure_keeps_original_order_and_returns_warning(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        novel_id = uuid.uuid4()
        chunks = [_rerank_test_chunk(novel_id, index) for index in range(4)]
        original = [(chunk, 1.0 - index * 0.1) for index, chunk in enumerate(chunks)]
        lifecycle: list[str] = []

        @asynccontextmanager
        async def open_project_client(
            actual_db,
            actual_novel_id,
            *,
            timeout_override,
        ):
            assert actual_db is None
            assert actual_novel_id == str(novel_id)
            assert timeout_override == RERANKER_TOTAL_TIMEOUT_SECONDS
            lifecycle.append("entered")
            try:
                yield object()
            finally:
                lifecycle.append("exited")

        class _Metrics:
            def record(self, **kwargs) -> None:
                pass

        repo = type("Repo", (), {"has_embeddings": AsyncMock(return_value=False)})()
        orchestrator = RetrievalOrchestrator(
            repo=repo,  # type: ignore[arg-type]
            metrics=lambda: _Metrics(),
        )
        orchestrator.hybrid_search = AsyncMock(return_value=original)  # type: ignore[method-assign]
        monkeypatch.setattr(
            "modules.project.facade.open_project_llm_client",
            open_project_client,
        )
        secret = "private-token-value"
        rerank_mock = AsyncMock(
            side_effect=RuntimeError(
                f"reranker unavailable Authorization: Bearer {secret} api_key={secret}"
            )
        )
        monkeypatch.setattr(
            "modules.rag.reranker.rerank",
            rerank_mock,
        )
        monkeypatch.setattr(
            "modules.rag.retrieval._is_rerank_enabled",
            lambda _mode: True,
        )

        result = await orchestrator.retrieve(
            None,  # type: ignore[arg-type]
            novel_id,
            "灰雾",
            mode="extraction",
            top_k=2,
            retrieval_purpose="world_fusion",
        )

        assert [chunk.id for chunk in result.chunks] == [
            str(chunks[0].id),
            str(chunks[1].id),
        ]
        assert len(result.warnings) == 1
        assert result.warnings[0].startswith(
            "重排序失败，使用原始排序: reranker unavailable"
        )
        assert secret not in result.warnings[0]
        assert result.degraded is True
        assert lifecycle == ["entered", "exited"]
        assert rerank_mock.await_args.kwargs["retrieval_mode"] == "extraction"
        assert rerank_mock.await_args.kwargs["retrieval_purpose"] == "world_fusion"

    @pytest.mark.asyncio
    async def test_reranker_managed_step_uses_full_total_timeout(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        output = RerankerOutput(
            support_status=RerankerSupportStatus.supported,
            confidence=0.9,
            basis="候选直接支持查询。",
            ranked_candidates=[
                RerankerCandidateDecision(
                    candidate_ref="candidate-001",
                    evidence_role=RerankerEvidenceRole.direct,
                    relevance_score=0.9,
                    basis="正文直接陈述。",
                ),
            ],
            uncertainties=[],
        )
        managed = AsyncMock(return_value=output)
        monkeypatch.setattr(
            "modules.rag.reranker.run_managed_structured",
            managed,
        )
        client = type("Client", (), {"model_name": "test-model"})()

        result = await rerank(
            "克莱恩为何加入值夜者？",
            [{"text": "他接受邀请加入值夜者。", "chapter_index": 14}],
            llm_client=client,  # type: ignore[arg-type]
        )

        assert result == output
        assert managed.await_args.kwargs["timeout"] == RERANKER_TOTAL_TIMEOUT_SECONDS

    @pytest.mark.asyncio
    async def test_reranker_abstention_returns_empty_without_degraded(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        novel_id = uuid.uuid4()
        chunks = [_rerank_test_chunk(novel_id, index) for index in range(4)]
        original = [(chunk, 1.0 - index * 0.1) for index, chunk in enumerate(chunks)]

        async def fake_reranker(query, scored_chunks, *, top_k):
            assert query == "不存在的事实"
            assert len(scored_chunks) == 4
            assert top_k == 2
            return RerankOutcome(
                chunks=[],
                support_status=RerankerSupportStatus.unsupported,
                warning="当前候选不足以支持检索意图",
            )

        class _Metrics:
            def record(self, **kwargs) -> None:
                pass

        repo = type("Repo", (), {"has_embeddings": AsyncMock(return_value=False)})()
        orchestrator = RetrievalOrchestrator(
            repo=repo,  # type: ignore[arg-type]
            reranker_fn=fake_reranker,
            metrics=lambda: _Metrics(),
        )
        orchestrator.hybrid_search = AsyncMock(return_value=original)  # type: ignore[method-assign]
        monkeypatch.setattr(
            "modules.rag.retrieval._is_rerank_enabled",
            lambda _mode: True,
        )

        result = await orchestrator.retrieve(
            None,  # type: ignore[arg-type]
            novel_id,
            "不存在的事实",
            mode="search",
            top_k=2,
        )

        assert result.chunks == []
        assert result.warnings == ["当前候选不足以支持检索意图"]
        assert result.degraded is False

    @pytest.mark.asyncio
    async def test_enabled_reranker_receives_more_than_final_top_k(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        novel_id = uuid.uuid4()
        chunks = [
            type(
                "Chunk",
                (),
                {
                    "id": uuid.uuid4(),
                    "novel_id": novel_id,
                    "source_type": "chapter_text",
                    "source_id": None,
                    "chapter_index": index + 1,
                    "chunk_index": index,
                    "start_offset": 0,
                    "end_offset": 10,
                    "char_count": 10,
                    "text": f"候选 {index}",
                    "summary": None,
                    "entity_ids": [],
                    "character_ids": [],
                    "thread_ids": [],
                    "visibility": "author_only",
                    "importance": 0.5,
                    "index_version": "cn-novel-v1",
                    "embedding_status": "succeeded",
                    "embedding_error": None,
                    "index_warnings": [],
                    "meta": {},
                    "embedding": None,
                },
            )()
            for index in range(4)
        ]
        rerank_calls: list[int] = []

        async def fake_reranker(query, scored_chunks, *, top_k):
            assert query == "灰雾"
            rerank_calls.append(len(scored_chunks))
            return list(reversed(scored_chunks))[:top_k]

        class _Metrics:
            def record(self, **kwargs) -> None:
                pass

        repo = type("Repo", (), {"has_embeddings": AsyncMock(return_value=False)})()
        orchestrator = RetrievalOrchestrator(
            repo=repo,  # type: ignore[arg-type]
            reranker_fn=fake_reranker,
            metrics=lambda: _Metrics(),
        )
        orchestrator.hybrid_search = AsyncMock(  # type: ignore[method-assign]
            return_value=[
                (chunk, 1.0 - index * 0.1) for index, chunk in enumerate(chunks)
            ]
        )
        monkeypatch.setattr(
            "modules.rag.retrieval._is_rerank_enabled",
            lambda _mode: True,
        )

        result = await orchestrator.retrieve(
            None,  # type: ignore[arg-type]
            novel_id,
            "灰雾",
            mode="extraction",
            top_k=2,
        )

        assert orchestrator.hybrid_search.await_args.kwargs["top_k"] == 4
        assert rerank_calls == [4]
        assert len(result.chunks) == 2

    @pytest.mark.asyncio
    async def test_default_circuit_breaker_provider_uses_novel_id(self) -> None:
        novel_id = uuid.uuid4()
        breaker = type(
            "CB",
            (),
            {
                "allow_request": lambda self: False,
                "record_success": lambda self: None,
                "record_failure": lambda self: None,
            },
        )()
        repo = type(
            "Repo",
            (),
            {
                "has_embeddings": AsyncMock(return_value=True),
                "keyword_search": AsyncMock(return_value=[]),
            },
        )()

        class _Metrics:
            def record(self, **kwargs) -> None:
                pass

        async def _fake_expand(db, novel_id, query, **kwargs):
            return query

        expander = QueryExpander(term_loader=lambda db, nid: [])
        expander.expand = _fake_expand  # type: ignore[method-assign]

        with patch(
            "modules.rag.retrieval.get_circuit_breaker",
            return_value=breaker,
            autospec=True,
        ) as get_cb:
            orch = RetrievalOrchestrator(
                repo=repo,  # type: ignore[arg-type]
                query_expander=expander,
                embedder_fn=AsyncMock(return_value=[1.0, 0.0]),
                metrics=lambda: _Metrics(),
            )
            bundle = await orch.retrieve(
                None,  # type: ignore[arg-type]
                novel_id,
                "灰雾",
            )

        get_cb.assert_called_once_with(novel_id)
        assert bundle.degraded is True
        assert "BGE 服务熔断中" in bundle.warnings[0]

    @pytest.mark.asyncio
    async def test_retrieve_includes_vector_only_candidates(self) -> None:
        fake_chunk = type(
            "Chunk",
            (),
            {
                "id": uuid.uuid4(),
                "novel_id": uuid.uuid4(),
                "source_type": "chapter_text",
                "source_id": None,
                "chapter_index": 1,
                "chunk_index": 0,
                "start_offset": 0,
                "end_offset": 12,
                "char_count": 12,
                "text": "完全不同的片段文本",
                "summary": None,
                "entity_ids": [],
                "character_ids": [],
                "thread_ids": [],
                "visibility": "author_only",
                "importance": 0.5,
                "index_version": "cn-novel-v1",
                "embedding_status": "succeeded",
                "embedding_error": None,
                "index_warnings": [],
                "meta": {},
                "embedding": [1.0, 0.0],
            },
        )()

        repo = type(
            "Repo",
            (),
            {
                "has_embeddings": AsyncMock(return_value=True),
                "keyword_search": AsyncMock(return_value=[]),
                "vector_search": AsyncMock(return_value=[(fake_chunk, 0.99)]),
            },
        )()

        class _Metrics:
            def record(self, **kwargs) -> None:
                pass

        async def _fake_expand(db, novel_id, query, **kwargs):
            return query

        expander = QueryExpander(term_loader=lambda db, nid: [])
        expander.expand = _fake_expand  # type: ignore[method-assign]

        orch = RetrievalOrchestrator(
            repo=repo,  # type: ignore[arg-type]
            query_expander=expander,
            embedder_fn=AsyncMock(return_value=[1.0, 0.0]),
            metrics=lambda: _Metrics(),
            circuit_breaker=lambda _novel_id: type(
                "CB",
                (),
                {
                    "allow_request": lambda self: True,
                    "record_success": lambda self: None,
                    "record_failure": lambda self: None,
                },
            )(),
        )

        bundle = await orch.retrieve(
            None,  # type: ignore[arg-type]
            uuid.uuid4(),
            "语义相关但无关键词",
        )

        assert [chunk.id for chunk in bundle.chunks] == [str(fake_chunk.id)]
        repo.vector_search.assert_awaited_once()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("similarity", "expected_count"),
        [(0.64, 0), (0.65, 1)],
    )
    async def test_vector_only_match_requires_meaningful_similarity(
        self,
        similarity: float,
        expected_count: int,
    ) -> None:
        orthogonal = (1.0 - similarity**2) ** 0.5
        fake_chunk = _rerank_test_chunk(uuid.uuid4(), 0)
        fake_chunk.text = "没有字面命中的正文"
        fake_chunk.embedding = [similarity, orthogonal]
        repo = type(
            "Repo",
            (),
            {
                "keyword_search": AsyncMock(return_value=[]),
                "vector_search": AsyncMock(return_value=[(fake_chunk, similarity)]),
            },
        )()

        async def _fake_expand(db, novel_id, query, **kwargs):
            return query

        expander = QueryExpander(term_loader=lambda db, nid: [])
        expander.expand = _fake_expand  # type: ignore[method-assign]
        orch = RetrievalOrchestrator(
            repo=repo,  # type: ignore[arg-type]
            query_expander=expander,
        )

        results = await orch.hybrid_search(
            None,  # type: ignore[arg-type]
            fake_chunk.novel_id,
            "语义查询",
            query_embedding=[1.0, 0.0],
        )

        assert len(results) == expected_count

    @pytest.mark.asyncio
    async def test_retrieve_uses_injected_embedder_and_metrics(self) -> None:
        fake_chunk = type(
            "Chunk",
            (),
            {
                "id": uuid.uuid4(),
                "novel_id": uuid.uuid4(),
                "source_type": "chapter_text",
                "source_id": None,
                "chapter_index": 1,
                "chunk_index": 0,
                "start_offset": 0,
                "end_offset": 10,
                "char_count": 10,
                "text": "测试文本",
                "summary": None,
                "entity_ids": [],
                "character_ids": [],
                "thread_ids": [],
                "visibility": "author_only",
                "importance": 0.5,
                "index_version": "cn-novel-v1",
                "embedding_status": "succeeded",
                "embedding_error": None,
                "index_warnings": [],
                "meta": {},
                "embedding": None,
            },
        )()

        repo = type(
            "Repo",
            (),
            {
                "has_embeddings": AsyncMock(return_value=False),
                "keyword_search": AsyncMock(return_value=[fake_chunk]),
            },
        )()

        class _Metrics:
            def record(self, **kwargs) -> None:
                pass

        metrics = _Metrics()

        def _get_metrics():
            return metrics

        embedder = AsyncMock(return_value=[0.1, 0.2])

        async def _fake_expand(db, novel_id, query, **kwargs):
            return query

        expander = QueryExpander(term_loader=lambda db, nid: [])
        expander.expand = _fake_expand  # type: ignore[method-assign]

        orch = RetrievalOrchestrator(
            repo=repo,  # type: ignore[arg-type]
            query_expander=expander,
            embedder_fn=embedder,
            metrics=_get_metrics,
            circuit_breaker=lambda _novel_id: type(
                "CB",
                (),
                {"allow_request": lambda: True, "record_success": lambda: None},
            )(),
        )

        bundle = await orch.retrieve(
            None,  # type: ignore[arg-type]
            uuid.uuid4(),
            "测试",
        )
        assert bundle.total == 1
        assert len(bundle.chunks) == 1
        # embedding 不可用，embedder 不应被调用
        embedder.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_retrieve_records_stage_latency_metrics(self) -> None:
        fake_chunk = type(
            "Chunk",
            (),
            {
                "id": uuid.uuid4(),
                "novel_id": uuid.uuid4(),
                "source_type": "chapter_text",
                "source_id": None,
                "chapter_index": 1,
                "chunk_index": 0,
                "start_offset": 0,
                "end_offset": 10,
                "char_count": 10,
                "text": "灰雾中的测试文本",
                "summary": None,
                "entity_ids": [],
                "character_ids": [],
                "thread_ids": [],
                "visibility": "author_only",
                "importance": 0.5,
                "index_version": "cn-novel-v1",
                "embedding_status": "succeeded",
                "embedding_error": None,
                "index_warnings": [],
                "meta": {},
                "embedding": [0.1, 0.2],
            },
        )()

        repo = type(
            "Repo",
            (),
            {
                "has_embeddings": AsyncMock(return_value=True),
                "keyword_search": AsyncMock(return_value=[fake_chunk]),
                "vector_search": AsyncMock(return_value=[]),
            },
        )()

        class _Metrics:
            def __init__(self) -> None:
                self.calls = []

            def record(self, **kwargs) -> None:
                self.calls.append(kwargs)

        metrics = _Metrics()

        async def _fake_expand(db, novel_id, query, **kwargs):
            return query

        expander = QueryExpander(term_loader=lambda db, nid: [])
        expander.expand = _fake_expand  # type: ignore[method-assign]

        orch = RetrievalOrchestrator(
            repo=repo,  # type: ignore[arg-type]
            query_expander=expander,
            embedder_fn=AsyncMock(return_value=[0.1, 0.2]),
            metrics=lambda: metrics,
            circuit_breaker=lambda _novel_id: type(
                "CB",
                (),
                {
                    "allow_request": lambda self: True,
                    "record_success": lambda self: None,
                    "record_failure": lambda self: None,
                },
            )(),
        )

        await orch.retrieve(None, uuid.uuid4(), "灰雾")  # type: ignore[arg-type]

        call = metrics.calls[-1]
        assert call["embedding_ms"] >= 0
        assert call["search_ms"] >= 0
        assert call["rerank_ms"] >= 0
