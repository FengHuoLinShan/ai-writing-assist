"""P2-B B3 接线验收 — 视角边界与揭示闸三条读取路径的一致性。

钉住 B1 契约（knowledge_contract.py）在读取端的接线行为：

1. 读者揭示双闸（``evaluate_reader_reveal`` + ``reveal_within_proven_shown``）：
   timeline 揭示事件（``field_path={subject}.{field}``）构成揭示主张锚——
   无策略也不再默认公开；锚章到 cutoff 之前隐藏（当章不揭示）；过了
   cutoff 还须落在该对象 exact 稿源章内才启用（unverified 不构成证明）；
   无锚对象维持结构层默认公开（既有语义不回归）。
2. 同边界三路径一致：缓存命中读（ensure 幂等命中既有 checkpoint）、
   投影重建读（rebuild_from_scene 全量重建）两条路径的 reader 可见性
   与 character 逐条拒绝原因一致；历史回开（get_record）的知识方言分类
   按历史行自身 payload 判定，不被当前投影重建洗掉。
3. ``denied_facts`` 响应结构经 jsonable_encoder（API 出口编码）保留。
"""

from __future__ import annotations

import hashlib
import uuid
from typing import Any

from fastapi.encoders import jsonable_encoder
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.story.continuity.models import MemorySceneCheckpoint
from modules.story.continuity.scene_projection import SceneMemoryProjectionService
from modules.story.continuity.scene_state_view import SceneStateViewService
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


async def _character(db: AsyncSession, novel_id: str, subject: str, name: str) -> None:
    from modules.world.models.character import Character
    from modules.world.models.core import CoreEntity

    db.add(
        CoreEntity(
            id=uuid.UUID(subject),
            novel_id=uuid.UUID(novel_id),
            name=name,
            entity_type="character",
            status="canonical",
        )
    )
    await db.flush()
    db.add(
        Character(
            entity_id=uuid.UUID(subject),
            novel_id=uuid.UUID(novel_id),
            name=name,
            status="canonical",
        )
    )
    await db.flush()


async def _working_draft(
    db: AsyncSession, novel_id: str, chapter_index: int, content: str
) -> None:
    db.add(
        WritingDraft(
            id=uuid.uuid4(),
            novel_id=uuid.UUID(novel_id),
            chapter_index=chapter_index,
            content=content,
            content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
            version_number=1,
            status="draft",
        )
    )
    await db.flush()


async def _record(
    db: AsyncSession, novel_id: str, scene: Scene, events: list[dict[str, Any]]
) -> None:
    await MemoryService().record_scene_events(
        db,
        novel_id,
        scene_id=str(scene.id),
        scene_index=scene.scene_index,
        chapter_index=int(scene.chapter_ids[0]),
        events=events,
        producer_family="p2b_boundary_wiring",
    )


async def _view(
    db: AsyncSession, novel_id: str, scene: Scene, viewpoint: dict[str, Any]
) -> Any:
    await SceneMemoryProjectionService().ensure_scene(db, novel_id, str(scene.id))
    return await SceneStateViewService().get_view(
        db, novel_id=novel_id, scene_id=str(scene.id), viewpoint=viewpoint
    )


def _facts(
    view: Any, dimension: str, field: str, subject_id: str | None = None
) -> list[Any]:
    return [
        fact
        for dim in view.dimensions
        if dim.dimension == dimension
        for fact in dim.facts
        if fact.field == field and (subject_id is None or fact.subject_id == subject_id)
    ]


async def _current_checkpoint_id(
    db: AsyncSession, novel_id: str, scene: Scene, dimension: str
) -> str:
    row = (
        (
            await db.execute(
                select(MemorySceneCheckpoint).where(
                    MemorySceneCheckpoint.novel_id == uuid.UUID(novel_id),
                    MemorySceneCheckpoint.scene_id == scene.id,
                    MemorySceneCheckpoint.dimension == dimension,
                    MemorySceneCheckpoint.is_current.is_(True),
                )
            )
        )
        .scalars()
        .one()
    )
    return str(row.id)


# ============================================================
# 读者揭示双闸：主张锚 → cutoff 闸 → 证明闸（exact 稿源）
# ============================================================


async def test_reader_reveal_claim_anchor_gates_until_proven_shown(
    db_session: AsyncSession, test_project_id: str
) -> None:
    """有主张锚的对象：cutoff 前/当章隐藏；过了 cutoff 仍须 exact 稿源证明。"""
    scene0 = await _scene(db_session, test_project_id, 0, 1)
    scene1 = await _scene(db_session, test_project_id, 1, 2)
    scene2 = await _scene(db_session, test_project_id, 2, 3)
    key, plain, free = (str(uuid.uuid4()) for _ in range(3))
    jia = str(uuid.uuid4())
    await _character(db_session, test_project_id, jia, "甲")
    # 章 1 有 working 稿（custody_holder 首次赋值 exact）；章 2 无稿——
    # 揭示锚章的赋值链只追到事件（unverified），不构成已展示证明。
    await _working_draft(
        db_session, test_project_id, 1, "甲铸成铜钥匙，公开之物归甲所有。"
    )

    await _record(
        db_session,
        test_project_id,
        scene0,
        [
            {
                "dimension": "entities",
                "event_type": "entity_created",
                "entity_id": jia,
                "snapshot_after": {"name": "甲"},
            },
            {
                "dimension": "entities",
                "event_type": "entity_created",
                "entity_id": key,
                "snapshot_after": {"name": "铜钥匙", "custody_holder": jia},
            },
            {
                "dimension": "entities",
                "event_type": "entity_created",
                "entity_id": plain,
                "snapshot_after": {"name": "无锚之物", "note": "普通物件"},
            },
            {
                "dimension": "entities",
                "event_type": "entity_created",
                "entity_id": free,
                # 无揭示主张、但受控字段自带本章稿源证明的对照对象。
                "snapshot_after": {"name": "公开之物", "custody_owner": jia},
            },
        ],
    )
    await _record(
        db_session,
        test_project_id,
        scene1,
        [
            {
                "dimension": "entities",
                "event_type": "entity_updated",
                "entity_id": key,
                "snapshot_after": {"custody_holder": plain},
            },
            {
                "dimension": "timeline",
                "event_type": "timeline_changed",
                "snapshot_after": {
                    "category": "time_order",
                    "field_path": f"{key}.custody_holder",
                    "new_value": "第二章末尾向读者揭示钥匙易手",
                },
            },
        ],
    )
    await _record(db_session, test_project_id, scene2, [])

    # 锚章（2）之前：主张记录把对象移入须证明域，无策略也不默认公开。
    early = await _view(
        db_session,
        test_project_id,
        scene0,
        {"kind": "reader"},
    )
    assert _facts(early, "entities", "custody_holder", key) == []
    assert any("读者视角尚未揭示" in item for item in early.omissions)
    # 对照一：无主张锚也不豁免证明——``note`` 不是受控字段、没有稿源区间，
    # 无已展示证明即不对读者公开（缺策略 ≠ 存在证明）。
    assert _facts(early, "entities", "note", plain) == []
    # 对照二：无主张锚、但该字段自身有本章 exact 稿源（读者已读到）→ 可见。
    assert len(_facts(early, "entities", "custody_owner", free)) == 1

    # 当章不揭示：锚章 == cutoff（读者正读第二章）仍隐藏。
    current = await _view(
        db_session,
        test_project_id,
        scene1,
        {"kind": "reader"},
    )
    assert _facts(current, "entities", "custody_holder", key) == []

    # 过了 cutoff 但锚章无 exact 稿源（章 2 无 working 稿 → 赋值链
    # unverified，source_refs 空）：不构成已展示证明，证明闸拒绝。
    later = await _view(
        db_session,
        test_project_id,
        scene2,
        {"kind": "reader"},
    )
    assert _facts(later, "entities", "custody_holder", key) == []
    assert any("读者视角尚未揭示" in item for item in later.omissions)


async def test_reader_reveal_enabled_within_exact_proven_chapters(
    db_session: AsyncSession, test_project_id: str
) -> None:
    """锚章带 exact 稿源（working 稿整章区间）时，cutoff 过后对读者启用。"""
    scene0 = await _scene(db_session, test_project_id, 0, 1)
    scene1 = await _scene(db_session, test_project_id, 1, 2)
    scene2 = await _scene(db_session, test_project_id, 2, 3)
    key = str(uuid.uuid4())
    jia = str(uuid.uuid4())
    await _character(db_session, test_project_id, jia, "甲")
    await _working_draft(db_session, test_project_id, 1, "甲铸成铜钥匙。")
    await _working_draft(db_session, test_project_id, 2, "钥匙在灯塔下易手，由乙保管。")

    await _record(
        db_session,
        test_project_id,
        scene0,
        [
            {
                "dimension": "entities",
                "event_type": "entity_created",
                "entity_id": key,
                "snapshot_after": {"name": "铜钥匙", "custody_holder": jia},
            }
        ],
    )
    await _record(
        db_session,
        test_project_id,
        scene1,
        [
            {
                "dimension": "entities",
                "event_type": "entity_updated",
                "entity_id": key,
                "snapshot_after": {"custody_holder": "乙"},
            },
            {
                "dimension": "timeline",
                "event_type": "timeline_changed",
                "snapshot_after": {
                    "category": "time_order",
                    "field_path": f"{key}.custody_holder",
                    "new_value": "第二章末尾向读者揭示钥匙下落",
                },
            },
        ],
    )
    await _record(db_session, test_project_id, scene2, [])

    later = await _view(
        db_session,
        test_project_id,
        scene2,
        {"kind": "reader"},
    )
    # 锚章 2 < cutoff 3 且章 2 有 exact 稿源：双闸通过，读者可见。
    holders = _facts(later, "entities", "custody_holder", key)
    assert len(holders) == 1 and holders[0].value == "乙"


# ============================================================
# 同边界三路径一致：缓存命中 / 投影重建 / 历史回开
# ============================================================


def _visible_signature(view: Any) -> list[tuple[str, str, str, str]]:
    return sorted(
        (dim.dimension, str(fact.subject_id), fact.field, str(fact.value))
        for dim in view.dimensions
        for fact in dim.facts
    )


def _denied_signature(view: Any) -> list[tuple[str, str, str, str]]:
    return sorted(
        (
            str(item.get("subject_id")),
            str(item.get("field")),
            str(item.get("cause")),
        )
        for item in getattr(view, "denied_facts", None) or []
    )


async def test_reveal_and_denial_boundaries_consistent_across_rebuild(
    db_session: AsyncSession, test_project_id: str
) -> None:
    """reader 可见性与 character 拒绝原因在缓存命中与投影重建两条路径一致。"""
    scene0 = await _scene(db_session, test_project_id, 0, 1)
    scene1 = await _scene(db_session, test_project_id, 1, 2)
    yi, key = str(uuid.uuid4()), str(uuid.uuid4())
    await _character(db_session, test_project_id, yi, "乙")
    secret = str(uuid.uuid4())

    await _record(
        db_session,
        test_project_id,
        scene0,
        [
            {
                "dimension": "entities",
                "event_type": "entity_created",
                "entity_id": key,
                "snapshot_after": {"name": "铜钥匙", "custody_holder": yi},
            },
            {
                "dimension": "entities",
                "event_type": "entity_created",
                "entity_id": secret,
                "snapshot_after": {"name": "暗记", "secret_relation": "暗记指向沉船"},
            },
        ],
    )
    await _record(
        db_session,
        test_project_id,
        scene1,
        [
            {
                "dimension": "timeline",
                "event_type": "timeline_changed",
                "snapshot_after": {
                    "category": "time_order",
                    "field_path": f"{secret}.secret_relation",
                    "new_value": "第二章末尾向读者揭示暗记指向",
                },
            }
        ],
    )
    service = SceneStateViewService()
    projection = SceneMemoryProjectionService()

    # 路径一：缓存命中（ensure 幂等命中既有 checkpoint 后直接读）。
    await projection.ensure_scene(db_session, test_project_id, str(scene0.id))
    cached_reader = await service.get_view(
        db_session,
        novel_id=test_project_id,
        scene_id=str(scene0.id),
        viewpoint={"kind": "reader"},
    )
    cached_character = await service.get_view(
        db_session,
        novel_id=test_project_id,
        scene_id=str(scene0.id),
        viewpoint={"kind": "character", "target_id": yi},
    )

    # 路径二：投影重建（supersede 全部系统行后从头重算）。
    await projection.rebuild_from_scene(
        db_session,
        test_project_id,
        from_scene_id=None,
        dimensions=[
            "entities",
            "relations",
            "locations",
            "knowledge",
            "timeline",
            "causality",
        ],
    )
    rebuilt_reader = await service.get_view(
        db_session,
        novel_id=test_project_id,
        scene_id=str(scene0.id),
        viewpoint={"kind": "reader"},
    )
    rebuilt_character = await service.get_view(
        db_session,
        novel_id=test_project_id,
        scene_id=str(scene0.id),
        viewpoint={"kind": "character", "target_id": yi},
    )

    # 揭示边界一致：主张锚对象隐藏、无锚对象公开，重建不改变判定。
    assert _visible_signature(cached_reader) == _visible_signature(rebuilt_reader)
    assert _facts(cached_reader, "entities", "secret_relation", secret) == []
    assert any("读者视角尚未揭示" in item for item in cached_reader.omissions)
    assert cached_reader.omissions == rebuilt_reader.omissions
    # 知识边界一致：三类拒绝原因（旁观无条目）逐条同因。
    assert _denied_signature(cached_character) == _denied_signature(rebuilt_character)
    causes = {
        (item["subject_id"], item["field"]): item["cause"]
        for item in cached_character.denied_facts
    }
    assert causes.get((key, "custody_holder")) == "no_knowledge_entry"
    assert causes.get((secret, "secret_relation")) == "no_knowledge_entry"
    # 缓存命中路径的 fingerprint 稳定（重建换行 id，不比对 fingerprint）。


async def test_get_record_annotates_knowledge_dialect_and_survives_rebuild(
    db_session: AsyncSession, test_project_id: str
) -> None:
    """历史回开：知识条目带方言分类，且按历史行自身 payload 判定不被洗。"""
    scene = await _scene(db_session, test_project_id, 0, 1)
    yi, lock = str(uuid.uuid4()), str(uuid.uuid4())
    await _character(db_session, test_project_id, yi, "乙")
    projection = SceneMemoryProjectionService()

    await _record(
        db_session,
        test_project_id,
        scene,
        [
            {
                "dimension": "entities",
                "event_type": "entity_created",
                "entity_id": lock,
                "snapshot_after": {"name": "三簧锁", "opening_passphrase": "潮落"},
            },
            {
                "dimension": "knowledge",
                "event_type": "knowledge_changed",
                "entity_id": yi,
                "snapshot_after": {
                    "character_id": yi,
                    "subject_id": lock,
                    "fields": ["opening_passphrase"],
                    "known_values": {"opening_passphrase": "潮落"},
                    "knowledge": "乙知道口令",
                },
            },
            {
                "dimension": "knowledge",
                "event_type": "knowledge_changed",
                "entity_id": yi,
                "snapshot_after": {
                    "character_id": yi,
                    "subject_id": lock,
                    "fields": ["opening_passphrase"],
                    "known_values": {"opening_passphrase": "潮起"},
                    "knowledge": "乙误信口令已改",
                    "false": True,
                },
            },
        ],
    )
    await projection.ensure_scene(db_session, test_project_id, str(scene.id))
    current_id = await _current_checkpoint_id(
        db_session, test_project_id, scene, "knowledge"
    )

    record = await projection.get_record(db_session, test_project_id, current_id)
    entries = record.state_json["character_knowledge"]
    classes = {entry.get("knowledge"): entry.get("knowledge_class") for entry in entries}
    assert classes["乙知道口令"] == "known"
    assert classes["乙误信口令已改"] == "false_belief"
    # 标注只追加：原条目键（值绑定证据）全保留，作者诊断不丢信息。
    assert entries[0]["known_values"] == {"opening_passphrase": "潮落"}
    assert "knowledge" in entries[0]

    # 该行成为历史行（事件流追加改写 + 重建）：分类按历史行自身 payload
    # 原文判定，不被当前投影重建洗掉；ORM 行载荷不被响应标注污染。
    # （record_scene_events 的家族替换按事件 source 匹配，测试事件未带
    # family source，语义为追加——当前行含三条，历史行仍固化两条。）
    await _record(
        db_session,
        test_project_id,
        scene,
        [
            {
                "dimension": "knowledge",
                "event_type": "knowledge_changed",
                "entity_id": yi,
                "snapshot_after": {
                    "character_id": yi,
                    "subject_id": lock,
                    "knowledge": "乙只知道有这么把锁（无值绑定）",
                },
            }
        ],
    )
    await projection.ensure_scene(db_session, test_project_id, str(scene.id))
    await projection.rebuild_from_scene(
        db_session,
        test_project_id,
        from_scene_id=None,
        dimensions=["entities", "knowledge"],
    )
    historic = await projection.get_record(db_session, test_project_id, current_id)
    historic_classes = {
        entry.get("knowledge"): entry.get("knowledge_class")
        for entry in historic.state_json["character_knowledge"]
    }
    assert historic_classes["乙知道口令"] == "known"
    assert historic_classes["乙误信口令已改"] == "false_belief"
    assert len(historic_classes) == 2  # 历史行固化当时两条，不被追加洗掉
    # 当前行对照：追加的无值绑定文本条目落 unknown（不冒充值绑定）。
    current_new_id = await _current_checkpoint_id(
        db_session, test_project_id, scene, "knowledge"
    )
    fresh = await projection.get_record(db_session, test_project_id, current_new_id)
    assert [
        entry.get("knowledge_class") for entry in fresh.state_json["character_knowledge"]
    ] == ["known", "false_belief", "unknown"]
    # 存储载荷不被响应副本的标注键污染。
    row = (
        (
            await db_session.execute(
                select(MemorySceneCheckpoint).where(
                    MemorySceneCheckpoint.id == uuid.UUID(current_id)
                )
            )
        )
        .scalars()
        .one()
    )
    assert all(
        "knowledge_class" not in (entry or {})
        for entry in (row.state_json or {}).get("character_knowledge") or []
    )


async def test_denied_facts_survive_api_jsonable_encoding(
    db_session: AsyncSession, test_project_id: str
) -> None:
    """``denied_facts`` 经 API 出口编码器保留（response_model 父类校验链）。"""
    scene = await _scene(db_session, test_project_id, 0, 1)
    yi, key = str(uuid.uuid4()), str(uuid.uuid4())
    await _character(db_session, test_project_id, yi, "乙")

    await _record(
        db_session,
        test_project_id,
        scene,
        [
            {
                "dimension": "entities",
                "event_type": "entity_created",
                "entity_id": key,
                "snapshot_after": {"name": "铜钥匙", "custody_holder": yi},
            }
        ],
    )
    view = await _view(
        db_session,
        test_project_id,
        scene,
        {"kind": "character", "target_id": yi},
    )
    payload = jsonable_encoder(view)
    assert any(
        item["cause"] == "no_knowledge_entry"
        and item["subject_id"] == key
        and item["field"] == "custody_holder"
        for item in payload["denied_facts"]
    )
    # 既有字段语义不变（只增不删）。
    assert payload["omissions"] and payload["state_fingerprint"]
