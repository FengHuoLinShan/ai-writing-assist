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
    _load_project_terms,
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


class TestLoadProjectTerms:
    @pytest.mark.asyncio
    async def test_loads_entity_terms_without_unused_character_query(self) -> None:
        from app.main import _register_container_services
        from core.container import register, reset

        calls: list[str] = []

        async def _list_characters(*args: Any, **kwargs: Any):
            calls.append("characters")
            raise AssertionError("unused character listing should not be called")

        async def _list_entity_terms(*args: Any, **kwargs: Any):
            calls.append("entity_terms")
            return [{
                "id": "entity-1",
                "terms": ["克莱恩", "周明瑞"],
            }]

        reset()
        register("world.list_characters", _list_characters)
        register("world.list_entity_terms", _list_entity_terms)
        try:
            terms = await _load_project_terms(None, uuid.uuid4())  # type: ignore[arg-type]
        finally:
            reset()
            _register_container_services()

        assert calls == ["entity_terms"]
        assert terms == [
            {"term": "克莱恩", "id": "entity-1", "type": "entity"},
            {"term": "周明瑞", "id": "entity-1", "type": "entity"},
        ]
