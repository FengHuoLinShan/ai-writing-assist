"""指定场景状态读取（M2 scene-state-view-v1）单测。

合成切片对齐主计划 §3.1：甲把钥匙交给乙保管（所有权与保管证据分开）、
秘密仅丙知道、锁的开启条件未记载。视角分层按 M2 契约 §5 验收。
"""

from __future__ import annotations

import hashlib
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from modules.story.continuity.scene_projection import SceneMemoryProjectionService
from modules.story.continuity.scene_state_view import (
    SCENE_STATE_VIEW_CONTRACT_VERSION,
    SceneStateViewService,
)
from modules.story.continuity.services import MemoryService
from modules.story.outline_state.models import Scene
from modules.writing.models import WritingDraft

pytestmark = pytest.mark.asyncio


async def _working_draft(
    db: AsyncSession,
    novel_id: str,
    chapter_index: int,
    version_number: int,
    content: str,
) -> WritingDraft:
    """直接落 working 稿行（绕过保存失效钩子，沿用模块内夹具惯例）。"""
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


def _custody_fixture_events(key_id: str, jia: str, yi: str, bing: str) -> list[dict]:
    """甲交钥匙给乙保管：holder=乙、owner=甲 两份独立证据；丙知道秘密。"""
    return [
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
            "dimension": "entities",
            "event_type": "entity_updated",
            "entity_id": key_id,
            "snapshot_after": {"custody_holder": yi},
        },
        {
            "dimension": "knowledge",
            "event_type": "knowledge_changed",
            "entity_id": bing,
            "snapshot_after": {
                "character_id": bing,
                "subject_id": key_id,
                "fields": ["custody_holder"],
                "known_values": {"custody_holder": yi},
                "knowledge": "丙知道铜钥匙在乙手中",
            },
        },
        {
            "dimension": "knowledge",
            "event_type": "knowledge_changed",
            "entity_id": yi,
            "snapshot_after": {
                "character_id": yi,
                "subject_id": key_id,
                "knowledge": "乙误信钥匙已归还甲",
                "false": True,
            },
        },
        {
            "dimension": "locations",
            "event_type": "entity_moved",
            "entity_id": yi,
            "snapshot_after": {"node": "雾渡港灯塔", "label": "灯塔下"},
        },
        {
            "dimension": "timeline",
            "event_type": "timeline_changed",
            "snapshot_after": {
                "category": "time_order",
                "field_path": "handover",
                "new_value": "甲在灯塔下把铜钥匙交给乙",
            },
        },
    ]


async def _custody_scene(db: AsyncSession, test_project_id: str):
    scene = await _scene(db, test_project_id, 0, 1)
    # 本章 working 稿：读者视角按「已展示原文证明」判定（无稿即无证明），
    # 保管字段的精确来源就落在这份稿上。
    await _working_draft(
        db, test_project_id, 1, 1, "甲在雾渡港灯塔下把铜钥匙交给乙保管。"
    )
    key_id, jia, yi, bing = (str(uuid.uuid4()) for _ in range(4))
    from modules.world.models import Character, CoreEntity

    for subject, name in ((jia, "甲"), (yi, "乙"), (bing, "丙")):
        db.add(
            CoreEntity(
                id=uuid.UUID(subject),
                novel_id=uuid.UUID(test_project_id),
                name=name,
                entity_type="character",
                status="canonical",
            )
        )
    await db.flush()
    for subject, name in ((jia, "甲"), (yi, "乙"), (bing, "丙")):
        db.add(
            Character(
                entity_id=uuid.UUID(subject),
                novel_id=uuid.UUID(test_project_id),
                name=name,
                status="canonical",
            )
        )
    await db.flush()
    await MemoryService().record_scene_events(
        db,
        test_project_id,
        scene_id=str(scene.id),
        scene_index=0,
        chapter_index=1,
        events=_custody_fixture_events(key_id, jia, yi, bing),
    )
    await SceneMemoryProjectionService().ensure_scene(db, test_project_id, str(scene.id))
    return scene, {"key": key_id, "jia": jia, "yi": yi, "bing": bing}


def _fact(dimensions: list, dimension: str, field: str, subject_id: str | None = None):
    view = next(item for item in dimensions if item.dimension == dimension)
    return [
        fact
        for fact in view.facts
        if fact.field == field and (subject_id is None or fact.subject_id == subject_id)
    ]


async def test_author_view_separates_custody_owner_and_holder(
    db_session: AsyncSession, test_project_id: str
) -> None:
    scene, ids = await _custody_scene(db_session, test_project_id)

    view = await SceneStateViewService().get_view(
        db_session,
        novel_id=test_project_id,
        scene_id=str(scene.id),
        viewpoint={"kind": "author"},
    )

    assert view.contract_version == SCENE_STATE_VIEW_CONTRACT_VERSION
    holders = _fact(view.dimensions, "entities", "custody_holder", ids["key"])
    owners = _fact(view.dimensions, "entities", "custody_owner", ids["key"])
    assert len(holders) == 1 and holders[0].value == ids["yi"]
    assert len(owners) == 1 and owners[0].value == ids["jia"]
    assert holders[0].layer == "fact" and holders[0].confidence == "derived"
    # 作者视角能看到误信标记
    beliefs = [f for f in _fact(view.dimensions, "knowledge", f"knows:{ids['key']}")]
    assert {f.subject_id for f in beliefs} == {ids["bing"], ids["yi"]}
    false_beliefs = [f for f in beliefs if f.possibly_false]
    assert [f.subject_id for f in false_beliefs] == [ids["yi"]]
    # 位置事实
    locations = _fact(view.dimensions, "locations", "location", ids["yi"])
    assert locations[0].value["node"] == "雾渡港灯塔"
    # 时间事实按叙述呈现
    assert _fact(view.dimensions, "timeline", "timeline_fact")
    # 未支持维度显式
    assert "world_valid_time" in view.unsupported_dimensions


async def test_character_view_grants_only_known_facts_and_beliefs(
    db_session: AsyncSession, test_project_id: str
) -> None:
    scene, ids = await _custody_scene(db_session, test_project_id)

    # 乙的视角：自己的位置可见；钥匙事实未经知识授予不可见（乙不知道 owner），
    # 但乙自己的误信 belief 可见且带 possibly_false。
    view = await SceneStateViewService().get_view(
        db_session,
        novel_id=test_project_id,
        scene_id=str(scene.id),
        viewpoint={"kind": "character", "target_id": ids["yi"]},
    )

    entity_facts = [
        f
        for f in next(
            item for item in view.dimensions if item.dimension == "entities"
        ).facts
    ]
    assert entity_facts == []  # 乙无 subject 授权，钥匙字段不出现
    locations = _fact(view.dimensions, "locations", "location", ids["yi"])
    assert locations and locations[0].value["node"] == "雾渡港灯塔"
    beliefs = [
        f
        for f in next(
            item for item in view.dimensions if item.dimension == "knowledge"
        ).facts
        if f.subject_id == ids["yi"]
    ]
    assert len(beliefs) == 1 and beliefs[0].possibly_false
    # 未知显式：不冒充「乙知道一切」
    assert any("角色视角未获得依据" in item for item in view.omissions)

    # 丙的视角：知识显式授予钥匙 subject → 事实可见（丙知道 holder 的事实）。
    view_bing = await SceneStateViewService().get_view(
        db_session,
        novel_id=test_project_id,
        scene_id=str(scene.id),
        viewpoint={"kind": "character", "target_id": ids["bing"]},
    )
    bing_holders = _fact(view_bing.dimensions, "entities", "custody_holder", ids["key"])
    assert len(bing_holders) == 1 and bing_holders[0].value == ids["yi"]
    # 丙的知识只声明 custody_holder：owner 字段不出现（unknown），而不是「无主」。
    assert _fact(view_bing.dimensions, "entities", "custody_owner", ids["key"]) == []


async def test_reader_view_gates_entities_by_reveal(
    db_session: AsyncSession, test_project_id: str
) -> None:
    from unittest.mock import patch

    from modules.story.outline_state.contracts import ReaderRevealDecisionContract

    scene, ids = await _custody_scene(db_session, test_project_id)

    # 无 reveal 策略：不豁免证明——该字段有本章 working 稿的精确来源
    # （读者已读到这一章）才对读者可见。
    view = await SceneStateViewService().get_view(
        db_session,
        novel_id=test_project_id,
        scene_id=str(scene.id),
        viewpoint={"kind": "reader"},
    )
    assert len(_fact(view.dimensions, "entities", "custody_holder", ids["key"])) == 1
    assert _fact(view.dimensions, "timeline", "timeline_fact") == []
    assert (
        next(dim for dim in view.dimensions if dim.dimension == "timeline").status
        == "unsupported"
    )
    # belief / 观察不进入读者视图；因果主张是作者层断言。
    assert all(fact.layer == "fact" for item in view.dimensions for fact in item.facts)
    causality = next(
        (item for item in view.dimensions if item.dimension == "causality"), None
    )
    assert causality is None or causality.facts == []

    # 有策略且未到揭示章 → 门控隐藏，omissions 只报数量不泄露对象。
    async def _hidden(db, *, novel_id, target_type, target_id, cutoff_chapter):
        return ReaderRevealDecisionContract(
            target_type=target_type,
            target_id=target_id,
            has_policy=True,
            revealed=False,
        )

    with patch(
        "modules.story.continuity.scene_state_view.get_reader_reveal_decision",
        autospec=True,
        side_effect=_hidden,
    ):
        gated = await SceneStateViewService().get_view(
            db_session,
            novel_id=test_project_id,
            scene_id=str(scene.id),
            viewpoint={"kind": "reader"},
        )
    assert _fact(gated.dimensions, "entities", "custody_holder", ids["key"]) == []
    assert _fact(gated.dimensions, "locations", "location", ids["yi"]) == []
    assert _fact(gated.dimensions, "timeline", "timeline_fact") == []
    assert gated.subject_labels == {}
    assert any("读者视角尚未揭示" in item for item in gated.omissions)
    assert all(ids["key"] not in item for item in gated.omissions)  # 不泄露对象身份


async def test_same_state_same_viewpoint_same_fingerprint(
    db_session: AsyncSession, test_project_id: str
) -> None:
    scene, _ids = await _custody_scene(db_session, test_project_id)
    service = SceneStateViewService()

    first = await service.get_view(
        db_session,
        novel_id=test_project_id,
        scene_id=str(scene.id),
        viewpoint={"kind": "author"},
    )
    second = await service.get_view(
        db_session,
        novel_id=test_project_id,
        scene_id=str(scene.id),
        viewpoint={"kind": "author"},
    )
    assert first.state_fingerprint == second.state_fingerprint
    # 视角不同 → 指纹不同（视角参数进指纹）
    reader = await service.get_view(
        db_session,
        novel_id=test_project_id,
        scene_id=str(scene.id),
        viewpoint={"kind": "reader"},
    )
    assert reader.state_fingerprint != first.state_fingerprint


async def test_missing_dimensions_are_explicit_gaps(
    db_session: AsyncSession, test_project_id: str
) -> None:
    # 空事件 Scene：V2 的 timeline/causality 保持 missing，不读当前 World 补齐。
    scene = await _scene(db_session, test_project_id, 0, 1)
    await SceneMemoryProjectionService().ensure_scene(
        db_session, test_project_id, str(scene.id)
    )

    view = await SceneStateViewService().get_view(
        db_session,
        novel_id=test_project_id,
        scene_id=str(scene.id),
        viewpoint={"kind": "author"},
    )
    by_dim = {item.dimension: item for item in view.dimensions}
    assert by_dim["timeline"].status == "missing"
    assert by_dim["timeline"].gap_reason
    assert by_dim["entities"].facts == []  # 空状态 ≠ 有事实


async def test_invalid_viewpoint_rejected(
    db_session: AsyncSession, test_project_id: str
) -> None:
    scene = await _scene(db_session, test_project_id, 0, 1)
    from core.errors import ValidationError

    with pytest.raises(ValidationError):
        await SceneStateViewService().get_view(
            db_session,
            novel_id=test_project_id,
            scene_id=str(scene.id),
            viewpoint={"kind": "narrator"},
        )
    with pytest.raises(ValidationError):
        await SceneStateViewService().get_view(
            db_session,
            novel_id=test_project_id,
            scene_id=str(scene.id),
            viewpoint={"kind": "character"},
        )


async def test_a01_state_view_and_scene_lens_agree_on_core_facts(
    db_session: AsyncSession, test_project_id: str
) -> None:
    """A01：状态视图与 Scene Lens 对象状态区读同一投影，核心事实一致。"""
    from modules.evidence.compilation.services.scene_lens import SceneLensService

    key_id, jia, yi = (str(uuid.uuid4()) for _ in range(3))
    scene = await _scene(db_session, test_project_id, 0, 1)
    scene.structure_meta = {"related_entity_ids": [key_id, jia, yi]}
    await db_session.flush()
    await MemoryService().record_scene_events(
        db_session,
        test_project_id,
        scene_id=str(scene.id),
        scene_index=0,
        chapter_index=1,
        events=[
            {
                "dimension": "entities",
                "event_type": "entity_created",
                "entity_id": jia,
                "snapshot_after": {"name": "甲"},
            },
            {
                "dimension": "entities",
                "event_type": "entity_created",
                "entity_id": yi,
                "snapshot_after": {"name": "乙"},
            },
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
                "dimension": "entities",
                "event_type": "entity_updated",
                "entity_id": key_id,
                "snapshot_after": {"custody_holder": yi},
            },
        ],
    )
    await SceneMemoryProjectionService().ensure_scene(
        db_session, test_project_id, str(scene.id)
    )

    view = await SceneStateViewService().get_view(
        db_session,
        novel_id=test_project_id,
        scene_id=str(scene.id),
        viewpoint={"kind": "author"},
    )
    holder = _fact(view.dimensions, "entities", "custody_holder", key_id)[0]
    owner = _fact(view.dimensions, "entities", "custody_owner", key_id)[0]

    scene_row = await db_session.get(Scene, scene.id)
    lens_payload = await SceneLensService().load(
        db_session,
        novel_id=test_project_id,
        scene_id=str(scene.id),
        chapter_index=1,
    )
    objects = {str(item["subject_id"]): item for item in lens_payload["object_states"]}
    key_state = objects[key_id]
    holder_field = next(
        field for field in key_state["fields"] if field["field"] == "custody_holder"
    )
    owner_field = next(
        field for field in key_state["fields"] if field["field"] == "custody_owner"
    )
    # Lens 展示用对象名渲染，状态视图保留原始值：核心事实一致。
    assert (holder_field["display"], owner_field["display"]) == ("乙", "甲")
    assert (holder.value, owner.value) == (yi, jia)
    assert scene_row is not None


async def test_unseen_handover_keeps_old_belief_and_history_source(
    db_session, test_project_id
):
    from core.errors import NotFoundError

    scene, ids = await _custody_scene(db_session, test_project_id)
    projection = SceneMemoryProjectionService()
    previous = await projection.get_scene(db_session, test_project_id, str(scene.id))
    next_scene = await _scene(db_session, test_project_id, 1, 2)
    await MemoryService().record_scene_events(
        db_session,
        test_project_id,
        scene_id=str(next_scene.id),
        scene_index=1,
        chapter_index=2,
        events=[
            {
                "dimension": "entities",
                "event_type": "entity_updated",
                "entity_id": ids["key"],
                "snapshot_after": {"custody_holder": ids["jia"]},
            },
            {
                "dimension": "entities",
                "event_type": "entity_created",
                "entity_id": ids["bing"],
                "snapshot_after": {"name": "丙", "hidden_truth": "丙不知自己的身世"},
            },
        ],
    )
    await projection.ensure_scene(db_session, test_project_id, str(next_scene.id))
    view = await SceneStateViewService().get_view(
        db_session,
        novel_id=test_project_id,
        scene_id=str(next_scene.id),
        viewpoint={"kind": "character", "target_id": ids["bing"]},
    )
    assert _fact(view.dimensions, "entities", "custody_holder", ids["key"]) == []
    assert _fact(view.dimensions, "entities", "hidden_truth", ids["bing"]) == []
    assert "乙手中" in _fact(view.dimensions, "knowledge", f"knows:{ids['key']}")[0].value
    current = await projection.get_scene(db_session, test_project_id, str(next_scene.id))
    inherited = next(item for item in current.items if item.dimension == "knowledge")
    parent_id = next(
        ref["id"] for ref in inherited.evidence_refs if ref["type"] == "scene_checkpoint"
    )
    assert parent_id == next(
        item.id for item in previous.items if item.dimension == "knowledge"
    )
    historical = await projection.get_record(db_session, test_project_id, parent_id)
    assert any(ref["type"] == "memory_event" for ref in historical.evidence_refs)
    with pytest.raises(NotFoundError):
        await projection.get_record(db_session, str(uuid.uuid4()), parent_id)
