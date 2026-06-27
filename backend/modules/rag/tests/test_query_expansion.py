"""
RAG 查询扩展单元测试
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from modules.rag.query_expansion import (
    QueryExpander,
    _cn_ngrams,
    _match_project_terms,
)


class TestCnNgrams:
    def test_chinese_ngrams(self) -> None:
        grams = _cn_ngrams("克莱恩")
        assert "克莱" in grams
        assert "莱恩" in grams
        assert "克莱恩" in grams

    def test_non_chinese_returns_empty(self) -> None:
        assert _cn_ngrams("hello world") == []

    def test_respects_max_n(self) -> None:
        grams = _cn_ngrams("一二三四五六", max_n=3)
        assert max(len(g) for g in grams) <= 3


class TestMatchProjectTerms:
    def test_match_character(self) -> None:
        terms = [{"term": "周明瑞", "id": "char-1", "type": "character"}]
        chars, entities, threads = _match_project_terms("周明瑞醒来", terms)
        assert chars == ["char-1"]
        assert entities == []

    def test_match_entity(self) -> None:
        terms = [{"term": "灰雾", "id": "ent-1", "type": "entity"}]
        chars, entities, threads = _match_project_terms("灰雾翻涌", terms)
        assert entities == ["ent-1"]

    def test_deduplicates_by_type_id(self) -> None:
        terms = [
            {"term": "克莱恩", "id": "char-1", "type": "character"},
            {"term": "周明瑞", "id": "char-1", "type": "character"},
        ]
        chars, _, _ = _match_project_terms("克莱恩醒来，周明瑞头疼", terms)
        assert chars == ["char-1"]


class TestQueryExpander:
    @pytest.mark.asyncio
    async def test_injectable_term_loader(self) -> None:
        async def _fake_loader(db: Any, novel_id: uuid.UUID) -> list[dict[str, str]]:
            return [{"term": "周明瑞", "id": "char-1", "type": "character"}]

        expander = QueryExpander(term_loader=_fake_loader)
        result = await expander.expand(
            None,  # type: ignore[arg-type]
            uuid.uuid4(),
            "克莱恩",
            character_ids=["char-1"],
        )
        assert "克莱恩" in result
        assert "周明瑞" in result

    @pytest.mark.asyncio
    async def test_empty_terms_returns_query(self) -> None:
        async def _empty(db: Any, novel_id: uuid.UUID) -> list[dict[str, str]]:
            return []

        expander = QueryExpander(term_loader=_empty)
        result = await expander.expand(None, uuid.uuid4(), "测试")  # type: ignore[arg-type]
        assert result == "测试"
