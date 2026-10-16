from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from core.container import container_scope
from core.errors import ConflictError
from core.service_keys import ASSISTANT_REQUIRE_OPERATION_TARGETS
from modules.assistant.contracts import AssistantOperationContext, WorkContext
from modules.assistant.operation_scope import require_operation_targets
from modules.story.continuity.fact_timeline import StoryFactTimelineService
from modules.story.continuity.models import MemoryEvent, StoryChapterOrderReceipt
from modules.story.continuity.operations import _read_fact_timeline
from modules.story.continuity.schemas import StoryFactTimelineQuery
from modules.story.outline_state.models import Scene


@pytest.mark.asyncio
async def test_assistant_fact_timeline_uses_trusted_scene_cutoff(
    db_session, test_project_id
) -> None:
    novel_id = uuid.UUID(test_project_id)
    scenes = [
        Scene(
            novel_id=novel_id,
            scene_index=index,
            title=f"场景{index}",
            chapter_ids=[str(index + 1)],
            scene_chunks=[],
        )
        for index in range(2)
    ]
    db_session.add_all(scenes)
    await db_session.flush()
    for index, scene in enumerate(scenes):
        db_session.add(
            MemoryEvent(
                novel_id=novel_id,
                chapter_index=index + 1,
                sequence=1,
                scene_id=scene.id,
                scene_index=index,
                scene_sequence=1,
                event_type="entity_updated",
                source="author",
                snapshot_after={"name": f"第{index + 1}场"},
            )
        )
    await db_session.flush()
    current = AssistantOperationContext(
        str(uuid.uuid4()),
        str(uuid.uuid4()),
        WorkContext(scope="current", scene_id=scenes[0].id),
    )
    with container_scope(
        {ASSISTANT_REQUIRE_OPERATION_TARGETS: require_operation_targets}
    ):
        with pytest.raises(ConflictError):
            await _read_fact_timeline(
                db_session,
                test_project_id,
                StoryFactTimelineQuery(cutoff_scene_id=scenes[1].id),
                context=current,
            )
        timeline = await _read_fact_timeline(
            db_session,
            test_project_id,
            StoryFactTimelineQuery(),
            context=current,
        )
        assert timeline["total"] == 1
        assert [item["scene_id"] for item in timeline["scene_options"]] == [
            str(scenes[0].id)
        ]
        excluded = AssistantOperationContext(
            str(uuid.uuid4()),
            str(uuid.uuid4()),
            WorkContext(
                scope="current",
                scene_id=scenes[0].id,
                excluded_targets=[str(scenes[1].id)],
            ),
        )
        with pytest.raises(ConflictError):
            await _read_fact_timeline(
                db_session, test_project_id, StoryFactTimelineQuery(), context=excluded
            )


@pytest.mark.asyncio
async def test_fact_timeline_cutoff_filters_future_events_and_filter_options(
    db_session, test_project_id
) -> None:
    novel_id = uuid.UUID(test_project_id)
    scenes = [
        Scene(
            novel_id=novel_id,
            scene_index=index,
            title=f"场景{index}",
            chapter_ids=[str(index + 1)],
            scene_chunks=[],
        )
        for index in range(3)
    ]
    db_session.add_all(scenes)
    await db_session.flush()
    now = datetime(2026, 10, 16, 0, 0, tzinfo=UTC)
    early_entity = uuid.uuid4()
    middle_entity = uuid.uuid4()
    future_entity = uuid.uuid4()
    events = [
        MemoryEvent(
            novel_id=novel_id,
            chapter_index=1,
            sequence=1,
            scene_id=scenes[0].id,
            scene_index=0,
            scene_sequence=1,
            event_type="entity_created",
            entity_id=early_entity,
            entity_type="character",
            snapshot_after={
                "name": "阿蘅",
                "state": "刚到旧港",
                "entity_id": str(early_entity),
                "meta": {"source_confirmation_id": str(uuid.uuid4())},
            },
            source="author",
            created_at=now,
        ),
        MemoryEvent(
            novel_id=novel_id,
            chapter_index=2,
            sequence=1,
            scene_id=scenes[1].id,
            scene_index=1,
            scene_sequence=1,
            event_type="entity_updated",
            entity_id=middle_entity,
            entity_type="character",
            snapshot_after={"name": "闻舟", "state": "藏起船票"},
            source="manual_edit",
            created_at=now,
        ),
        MemoryEvent(
            novel_id=novel_id,
            chapter_index=3,
            sequence=1,
            scene_id=scenes[2].id,
            scene_index=2,
            scene_sequence=1,
            event_type="entity_updated",
            entity_id=future_entity,
            entity_type="character",
            snapshot_after={"name": "沈砚", "state": "离开小镇"},
            source="deep_import",
            created_at=now,
        ),
        MemoryEvent(
            novel_id=novel_id,
            chapter_index=4,
            sequence=1,
            scene_id=None,
            event_type="entity_updated",
            entity_id=uuid.uuid4(),
            entity_type="character",
            snapshot_after={"name": "时间未明"},
            source="author",
            created_at=now,
        ),
    ]
    db_session.add_all(events)
    await db_session.flush()

    result = await StoryFactTimelineService().list(
        db_session,
        test_project_id,
        StoryFactTimelineQuery(cutoff_scene_id=scenes[1].id, limit=20),
    )

    assert result.total == 2
    assert [item.id for item in result.items] == [str(events[0].id), str(events[1].id)]
    assert result.unknown_time_count == 0
    assert set(result.source_options) == {"author", "manual_edit"}
    assert {item["entity_id"] for item in result.entity_options} == {
        str(early_entity),
        str(middle_entity),
    }
    assert result.cutoff_scene["scene_id"] == str(scenes[1].id)
    assert [item["scene_id"] for item in result.scene_options] == [
        str(scenes[0].id),
        str(scenes[1].id),
    ]
    first_snapshot = result.items[0].snapshot_after
    assert first_snapshot == {"name": "阿蘅", "state": "刚到旧港"}


@pytest.mark.asyncio
async def test_fact_timeline_projects_current_chapter_without_mutating_history(
    db_session, test_project_id
) -> None:
    novel_id = uuid.UUID(test_project_id)
    scene = Scene(
        novel_id=novel_id,
        scene_index=2,
        title="重排後的場景",
        chapter_ids=["2"],
        scene_chunks=[],
    )
    db_session.add(scene)
    await db_session.flush()
    applied_at = datetime(2026, 10, 16, 1, 0, tzinfo=UTC)
    before = MemoryEvent(
        novel_id=novel_id,
        chapter_index=1,
        sequence=1,
        scene_id=scene.id,
        scene_index=2,
        scene_sequence=1,
        event_type="entity_updated",
        entity_type="character",
        snapshot_after={"name": "阿蘅", "state": "拿到钥匙"},
        source="author",
        created_at=datetime(2026, 10, 16, 0, 0, tzinfo=UTC),
    )
    after = MemoryEvent(
        novel_id=novel_id,
        chapter_index=2,
        sequence=2,
        scene_id=scene.id,
        scene_index=2,
        scene_sequence=2,
        event_type="entity_updated",
        entity_type="character",
        snapshot_after={"name": "阿蘅", "state": "打开门"},
        source="author",
        created_at=datetime(2026, 10, 16, 2, 0, tzinfo=UTC),
    )
    receipt = StoryChapterOrderReceipt(
        id=uuid.uuid4(),
        novel_id=novel_id,
        status="applied",
        chapter_map_json={"1": 2, "2": 1},
        before_fingerprint="a" * 64,
        after_fingerprint="b" * 64,
        impact_json={"affected_scene_ids": [str(scene.id)]},
        manifest_json={},
        created_at=applied_at,
    )
    db_session.add_all([before, after, receipt])
    await db_session.flush()

    service = StoryFactTimelineService()
    current = await service.list(
        db_session, test_project_id, StoryFactTimelineQuery(limit=20)
    )
    assert [item.current_chapter_index for item in current.items] == [2, 2]
    assert [item.time_status for item in current.items] == ["stale", "stale"]
    assert before.chapter_index == 1
    assert after.chapter_index == 2

    receipt.status = "restored"
    receipt.restored_at = datetime(2026, 10, 16, 3, 0, tzinfo=UTC)
    scene.chapter_ids = ["1"]
    await db_session.flush()
    restored = await service.list(
        db_session, test_project_id, StoryFactTimelineQuery(limit=20)
    )
    assert [item.current_chapter_index for item in restored.items] == [1, 1]
    assert [item.time_status for item in restored.items] == ["current", "current"]
    assert before.chapter_index == 1
    assert after.chapter_index == 2


@pytest.mark.asyncio
async def test_fact_timeline_projects_interleaved_reorders_in_global_time_order(
    db_session, test_project_id
) -> None:
    novel_id = uuid.UUID(test_project_id)
    scene = Scene(
        novel_id=novel_id,
        scene_index=2,
        title="两次重排后发生的事实",
        chapter_ids=["3"],
        scene_chunks=[],
    )
    db_session.add(scene)
    await db_session.flush()
    origin = datetime(2026, 10, 16, 0, 0, tzinfo=UTC)
    event = MemoryEvent(
        novel_id=novel_id,
        chapter_index=2,
        sequence=1,
        scene_id=scene.id,
        scene_index=2,
        scene_sequence=1,
        event_type="entity_updated",
        entity_type="character",
        snapshot_after={"name": "阿蘅"},
        source="author",
        created_at=origin.replace(hour=3),
    )
    first = StoryChapterOrderReceipt(
        novel_id=novel_id,
        status="restored",
        chapter_map_json={"1": 2, "2": 1, "3": 3},
        before_fingerprint="a" * 64,
        after_fingerprint="b" * 64,
        impact_json={},
        manifest_json={},
        created_at=origin.replace(hour=1),
        restored_at=origin.replace(hour=5),
    )
    second = StoryChapterOrderReceipt(
        novel_id=novel_id,
        status="restored",
        chapter_map_json={"1": 1, "2": 3, "3": 2},
        before_fingerprint="c" * 64,
        after_fingerprint="d" * 64,
        impact_json={},
        manifest_json={},
        created_at=origin.replace(hour=2),
        restored_at=origin.replace(hour=4),
    )
    db_session.add_all([event, first, second])
    await db_session.flush()

    timeline = await StoryFactTimelineService().list(
        db_session, test_project_id, StoryFactTimelineQuery(limit=20)
    )
    assert timeline.items[0].current_chapter_index == 3
    assert event.chapter_index == 2
