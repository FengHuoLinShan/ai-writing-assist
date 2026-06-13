"""
RAG 检索编排单元测试
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest

from modules.rag.query_expansion import QueryExpander
from modules.rag.repositories import RagChunkRepository
from modules.rag.retrieval import RetrievalOrchestrator
from modules.rag.scoring import Scorer


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


class TestRetrievalOrchestratorInjected:
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
            circuit_breaker=lambda: type(
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
