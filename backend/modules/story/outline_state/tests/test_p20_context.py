from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from modules.story.outline_state import p20_context
from modules.story.outline_state.p20_context import P20ContextBuilder
from modules.story.outline_state.p20_schemas import OutlineLayerGenerateRequest


class _CharacterContextItem:
    def __init__(self, character_id: str, name: str) -> None:
        self.character_id = character_id
        self.name = name

    def model_dump(self, *, mode: str) -> dict:
        assert mode == "json"
        return {"character_id": self.character_id, "name": self.name}


class _EntityContextItem:
    def __init__(self, entity_id: str, name: str) -> None:
        self.entity_id = entity_id
        self.name = name

    def model_dump(self, *, mode: str) -> dict:
        assert mode == "json"
        return {
            "entity_id": self.entity_id,
            "name": self.name,
            "related_entity_ids": [],
        }


@pytest.mark.asyncio
async def test_world_context_uses_stable_top_k_as_asset_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    novel_id = str(uuid.uuid4())
    character_rows = [
        SimpleNamespace(entity_id=uuid.uuid4(), name=f"人物{i:02d}") for i in range(8)
    ]
    entity_rows = [
        {
            "id": str(uuid.uuid4()),
            "entity_type": "artifact",
            "name": f"物品{i:02d}",
        }
        for i in range(20)
    ]
    explicit_character = str(character_rows[-1].entity_id)
    explicit_entity = entity_rows[-1]["id"]
    list_characters = AsyncMock(return_value=(character_rows, len(character_rows)))
    list_entities = AsyncMock(return_value=entity_rows)

    async def character_context(_db, requested_novel, ids, *, reveal_mode):
        assert requested_novel == novel_id
        assert reveal_mode == "author_safe"
        names = {str(item.entity_id): item.name for item in character_rows}
        return SimpleNamespace(
            characters=[_CharacterContextItem(value, names[value]) for value in ids]
        )

    async def entity_context(
        _db,
        requested_novel,
        *,
        entity_ids,
        reveal_mode,
        limit,
    ):
        assert requested_novel == novel_id
        assert reveal_mode == "author_safe"
        assert limit == 16
        names = {str(item["id"]): item["name"] for item in entity_rows}
        return SimpleNamespace(
            entities=[_EntityContextItem(value, names[value]) for value in entity_ids]
        )

    monkeypatch.setattr(p20_context, "list_characters", list_characters)
    monkeypatch.setattr(p20_context, "list_entities", list_entities)
    monkeypatch.setattr(p20_context, "get_characters_context", character_context)
    monkeypatch.setattr(p20_context, "get_world_context", entity_context)
    request = OutlineLayerGenerateRequest.model_validate(
        {
            "novel_id": novel_id,
            "context_confirmation_id": str(uuid.uuid4()),
            "target": "plot_thread",
            "mode": "create",
            "instruction": "重点考虑人物06与物品18，但不要裁剪已确认正文。",
        }
    )

    characters, entities, _, _, selection = await P20ContextBuilder()._world_context(
        None,
        request,
        {
            "character_ids": [explicit_character],
            "entity_ids": [explicit_entity],
        },
        threads=[],
        arcs=[],
        scenes=[],
    )

    assert len(characters) == 6
    assert len(entities) == 16
    assert selection["included_asset_ids"]["characters"][0] == explicit_character
    assert selection["included_asset_ids"]["entities"][0] == explicit_entity
    assert len(selection["omitted_assets"]) == 6
    assert selection["top_k"]["characters"]["reason"] == (
        "explicit_then_instruction_outline_mention_then_scene_then_structure_affinity"
    )
    list_characters.assert_awaited_once_with(
        None,
        novel_id,
        skip=0,
        limit=50,
    )
    list_entities.assert_awaited_once_with(
        None,
        novel_id,
        statuses=("canonical",),
        limit=1000,
    )


def test_relevance_helpers_match_short_names_and_stable_scene_mentions() -> None:
    scenes = [
        SimpleNamespace(
            scene_index=10,
            title="克莱恩向梅丽莎隐瞒值夜者工作",
            goal="维持家庭生活",
            core_conflict=None,
            emotional_beat=None,
            must_happen=None,
            must_not_happen=None,
            structure_meta={},
        ),
        SimpleNamespace(
            scene_index=20,
            title="梅丽莎讨论搬家",
            goal=None,
            core_conflict=None,
            emotional_beat=None,
            must_happen=None,
            must_not_happen=None,
            structure_meta={},
        ),
    ]

    assert (
        P20ContextBuilder._name_mention_score(
            "克莱恩·莫雷蒂",
            "创作克莱恩身份与责任主线",
        )
        == 3
    )
    assert (
        P20ContextBuilder._name_mention_score(
            "安提哥努斯家族笔记",
            "安提哥努斯笔记保持未决",
        )
        >= 3
    )
    assert P20ContextBuilder._scene_mention_stats("梅丽莎·莫雷蒂", scenes) == (
        2,
        10,
    )
    assert (
        P20ContextBuilder._shared_ngram_score(
            "塔罗会与灰雾空间",
            "倒吊人是塔罗会成员",
        )
        > 0
    )


@pytest.mark.asyncio
async def test_character_top_k_reads_all_facade_pages_before_ranking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    novel_id = str(uuid.uuid4())
    rows = [
        SimpleNamespace(entity_id=uuid.uuid4(), name=f"普通人物{i:02d}")
        for i in range(55)
    ]
    tail = SimpleNamespace(entity_id=uuid.uuid4(), name="关键人物·尾页")
    rows.append(tail)

    async def paged_characters(_db, _novel_id, *, skip, limit):
        assert _novel_id == novel_id
        return rows[skip : skip + limit], len(rows)

    async def character_context(_db, _novel_id, ids, *, reveal_mode):
        assert reveal_mode == "author_safe"
        names = {str(item.entity_id): item.name for item in rows}
        return SimpleNamespace(
            characters=[_CharacterContextItem(value, names[value]) for value in ids]
        )

    monkeypatch.setattr(p20_context, "list_characters", paged_characters)
    monkeypatch.setattr(p20_context, "list_entities", AsyncMock(return_value=[]))
    monkeypatch.setattr(p20_context, "get_characters_context", character_context)
    monkeypatch.setattr(
        p20_context,
        "get_world_context",
        AsyncMock(return_value=SimpleNamespace(entities=[])),
    )
    request = OutlineLayerGenerateRequest.model_validate(
        {
            "novel_id": novel_id,
            "context_confirmation_id": str(uuid.uuid4()),
            "target": "plot_thread",
            "mode": "create",
            "instruction": "围绕关键人物的选择创作剧情线。",
        }
    )

    _, _, _, _, selection = await P20ContextBuilder()._world_context(
        None,
        request,
        {},
        threads=[],
        arcs=[],
        scenes=[],
    )

    assert str(tail.entity_id) in selection["included_asset_ids"]["characters"]
    assert selection["top_k"]["characters"]["candidate_count"] == 56


def test_structure_coverage_separates_materialized_and_planned_scenes() -> None:
    coverage = P20ContextBuilder._structure_coverage(
        [
            SimpleNamespace(
                structure_meta={"planning_state": "materialized"},
                chapter_ids=[2],
                scene_chunks=[{"chapter_index": 4}],
            ),
            SimpleNamespace(
                structure_meta={"planning_state": "planned"},
                chapter_ids=[],
                scene_chunks=[],
            ),
            SimpleNamespace(
                structure_meta={},
                chapter_ids=[9],
                scene_chunks=[],
            ),
        ]
    )

    assert coverage["materialized_scene_count"] == 2
    assert coverage["planned_scene_count"] == 1
    assert coverage["materialized_chapter_range"] == {"start": 2, "end": 9}
