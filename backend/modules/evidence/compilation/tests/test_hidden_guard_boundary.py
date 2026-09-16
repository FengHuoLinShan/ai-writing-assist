from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from modules.evidence.compilation.services.hidden_guard import HiddenGuardBuilder
from modules.world.contracts import CoreEntityContract, EntityRelationContract


@pytest.mark.asyncio
async def test_hidden_guard_uses_world_facade_and_preserves_guard_rules(
    monkeypatch,
) -> None:
    novel_id = str(uuid.uuid4())
    character_id = str(uuid.uuid4())
    entity_id = str(uuid.uuid4())
    relation_id = str(uuid.uuid4())
    captured = {}

    async def knowledge(*_args, **_kwargs):
        return []

    async def sources(_db, **kwargs):
        captured.update(kwargs)
        return (
            [
                CoreEntityContract(
                    novel_id=novel_id,
                    entity_id=entity_id,
                    entity_type="character",
                    name="守门人",
                    hidden_truth="他其实是密道的守护者",
                )
            ],
            [
                EntityRelationContract(
                    novel_id=novel_id,
                    relation_id=relation_id,
                    source_id=entity_id,
                    target_id=str(uuid.uuid4()),
                    relation_type="guards",
                    description="守护者知道旧塔底部的真实入口",
                )
            ],
        )

    monkeypatch.setattr(
        "modules.world.facade.get_character_knowledge_context",
        knowledge,
    )
    monkeypatch.setattr("modules.world.facade.get_hidden_guard_sources", sources)
    context = SimpleNamespace(
        compile_options={"viewpoint_character_id": character_id},
        confirmation=SimpleNamespace(novel_id=novel_id),
        compiled=SimpleNamespace(
            sections=[
                SimpleNamespace(
                    key="world",
                    content="",
                    sources=[
                        {"type": "world_entity", "id": entity_id},
                        {"type": "entity_relation", "id": relation_id},
                    ],
                )
            ]
        ),
    )

    terms = await HiddenGuardBuilder().build(SimpleNamespace(), context)

    assert captured == {
        "novel_id": novel_id,
        "entity_ids": [entity_id],
        "relation_ids": [relation_id],
    }
    assert [(item.rule, item.severity) for item in terms] == [
        ("hidden_truth_match", "error"),
        ("hidden_relation_match", "warning"),
    ]
