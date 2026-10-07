"""P2-A A0 验收夹具 — 逐字段来源（field provenance）期望契约先行。

六固定场景中属 P2-A 的三个场景 + 两个反向断言 + 来源缺失空态。全部用例标注
``xfail(reason="P2-A field provenance not implemented", strict=False)``：夹具数据
经现有公开入口（MemoryService / SceneMemoryProjectionService /
SceneStateViewService，沿用 continuity 模块内测试惯例）真实落库执行到当前实现；
断言针对"将要实现"的逐字段来源接口，A2/A3 实现批完成后逐条转绿。

基线操作步骤与预期（供汇合验收对照）
====================================

场景一「倒叙」（发生时间早但后写）：
  1. Scene 0（第 1 章，working 稿 v1：甲来到集市。）记录 entity_moved：甲 →
     location_id=loc-bazaar（人物位置母题用 CharacterLocationInPanorama 的
     受控键 location_id/text_state，不用自由键）。
  2. Scene 1（第 2 章，working 稿 v1：倒叙——更早的故事时间里甲在灯塔。）记录
     entity_moved：甲 → location_id=loc-lighthouse（故事时间早于 Scene 0）+
     timeline 事件登记「灯塔在集市之前」的相对顺序。
  3. 逐场景 ensure 后分别读 author 视图。
  预期：Scene 0 的甲位置仍是 loc-bazaar、指纹不变，后写场景揭示的灯塔事实不
  回流；Scene 0 位置字段的最后赋值事件是它自己的移动事件（第 1 章 v1 working
  稿范围）；Scene 1 的位置字段 provenance 指向倒叙事件本身；timeline 的
  time_order 事实按叙述呈现，但它不是受控母题字段，不得宣称 exact。

场景二「保管交接」（所有权不变的交接 + 保管再次转移）：
  1. 三章各建 working 稿 v1；Scene 0（第 1 章）entity_created 铜钥匙
     （custody_owner=甲、custody_holder=甲）。
  2. Scene 1（第 2 章）custody_holder → 乙；Scene 2（第 3 章）custody_holder → 丙；
     所有者全程甲。逐场景 ensure。
  预期：custody_owner 的最后赋值停在 Scene 0 创建事件，不被后续交接冒充；
  custody_holder 逐场景指向各自交接事件；历史 checkpoint 逐场景可回开
  （Scene 0 读甲、Scene 1 读乙、Scene 2 读丙）。

场景三「历史版本」（改稿产生新版本）：
  1. Scene 0（第 1 章 working 稿 v1）记录保管事件，ensure 后记下当前
     entities checkpoint id。
  2. 同章插入 working 稿 v2（改稿），rebuild_from_scene 重建。
  预期：旧 checkpoint 仍可经 get_record 回开且 is_current=False；其逐字段来源
  仍指向 v1（不因新 head/重建被洗成当前证明）；新当前视图逐字段来源存在且
  status 合法。

反向断言一「改动无关稿件不改字段内容指纹」：
  Scene 0（第 1 章）/Scene 1（第 2 章）各自有稿与事件；改第 2 章（插 v2）并
  重建后重读 Scene 0 视图：state_fingerprint、字段值与逐字段来源均不变。

反向断言二「历史读取不回填当前 World」：
  Scene 0 建立后修改今天的 World（CoreEntity 补 summary/hidden_truth/别名标签、
  新增今日 CharacterKnowledge），重读历史视图：事实值、subject_labels、
  fingerprint 不变，逐字段来源仍只指向当时的事件与稿件。

来源缺失空态：
  有事件但该章无任何 working 稿时，字段 provenance 必须标 unverified、
  source_refs 为空，不得拿整场事件列表冒充精确依据。

逐字段来源期望契约形态（A1 契约单元对齐基准）
============================================

读取场景状态（SceneStateViewService author 视图）时，每条受控母题字段的 fact
在 ``source`` dict 增加 ``provenance`` 键，为单条记录（非事件列表）：

    {
        "field": <str，受控母题字段键（payload 键，如 custody_holder /
                  location_id；非母题字段不带 provenance 或不得为 exact）>,
        "event_id": <最后赋值 MemoryEvent.id（str）；追不到为 None>,
        "source_refs": [<SourceRangeRefContract 形态 dict>, ...],
        "status": "exact" | "unverified" | "conflict",
    }

- ``status="exact"``：赋值链完整可追（事件 + 稿件范围 + 版本）——event_id 非空
  且 source_refs 至少一条。
- ``source_refs`` 元素以 ``modules/evidence/source_ref_contracts.py`` 的
  SourceRangeRefContract 字段为基准（本文件直接从 dataclass 推导字段集）；
  scene memory 事件链派生自 working 稿（basis.py 同口径），content_mode
  固定 ``"working"``。
- ``status="unverified"``：追不到赋值链（如事件无对应稿件范围）——source_refs
  为空；event_id 可保留已知赋值事件，不得用整场事件列表冒充。
- ``status="conflict"``：多来源竞争，待人工核实。
- 受控母题字段先行：custody_owner/custody_holder、location_id/text_state、
  opening_*；非母题字段（如 timeline 的 time_order 事实）不宣称 exact。
- 历史 checkpoint 回开（SceneMemoryProjectionService.get_record）：暴露
  ``field_provenance``（响应属性或 state_json 的 ``_field_provenance`` 内嵌键，
  两者取其一），保留构建当时生效的版本语义。
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import fields as dataclass_fields
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from modules.evidence.source_ref_contracts import SourceRangeRefContract
from modules.story.continuity.contracts import SCENE_MEMORY_DIMENSIONS
from modules.story.continuity.scene_projection import SceneMemoryProjectionService
from modules.story.continuity.scene_state_view import SceneStateViewService
from modules.story.continuity.services import MemoryService
from modules.story.outline_state.models import Scene
from modules.writing.models import WritingDraft

_PROVENANCE_REASON = "P2-A field provenance not implemented"

_SOURCE_REF_KEYS = frozenset(f.name for f in dataclass_fields(SourceRangeRefContract))

_PROVENANCE_STATUSES = {"exact", "unverified", "conflict"}


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
    db: AsyncSession, novel_id: str, chapter_index: int, version_number: int, content: str
) -> WritingDraft:
    """直接落 working 稿行（绕过失效钩子，同 test_scene_basis 惯例）。

    显式指定 id，供 source_refs 的 draft_id 断言使用。
    """
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


def _event_id(records: list[Any], event_type: str, marker: str) -> str:
    for item in records:
        if item.event_type == event_type and marker in str(item.snapshot_after):
            return str(item.id)
    raise AssertionError(f"fixture event not found: {event_type} / {marker}")


async def _author_view(db: AsyncSession, novel_id: str, scene: Scene) -> Any:
    return await SceneStateViewService().get_view(
        db,
        novel_id=novel_id,
        scene_id=str(scene.id),
        viewpoint={"kind": "author"},
    )


def _dim(view: Any, dimension: str) -> Any:
    return next(item for item in view.dimensions if item.dimension == dimension)


def _facts(
    view: Any, dimension: str, field: str, subject_id: str | None = None
) -> list[Any]:
    return [
        fact
        for fact in _dim(view, dimension).facts
        if fact.field == field and (subject_id is None or fact.subject_id == subject_id)
    ]


def _provenance(fact: Any) -> Any:
    return (fact.source or {}).get("provenance")


def _ref_matches(
    ref: Any, *, draft_id: str, version_number: int, chapter_index: int
) -> bool:
    if not isinstance(ref, dict) or not _SOURCE_REF_KEYS <= set(ref):
        return False
    try:
        return (
            str(ref.get("draft_id")) == draft_id
            and int(ref.get("version_number")) == version_number
            and int(ref.get("chapter_index")) == chapter_index
            and ref.get("content_mode") == "working"
        )
    except (TypeError, ValueError):
        return False


def _assert_exact_provenance(
    provenance: Any,
    *,
    field: str,
    event_id: str,
    draft_id: str,
    version_number: int,
    chapter_index: int,
) -> None:
    """exact 依据：追到赋值事件 + SourceRangeRefContract 形态的稿件范围与版本。"""
    assert isinstance(provenance, dict), f"field provenance missing: {field}"
    assert provenance.get("field") == field
    assert provenance.get("status") == "exact"
    assert provenance.get("event_id") == event_id, (
        f"{field}: last-assignment event must be {event_id}, "
        f"got {provenance.get('event_id')}"
    )
    refs = provenance.get("source_refs")
    assert isinstance(refs, list) and refs, f"{field}: exact provenance needs ranges"
    assert any(
        _ref_matches(
            ref,
            draft_id=draft_id,
            version_number=version_number,
            chapter_index=chapter_index,
        )
        for ref in refs
    ), f"{field}: no working-draft ref for chapter {chapter_index} v{version_number}"


# ============================================================
# 场景一：倒叙（发生时间早但后写）
# ============================================================


@pytest.mark.xfail(reason=_PROVENANCE_REASON, strict=False)
async def test_p2a_flashback_later_scene_facts_do_not_backflow(
    db_session: AsyncSession, test_project_id: str
) -> None:
    scene_present = await _scene(db_session, test_project_id, 0, 1)
    scene_flashback = await _scene(db_session, test_project_id, 1, 2)
    draft_ch1 = await _working_draft(
        db_session, test_project_id, 1, 1, "甲来到集市，在摊前停下。"
    )
    draft_ch2 = await _working_draft(
        db_session, test_project_id, 2, 1, "倒叙：更早的那个清晨，甲还在雾渡港灯塔下。"
    )
    jia = str(uuid.uuid4())
    projection = SceneMemoryProjectionService()

    present_records = await _record(
        db_session,
        test_project_id,
        scene_present,
        [
            {
                "dimension": "locations",
                "event_type": "entity_moved",
                "entity_id": jia,
                "snapshot_after": {"location_id": "loc-bazaar", "text_state": "集市摊前"},
            },
        ],
    )
    await projection.ensure_scene(db_session, test_project_id, str(scene_present.id))
    before = await _author_view(db_session, test_project_id, scene_present)

    flashback_records = await _record(
        db_session,
        test_project_id,
        scene_flashback,
        [
            {
                "dimension": "locations",
                "event_type": "entity_moved",
                "entity_id": jia,
                "snapshot_after": {
                    "location_id": "loc-lighthouse",
                    "text_state": "雾渡港灯塔下",
                },
            },
            {
                "dimension": "timeline",
                "event_type": "timeline_changed",
                "snapshot_after": {
                    "category": "time_order",
                    "field_path": f"{jia}.location",
                    "new_value": "雾渡港灯塔在集市之前",
                },
            },
        ],
    )
    await projection.ensure_scene(db_session, test_project_id, str(scene_flashback.id))
    after = await _author_view(db_session, test_project_id, scene_present)
    later = await _author_view(db_session, test_project_id, scene_flashback)

    # 无当前事实回填：早场景的位置与指纹不因后写倒叙改变。
    assert after.state_fingerprint == before.state_fingerprint
    present_location = _facts(after, "locations", "location", jia)
    assert len(present_location) == 1
    assert present_location[0].value["location_id"] == "loc-bazaar"

    # 早场景字段的最后赋值事件是它自己的移动事件，不是倒叙事件。
    present_event = _event_id(present_records, "entity_moved", "loc-bazaar")
    _assert_exact_provenance(
        _provenance(present_location[0]),
        field="location_id",
        event_id=present_event,
        draft_id=str(draft_ch1.id),
        version_number=1,
        chapter_index=1,
    )

    # 倒叙事实登记在后写场景：位置字段 provenance 指向倒叙事件本身。
    flashback_event = _event_id(flashback_records, "entity_moved", "loc-lighthouse")
    later_location = _facts(later, "locations", "location", jia)
    assert len(later_location) == 1
    assert later_location[0].value["location_id"] == "loc-lighthouse"
    _assert_exact_provenance(
        _provenance(later_location[0]),
        field="location_id",
        event_id=flashback_event,
        draft_id=str(draft_ch2.id),
        version_number=1,
        chapter_index=2,
    )
    # 时间顺序是登记事实（value 按叙述呈现），但 time_order 不是受控母题字段：
    # 不得宣称 exact 逐字段来源，未登记字段不冒充精确依据。
    timeline_fact = _facts(later, "timeline", "timeline_fact")
    assert timeline_fact and timeline_fact[0].value["new_value"] == "雾渡港灯塔在集市之前"
    timeline_provenance = _provenance(timeline_fact[0])
    assert timeline_provenance is None or (
        isinstance(timeline_provenance, dict)
        and timeline_provenance.get("status") != "exact"
    )


# ============================================================
# 场景二：保管交接（所有权不变 + 两次转移，逐场景回开）
# ============================================================


@pytest.mark.xfail(reason=_PROVENANCE_REASON, strict=False)
async def test_p2a_custody_handover_traces_per_scene_field_provenance(
    db_session: AsyncSession, test_project_id: str
) -> None:
    chapters = [
        (0, 1, "甲铸成铜钥匙，亲自收着。"),
        (1, 2, "甲把铜钥匙交给乙保管。"),
        (2, 3, "乙又把铜钥匙转交丙保管。"),
    ]
    scenes = []
    drafts = []
    for scene_index, chapter_index, content in chapters:
        scenes.append(
            await _scene(db_session, test_project_id, scene_index, chapter_index)
        )
        drafts.append(
            await _working_draft(db_session, test_project_id, chapter_index, 1, content)
        )
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

    create_event = _event_id(scene0_records, "entity_created", "铜钥匙")
    transfer_yi = _event_id(scene1_records, "entity_updated", yi)
    transfer_bing = _event_id(scene2_records, "entity_updated", bing)

    view0 = await _author_view(db_session, test_project_id, scenes[0])
    view1 = await _author_view(db_session, test_project_id, scenes[1])
    view2 = await _author_view(db_session, test_project_id, scenes[2])

    # 历史 checkpoint 逐场景可回开：保管者语义不随后续交接漂移，所有者不变。
    assert _facts(view0, "entities", "custody_holder", key_id)[0].value == jia
    assert _facts(view1, "entities", "custody_holder", key_id)[0].value == yi
    assert _facts(view2, "entities", "custody_holder", key_id)[0].value == bing
    assert _facts(view2, "entities", "custody_owner", key_id)[0].value == jia

    # 所有者的最后赋值停留在创建事件，不被后续交接事件冒充。
    _assert_exact_provenance(
        _provenance(_facts(view2, "entities", "custody_owner", key_id)[0]),
        field="custody_owner",
        event_id=create_event,
        draft_id=str(drafts[0].id),
        version_number=1,
        chapter_index=1,
    )
    # 保管者逐场景指向各自的最后交接事件与稿件。
    _assert_exact_provenance(
        _provenance(_facts(view0, "entities", "custody_holder", key_id)[0]),
        field="custody_holder",
        event_id=create_event,
        draft_id=str(drafts[0].id),
        version_number=1,
        chapter_index=1,
    )
    _assert_exact_provenance(
        _provenance(_facts(view1, "entities", "custody_holder", key_id)[0]),
        field="custody_holder",
        event_id=transfer_yi,
        draft_id=str(drafts[1].id),
        version_number=1,
        chapter_index=2,
    )
    _assert_exact_provenance(
        _provenance(_facts(view2, "entities", "custody_holder", key_id)[0]),
        field="custody_holder",
        event_id=transfer_bing,
        draft_id=str(drafts[2].id),
        version_number=1,
        chapter_index=3,
    )


# ============================================================
# 场景三：历史版本（改稿产生新版本，旧 checkpoint 不被洗成当前证明）
# ============================================================


@pytest.mark.xfail(reason=_PROVENANCE_REASON, strict=False)
async def test_p2a_revision_keeps_old_checkpoint_on_its_version(
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
    current = await projection.get_scene(db_session, test_project_id, str(scene.id))
    entities_checkpoint_id = next(
        item.id for item in current.items if item.dimension == "entities"
    )

    # 改稿：同章插入 working 稿 v2，然后重建投影链。
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

    # 旧 checkpoint 仍可回开，且不再冒充当前。
    old = await projection.get_record(
        db_session, test_project_id, str(entities_checkpoint_id)
    )
    assert old.is_current is False

    # 旧行保留构建当时的版本语义：custody_holder 来源指向 v1，不被洗成 v2。
    # 历史回开暴露面：响应 field_provenance 属性，或内嵌 state_json 的
    # ``_field_provenance`` 键（A1 契约的存放位置），两者取其一。
    old_provenance = getattr(old, "field_provenance", None) or (old.state_json or {}).get(
        "_field_provenance"
    )
    assert old_provenance, "historical checkpoint must expose per-field provenance"
    holder = next(
        item
        for item in old_provenance
        if isinstance(item, dict)
        and item.get("field", item.get("field_key")) == "custody_holder"
    )
    old_refs = holder.get("source_refs") or []
    assert any(
        _ref_matches(ref, draft_id=str(draft_v1.id), version_number=1, chapter_index=1)
        for ref in old_refs
    ), "old checkpoint provenance must stay on version 1"
    assert not any(
        isinstance(ref, dict) and str(ref.get("draft_id")) == str(draft_v2.id)
        for ref in old_refs
    ), "old checkpoint provenance must not be washed to the new head"

    # 新当前视图逐字段来源存在且 status 合法（exact 或显式降级，不冒充）。
    view = await _author_view(db_session, test_project_id, scene)
    fact = _facts(view, "entities", "custody_holder", key_id)[0]
    assert fact.value == yi
    provenance = _provenance(fact)
    assert isinstance(provenance, dict)
    assert provenance.get("status") in _PROVENANCE_STATUSES


# ============================================================
# 反向断言一：改动无关稿件不改字段内容指纹
# ============================================================


@pytest.mark.xfail(reason=_PROVENANCE_REASON, strict=False)
async def test_p2a_unrelated_manuscript_change_keeps_field_fingerprint(
    db_session: AsyncSession, test_project_id: str
) -> None:
    scene_key = await _scene(db_session, test_project_id, 0, 1)
    scene_other = await _scene(db_session, test_project_id, 1, 2)
    draft_key = await _working_draft(
        db_session, test_project_id, 1, 1, "甲把铜钥匙交给乙保管。"
    )
    await _working_draft(db_session, test_project_id, 2, 1, "远处港口的钟声敲了三下。")
    key_id, jia, yi = (str(uuid.uuid4()) for _ in range(3))
    projection = SceneMemoryProjectionService()

    key_records = await _record(
        db_session,
        test_project_id,
        scene_key,
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
    # 无关场景也有自己的事件，避免只靠空场景证明隔离。
    await _record(
        db_session,
        test_project_id,
        scene_other,
        [
            {
                "dimension": "timeline",
                "event_type": "timeline_changed",
                "snapshot_after": {
                    "category": "time_order",
                    "field_path": "bell",
                    "new_value": "港口钟声敲了三下",
                },
            },
        ],
    )
    await projection.ensure_scene(db_session, test_project_id, str(scene_other.id))
    before = await _author_view(db_session, test_project_id, scene_key)
    fact_before = _facts(before, "entities", "custody_holder", key_id)[0]
    provenance_before = _provenance(fact_before)
    create_event = _event_id(key_records, "entity_created", "铜钥匙")

    # 改无关稿件（第 2 章 v2），重建无关场景后重读 Scene 0。
    await _working_draft(
        db_session, test_project_id, 2, 2, "远处港口的钟声敲了四下，雾更浓了。"
    )
    await projection.ensure_scene(db_session, test_project_id, str(scene_other.id))
    after = await _author_view(db_session, test_project_id, scene_key)
    fact_after = _facts(after, "entities", "custody_holder", key_id)[0]

    # 字段内容指纹不变：视图指纹与字段值都不受无关稿件改动影响。
    assert after.state_fingerprint == before.state_fingerprint
    assert fact_after.value == fact_before.value

    # 逐字段来源同样不变：仍指向原事件与原稿件（第 1 章 v1）。
    assert isinstance(provenance_before, dict), "field provenance missing"
    assert _provenance(fact_after) == provenance_before
    _assert_exact_provenance(
        provenance_before,
        field="custody_holder",
        event_id=create_event,
        draft_id=str(draft_key.id),
        version_number=1,
        chapter_index=1,
    )


# ============================================================
# 反向断言二：历史读取不回填当前 World 知识/地点/标签
# ============================================================


@pytest.mark.xfail(reason=_PROVENANCE_REASON, strict=False)
async def test_p2a_historical_read_does_not_backfill_current_world(
    db_session: AsyncSession, test_project_id: str
) -> None:
    from modules.world.models.character import Character, CharacterKnowledge
    from modules.world.models.core import CoreEntity

    scene = await _scene(db_session, test_project_id, 0, 1)
    draft = await _working_draft(
        db_session, test_project_id, 1, 1, "乙提着灯走到雾渡港灯塔下。"
    )
    jia = str(uuid.uuid4())
    db_session.add(
        CoreEntity(
            id=uuid.UUID(jia),
            novel_id=uuid.UUID(test_project_id),
            name="乙",
            entity_type="character",
            status="canonical",
        )
    )
    db_session.add(
        Character(
            entity_id=uuid.UUID(jia),
            novel_id=uuid.UUID(test_project_id),
            name="乙",
            status="canonical",
        )
    )
    await db_session.flush()
    records = await _record(
        db_session,
        test_project_id,
        scene,
        [
            {
                "dimension": "entities",
                "event_type": "entity_created",
                "entity_id": jia,
                "snapshot_after": {"name": "乙", "mood": "疲惫"},
            },
            {
                "dimension": "locations",
                "event_type": "entity_moved",
                "entity_id": jia,
                "snapshot_after": {"location_id": "loc-lighthouse"},
            },
        ],
    )
    projection = SceneMemoryProjectionService()
    await projection.ensure_scene(db_session, test_project_id, str(scene.id))
    before = await _author_view(db_session, test_project_id, scene)
    location_before = _facts(before, "locations", "location", jia)[0]
    mood_before = _facts(before, "entities", "mood", jia)[0]

    # 今天的 World：乙补写概要与隐藏真相、加别名标签，并新增今日知识。
    entity = await db_session.get(CoreEntity, uuid.UUID(jia))
    entity.summary = "今日补写的概要"
    entity.hidden_truth = "今日新增的隐藏真相"
    entity.content_json = {"aliases": ["阿乙"], "tags": ["重犯"]}
    db_session.add(
        CharacterKnowledge(
            novel_id=uuid.UUID(test_project_id),
            character_id=uuid.UUID(jia),
            target_type="entity",
            target_id=uuid.UUID(jia),
            knowledge_level="full",
            known_content="今日才写下的知识：乙其实认得灯塔看守",
            status="canonical",
        )
    )
    await db_session.flush()

    after = await _author_view(db_session, test_project_id, scene)

    # 事实值、subject_labels、指纹都不回填今天的 World 内容。
    assert after.state_fingerprint == before.state_fingerprint
    assert after.subject_labels == before.subject_labels
    location_after = _facts(after, "locations", "location", jia)[0]
    assert location_after.value == location_before.value
    assert "aliases" not in location_after.value and "tags" not in location_after.value
    assert _facts(after, "entities", "mood", jia)[0].value == mood_before.value
    assert _dim(after, "knowledge").facts == []

    # 逐字段来源仍只指向当时的事件与稿件，不引用今日 World 对象。
    moved_event = _event_id(records, "entity_moved", "loc-lighthouse")
    _assert_exact_provenance(
        _provenance(location_after),
        field="location_id",
        event_id=moved_event,
        draft_id=str(draft.id),
        version_number=1,
        chapter_index=1,
    )


# ============================================================
# 来源缺失空态：无稿事件的字段标 unverified，不拿整场事件列表冒充
# ============================================================


@pytest.mark.xfail(reason=_PROVENANCE_REASON, strict=False)
async def test_p2a_missing_manuscript_source_marks_fields_unverified(
    db_session: AsyncSession, test_project_id: str
) -> None:
    scene = await _scene(db_session, test_project_id, 0, 1)  # 第 1 章无任何 working 稿
    key_id, jia = (str(uuid.uuid4()) for _ in range(2))
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

    view = await _author_view(db_session, test_project_id, scene)
    fact = _facts(view, "entities", "custody_owner", key_id)[0]
    assert fact.value == jia

    provenance = _provenance(fact)
    assert isinstance(provenance, dict), "field provenance missing"
    assert provenance.get("status") == "unverified"
    assert provenance.get("source_refs") == []
    assert not provenance.get("event_ids"), (
        "unverified 字段不得用整场事件列表冒充精确依据"
    )
