from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.memory.models import MemoryEvent, MemorySceneCheckpoint, MemorySceneSnapshot
from modules.memory.scene_projection import SceneMemoryProjectionService
from modules.memory.services import MemoryService
from modules.outline.models import Scene


async def _scene(
    db: AsyncSession,
    novel_id: str,
    scene_index: int,
    chapter_index: int,
) -> Scene:
    item = Scene(
        novel_id=uuid.UUID(novel_id),
        scene_index=scene_index,
        title=f"Scene {scene_index}",
        chapter_ids=[chapter_index],
        scene_chunks=[{"chapter_index": chapter_index}],
        status="draft",
    )
    db.add(item)
    await db.flush()
    return item


@pytest.mark.asyncio
async def test_scene_checkpoint_builds_all_dimensions_and_sparse_stage0(
    db_session: AsyncSession,
    test_project_id: str,
) -> None:
    scene = await _scene(db_session, test_project_id, 0, 1)
    service = SceneMemoryProjectionService()

    result = await service.ensure_scene(db_session, test_project_id, str(scene.id))

    assert result.coverage_status == "ready"
    assert {item.dimension for item in result.items} == {
        "entities",
        "relations",
        "locations",
        "knowledge",
    }
    snapshots = list(
        (
            await db_session.execute(
                select(MemorySceneSnapshot)
                .where(MemorySceneSnapshot.novel_id == uuid.UUID(test_project_id))
                .order_by(MemorySceneSnapshot.stage_index)
            )
        )
        .scalars()
        .all()
    )
    assert [item.stage_index for item in snapshots] == [0, 1]
    assert snapshots[0].snapshot_reasons == ["initial"]
    assert set(snapshots[1].snapshot_reasons) == {"chapter_end", "latest"}



@pytest.mark.asyncio
async def test_empty_scene_rerun_clears_events_and_invalidates_downstream_projection(
    db_session: AsyncSession,
    test_project_id: str,
) -> None:
    first = await _scene(db_session, test_project_id, 0, 1)
    second = await _scene(db_session, test_project_id, 1, 2)
    memory = MemoryService()
    projection = SceneMemoryProjectionService()
    await memory.record_scene_events(
        db_session,
        test_project_id,
        scene_id=str(first.id),
        scene_index=0,
        chapter_index=1,
        events=[
            {
                "dimension": "entities",
                "event_type": "manual_correction",
                "snapshot_after": {"summary": "人物取得钥匙"},
            }
        ],
    )
    await projection.ensure_scene(db_session, test_project_id, str(second.id))

    await memory.record_scene_events(
        db_session,
        test_project_id,
        scene_id=str(first.id),
        scene_index=0,
        chapter_index=1,
        events=[],
    )

    remaining_events = list(
        (
            await db_session.execute(
                select(MemoryEvent).where(
                    MemoryEvent.novel_id == uuid.UUID(test_project_id),
                    MemoryEvent.scene_id == first.id,
                )
            )
        )
        .scalars()
        .all()
    )
    assert remaining_events == []
    current_entity_checkpoints = list(
        (
            await db_session.execute(
                select(MemorySceneCheckpoint).where(
                    MemorySceneCheckpoint.novel_id == uuid.UUID(test_project_id),
                    MemorySceneCheckpoint.dimension == "entities",
                    MemorySceneCheckpoint.is_current.is_(True),
                )
            )
        )
        .scalars()
        .all()
    )
    assert current_entity_checkpoints == []
    current_scene_snapshots = list(
        (
            await db_session.execute(
                select(MemorySceneSnapshot).where(
                    MemorySceneSnapshot.novel_id == uuid.UUID(test_project_id),
                    MemorySceneSnapshot.scene_id.is_not(None),
                    MemorySceneSnapshot.is_current.is_(True),
                )
            )
        )
        .scalars()
        .all()
    )
    assert current_scene_snapshots == []
