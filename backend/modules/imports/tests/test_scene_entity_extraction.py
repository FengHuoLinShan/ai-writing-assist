"""SceneEntityExtractionService 单元/集成测试。

覆盖 Phase 2 的实体/关系持久化、auto_ingested 元数据、Delta 记录。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, Mock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from modules.imports.llm_schemas import (
    DeltaEvent,
    ExtractedEntity,
    ExtractedRelation,
)
from modules.imports.scene_entity_extraction import SceneEntityExtractionService


@pytest.fixture
async def novel_with_drafts(db_session: AsyncSession):
    """创建一个项目并写入第 1、2 章 draft。"""
    from modules.project.schemas import ProjectCreate
    from modules.project.services import ProjectService
    from modules.writing.facade import create_draft_only

    project = await ProjectService().create_project(
        db_session,
        ProjectCreate(title="Scene Extraction Test", language="zh"),
    )
    novel_id = str(project.id)
    await create_draft_only(
        db_session,
        novel_id,
        chapter_index=1,
        title="第一章",
        content="主角克莱恩醒来。",
    )
    await create_draft_only(
        db_session,
        novel_id,
        chapter_index=2,
        title="第二章",
        content="他遇到了梅丽莎。",
    )
    return novel_id


@pytest.mark.asyncio
async def test_persist_entities_writes_auto_ingested_meta(
    db_session: AsyncSession,
    novel_with_drafts: str,
) -> None:
    svc = SceneEntityExtractionService()
    entity = ExtractedEntity(
        name="克莱恩",
        entity_type="character",
        suggested_action="create_new",
    )

    with patch(
        "modules.world.facade.find_similar_entities",
        new_callable=AsyncMock,
        return_value={},
    ):
        created = await svc._persist_entities(
            db_session,
            novel_with_drafts,
            [entity],
            scene_index=1,
            source_chapter_index=1,
            workflow_id="wf-test-1",
        )

    assert created == 1
    from sqlalchemy import select

    from modules.world.models import CoreEntity
    from shared.utils import parse_uuid

    nid = parse_uuid(novel_with_drafts, "novel_id")
    stmt = select(CoreEntity).where(CoreEntity.novel_id == nid)
    result = await db_session.execute(stmt)
    found = next((e for e in result.scalars() if e.name == "克莱恩"), None)
    assert found is not None
    assert found.status == "canonical"
    meta = (found.content_json or {}).get("_meta", {})
    assert meta.get("auto_ingested") is True
    assert meta.get("source_scene_index") == 1
    assert meta.get("source_chapter_index") == 1
    assert meta.get("batch_id") == "wf-test-1"


@pytest.mark.asyncio
async def test_persist_relations_links_existing_entities(
    db_session: AsyncSession,
    novel_with_drafts: str,
) -> None:
    svc = SceneEntityExtractionService()
    from modules.world.facade import create_entity

    await create_entity(
        db_session,
        novel_with_drafts,
        {"name": "克莱恩", "entity_type": "character", "status": "canonical"},
    )
    await create_entity(
        db_session,
        novel_with_drafts,
        {"name": "梅丽莎", "entity_type": "character", "status": "canonical"},
    )

    relation = ExtractedRelation(
        source_name="克莱恩",
        target_name="梅丽莎",
        relation_type="sibling",
        description="兄妹",
    )
    created = await svc._persist_relations(
        db_session,
        novel_with_drafts,
        [relation],
        scene_index=1,
        workflow_id="wf-test-2",
    )

    assert created == 1
    from modules.world.facade import get_entity_relations

    rels, _ = await get_entity_relations(db_session, novel_with_drafts)
    assert any(r.relation_type == "sibling" for r in rels)


@pytest.mark.asyncio
async def test_record_deltas_creates_delta_log(
    db_session: AsyncSession,
    novel_with_drafts: str,
) -> None:
    svc = SceneEntityExtractionService()
    deltas = [
        DeltaEvent(
            category="ENTITY_CREATED",
            field="summary",
            old=None,
            new="summary text",
            meta={"source": "test"},
        )
    ]
    count = await svc._record_deltas(db_session, novel_with_drafts, deltas, scene_index=2)
    assert count == 1

    from sqlalchemy import select

    from modules.memory.models import DeltaLog
    from shared.utils import parse_uuid

    nid = parse_uuid(novel_with_drafts, "novel_id")
    stmt = select(DeltaLog).where(DeltaLog.novel_id == nid, DeltaLog.scene_index == 2)
    result = await db_session.execute(stmt)
    items = result.scalars().all()
    assert len(items) == 1
    assert items[0].category == "ENTITY_CREATED"


@pytest.mark.asyncio
async def test_process_scene_captures_memory_snapshot(
    db_session: AsyncSession,
    novel_with_drafts: str,
) -> None:
    svc = SceneEntityExtractionService()
    scene = {
        "id": "scene-1",
        "novel_id": novel_with_drafts,
        "scene_index": 1,
        "chapter_ids": ["1"],
    }
    with (
        patch.object(
            svc,
            "_call_llm_extraction",
            return_value=Mock(
                entities=[
                    ExtractedEntity(
                        name="克莱恩",
                        entity_type="character",
                        suggested_action="create_new",
                    )
                ],
                relations=[],
                delta_events=[],
            ),
        ),
        patch(
            "modules.memory.facade.capture_snapshot",
            new_callable=AsyncMock,
        ) as mock_snapshot,
        patch(
            "modules.world.facade.find_similar_entities",
            new_callable=AsyncMock,
            return_value={},
        ),
    ):
        result = await svc._process_scene(
            db_session,
            novel_with_drafts,
            scene,
            scene_idx=0,
            existing_context="",
            accumulated_memory=[],
            workflow_id="wf-test-3",
        )

    assert result["created"] == 1
    mock_snapshot.assert_awaited_once()
