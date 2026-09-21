"""G0 基线保护契约：作者权威事件不可被机器重跑删除或覆写（V4 T05/T04）。

对应 docs/plans/novelcraft-v4/plans/05-TRACEABILITY-ACCEPTANCE.md 的
T05（Scene 重跑为空/变短时人工确认保留）与 T04（章节/Scene 两视图同截止点
核心状态一致），以及 G0 出口要求的"关键语义用例可复现；缺口明确"。
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.story.continuity.contracts import ConfirmedContinuityEventIngest
from modules.story.continuity.models import MemoryEvent
from modules.story.continuity.scene_projection import SceneMemoryProjectionService
from modules.story.continuity.services import MemoryService
from modules.story.outline_state.models import Scene

ENTITY_ID = "11111111-1111-4111-8111-111111111111"


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


async def _confirm_author_event(
    db: AsyncSession,
    novel_id: str,
    scene: Scene,
    *,
    new_value: str,
    idempotency_key: str,
) -> None:
    from modules.story.continuity.services import MemoryService as _MemoryService

    await _MemoryService().confirm_scene_continuity_event(
        db,
        novel_id,
        scene_id=str(scene.id),
        scene_index=scene.scene_index,
        chapter_index=1,
        event=ConfirmedContinuityEventIngest(
            dimension="entities",
            category="profile",
            field_path="林舟.status",
            old_value="未知",
            new_value=new_value,
            idempotency_key=idempotency_key,
            evidence_summary="作者核对第 1 章后确认",
        ),
    )


async def _scene_events(
    db: AsyncSession,
    novel_id: str,
    scene_id: uuid.UUID,
) -> list[MemoryEvent]:
    return list(
        (
            await db.execute(
                select(MemoryEvent)
                .where(
                    MemoryEvent.novel_id == uuid.UUID(novel_id),
                    MemoryEvent.scene_id == scene_id,
                )
                .order_by(MemoryEvent.scene_sequence)
            )
        )
        .scalars()
        .all()
    )


def _machine_events(count: int) -> list[dict]:
    return [
        {
            "dimension": "entities",
            "event_type": "manual_correction",
            "snapshot_after": {"summary": f"机器观察 {index}"},
            "source": "deep_import",
        }
        for index in range(1, count + 1)
    ]


@pytest.mark.asyncio
async def test_scene_rerun_preserves_author_confirmed_events(
    db_session: AsyncSession,
    test_project_id: str,
) -> None:
    """机器重跑条数变多变少或清空，作者确认事件都不被删除或覆写。"""
    scene = await _scene(db_session, test_project_id, 0, 1)
    memory = MemoryService()

    await memory.record_scene_events(
        db_session,
        test_project_id,
        scene_id=str(scene.id),
        scene_index=0,
        chapter_index=1,
        events=_machine_events(2),
    )
    await _confirm_author_event(
        db_session,
        test_project_id,
        scene,
        new_value="持有铜钥匙",
        idempotency_key="confirm-1",
    )
    confirmed = await _scene_events(db_session, test_project_id, scene.id)
    assert [item.source for item in confirmed] == [
        "deep_import",
        "deep_import",
        "author_confirmation",
    ]
    author_slot = confirmed[-1].scene_sequence
    assert author_slot == 3

    # 机器输出变少：派生事件收缩，作者确认保留。
    await memory.record_scene_events(
        db_session,
        test_project_id,
        scene_id=str(scene.id),
        scene_index=0,
        chapter_index=1,
        events=_machine_events(1),
    )
    events = await _scene_events(db_session, test_project_id, scene.id)
    assert [(item.source, item.scene_sequence) for item in events] == [
        ("deep_import", 1),
        ("author_confirmation", 3),
    ]

    # 机器空重跑（imports 空 Delta 路径）：只清派生带。
    await memory.record_scene_events(
        db_session,
        test_project_id,
        scene_id=str(scene.id),
        scene_index=0,
        chapter_index=1,
        events=[],
    )
    events = await _scene_events(db_session, test_project_id, scene.id)
    assert [(item.source, item.scene_sequence) for item in events] == [
        ("author_confirmation", 3),
    ]
    payload = events[0].snapshot_after
    assert payload["new_value"] == "持有铜钥匙"

    # 机器输出变多、序号请求撞上作者槽位：机器行避让，作者行内容不变。
    await memory.record_scene_events(
        db_session,
        test_project_id,
        scene_id=str(scene.id),
        scene_index=0,
        chapter_index=1,
        events=_machine_events(3),
    )
    events = await _scene_events(db_session, test_project_id, scene.id)
    assert [(item.source, item.scene_sequence) for item in events] == [
        ("deep_import", 1),
        ("deep_import", 2),
        ("author_confirmation", 3),
        ("deep_import", 4),
    ]
    author_event = events[2]
    assert author_event.snapshot_after["new_value"] == "持有铜钥匙"
    assert author_event.snapshot_after["meta"]["idempotency_key"] == "confirm-1"


@pytest.mark.asyncio
async def test_author_confirmation_idempotent_append_still_dedupes(
    db_session: AsyncSession,
    test_project_id: str,
) -> None:
    scene = await _scene(db_session, test_project_id, 0, 1)

    await _confirm_author_event(
        db_session,
        test_project_id,
        scene,
        new_value="持有铜钥匙",
        idempotency_key="confirm-1",
    )
    await _confirm_author_event(
        db_session,
        test_project_id,
        scene,
        new_value="持有铜钥匙",
        idempotency_key="confirm-1",
    )
    events = await _scene_events(db_session, test_project_id, scene.id)
    assert len(events) == 1


@pytest.mark.asyncio
async def test_scene_and_chapter_replay_agree_on_core_state(
    db_session: AsyncSession,
    test_project_id: str,
) -> None:
    """T04：同截止点下章节重放与 Scene 投影的核心实体/关系/位置/知识一致。"""
    scene = await _scene(db_session, test_project_id, 0, 1)
    memory = MemoryService()
    await memory.record_scene_events(
        db_session,
        test_project_id,
        scene_id=str(scene.id),
        scene_index=0,
        chapter_index=1,
        events=[
            {
                "dimension": "entities",
                "event_type": "entity_created",
                "entity_id": ENTITY_ID,
                "entity_type": "character",
                "snapshot_after": {"id": ENTITY_ID, "name": "林舟", "status": "旅人"},
            },
            {
                "dimension": "locations",
                "event_type": "entity_moved",
                "entity_id": ENTITY_ID,
                "entity_type": "character",
                "snapshot_after": {
                    "location_id": "22222222-2222-4222-8222-222222222222",
                    "text_state": "白石城",
                },
            },
            {
                "dimension": "relations",
                "event_type": "relation_established",
                "entity_id": ENTITY_ID,
                "entity_type": "character",
                "snapshot_after": {
                    "id": "rel-1",
                    "source_id": ENTITY_ID,
                    "target_id": "33333333-3333-4333-8333-333333333333",
                    "relation_type": "持有",
                },
            },
            {
                "dimension": "knowledge",
                "event_type": "knowledge_changed",
                "entity_id": ENTITY_ID,
                "entity_type": "character",
                "snapshot_after": {
                    "id": "know-1",
                    "character_id": ENTITY_ID,
                    "knowledge": "青竹保管铜钥匙",
                },
            },
        ],
    )

    chapter_state = await memory.replay_state(db_session, test_project_id, 1)
    projection = await SceneMemoryProjectionService().ensure_scene(
        db_session, test_project_id, str(scene.id)
    )
    dimension_states = {item.dimension: item.state_json for item in projection.items}

    scene_entities = dimension_states["entities"]["entities"]
    assert scene_entities[ENTITY_ID]["name"] == "林舟"
    assert chapter_state["entities"][0]["name"] == "林舟"
    assert scene_entities[ENTITY_ID]["status"] == chapter_state["entities"][0]["status"]

    scene_locations = dimension_states["locations"]["character_locations"]
    assert scene_locations[ENTITY_ID] == chapter_state["character_locations"][ENTITY_ID]

    assert dimension_states["relations"]["relations"] == chapter_state["relations"]

    scene_knowledge = dimension_states["knowledge"]["character_knowledge"]
    assert scene_knowledge == chapter_state["character_knowledge"]
    assert scene_knowledge[0]["knowledge"] == "青竹保管铜钥匙"


@pytest.mark.asyncio
async def test_manual_correction_delta_kept_as_observation_not_state_operation(
    db_session: AsyncSession,
    test_project_id: str,
) -> None:
    """缺口钉住（E03 统一前不得静默改变）：

    manual_correction（Delta 观察）在两套归约里都不改变核心状态——章节
    重放忽略该类型，Scene 投影归入 changes 列表。这正是 V4 计划
    01-EVOLUTION §2.1「观察/解释/状态操作分离」要修的断层；在此钉住
    现状，防止 E03 之前的改动无意间让某一套视图单边开始解释观察。
    """
    scene = await _scene(db_session, test_project_id, 0, 1)
    memory = MemoryService()
    await memory.record_scene_events(
        db_session,
        test_project_id,
        scene_id=str(scene.id),
        scene_index=0,
        chapter_index=1,
        events=[
            {
                "dimension": "entities",
                "event_type": "manual_correction",
                "snapshot_after": {
                    "category": "profile",
                    "field_path": "林舟.status",
                    "new_value": "持有铜钥匙",
                },
                "source": "deep_import",
            }
        ],
    )

    chapter_state = await memory.replay_state(db_session, test_project_id, 1)
    assert chapter_state["entities"] == []
    assert chapter_state["character_locations"] == {}

    projection = await SceneMemoryProjectionService().ensure_scene(
        db_session, test_project_id, str(scene.id)
    )
    entities_state = {
        item.dimension: item.state_json for item in projection.items
    }["entities"]
    assert entities_state["entities"] == {}
    assert entities_state["changes"] == [
        {
            "category": "profile",
            "field_path": "林舟.status",
            "new_value": "持有铜钥匙",
        }
    ]


@pytest.mark.asyncio
async def test_entity_update_on_unknown_entity_diverges_between_views(
    db_session: AsyncSession,
    test_project_id: str,
) -> None:
    """缺口钉住（E03 统一前不得静默改变）：

    对未见实体的 entity_updated，章节重放丢弃（信息丢失），Scene 投影
    凭更新负载创建实体（幻影准入）。两套语义分叉是已知缺口，统一归约
    内核归 E03；E07.b 影子运行会以此对照新旧结果。
    """
    scene = await _scene(db_session, test_project_id, 0, 1)
    memory = MemoryService()
    await memory.record_scene_events(
        db_session,
        test_project_id,
        scene_id=str(scene.id),
        scene_index=0,
        chapter_index=1,
        events=[
            {
                "dimension": "entities",
                "event_type": "entity_updated",
                "entity_id": ENTITY_ID,
                "entity_type": "character",
                "snapshot_after": {"id": ENTITY_ID, "name": "林舟", "status": "旅人"},
            }
        ],
    )

    chapter_state = await memory.replay_state(db_session, test_project_id, 1)
    assert chapter_state["entities"] == []

    projection = await SceneMemoryProjectionService().ensure_scene(
        db_session, test_project_id, str(scene.id)
    )
    entities_state = {
        item.dimension: item.state_json for item in projection.items
    }["entities"]
    assert entities_state["entities"][ENTITY_ID]["name"] == "林舟"
