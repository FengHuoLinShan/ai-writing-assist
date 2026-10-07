"""P2-B B2 机器知识接线 — 机器断言进 continuity 恒为 unknown 文本知识。

机器路径（evolution ``state_gate`` 派生观察 → ``KnowledgeInPanorama`` 方言
→ ``replace_scene_memory_events(producer_family="evolution")``）写入
continuity 的两条不变量（B1 方言统一裁定的接线验收）：

1. **产出门拒绝值绑定**：机器知识 payload 携带 ``VALUE_BINDING_KEYS``
   （subject_id/fields/known_values）时被 ``gate_scene_events`` 以
   ``value_binding_not_machine_grounded`` 拒进待裁定——机器观察没有值级
   证据（``GROUNDING_MODALITIES``），方言表达不了"知道哪个值"；镜像常量
   与 ``knowledge_contract.VALUE_BINDING_KEYS`` 钉死相等，防漂移。
2. **信任边界不采信透传键**：``KnowledgeInPanorama`` 未声明 ``extra``
   （Pydantic 默认忽略额外键），绑定键即便绕过产出门到达 continuity
   写入边界（source=evolution），``MemoryService.record_scene_events`` 也
   经 ``read_machine_knowledge`` 投影后剥除绑定键再入库——continuity 状态
   （``character_knowledge``）与角色视角授予都不含值绑定。机器断言端到端
   落统一方言形态：unknown 文本知识、无值绑定、origin=
   machine_observation、传闻级 unchecked_note 保留。

对照：Story 事件方言（character_id + subject_id + fields + known_values，
作者确认/抽取路径）不受机器边界影响——绑定键原样入库并照常授予，证明
剥除只针对机器方言，不越界清洗作者/抽取路径的知识。
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from modules.evolution.state_gate import gate_scene_events
from modules.story.continuity.knowledge_contract import (
    VALUE_BINDING_KEYS,
    KnowledgeClass,
    KnowledgeOrigin,
    read_machine_knowledge,
)
from modules.story.continuity.scene_projection import SceneMemoryProjectionService
from modules.story.continuity.scene_state_view import SceneStateViewService
from modules.story.continuity.services import MACHINE_EVENT_SOURCE, MemoryService
from modules.story.outline_state.models import Scene

E1 = "11111111-1111-4111-8111-111111111111"  # 持有者（角色）
E2 = "22222222-2222-4222-8222-222222222222"  # 知识对象（青铜锁）


# ============================================================
# 合成数据构造（沿用 continuity 模块内测试惯例与 state_gate 测试口径）
# ============================================================


def _obs(
    observation_id: str,
    modality: str,
    resolutions: dict[str, str],
) -> dict[str, Any]:
    """编译后的观察条目：mentions 按表面名 → 已解析实体（reuse）。"""
    return {
        "observation_id": observation_id,
        "predicate": f"predicate-{observation_id[:4]}",
        "modality": modality,
        "quote": "原文引用",
        "mentions": [
            {
                "mention_id": f"m-{surface}",
                "surface": surface,
                "entity_type": "character",
                "resolution": {
                    "outcome": "reuse",
                    "resolved_entity_id": entity_id,
                },
            }
            for surface, entity_id in resolutions.items()
        ],
    }


EVENT_WITH_LOCK = _obs("e" * 64, "event_observed", {"林舟": E1, "青铜锁": E2})


def _machine_knowledge_event(snapshot_after: dict[str, Any]) -> dict[str, Any]:
    """机器知识事件提议（state_gate 输入形态，evolution 管线产出）。"""
    return {
        "dimension": "knowledge",
        "event_type": "knowledge_changed",
        "knowledge_subject": "林舟",
        "subject_surface": "林舟",
        "source_observation_indices": [0],
        "snapshot_after": snapshot_after,
    }


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
    """登记真实人物（CoreEntity + Character），供 character 视角校验通过。"""
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


async def _record(
    db: AsyncSession,
    novel_id: str,
    scene: Scene,
    events: list[dict[str, Any]],
    *,
    producer_family: str = "evolution",
) -> list[Any]:
    return await MemoryService().record_scene_events(
        db,
        novel_id,
        scene_id=str(scene.id),
        scene_index=scene.scene_index,
        chapter_index=int(scene.chapter_ids[0]),
        events=events,
        producer_family=producer_family,
    )


async def _knowledge_state(
    db: AsyncSession, novel_id: str, scene: Scene
) -> dict[str, Any]:
    """ensure_scene 后取 knowledge 维度 checkpoint 的 state_json。"""
    from modules.story.continuity.repositories import SceneCheckpointRepository

    await SceneMemoryProjectionService().ensure_scene(db, novel_id, str(scene.id))
    rows = await SceneCheckpointRepository().list_current_for_scene(
        db, uuid.UUID(novel_id), scene.id
    )
    row = next(item for item in rows if item.dimension == "knowledge")
    return row.state_json or {}


def _facts(view: Any, dimension: str, field: str, subject_id: str | None = None):
    dim = next(item for item in view.dimensions if item.dimension == dimension)
    return [
        fact
        for fact in dim.facts
        if fact.field == field and (subject_id is None or fact.subject_id == subject_id)
    ]


# ============================================================
# 不变量一：产出门拒绝机器值绑定键（evolution/state_gate）
# ============================================================


def test_gate_value_binding_keys_mirror_contract() -> None:
    """state_gate 镜像常量与契约 VALUE_BINDING_KEYS 相等（镜像防漂移）。"""
    from modules.evolution.state_gate import _MACHINE_VALUE_BINDING_KEYS

    assert _MACHINE_VALUE_BINDING_KEYS == VALUE_BINDING_KEYS


def test_gate_rejects_machine_knowledge_claiming_value_bindings() -> None:
    """机器知识 payload 偷带值绑定键 → value_binding_not_machine_grounded 拒绝。"""
    clean = {
        "target_type": "entity",
        "target_id": E2,
        "known_content": "林舟听说青铜锁的口令",
        "knowledge_level": "rumor",
    }
    applied, gated = gate_scene_events(
        [_machine_knowledge_event(dict(clean))], [EVENT_WITH_LOCK]
    )
    assert not gated and len(applied) == 1

    smuggled_cases = [
        {"subject_id": E2},
        {"fields": ["opening_passphrase"]},
        {"known_values": {"opening_passphrase": "潮落"}},
        {
            "subject_id": E2,
            "fields": ["opening_passphrase"],
            "known_values": {"opening_passphrase": "潮落"},
        },
    ]
    for extra in smuggled_cases:
        _, rejected = gate_scene_events(
            [_machine_knowledge_event({**clean, **extra})], [EVENT_WITH_LOCK]
        )
        assert rejected, f"绑定键 {sorted(extra)} 未被产出门拦截"
        assert "value_binding_not_machine_grounded" in rejected[0]["_gate_reasons"]


# ============================================================
# 不变量二：端到端 — 机器断言落统一方言（unknown 文本知识，零授予）
# ============================================================


async def test_machine_knowledge_lands_as_unbound_text_knowledge(
    db_session: AsyncSession, test_project_id: str
) -> None:
    """gate 通过的机器知识端到端进 continuity：unknown 文本知识、无值绑定。

    真实链路：gate_scene_events 产出 → source=evolution 入库（tasks.py 口径）
    → reducer 落 character_knowledge → 视图与统一方言契约读取。
    """
    scene = await _scene(db_session, test_project_id, 0, 1)
    await _character(db_session, test_project_id, E1, "林舟")

    applied, gated = gate_scene_events(
        [
            _machine_knowledge_event(
                {
                    "target_type": "entity",
                    "target_id": E2,
                    "known_content": "林舟听说青铜锁的口令",
                    "knowledge_level": "rumor",
                }
            )
        ],
        [EVENT_WITH_LOCK],
    )
    assert not gated and len(applied) == 1
    machine_event = applied[0]
    # 产出门注入机器方言身份：uuid5 id、character_id == knowledge_subject。
    assert machine_event["snapshot_after"]["character_id"] == E1
    assert machine_event["snapshot_after"]["id"]

    # 对照事实：锁的口令已记载（作者层），机器知识"关于"该锁但无绑定。
    await _record(
        db_session,
        test_project_id,
        scene,
        [
            {
                "dimension": "entities",
                "event_type": "entity_created",
                "entity_id": E2,
                "snapshot_after": {
                    "name": "青铜锁",
                    "opening_passphrase": "潮落",
                },
            },
            {**machine_event, "source": MACHINE_EVENT_SOURCE},
        ],
    )

    state = await _knowledge_state(db_session, test_project_id, scene)
    entries = state.get("character_knowledge") or []
    assert len(entries) == 1
    assert not any(key in entries[0] for key in VALUE_BINDING_KEYS)

    # 统一方言形态：unknown 文本知识、无值绑定、机器来源、传闻级未检查说明。
    statement = read_machine_knowledge(entries[0])
    assert statement is not None
    assert statement.knowledge_class is KnowledgeClass.unknown
    assert statement.value_bindings == {}
    assert statement.subject_id is None  # target_id 无字段语义，不冒充绑定锚
    assert statement.origin is KnowledgeOrigin.machine_observation
    assert statement.text_summary == "林舟听说青铜锁的口令"
    assert statement.unchecked_note == "传闻级证据，未直接目击"
    assert statement.entry_id == machine_event["snapshot_after"]["id"]

    # 角色视角：机器断言不授予事实访问（口令不可见），belief 文本层存在。
    service = SceneStateViewService()
    view = await service.get_view(
        db_session,
        novel_id=test_project_id,
        scene_id=str(scene.id),
        viewpoint={"kind": "character", "target_id": E1},
    )
    assert _facts(view, "entities", "opening_passphrase", E2) == []
    beliefs = [
        fact
        for fact in next(
            item for item in view.dimensions if item.dimension == "knowledge"
        ).facts
        if fact.subject_id == E1
    ]
    assert beliefs, "机器知识应以其持有者 belief 条目呈现（文本知识层）"
    assert any("角色视角未获得依据" in item for item in view.omissions)
    # 对照：作者视角事实仍在（视角过滤不改变投影本体）。
    author = await service.get_view(
        db_session,
        novel_id=test_project_id,
        scene_id=str(scene.id),
        viewpoint={"kind": "author"},
    )
    assert _facts(author, "entities", "opening_passphrase", E2)[0].value == "潮落"


# ============================================================
# 不变量三：信任边界 — 绕过产出门的透传绑定键不采信、不持久化
# ============================================================


async def test_smuggled_binding_keys_never_reach_continuity_state(
    db_session: AsyncSession, test_project_id: str
) -> None:
    """模拟门禁旁路：source=evolution 的透传绑定键在写入边界剥除，零授予。

    对照行：同一批 Story 事件方言条目（默认 ai_extraction）绑定键原样入库
    并照常授予——剥除只针对机器方言，不清洗作者/抽取路径。
    """
    scene = await _scene(db_session, test_project_id, 0, 1)
    holder, lock = str(uuid.uuid4()), str(uuid.uuid4())
    await _character(db_session, test_project_id, holder, "持有者")

    machine_payload = {
        "id": "machine-knowledge-1",
        "character_id": holder,
        "target_type": "entity",
        "target_id": lock,
        "knowledge_level": "full",
        "known_content": "机器断言只表达听说，表达不了知道哪个值",
        # 透传的值绑定键（KnowledgeInPanorama extra=ignore 会静默放行的形态）。
        "subject_id": lock,
        "fields": ["opening_passphrase"],
        "known_values": {"opening_passphrase": "潮落"},
    }
    story_payload = {
        "character_id": holder,
        "subject_id": lock,
        "fields": ["opening_passphrase"],
        "known_values": {"opening_passphrase": "潮落"},
        "knowledge": "持有者知道口令",
    }
    recorded = await _record(
        db_session,
        test_project_id,
        scene,
        [
            {
                "dimension": "entities",
                "event_type": "entity_created",
                "entity_id": lock,
                "snapshot_after": {
                    "name": "青铜锁",
                    "opening_passphrase": "潮落",
                },
            },
            {
                "dimension": "knowledge",
                "event_type": "knowledge_changed",
                "entity_id": holder,
                "source": MACHINE_EVENT_SOURCE,
                "snapshot_after": dict(machine_payload),
            },
            {
                "dimension": "knowledge",
                "event_type": "knowledge_changed",
                "entity_id": holder,
                "snapshot_after": dict(story_payload),
            },
        ],
    )

    # 写入边界：机器行剥除绑定键；Story 方言行原样保留（不越界清洗）。
    machine_row = next(
        row
        for row in recorded
        if row.dimension == "knowledge" and row.snapshot_after.get("id")
    )
    story_row = next(
        row
        for row in recorded
        if row.dimension == "knowledge" and not row.snapshot_after.get("id")
    )
    assert not any(key in machine_row.snapshot_after for key in VALUE_BINDING_KEYS)
    assert machine_row.snapshot_after["known_content"] == machine_payload["known_content"]
    assert all(key in story_row.snapshot_after for key in VALUE_BINDING_KEYS)

    # 状态与视角：机器条目落 unknown 文本知识；授予仅来自 Story 方言条目。
    state = await _knowledge_state(db_session, test_project_id, scene)
    entries = state.get("character_knowledge") or []
    machine_entry = next(item for item in entries if item.get("id"))
    assert not any(key in machine_entry for key in VALUE_BINDING_KEYS)
    statement = read_machine_knowledge(machine_entry)
    assert statement is not None
    assert statement.knowledge_class is KnowledgeClass.unknown
    assert statement.value_bindings == {}
    assert statement.origin is KnowledgeOrigin.machine_observation

    view = await SceneStateViewService().get_view(
        db_session,
        novel_id=test_project_id,
        scene_id=str(scene.id),
        viewpoint={"kind": "character", "target_id": holder},
    )
    granted = _facts(view, "entities", "opening_passphrase", lock)
    assert len(granted) == 1 and granted[0].value == "潮落"
    # 反证不变量：去掉 Story 方言授予后（仅机器条目在场）即零授予——
    # 由上面机器条目已剥除绑定键 + _knowledge_grants 按绑定授予共同钉死。

    # 同一 payload 若不带机器 source 标记（作者/抽取路径）不受剥除影响。
    # 返回值是该 Scene 的全部事件，按负载 id + 非机器来源定位新行。
    preserved = await _record(
        db_session,
        test_project_id,
        scene,
        [
            {
                "dimension": "knowledge",
                "event_type": "knowledge_changed",
                "entity_id": holder,
                "snapshot_after": dict(machine_payload),
            }
        ],
        producer_family="p2b_machine_fixture",
    )
    preserved_row = next(
        row
        for row in preserved
        if row.dimension == "knowledge"
        and row.snapshot_after.get("id") == "machine-knowledge-1"
        and row.source != MACHINE_EVENT_SOURCE
    )
    assert all(key in preserved_row.snapshot_after for key in VALUE_BINDING_KEYS), (
        "非机器来源的绑定键不得被机器边界清洗"
    )


async def test_holder_id_variant_bypass_also_strips_machine_bindings(
    db_session: AsyncSession, test_project_id: str
) -> None:
    """holder 形态不影响剥除：holder_id 变体（不可归属机器方言的 payload）。

    ``_knowledge_grants`` 的 holder 走 character_id/holder_id 双键——机器
    payload 若用 holder_id 且偷带绑定键，剥除不得因 payload 不符合
    character_id 白名单而放行；端到端角色视角仍零授予。
    """
    scene = await _scene(db_session, test_project_id, 0, 1)
    holder, lock = str(uuid.uuid4()), str(uuid.uuid4())
    await _character(db_session, test_project_id, holder, "持有者")

    recorded = await _record(
        db_session,
        test_project_id,
        scene,
        [
            {
                "dimension": "entities",
                "event_type": "entity_created",
                "entity_id": lock,
                "snapshot_after": {"name": "青铜锁", "opening_passphrase": "潮落"},
            },
            {
                "dimension": "knowledge",
                "event_type": "knowledge_changed",
                "entity_id": holder,
                "source": MACHINE_EVENT_SOURCE,
                "snapshot_after": {
                    "holder_id": holder,
                    "target_type": "entity",
                    "target_id": lock,
                    "knowledge_level": "full",
                    "known_content": "holder_id 变体同样表达不了值绑定",
                    "subject_id": lock,
                    "fields": ["opening_passphrase"],
                    "known_values": {"opening_passphrase": "潮落"},
                },
            },
        ],
    )
    machine_row = next(row for row in recorded if row.dimension == "knowledge")
    assert not any(key in machine_row.snapshot_after for key in VALUE_BINDING_KEYS)
    assert machine_row.snapshot_after["holder_id"] == holder  # 只剥绑定键

    # 投影后的 checkpoint 状态同样剥除；转换器对不可归属形态返回 None
    # （不冒充），不产生任何可授予条目。
    state = await _knowledge_state(db_session, test_project_id, scene)
    entries = state.get("character_knowledge") or []
    assert len(entries) == 1
    assert not any(key in entries[0] for key in VALUE_BINDING_KEYS)
    assert read_machine_knowledge(entries[0]) is None  # 无 character_id 不归属

    view = await SceneStateViewService().get_view(
        db_session,
        novel_id=test_project_id,
        scene_id=str(scene.id),
        viewpoint={"kind": "character", "target_id": holder},
    )
    assert _facts(view, "entities", "opening_passphrase", lock) == []
    assert any("角色视角未获得依据" in item for item in view.omissions)
