"""P2-A A2 写入端 — checkpoint ``state_json["_field_provenance"]`` 赋值链落库。

证明 ensure_scene / rebuild_from_scene 两条路径为受控注册字段写正确赋值链：

- exact：赋值事件 + 所属章 working 稿整章区间 + 版本（basis.py 同口径）；
- 继承链：投影从 previous checkpoint 续算时继承历史链，跨场景按
  ``recorded_at_sequence`` 「后者胜」裁决（custody_owner 不被交接冒充）；
- unverified：事件无稿源（该章无 working 稿）→ source_refs 空、version 0，
  不拿整场事件列表冒充；
- timeline：``moon_phase`` 挂链；受控发生时间键在事件 payload 构造处
  规范化（成对相对锚保留、半个丢弃、类型不符丢弃、未受控键透传）；
- 旧格式 checkpoint（无 ``_field_provenance`` 键）续算不报错；
- drift 缓存路径：同 source_hash 幂等短路返回的行与新建路径 provenance 同源。
"""

from __future__ import annotations

import hashlib
import uuid
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.story.continuity.contracts import SCENE_MEMORY_DIMENSIONS
from modules.story.continuity.field_provenance import (
    FIELD_PROVENANCE_STATE_KEY,
    ProvenanceStatus,
    provenance_status_for,
    read_field_provenance,
)
from modules.story.continuity.models import MemoryEvent, MemorySceneCheckpoint
from modules.story.continuity.scene_projection import SceneMemoryProjectionService
from modules.story.continuity.services import MemoryService
from modules.story.outline_state.models import Scene
from modules.writing.models import WritingDraft

# ============================================================
# 合成数据构造（沿用 continuity 模块内测试惯例）
# ============================================================


async def _scene(
    db: AsyncSession, novel_id: str, scene_index: int, chapter_index: int
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


async def _working_draft(
    db: AsyncSession,
    novel_id: str,
    chapter_index: int,
    version_number: int,
    content: str,
) -> WritingDraft:
    draft = WritingDraft(
        id=uuid.uuid4(),
        novel_id=uuid.UUID(novel_id),
        chapter_index=chapter_index,
        content=content,
        content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
        version_number=version_number,
        status="draft",
    )
    db.add(draft)
    await db.flush()
    return draft


async def _record(
    db: AsyncSession, novel_id: str, scene: Scene, events: list[dict[str, Any]]
) -> list[Any]:
    return await MemoryService().record_scene_events(
        db,
        novel_id,
        scene_id=str(scene.id),
        scene_index=scene.scene_index,
        chapter_index=int(scene.chapter_ids[0]),
        events=events,
    )


async def _current_checkpoint(
    db: AsyncSession, novel_id: str, scene: Scene, dimension: str
) -> MemorySceneCheckpoint:
    row = (
        await db.execute(
            select(MemorySceneCheckpoint).where(
                MemorySceneCheckpoint.novel_id == uuid.UUID(novel_id),
                MemorySceneCheckpoint.scene_id == scene.id,
                MemorySceneCheckpoint.dimension == dimension,
                MemorySceneCheckpoint.is_current.is_(True),
            )
        )
    ).scalar_one()
    return row


def _records_for(state_json: dict[str, Any], field_key: str) -> list[Any]:
    return [
        record
        for record in read_field_provenance(state_json)
        if record.field_key == field_key
    ]


def _latest_record(state_json: dict[str, Any], field_key: str) -> Any:
    records = _records_for(state_json, field_key)
    assert records, f"no provenance chain for {field_key}"
    return max(records, key=lambda item: item.recorded_at_sequence)


def _event_id(records: list[Any], marker: str) -> str:
    for item in records:
        if marker in str(item.snapshot_after):
            return str(item.id)
    raise AssertionError(f"fixture event not found: {marker}")


# ============================================================
# exact：注册字段赋值链 = 事件 + 该章 working 稿整章区间 + 版本
# ============================================================


@pytest.mark.asyncio
async def test_ensure_scene_writes_exact_provenance_for_registered_fields(
    db_session: AsyncSession, test_project_id: str
) -> None:
    scene = await _scene(db_session, test_project_id, 0, 1)
    draft = await _working_draft(
        db_session, test_project_id, 1, 1, "甲铸成铜钥匙，亲自收着。"
    )
    key_id, jia = str(uuid.uuid4()), str(uuid.uuid4())
    moved_id = str(uuid.uuid4())
    records = await _record(
        db_session,
        test_project_id,
        scene,
        [
            {
                "dimension": "entities",
                "event_type": "entity_created",
                "entity_id": key_id,
                "snapshot_after": {
                    "name": "铜钥匙",
                    "custody_owner": jia,
                    "custody_holder": jia,
                },
            },
            {
                "dimension": "locations",
                "event_type": "entity_moved",
                "entity_id": moved_id,
                "snapshot_after": {
                    "location_id": "loc-forge",
                    "text_state": "锻炉旁",
                },
            },
        ],
    )
    projection = SceneMemoryProjectionService()

    await projection.ensure_scene(db_session, test_project_id, str(scene.id))

    entities_state = (
        await _current_checkpoint(db_session, test_project_id, scene, "entities")
    ).state_json
    create_event = _event_id(records, "铜钥匙")
    assert set(record.field_key for record in read_field_provenance(entities_state)) == {
        "custody_owner",
        "custody_holder",
    }
    for field_key in ("custody_owner", "custody_holder"):
        assert (
            provenance_status_for(entities_state, field_key, "entities")
            is ProvenanceStatus.exact
        )
        record = _latest_record(entities_state, field_key)
        assert record.event_id == create_event
        assert record.version == 1
        assert record.recorded_at_sequence == 0 * 512 + 1
        assert len(record.source_refs) == 1
        ref = record.source_refs[0]
        assert str(ref.draft_id) == str(draft.id)
        assert ref.chapter_index == 1
        assert ref.version_number == 1
        assert ref.content_mode == "working"
        assert ref.source_hash == draft.content_hash
        assert (ref.start_offset, ref.end_offset) == (0, len(draft.content))

    locations_state = (
        await _current_checkpoint(db_session, test_project_id, scene, "locations")
    ).state_json
    moved_event = _event_id(records, "loc-forge")
    assert set(record.field_key for record in read_field_provenance(locations_state)) == {
        "location_id",
        "text_state",
    }
    assert (
        provenance_status_for(locations_state, "location_id", "locations")
        is ProvenanceStatus.exact
    )
    for field_key in ("location_id", "text_state"):
        assert _latest_record(locations_state, field_key).event_id == moved_event


# ============================================================
# 继承链 + 后者胜：跨场景 custody 交接，owner 不被交接冒充
# ============================================================


@pytest.mark.asyncio
async def test_provenance_chain_inherits_and_latest_scene_wins(
    db_session: AsyncSession, test_project_id: str
) -> None:
    chapters = [
        (0, 1, "甲铸成铜钥匙，亲自收着。"),
        (1, 2, "甲把铜钥匙交给乙保管。"),
        (2, 3, "乙又把铜钥匙转交丙保管。"),
    ]
    scenes = []
    for scene_index, chapter_index, content in chapters:
        scenes.append(
            await _scene(db_session, test_project_id, scene_index, chapter_index)
        )
        await _working_draft(db_session, test_project_id, chapter_index, 1, content)
    key_id, jia, yi, bing = (str(uuid.uuid4()) for _ in range(4))
    projection = SceneMemoryProjectionService()

    scene0_records = await _record(
        db_session,
        test_project_id,
        scenes[0],
        [
            {
                "dimension": "entities",
                "event_type": "entity_created",
                "entity_id": key_id,
                "snapshot_after": {
                    "name": "铜钥匙",
                    "custody_owner": jia,
                    "custody_holder": jia,
                },
            },
        ],
    )
    await projection.ensure_scene(db_session, test_project_id, str(scenes[0].id))
    scene1_records = await _record(
        db_session,
        test_project_id,
        scenes[1],
        [
            {
                "dimension": "entities",
                "event_type": "entity_updated",
                "entity_id": key_id,
                "snapshot_after": {"custody_holder": yi},
            },
        ],
    )
    await projection.ensure_scene(db_session, test_project_id, str(scenes[1].id))
    scene2_records = await _record(
        db_session,
        test_project_id,
        scenes[2],
        [
            {
                "dimension": "entities",
                "event_type": "entity_updated",
                "entity_id": key_id,
                "snapshot_after": {"custody_holder": bing},
            },
        ],
    )
    await projection.ensure_scene(db_session, test_project_id, str(scenes[2].id))

    create_event = _event_id(scene0_records, "铜钥匙")
    transfer_yi = _event_id(scene1_records, yi)
    transfer_bing = _event_id(scene2_records, bing)

    # 继承链：scene 2 的 entities checkpoint 同时持有创建链与两条交接链。
    state2 = (
        await _current_checkpoint(db_session, test_project_id, scenes[2], "entities")
    ).state_json
    holder_records = _records_for(state2, "custody_holder")
    assert {record.event_id for record in holder_records} == {
        create_event,
        transfer_yi,
        transfer_bing,
    }
    assert [record.recorded_at_sequence for record in holder_records] == sorted(
        record.recorded_at_sequence for record in holder_records
    )

    # 后者胜：最新链唯一且指向各自场景的最后交接事件，status exact。
    assert (
        provenance_status_for(state2, "custody_holder", "entities")
        is ProvenanceStatus.exact
    )
    assert _latest_record(state2, "custody_holder").event_id == transfer_bing
    assert _latest_record(state2, "custody_holder").source_refs[0].chapter_index == 3
    # 所有者的最后赋值停在创建事件，不被后续交接冒充。
    assert (
        provenance_status_for(state2, "custody_owner", "entities")
        is ProvenanceStatus.exact
    )
    assert _latest_record(state2, "custody_owner").event_id == create_event
    assert _latest_record(state2, "custody_owner").source_refs[0].chapter_index == 1

    # 历史 checkpoint 逐场景可回开，链保留构建当时的语义。
    state1 = (
        await _current_checkpoint(db_session, test_project_id, scenes[1], "entities")
    ).state_json
    assert _latest_record(state1, "custody_holder").event_id == transfer_yi
    state0 = (
        await _current_checkpoint(db_session, test_project_id, scenes[0], "entities")
    ).state_json
    assert _latest_record(state0, "custody_holder").event_id == create_event


# ============================================================
# unverified：该章无 working 稿 → source_refs 空、version 0
# ============================================================


@pytest.mark.asyncio
async def test_missing_working_draft_marks_unverified_with_empty_refs(
    db_session: AsyncSession, test_project_id: str
) -> None:
    scene = await _scene(db_session, test_project_id, 0, 1)  # 第 1 章无任何稿
    key_id, jia = str(uuid.uuid4()), str(uuid.uuid4())
    records = await _record(
        db_session,
        test_project_id,
        scene,
        [
            {
                "dimension": "entities",
                "event_type": "entity_created",
                "entity_id": key_id,
                "snapshot_after": {"name": "铜钥匙", "custody_owner": jia},
            },
        ],
    )
    await SceneMemoryProjectionService().ensure_scene(
        db_session, test_project_id, str(scene.id)
    )

    state = (
        await _current_checkpoint(db_session, test_project_id, scene, "entities")
    ).state_json
    assert (
        provenance_status_for(state, "custody_owner", "entities")
        is ProvenanceStatus.unverified
    )
    record = _latest_record(state, "custody_owner")
    assert record.event_id == _event_id(records, "铜钥匙")
    assert record.source_refs == ()
    assert record.version == 0


# ============================================================
# timeline：moon_phase 挂链 + 受控发生时间键规范化
# ============================================================


@pytest.mark.asyncio
async def test_timeline_moon_phase_chained_and_when_keys_normalized(
    db_session: AsyncSession, test_project_id: str
) -> None:
    scene = await _scene(db_session, test_project_id, 0, 1)
    draft = await _working_draft(db_session, test_project_id, 1, 1, "满月升起。")
    await _record(
        db_session,
        test_project_id,
        scene,
        [
            {
                "dimension": "timeline",
                "event_type": "timeline_changed",
                "snapshot_after": {
                    "category": "moon_phase",
                    "field_path": "sky.moon",
                    "new_value": "满月",
                    "moon_phase": "full",
                    # 半个相对锚：整体丢弃
                    "relative_to_fact_id": "fact-1",
                    # 类型不符的 Scene 锚：丢弃
                    "scene_sequence": "12",
                },
            },
            {
                "dimension": "timeline",
                "event_type": "timeline_changed",
                "snapshot_after": {
                    "category": "time_order",
                    "field_path": "sky.moon",
                    "new_value": "月升之后",
                    # 成对相对锚：保留
                    "relative_to_fact_id": "fact-1",
                    "relative_order": "after",
                    # 原文明示日期：原样保留
                    "stated_date": "腊月初七",
                },
            },
        ],
    )
    await SceneMemoryProjectionService().ensure_scene(
        db_session, test_project_id, str(scene.id)
    )

    # 事件侧：受控键规范化进 payload，未受控键照旧透传。
    stored = (
        await db_session.execute(
            select(MemoryEvent.snapshot_after)
            .where(MemoryEvent.scene_id == scene.id)
            .order_by(MemoryEvent.scene_sequence)
        )
    ).all()
    assert stored, "timeline events must be stored"
    moon_payload, order_payload = stored[0][0], stored[1][0]
    assert moon_payload["moon_phase"] == "full"
    assert moon_payload["category"] == "moon_phase"
    assert moon_payload["new_value"] == "满月"
    assert "relative_to_fact_id" not in moon_payload  # 半个相对锚被丢弃
    assert "scene_sequence" not in moon_payload  # str 类型 Scene 锚被丢弃
    assert order_payload["relative_to_fact_id"] == "fact-1"
    assert order_payload["relative_order"] == "after"
    assert order_payload["stated_date"] == "腊月初七"
    assert order_payload["category"] == "time_order"

    # 投影侧：moon_phase 是 timeline 注册字段，赋值同样挂链。
    state = (
        await _current_checkpoint(db_session, test_project_id, scene, "timeline")
    ).state_json
    assert (
        provenance_status_for(state, "moon_phase", "timeline") is ProvenanceStatus.exact
    )
    record = _latest_record(state, "moon_phase")
    assert record.dimension == "timeline"
    assert record.version == 1
    assert record.source_refs[0].draft_id == str(draft.id)
    # 未受控字段照旧投影为 fact，不因规范化丢失。
    assert [fact.get("new_value") for fact in state["facts"]] == ["满月", "月升之后"]


# ============================================================
# rebuild_from_scene：旧 checkpoint 链留在 v1，新当前指向 v2
# ============================================================


@pytest.mark.asyncio
async def test_rebuild_keeps_old_checkpoint_provenance_on_old_version(
    db_session: AsyncSession, test_project_id: str
) -> None:
    scene = await _scene(db_session, test_project_id, 0, 1)
    draft_v1 = await _working_draft(
        db_session, test_project_id, 1, 1, "甲把铜钥匙交给乙保管。"
    )
    key_id, jia, yi = (str(uuid.uuid4()) for _ in range(3))
    projection = SceneMemoryProjectionService()
    await _record(
        db_session,
        test_project_id,
        scene,
        [
            {
                "dimension": "entities",
                "event_type": "entity_created",
                "entity_id": key_id,
                "snapshot_after": {
                    "name": "铜钥匙",
                    "custody_owner": jia,
                    "custody_holder": yi,
                },
            },
        ],
    )
    await projection.ensure_scene(db_session, test_project_id, str(scene.id))
    old_row = await _current_checkpoint(db_session, test_project_id, scene, "entities")
    old_id = old_row.id

    draft_v2 = await _working_draft(
        db_session,
        test_project_id,
        1,
        2,
        "甲把铜钥匙交给乙保管，并低声嘱托入夜前归还。",
    )
    await projection.rebuild_from_scene(
        db_session,
        test_project_id,
        from_scene_id=str(scene.id),
        dimensions=list(SCENE_MEMORY_DIMENSIONS),
    )

    old = await projection.get_record(db_session, test_project_id, str(old_id))
    assert old.is_current is False
    old_records = [
        record
        for record in (old.state_json or {}).get(FIELD_PROVENANCE_STATE_KEY, [])
        if isinstance(record, dict) and record.get("field_key") == "custody_holder"
    ]
    assert old_records, "historical checkpoint must keep its provenance chain"
    old_refs = old_records[0]["source_refs"]
    assert any(str(ref.get("draft_id")) == str(draft_v1.id) for ref in old_refs)
    assert not any(str(ref.get("draft_id")) == str(draft_v2.id) for ref in old_refs)

    new_row = await _current_checkpoint(db_session, test_project_id, scene, "entities")
    assert new_row.id != old_id
    new_ref = _latest_record(new_row.state_json, "custody_holder").source_refs[0]
    assert str(new_ref.draft_id) == str(draft_v2.id)
    assert new_ref.version_number == 2


# ============================================================
# 旧格式 checkpoint（无 _field_provenance 键）续算不报错
# ============================================================


@pytest.mark.asyncio
async def test_legacy_state_without_provenance_key_continues(
    db_session: AsyncSession, test_project_id: str
) -> None:
    scene0 = await _scene(db_session, test_project_id, 0, 1)
    scene1 = await _scene(db_session, test_project_id, 1, 2)
    await _working_draft(db_session, test_project_id, 1, 1, "甲铸成铜钥匙。")
    await _working_draft(db_session, test_project_id, 2, 1, "甲把钥匙交给乙。")
    key_id, jia, yi = (str(uuid.uuid4()) for _ in range(3))
    projection = SceneMemoryProjectionService()
    await _record(
        db_session,
        test_project_id,
        scene0,
        [
            {
                "dimension": "entities",
                "event_type": "entity_created",
                "entity_id": key_id,
                "snapshot_after": {
                    "name": "铜钥匙",
                    "custody_owner": jia,
                    "custody_holder": jia,
                },
            },
        ],
    )
    await projection.ensure_scene(db_session, test_project_id, str(scene0.id))

    # 模拟第一阶段旧格式：剥掉 _field_provenance 键（其余语义保留）。
    legacy_row = await _current_checkpoint(
        db_session, test_project_id, scene0, "entities"
    )
    legacy_state = dict(legacy_row.state_json or {})
    legacy_state.pop(FIELD_PROVENANCE_STATE_KEY, None)
    legacy_row.state_json = legacy_state
    db_session.add(legacy_row)
    await db_session.flush()

    scene1_records = await _record(
        db_session,
        test_project_id,
        scene1,
        [
            {
                "dimension": "entities",
                "event_type": "entity_updated",
                "entity_id": key_id,
                "snapshot_after": {"custody_holder": yi},
            },
        ],
    )
    await projection.ensure_scene(db_session, test_project_id, str(scene1.id))

    state1 = (
        await _current_checkpoint(db_session, test_project_id, scene1, "entities")
    ).state_json
    # 不报错；继承侧无历史链，只有本场新赋值的链。
    transfer_event = _event_id(scene1_records, yi)
    holder_records = _records_for(state1, "custody_holder")
    assert {record.event_id for record in holder_records} == {transfer_event}
    assert _latest_record(state1, "custody_holder").event_id == transfer_event
    # 旧格式 previous 的核心状态照常继承（实体事实仍在）；未继承也未本场
    # 赋值的字段不带链 → 来源待核实（None），不冒充。
    assert state1["entities"][key_id]["custody_owner"] == jia
    assert _records_for(state1, "custody_owner") == []
    assert provenance_status_for(state1, "custody_owner", "entities") is None


# ============================================================
# drift 缓存路径：幂等短路返回的行与新建路径 provenance 同源
# ============================================================


@pytest.mark.asyncio
async def test_ensure_scene_idempotent_short_circuit_keeps_provenance(
    db_session: AsyncSession, test_project_id: str
) -> None:
    scene = await _scene(db_session, test_project_id, 0, 1)
    await _working_draft(db_session, test_project_id, 1, 1, "甲铸成铜钥匙。")
    key_id, jia = str(uuid.uuid4()), str(uuid.uuid4())
    await _record(
        db_session,
        test_project_id,
        scene,
        [
            {
                "dimension": "entities",
                "event_type": "entity_created",
                "entity_id": key_id,
                "snapshot_after": {"name": "铜钥匙", "custody_owner": jia},
            },
        ],
    )
    projection = SceneMemoryProjectionService()
    await projection.ensure_scene(db_session, test_project_id, str(scene.id))
    first = await _current_checkpoint(db_session, test_project_id, scene, "entities")
    first_provenance = first.state_json.get(FIELD_PROVENANCE_STATE_KEY)

    # 幂等重跑：source_hash 相等 → _build_dimension 短路返回旧行（不换行）。
    await projection.ensure_scene(db_session, test_project_id, str(scene.id))
    second = await _current_checkpoint(db_session, test_project_id, scene, "entities")

    assert second.id == first.id, "idempotent rerun must reuse the cached row"
    assert second.source_hash == first.source_hash
    assert second.state_json.get(FIELD_PROVENANCE_STATE_KEY) == first_provenance
    assert (
        provenance_status_for(second.state_json, "custody_owner", "entities")
        is ProvenanceStatus.exact
    )
    rows = await db_session.execute(
        select(MemorySceneCheckpoint).where(
            MemorySceneCheckpoint.scene_id == scene.id,
            MemorySceneCheckpoint.dimension == "entities",
        )
    )
    assert len(list(rows)) == 1, "no superseded churn for a no-op rerun"
