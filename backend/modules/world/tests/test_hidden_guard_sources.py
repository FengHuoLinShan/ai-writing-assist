from __future__ import annotations

import uuid

import pytest

from modules.project.models import Project
from modules.world.facade import get_hidden_guard_sources
from modules.world.models import CoreEntity, EntityRelation


@pytest.mark.asyncio
async def test_hidden_guard_sources_are_exact_and_project_scoped(
    db_session,
    test_project_id,
) -> None:
    novel_id = uuid.UUID(test_project_id)
    source = CoreEntity(
        novel_id=novel_id,
        entity_type="character",
        name="守门人",
        hidden_truth="他其实是密道的守护者",
        status="deprecated",
    )
    target = CoreEntity(
        novel_id=novel_id,
        entity_type="location",
        name="旧塔",
        status="canonical",
    )
    db_session.add_all([source, target])
    await db_session.flush()
    relation = EntityRelation(
        novel_id=novel_id,
        source_id=source.id,
        target_id=target.id,
        relation_type="guards",
        description="守护者知道旧塔底部的真实入口",
        status="deprecated",
    )
    db_session.add(relation)
    await db_session.flush()

    entities, relations = await get_hidden_guard_sources(
        db_session,
        novel_id=test_project_id,
        entity_ids=[str(source.id)],
        relation_ids=[str(relation.id)],
    )

    assert [(item.entity_id, item.hidden_truth, item.status) for item in entities] == [
        (str(source.id), "他其实是密道的守护者", "deprecated")
    ]
    assert [(item.relation_id, item.description, item.status) for item in relations] == [
        (str(relation.id), "守护者知道旧塔底部的真实入口", "deprecated")
    ]

    other_id = uuid.uuid4()
    owner = await db_session.get(Project, novel_id)
    assert owner is not None
    db_session.add(
        Project(id=other_id, title="Other trace project", owner_id=owner.owner_id)
    )
    await db_session.flush()
    other_entities, other_relations = await get_hidden_guard_sources(
        db_session,
        novel_id=str(other_id),
        entity_ids=[str(source.id)],
        relation_ids=[str(relation.id)],
    )
    assert other_entities == []
    assert other_relations == []
