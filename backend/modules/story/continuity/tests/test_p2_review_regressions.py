"""阶段 2 审查整改的定向回归（F1–F6，零 LLM、合成数据）。

来源：2026-10-08 独立审查报告（REVIEW-20261008.md）复现的缺陷反例。每条
用例对应一项「修复前必失败、修复后必通过」的产品不变量：

- F1 旧作者确认不被后来的稿洗成新稿的精确依据（赋值链在摄入时冻结来源）。
- F2 无已展示原文证明时，reader 视图不公开作者秘密。
- F3 揭示授权按字段生效：保管字段的证明不连坐同对象的未揭示秘密。
- F4 位置聚合条目只挂当前 payload 仍存在的受控字段的链。
- F5 timeline 月相事实按**事实实例**挂链，不共用最后一条赋值。
- F6 真实投影在产物行内登记自己的消费（稿件范围/版本/方法版本）。

夹具口径沿用 test_p2b_boundary_wiring（同构造、同 DB fixture）。
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from modules.evolution.impact import load_scene_consumption_records
from modules.story.continuity.scene_projection import SceneMemoryProjectionService
from modules.story.continuity.scene_state_view import SceneStateViewService
from modules.story.continuity.services import MemoryService
from modules.story.continuity.tests.test_p2a_write_side import (
    _current_checkpoint,
    _scene,
    _working_draft,
)
from modules.story.continuity.tests.test_p2b_boundary_wiring import _view
from modules.writing.repositories import WritingDraftRepository
from modules.writing.schemas import WritingDraftCreate

pytestmark = pytest.mark.asyncio


async def _record(
    db: AsyncSession, novel_id: str, scene: object, events: list[dict]
) -> None:
    await MemoryService().record_scene_events(
        db,
        novel_id,
        scene_id=str(scene.id),
        scene_index=int(scene.scene_index),
        chapter_index=int(scene.chapter_ids[0]),
        events=events,
    )


def _entity_facts(view: object, field: str, subject_id: str) -> list[object]:
    return [
        fact
        for dim in view.dimensions
        if dim.dimension == "entities"
        for fact in dim.facts
        if fact.field == field and fact.subject_id == subject_id
    ]


# ============================================================
# F1：重建不刷新旧事实的证明
# ============================================================


async def test_confirmed_v1_assignment_is_not_rebound_to_v2(
    db_session: AsyncSession, test_project_id: str
) -> None:
    """v1 时代的作者确认在 v2 建成后仍回开 v1，不得变成 v2 的精确依据。"""
    db, nid = db_session, test_project_id
    scene = await _scene(db, nid, 0, 1)
    v1 = await _working_draft(db, nid, 1, 1, "甲保管铜钥匙。")
    key, jia = str(uuid.uuid4()), str(uuid.uuid4())
    await _record(
        db,
        nid,
        scene,
        [
            {
                "dimension": "entities",
                "event_type": "entity_created",
                "entity_id": key,
                "source": "author_confirmation",
                "snapshot_after": {
                    "name": "铜钥匙",
                    "custody_holder": jia,
                    "meta": {"author_confirmed": True},
                },
            }
        ],
    )
    service = SceneMemoryProjectionService()
    await service.ensure_scene(db, nid, str(scene.id))
    old_id = str((await _current_checkpoint(db, nid, scene, "entities")).id)

    v2 = await WritingDraftRepository().create(
        db,
        WritingDraftCreate(
            novel_id=nid,
            chapter_index=1,
            content="乙拿走铜钥匙，旧保管记录已删除。",
        ),
    )
    assert v2.version_number == 2

    await service.rebuild_from_scene(
        db, nid, from_scene_id=str(scene.id), dimensions=["entities"]
    )
    view = await SceneStateViewService().get_view(
        db, novel_id=nid, scene_id=str(scene.id), viewpoint={"kind": "author"}
    )
    fact = next(
        fact
        for dim in view.dimensions
        if dim.dimension == "entities"
        for fact in dim.facts
        if fact.field == "custody_holder"
    )
    provenance = fact.source["provenance"]
    [ref] = provenance["source_refs"]
    assert ref["draft_id"] == str(v1.id), (
        "旧赋值只能回开 v1，不得被 v2 working 稿洗成 exact"
    )
    assert ref["version_number"] == 1
    assert provenance["status"] == "exact"
    # 历史行自身也仍指向 v1（历史回开不被重建改写）。
    old = await service.get_record(db, nid, old_id)
    assert old.is_current is False
    assert old.field_provenance[0]["source_refs"][0]["draft_id"] == str(v1.id)


# ============================================================
# F2 / F3：reader 揭示须按字段证明
# ============================================================


async def test_reader_with_no_shown_proof_hides_secret(
    db_session: AsyncSession, test_project_id: str
) -> None:
    """零正文、零来源证明时，reader 视图不得默认公开作者秘密。"""
    db, nid = db_session, test_project_id
    scene = await _scene(db, nid, 0, 1)
    key = str(uuid.uuid4())
    await _record(
        db,
        nid,
        scene,
        [
            {
                "dimension": "entities",
                "event_type": "entity_created",
                "entity_id": key,
                "snapshot_after": {
                    "name": "铜锁",
                    "secret_relation": "作者秘密，正文从未展示",
                },
            }
        ],
    )
    reader = await SceneStateViewService().get_view(
        db, novel_id=nid, scene_id=str(scene.id), viewpoint={"kind": "reader"}
    )
    assert _entity_facts(reader, "secret_relation", key) == []


async def test_holder_reveal_does_not_reveal_other_secret_field(
    db_session: AsyncSession, test_project_id: str
) -> None:
    """只揭示保管者：同对象未展示证明的秘密关系仍不得进入 reader 视图。"""
    db, nid = db_session, test_project_id
    scene1 = await _scene(db, nid, 0, 1)
    scene2 = await _scene(db, nid, 1, 2)
    await _working_draft(db, nid, 1, 1, "甲把铜锁交给乙保管。")
    key, jia = str(uuid.uuid4()), str(uuid.uuid4())
    await _record(
        db,
        nid,
        scene1,
        [
            {
                "dimension": "entities",
                "event_type": "entity_created",
                "entity_id": jia,
                "snapshot_after": {"name": "乙"},
            },
            {
                "dimension": "entities",
                "event_type": "entity_created",
                "entity_id": key,
                "snapshot_after": {
                    "name": "铜锁",
                    "custody_holder": jia,
                    "secret_relation": "未展示的作者关系",
                },
            },
            {
                "dimension": "timeline",
                "event_type": "timeline_changed",
                "snapshot_after": {
                    "category": "time_order",
                    "field_path": f"{key}.custody_holder",
                    "new_value": "本章揭示保管者",
                },
            },
        ],
    )
    reader = await _view(db, nid, scene2, {"kind": "reader"})
    assert len(_entity_facts(reader, "custody_holder", key)) == 1
    assert _entity_facts(reader, "secret_relation", key) == []


# ============================================================
# F4：位置聚合条目按当前字段取链
# ============================================================


async def test_location_provenance_follows_current_payload_field(
    db_session: AsyncSession, test_project_id: str
) -> None:
    """新位置只写描述时，来源不得回开旧的 location_id 赋值事件。"""
    db, nid = db_session, test_project_id
    scene0 = await _scene(db, nid, 0, 1)
    scene1 = await _scene(db, nid, 1, 2)
    jia = str(uuid.uuid4())
    await _working_draft(db, nid, 1, 1, "甲在集市摊前。")
    await _working_draft(db, nid, 2, 1, "甲只留下「新地点」的描述。")
    await _record(
        db,
        nid,
        scene0,
        [
            {
                "dimension": "locations",
                "event_type": "entity_moved",
                "entity_id": jia,
                "snapshot_after": {
                    "location_id": "loc-bazaar",
                    "text_state": "集市摊前",
                },
            }
        ],
    )
    await _record(
        db,
        nid,
        scene1,
        [
            {
                "dimension": "locations",
                "event_type": "entity_moved",
                "entity_id": jia,
                "snapshot_after": {"text_state": "新地点"},
            }
        ],
    )
    view = await _view(db, nid, scene1, {"kind": "author"})
    [fact] = [
        fact
        for dim in view.dimensions
        if dim.dimension == "locations"
        for fact in dim.facts
    ]
    assert fact.value["text_state"] == "新地点"
    assert "location_id" not in fact.value  # 旧位置已不在当前 payload
    # 来源必须跟着当前赋值（第二章的 text_state），不得回开第一章的
    # location_id 事件——点击来源要打开真正写出当前值的那一版稿。
    assert fact.source["provenance"]["field"] == "text_state"
    assert fact.source["provenance"]["source_refs"][0]["chapter_index"] == 2


# ============================================================
# F5：月相事实按实例挂链
# ============================================================


async def test_timeline_moon_phase_facts_keep_own_chain(
    db_session: AsyncSession, test_project_id: str
) -> None:
    """多条月相事实各挂各的赋值链，不共用最后一条来源。"""
    db, nid = db_session, test_project_id
    scene0 = await _scene(db, nid, 0, 1)
    scene1 = await _scene(db, nid, 1, 2)
    await _working_draft(db, nid, 1, 1, "满月之夜，甲铸成铜钥匙。")
    await _working_draft(db, nid, 2, 1, "残月之夜，甲把钥匙交给乙。")
    await _record(
        db,
        nid,
        scene0,
        [
            {
                "dimension": "timeline",
                "event_type": "timeline_changed",
                "snapshot_after": {
                    "category": "moon_phase",
                    "moon_phase": "full",
                    "label": "满月铸钥匙",
                },
            }
        ],
    )
    await _record(
        db,
        nid,
        scene1,
        [
            {
                "dimension": "timeline",
                "event_type": "timeline_changed",
                "snapshot_after": {
                    "category": "moon_phase",
                    "moon_phase": "other",
                    "label": "残月交钥匙",
                },
            }
        ],
    )
    view = await _view(db, nid, scene1, {"kind": "author"})
    moon_facts = [
        fact
        for dim in view.dimensions
        if dim.dimension == "timeline"
        for fact in dim.facts
        if (fact.value or {}).get("moon_phase") is not None
    ]
    assert len(moon_facts) == 2
    chapters = {
        fact.value["moon_phase"]: fact.source["provenance"]["source_refs"][0][
            "chapter_index"
        ]
        for fact in moon_facts
    }
    assert chapters == {"full": 1, "other": 2}


# ============================================================
# F6：真实投影登记自己的消费
# ============================================================


async def test_actual_projection_records_its_consumption(
    db_session: AsyncSession, test_project_id: str
) -> None:
    """真实投影建出 checkpoint 后，消费登记必须可查（不是只有定义）。"""
    db, nid = db_session, test_project_id
    scene = await _scene(db, nid, 0, 1)
    draft = await _working_draft(db, nid, 1, 1, "甲将铜钥匙交给乙。")
    await _record(
        db,
        nid,
        scene,
        [
            {
                "dimension": "entities",
                "event_type": "entity_created",
                "entity_id": str(uuid.uuid4()),
                "snapshot_after": {"name": "铜钥匙", "custody_holder": "乙"},
            }
        ],
    )
    built = await SceneMemoryProjectionService().ensure_scene(db, nid, str(scene.id))
    assert len(built.items) == 6

    records = await load_scene_consumption_records(
        db,
        nid,
        [{"id": str(scene.id), "scene_index": 0, "chapter_ids": [1]}],
    )
    assert records, "真实投影建了 6 个 checkpoint 却没有登记消费"
    entities_records = [
        record for record in records if record.consumer.dimension == "entities"
    ]
    assert entities_records, "登记须逐个维度落在产物行上"
    binding = entities_records[0].binding
    assert binding.chapter(1) is not None
    assert binding.chapter(1).draft_id == str(draft.id)
    assert binding.chapter(1).version_number == 1
    assert entities_records[0].method_version.startswith("scene-projection:")
    # 每行只登记本 Scene 本维度的消费：不把前序 Scene 的登记继承进来放大影响面。
    assert {record.consumer.scene_id for record in records} == {str(scene.id)}


async def test_same_draft_edit_invalidates_frozen_field_proof(
    db_session, test_project_id
):
    from modules.writing.schemas import WritingDraftUpdate

    db, nid = db_session, test_project_id
    scene = await _scene(db, nid, 0, 1)
    draft = await _working_draft(db, nid, 1, 1, "门的口令是晨光。")
    subject = str(uuid.uuid4())
    await _record(
        db,
        nid,
        scene,
        [
            {
                "dimension": "entities",
                "event_type": "entity_created",
                "source": "author_confirmation",
                "entity_id": subject,
                "snapshot_after": {"name": "门", "opening_passphrase": "晨光"},
            }
        ],
    )
    await WritingDraftRepository().update(
        db, draft.id, WritingDraftUpdate(content="门的口令已删除。")
    )
    view = await _view(db, nid, scene, {"kind": "author"})
    [fact] = _entity_facts(view, "opening_passphrase", subject)
    assert fact.source["provenance"]["status"] == "unverified"
    assert fact.source["provenance"]["source_refs"] == []
    reader = await _view(db, nid, scene, {"kind": "reader"})
    assert _entity_facts(reader, "opening_passphrase", subject) == []


async def test_reingestion_same_event_freezes_new_version(db_session, test_project_id):
    db, nid = db_session, test_project_id
    scene = await _scene(db, nid, 0, 1)
    await _working_draft(db, nid, 1, 1, "门的口令是晨光。")
    subject = str(uuid.uuid4())
    events = [
        {
            "dimension": "entities",
            "event_type": "entity_created",
            "entity_id": subject,
            "snapshot_after": {"name": "门", "opening_passphrase": "晨光"},
        }
    ]
    await _record(db, nid, scene, events)
    await _working_draft(db, nid, 1, 2, "新增内容。门的口令是晨光。")
    await _record(db, nid, scene, events)
    view = await _view(db, nid, scene, {"kind": "author"})
    [fact] = _entity_facts(view, "opening_passphrase", subject)
    assert fact.source["provenance"]["source_refs"][0]["version_number"] == 2


async def test_nonempty_chapter_does_not_prove_absent_secret(db_session, test_project_id):
    db, nid = db_session, test_project_id
    scene = await _scene(db, nid, 0, 1)
    await _working_draft(db, nid, 1, 1, "门上有一把锁。")
    subject = str(uuid.uuid4())
    await _record(
        db,
        nid,
        scene,
        [
            {
                "dimension": "entities",
                "event_type": "entity_created",
                "entity_id": subject,
                "snapshot_after": {"name": "门", "opening_passphrase": "秘密值"},
            }
        ],
    )
    author = await _view(db, nid, scene, {"kind": "author"})
    assert _entity_facts(author, "opening_passphrase", subject)
    reader = await _view(db, nid, scene, {"kind": "reader"})
    assert _entity_facts(reader, "opening_passphrase", subject) == []


async def test_reader_location_prunes_unshown_fields(db_session, test_project_id):
    db, nid = db_session, test_project_id
    scene = await _scene(db, nid, 0, 1)
    await _working_draft(db, nid, 1, 1, "甲走到灯塔。")
    subject, place = str(uuid.uuid4()), str(uuid.uuid4())
    await _record(
        db,
        nid,
        scene,
        [
            {
                "dimension": "entities",
                "event_type": "entity_created",
                "entity_id": place,
                "snapshot_after": {"name": "灯塔"},
            },
            {
                "dimension": "locations",
                "event_type": "entity_moved",
                "entity_id": subject,
                "snapshot_after": {
                    "location_id": place,
                    "text_state": "秘密房间",
                    "secret_relation": "隐藏",
                },
            },
        ],
    )
    reader = await _view(db, nid, scene, {"kind": "reader"})
    [fact] = [
        fact
        for dim in reader.dimensions
        if dim.dimension == "locations"
        for fact in dim.facts
    ]
    assert fact.value == {"location_id": place}


async def test_inherited_scene_registers_prefix_dependency(db_session, test_project_id):
    db, nid = db_session, test_project_id
    first = await _scene(db, nid, 0, 1)
    second = await _scene(db, nid, 1, 2)
    await _working_draft(db, nid, 1, 1, "甲保管钥匙。")
    await _working_draft(db, nid, 2, 1, "第二场继续。")
    await _record(
        db,
        nid,
        first,
        [
            {
                "dimension": "entities",
                "event_type": "entity_created",
                "entity_id": str(uuid.uuid4()),
                "snapshot_after": {"name": "钥匙", "custody_holder": "甲"},
            }
        ],
    )
    await SceneMemoryProjectionService().ensure_scene(db, nid, str(second.id))
    records = await load_scene_consumption_records(
        db, nid, [{"id": str(second.id), "scene_index": 1, "chapter_ids": [2]}]
    )
    inherited = [
        record for record in records if record.consumer.scene_id == str(second.id)
    ]
    assert inherited
    assert all(
        {chapter.chapter_index for chapter in record.binding.chapters} == {1, 2}
        for record in inherited
    )


async def test_evolution_receipt_from_real_v2_source_is_accepted(
    db_session, test_project_id
):
    from modules.evolution.pipeline import SceneSourceBinding, _observation_evidence

    db, nid = db_session, test_project_id
    scene = await _scene(db, nid, 0, 1)
    await _working_draft(db, nid, 1, 1, "旧稿。")
    v2 = await _working_draft(db, nid, 1, 2, "甲保管钥匙。")
    binding = SceneSourceBinding(
        draft_id=str(v2.id),
        chapter_index=1,
        content_hash=v2.content_hash,
        start_offset=0,
        end_offset=len(v2.content),
    )
    quotes = _observation_evidence(
        {"quote": v2.content},
        source=binding,
        scene_text=v2.content,
        novel_id=nid,
        content_mode="working",
    )
    assert quotes[0]["source_ref"]["source_revision"] == 1
    subject = str(uuid.uuid4())
    await _record(
        db,
        nid,
        scene,
        [
            {
                "dimension": "entities",
                "event_type": "entity_created",
                "entity_id": subject,
                "source": "evolution",
                "snapshot_after": {
                    "name": "钥匙",
                    "custody_holder": "甲",
                    "meta": {
                        "source_receipts": [{"source_ref": quotes[0]["source_ref"]}]
                    },
                },
            }
        ],
    )
    view = await _view(db, nid, scene, {"kind": "author"})
    [fact] = _entity_facts(view, "custody_holder", subject)
    assert fact.source["provenance"]["source_refs"][0]["version_number"] == 2


async def test_reader_cannot_use_later_scene_text_in_same_chapter(
    db_session, test_project_id
):
    db, nid = db_session, test_project_id
    first = await _scene(db, nid, 0, 1)
    second = await _scene(db, nid, 1, 1)
    content = "门仍紧闭。口令是晨光。"
    draft = await _working_draft(db, nid, 1, 1, content)
    for scene, start, end in ((first, 0, 5), (second, 5, len(content))):
        scene.scene_chunks = [
            {
                "chapter_index": 1,
                "start_offset": start,
                "end_offset": end,
                "source_draft_id": str(draft.id),
                "source_content_hash": draft.content_hash,
            }
        ]
    await db.flush()
    subject = str(uuid.uuid4())
    await _record(
        db,
        nid,
        first,
        [
            {
                "dimension": "entities",
                "event_type": "entity_created",
                "entity_id": subject,
                "snapshot_after": {"name": "门", "opening_passphrase": "晨光"},
            }
        ],
    )
    assert (
        _entity_facts(
            await _view(db, nid, first, {"kind": "reader"}), "opening_passphrase", subject
        )
        == []
    )
    assert (
        len(
            _entity_facts(
                await _view(db, nid, second, {"kind": "reader"}),
                "opening_passphrase",
                subject,
            )
        )
        == 1
    )
    first.scene_chunks = [{"chapter_index": 1, "start_offset": 0, "end_offset": 999}]
    await db.flush()
    assert (
        _entity_facts(
            await _view(db, nid, first, {"kind": "reader"}), "opening_passphrase", subject
        )
        == []
    )
    first.scene_chunks = [{"chapter_index": 1}]
    await db.flush()
    assert (
        _entity_facts(
            await _view(db, nid, first, {"kind": "reader"}), "opening_passphrase", subject
        )
        == []
    )


async def test_repeat_ensure_preserves_consumption_timestamp(db_session, test_project_id):
    db, nid = db_session, test_project_id
    scene = await _scene(db, nid, 0, 1)
    await _working_draft(db, nid, 1, 1, "甲持钥匙。")
    service = SceneMemoryProjectionService()
    first = await service.ensure_scene(db, nid, str(scene.id))
    before = {
        item.dimension: item.state_json.get("_consumption_registry")
        for item in first.items
    }
    after = await service.ensure_scene(db, nid, str(scene.id))
    assert {
        item.dimension: item.state_json.get("_consumption_registry")
        for item in after.items
    } == before
    assert [item.id for item in after.items] == [item.id for item in first.items]


async def test_reader_does_not_reuse_shown_proof_from_old_working_version(
    db_session, test_project_id
):
    db, nid = db_session, test_project_id
    scene = await _scene(db, nid, 0, 1)
    await _working_draft(db, nid, 1, 1, "口令是晨光。")
    subject = str(uuid.uuid4())
    await _record(
        db,
        nid,
        scene,
        [
            {
                "dimension": "entities",
                "event_type": "entity_created",
                "entity_id": subject,
                "source": "author_confirmation",
                "snapshot_after": {"name": "门", "opening_passphrase": "晨光"},
            }
        ],
    )
    assert _entity_facts(
        await _view(db, nid, scene, {"kind": "reader"}), "opening_passphrase", subject
    )
    await _working_draft(db, nid, 1, 2, "门仍紧闭；口令在这一版没有展示。")
    author = await _view(db, nid, scene, {"kind": "author"})
    [fact] = _entity_facts(author, "opening_passphrase", subject)
    assert fact.source["provenance"]["source_refs"][0]["version_number"] == 1
    assert (
        _entity_facts(
            await _view(db, nid, scene, {"kind": "reader"}), "opening_passphrase", subject
        )
        == []
    )
