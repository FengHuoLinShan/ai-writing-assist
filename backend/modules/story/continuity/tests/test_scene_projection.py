from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.story.continuity.contracts import SCENE_MEMORY_DIMENSIONS
from modules.story.continuity.models import (
    MemoryEvent,
    MemorySceneCheckpoint,
    MemorySceneSnapshot,
)
from modules.story.continuity.repositories import EventRepository
from modules.story.continuity.scene_projection import SceneMemoryProjectionService
from modules.story.continuity.services import MemoryService
from modules.story.outline_state.models import Scene


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
    assert {item.dimension for item in result.items} == set(SCENE_MEMORY_DIMENSIONS)
    assert result.missing_dimensions == []
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
async def test_scene_checkpoint_reports_only_contract_dimensions_as_missing(
    db_session: AsyncSession,
    test_project_id: str,
) -> None:
    scene = await _scene(db_session, test_project_id, 0, 1)

    result = await SceneMemoryProjectionService().get_scene(
        db_session,
        test_project_id,
        str(scene.id),
    )

    assert result.coverage_status == "missing"
    assert result.missing_dimensions == list(SCENE_MEMORY_DIMENSIONS)


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


@pytest.mark.asyncio
async def test_scene_event_sequences_avoid_chapter_event_band(
    db_session: AsyncSession,
    test_project_id: str,
) -> None:
    """scene_index=0 的场景事件不得与同章章级事件共享 (chapter, sequence) 唯一键。"""
    novel_id = uuid.UUID(test_project_id)
    scene = await _scene(db_session, test_project_id, 0, 1)

    await MemoryService().record_events(
        db_session,
        test_project_id,
        chapter_index=1,
        events=[
            {
                "event_type": "entity_introduced",
                "entity_id": "11111111-1111-4111-8111-111111111111",
                "entity_type": "core_entity",
            },
            {
                "event_type": "relation_changed",
                "entity_id": "11111111-1111-4111-8111-111111111111",
                "entity_type": "core_entity",
            },
        ],
    )
    await EventRepository().replace_scene_events(
        db_session,
        novel_id=novel_id,
        scene_id=scene.id,
        scene_index=0,
        chapter_index=1,
        rows=[
            {
                "event_type": "scene_state_changed",
                "entity_id": None,
                "entity_type": None,
                "source": "scene_projection",
                "dimension": "state",
                "snapshot_after": {"stage": "scene"},
                "scene_sequence": 1,
            },
            {
                "event_type": "scene_state_changed",
                "entity_id": None,
                "entity_type": None,
                "source": "scene_projection",
                "dimension": "state",
                "snapshot_after": {"stage": "scene"},
                "scene_sequence": 2,
            },
        ],
    )

    events = list(
        (
            await db_session.execute(
                select(MemoryEvent)
                .where(MemoryEvent.novel_id == novel_id)
                .order_by(MemoryEvent.sequence)
            )
        )
        .scalars()
        .all()
    )
    scene_events = [item for item in events if item.scene_id == scene.id]
    chapter_events = [item for item in events if item.scene_id is None]
    assert [item.sequence for item in chapter_events] == [1, 2]
    # 场景事件基数必须高于章级事件上限（500），否则 on_conflict 会互相覆盖
    assert all(item.sequence >= 1001 for item in scene_events)
    assert [item.sequence for item in scene_events] == [1001, 1002]

    # 重排场景索引时 sequence 同步重算
    await EventRepository().align_scene_indices(
        db_session,
        novel_id,
        {scene.id: 2},
    )
    realigned = list(
        (
            await db_session.execute(
                select(MemoryEvent).where(MemoryEvent.scene_id == scene.id)
            )
        )
        .scalars()
        .all()
    )
    assert [item.scene_index for item in realigned] == [2, 2]
    assert sorted(item.sequence for item in realigned) == [3001, 3002]
