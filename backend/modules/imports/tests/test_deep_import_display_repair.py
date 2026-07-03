"""Deep import display repair tests."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.imports.deep_import_display_repair import (
    DeepImportDisplayRepairService,
)
from modules.outline.models import OutlineArc, Scene
from modules.outline.schemas import SceneCreate
from modules.outline.services import SceneService
from modules.world.models import CoreEntity
from tests.utils import _create_project


@pytest.mark.asyncio
async def test_repair_reindexes_scenes_and_alias_metadata(
    db_session: AsyncSession,
) -> None:
    novel_id = str(uuid.uuid4())
    await _create_project(db_session, novel_id)
    scene_service = SceneService()
    for chapter in [3, 1, 2]:
        await scene_service.create(
            db_session,
            novel_id,
            SceneCreate(
                scene_index=0,
                title=f"第 {chapter} 章",
                chapter_ids=[str(chapter)],
                scene_chunks=[{"chapter_index": chapter}],
                source="deep_import",
            ),
        )
    entity = CoreEntity(
        novel_id=uuid.UUID(novel_id),
        entity_type="character",
        name="克莱恩",
        status="candidate",
        content_json={
            "_meta": {
                "source": "deep_import",
                "workflow_id": "wf-old",
                "source_scene_index": 0,
                "confidence": 0.82,
            },
            "aliases": ["周明瑞", {"alias": "小克", "type": "nickname"}],
        },
        created_by="ai_import",
    )
    db_session.add(entity)
    await db_session.flush()

    result = await DeepImportDisplayRepairService().repair(
        db_session,
        novel_id,
        workflow_id="wf-repair",
        start_chapter=1,
        end_chapter=3,
    )

    assert result.scenes_reindexed == 3
    assert result.aliases_repaired == 2
    scenes = (
        await db_session.execute(
            select(Scene).where(Scene.novel_id == uuid.UUID(novel_id))
        )
    ).scalars().all()
    by_title = {scene.title: scene.scene_index for scene in scenes}
    assert by_title == {"第 1 章": 0, "第 2 章": 1, "第 3 章": 2}
    refreshed = await db_session.get(CoreEntity, entity.id)
    aliases = (refreshed.content_json or {}).get("aliases")
    assert aliases == [
        {
            "alias": "周明瑞",
            "type": "alias",
            "status": "candidate",
            "source": "deep_import",
            "workflow_id": "wf-old",
            "scene_id": None,
            "scene_index": 0,
            "confidence": 0.82,
            "quote": None,
            "needs_review": True,
        },
        {
            "alias": "小克",
            "type": "nickname",
            "status": "candidate",
            "source": "deep_import",
            "workflow_id": "wf-old",
            "scene_id": None,
            "scene_index": 0,
            "confidence": 0.82,
            "quote": None,
            "needs_review": True,
        },
    ]


@pytest.mark.asyncio
async def test_repair_adds_large_sample_structure_minimums(
    db_session: AsyncSession,
) -> None:
    novel_id = str(uuid.uuid4())
    await _create_project(db_session, novel_id)
    entity = CoreEntity(
        novel_id=uuid.UUID(novel_id),
        entity_type="character",
        name="克莱恩",
        status="candidate",
        content_json={"_meta": {"source": "deep_import"}, "aliases": []},
        created_by="ai_import",
    )
    db_session.add(entity)
    db_session.add(
        OutlineArc(
            novel_id=uuid.UUID(novel_id),
            title="既有篇章纲",
            arc_index=1,
            start_chapter=1,
            end_chapter=15,
            status="draft",
        )
    )
    await db_session.flush()

    result = await DeepImportDisplayRepairService().repair(
        db_session,
        novel_id,
        workflow_id="wf-repair",
        start_chapter=1,
        end_chapter=60,
    )

    assert result.structure_before == {
        "threads": 0,
        "arcs": 1,
        "foreshadowing": 0,
        "reveals": 0,
    }
    assert result.structure_after == {
        "threads": 3,
        "arcs": 4,
        "foreshadowing": 3,
        "reveals": 3,
    }
