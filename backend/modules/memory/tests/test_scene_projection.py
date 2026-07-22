from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import ConflictError
from modules.memory.models import MemoryEvent, MemorySceneCheckpoint, MemorySceneSnapshot
from modules.memory.scene_projection import SceneMemoryProjectionService
from modules.memory.schemas import SceneCheckpointRepairRequest
from modules.memory.services import MemoryService
from modules.outline.models import Scene
from modules.world.map_models import MapFact


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
        "map",
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
async def test_undated_confirmed_map_fact_fails_closed_then_manual_repair_rebuilds(
    db_session: AsyncSession,
    test_project_id: str,
) -> None:
    first = await _scene(db_session, test_project_id, 0, 1)
    second = await _scene(db_session, test_project_id, 1, 2)
    third = await _scene(db_session, test_project_id, 2, 3)
    db_session.add(
        MapFact(
            novel_id=uuid.UUID(test_project_id),
            dynamic_type="location",
            target_name="未定时间地点",
            fact_status="confirmed",
        )
    )
    await db_session.flush()
    service = SceneMemoryProjectionService()

    result = await service.ensure_scene(db_session, test_project_id, str(first.id))
    gap = next(item for item in result.items if item.dimension == "map")
    assert gap.status == "manual_required"
    assert "缺少 Scene 锚点" in (gap.gap_reason or "")

    repaired = await service.repair(
        db_session,
        test_project_id,
        SceneCheckpointRepairRequest(
            scene_id=str(first.id),
            dimension="map",
            expected_checkpoint_id=gap.id,
            decision="replace_with_summary",
            replacement_summary="第一阶段人物仍在旧城",
            decision_summary="按正文逐段核对",
            confirmed=True,
        ),
    )

    assert repaired.checkpoint.source == "manual"
    assert repaired.checkpoint.confirmed is True
    assert repaired.rebuilt_scene_count == 2
    current = list(
        (
            await db_session.execute(
                select(MemorySceneCheckpoint).where(
                    MemorySceneCheckpoint.novel_id == uuid.UUID(test_project_id),
                    MemorySceneCheckpoint.scene_id == first.id,
                    MemorySceneCheckpoint.dimension == "map",
                    MemorySceneCheckpoint.is_current.is_(True),
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(current) == 1
    assert current[0].source == "manual"
    downstream = await service.get_scene(db_session, test_project_id, str(second.id))
    downstream_map = next(item for item in downstream.items if item.dimension == "map")
    assert downstream_map.source == "system_generated"
    assert downstream_map.status == "ready"
    third_result = await service.get_scene(db_session, test_project_id, str(third.id))
    third_map = next(item for item in third_result.items if item.dimension == "map")
    assert third_map.status == "ready"
    assert third_map.state_json["_coverage_confirmed"][
        "undated_map_fact_count"
    ] == 1
    snapshots = list(
        (
            await db_session.execute(
                select(MemorySceneSnapshot).where(
                    MemorySceneSnapshot.novel_id == uuid.UUID(test_project_id),
                    MemorySceneSnapshot.scene_id == first.id,
                    MemorySceneSnapshot.is_current.is_(True),
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(snapshots) == 1
    assert "chapter_end" in snapshots[0].snapshot_reasons


@pytest.mark.asyncio
async def test_manual_repair_rejects_stale_checkpoint_version(
    db_session: AsyncSession,
    test_project_id: str,
) -> None:
    scene = await _scene(db_session, test_project_id, 0, 1)
    db_session.add(
        MapFact(
            novel_id=uuid.UUID(test_project_id),
            dynamic_type="location",
            target_name="未定时间地点",
            fact_status="confirmed",
        )
    )
    await db_session.flush()
    service = SceneMemoryProjectionService()
    await service.ensure_scene(db_session, test_project_id, str(scene.id))

    with pytest.raises(ConflictError) as exc_info:
        await service.repair(
            db_session,
            test_project_id,
            SceneCheckpointRepairRequest(
                scene_id=str(scene.id),
                dimension="map",
                expected_checkpoint_id=str(uuid.uuid4()),
                decision="confirm_empty",
                decision_summary="正文核对",
                confirmed=True,
            ),
        )

    assert exc_info.value.code == "checkpoint_version_conflict"


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
async def test_map_gap_count_is_novel_scoped(
    db_session: AsyncSession,
    project_factory,
    test_project_id: str,
) -> None:
    scene = await _scene(db_session, test_project_id, 0, 1)
    other_id = await project_factory.create_project("other")
    db_session.add(
        MapFact(
            novel_id=other_id,
            dynamic_type="location",
            target_name="另一个项目的未定事实",
            fact_status="confirmed",
        )
    )
    await db_session.flush()

    result = await SceneMemoryProjectionService().ensure_scene(
        db_session, test_project_id, str(scene.id)
    )

    assert result.coverage_status == "ready"
