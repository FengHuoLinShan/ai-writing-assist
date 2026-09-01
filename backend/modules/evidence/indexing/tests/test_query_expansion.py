"""
RAG 查询扩展单元测试
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from modules.evidence.indexing.query_expansion import (
    QueryExpander,
    _load_project_terms,
    _match_project_terms,
    clear_project_terms_cache,
)


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

    @pytest.mark.asyncio
    async def test_exact_terms_and_unambiguous_name_prefixes_expand_aliases(self) -> None:
        async def _fake_loader(db: Any, novel_id: uuid.UUID) -> list[dict[str, str]]:
            return [
                {"term": "克莱恩", "id": "char-1", "type": "character"},
                {"term": "周明瑞", "id": "char-1", "type": "character"},
                {"term": "莱恩河", "id": "place-1", "type": "entity"},
                {"term": "亚伯拉罕家族", "id": "group-1", "type": "entity"},
            ]

        expander = QueryExpander(term_loader=_fake_loader)
        result = await expander.expand(
            None,  # type: ignore[arg-type]
            uuid.uuid4(),
            "克莱恩后来为什么改变了立场？",
        )

        assert result.split() == ["克莱恩后来为什么改变了立场？", "克莱恩", "周明瑞"]
        assert "莱恩河" not in result

        short_partial = await expander.expand(
            None,  # type: ignore[arg-type]
            uuid.uuid4(),
            "克莱",
        )
        assert short_partial == "克莱"

        async def _canonical_loader(db: Any, novel_id: uuid.UUID) -> list[dict[str, str]]:
            return [
                {
                    "term": "克莱恩·莫雷蒂",
                    "id": "char-1",
                    "type": "character",
                },
                {"term": "周明瑞", "id": "char-1", "type": "character"},
            ]

        canonical_expander = QueryExpander(term_loader=_canonical_loader)
        canonical_name = await canonical_expander.expand(
            None,  # type: ignore[arg-type]
            uuid.uuid4(),
            "克莱恩",
        )
        assert canonical_name.split() == [
            "克莱恩",
            "克莱恩·莫雷蒂",
            "周明瑞",
        ]

        async def _ambiguous_loader(db: Any, novel_id: uuid.UUID) -> list[dict[str, str]]:
            return [
                {
                    "term": "克莱恩·莫雷蒂",
                    "id": "char-1",
                    "type": "character",
                },
                {"term": "克莱恩河谷", "id": "place-1", "type": "entity"},
            ]

        ambiguous = await QueryExpander(term_loader=_ambiguous_loader).expand(
            None,  # type: ignore[arg-type]
            uuid.uuid4(),
            "克莱恩",
        )
        assert ambiguous == "克莱恩"

        long_partial = await expander.expand(
            None,  # type: ignore[arg-type]
            uuid.uuid4(),
            "亚伯拉罕家",
        )
        assert long_partial == "亚伯拉罕家"


class TestLoadProjectTerms:
    def teardown_method(self) -> None:
        clear_project_terms_cache()

    @pytest.mark.asyncio
    async def test_loads_entity_terms_without_unused_character_query(self) -> None:
        from app.bootstrap import register_container_services
        from core.container import register, reset

        calls: list[str] = []

        async def _list_characters(*args: Any, **kwargs: Any):
            calls.append("characters")
            raise AssertionError("unused character listing should not be called")

        async def _list_entity_terms(*args: Any, **kwargs: Any):
            calls.append("entity_terms")
            return [
                {
                    "id": "entity-1",
                    "entity_type": "character",
                    "terms": ["克莱恩", "周明瑞"],
                }
            ]

        reset()
        register("world.list_characters", _list_characters)
        register("world.list_entity_terms", _list_entity_terms)
        try:
            terms = await _load_project_terms(None, uuid.uuid4())  # type: ignore[arg-type]
        finally:
            reset()
            register_container_services()

        assert calls == ["entity_terms"]
        assert terms == [
            {"term": "克莱恩", "id": "entity-1", "type": "character"},
            {"term": "周明瑞", "id": "entity-1", "type": "character"},
        ]

    @pytest.mark.asyncio
    async def test_loads_entity_terms_from_novel_scoped_cache(self) -> None:
        from app.bootstrap import register_container_services
        from core.container import register, reset

        calls = 0
        novel_id = uuid.uuid4()

        async def _list_entity_terms(*args: Any, **kwargs: Any):
            nonlocal calls
            calls += 1
            return [{"id": "entity-1", "terms": ["灰雾"]}]

        reset()
        clear_project_terms_cache()
        register("world.list_entity_terms", _list_entity_terms)
        try:
            first = await _load_project_terms(None, novel_id)  # type: ignore[arg-type]
            second = await _load_project_terms(None, novel_id)  # type: ignore[arg-type]
        finally:
            reset()
            clear_project_terms_cache()
            register_container_services()

        assert calls == 1
        assert first == second == [{"term": "灰雾", "id": "entity-1", "type": "entity"}]

    @pytest.mark.asyncio
    async def test_world_term_failure_logs_and_keeps_best_effort_result(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        from app.bootstrap import register_container_services
        from core.container import register, reset

        novel_id = uuid.uuid4()

        async def _fail_entity_terms(*_args: Any, **_kwargs: Any):
            raise RuntimeError("api_key=credential-value")

        reset()
        clear_project_terms_cache()
        register("world.list_entity_terms", _fail_entity_terms)
        try:
            with caplog.at_level(
                "WARNING",
                logger="modules.evidence.indexing.query_expansion",
            ):
                terms = await _load_project_terms(
                    None,  # type: ignore[arg-type]
                    novel_id,
                )
        finally:
            reset()
            clear_project_terms_cache()
            register_container_services()

        assert terms == []
        record = next(
            item
            for item in caplog.records
            if "rag_project_terms_load_failed" in item.getMessage()
        )
        assert str(novel_id) in record.getMessage()
        assert record.exc_info is None
        assert "credential-value" not in record.getMessage()
        assert "[REDACTED]" in record.getMessage()
