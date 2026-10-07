"""P2-B B0 验收夹具 — 知识值与揭示边界六类统一验收集（预期先行）。

从同一 Scene 的 Story 角色投影建立版本化知识读取，保持 ``known / unknown /
false_belief`` 与"知道哪个值"的区别：人物曾知道旧口令 ≠ 知道改后的口令；
知晓人物身份 ≠ 知晓其秘密关系；在场 ≠ 知道；后文揭密不回流早场景。
有限开锁比较继续三值裁决：有明确不满足则 failed，无法证明则 uncertain。

六类场景矩阵（类别 × 视角 × 允许/拒绝 × 原因）
================================================

1. 旧值→新值（character + trial，拒绝，真绿）
   口令改写后，知识条目仍绑旧值：视角上新口令 fact 不可见；trial 条件
   status=unmet 且 observed=旧值 expected=新值——拒绝原因是"值不匹配"
   （知道旧口令），不是"不知道"。既有 test_state_trial 覆盖主干，
   本夹具钉值绑定双端（belief known_values + 条件 observed/expected）。
2. 误信（character + trial，拒绝，真绿）
   false 标记条目以 belief 呈现且 possibly_false=True，永不授予事实；
   trial 口令条件因候选被排除而为 unknown（无法证明），绝不为 met。
   05_memory.md 已钉语义，本夹具补"结构上可授予仍拒收"的误信形态。
3. 部分知晓（character，部分允许，真绿）
   授予按 (subject, field, value)：fields=["identity"] 只放行 identity
   fact（belief known_fields 可证），secret_relation 无授予链 → 不可见
   （不知道 ≠ 知道没有）。
4. 同场旁观（character，拒绝，边界真绿 + 原因结构 xfail）
   边界：同 Scene 有位置（在场）但无知识条目 → 他人事实不可见；本人
   位置可见（在场只证明位置），omissions 报"角色视角未获得依据"。
   缺口（xfail）：拒绝原因必须逐条可归因且三类互斥可区分——
   no_knowledge_entry（在场无条目）/ knowledge_value_mismatch（旧值）/
   false_belief（误信）；现状 omissions 只有维度级计数。
5. 后文揭密（character，拒绝，真绿）
   揭示事件（实体补秘密 + 获知知识）只入 Scene N+1 的 checkpoint；
   Scene N 视角按本场截止读取，秘密与揭示知识都不回流；对照：获知后
   的 Scene N+1 视角可见（揭示知识只授权其后场景）。
6. 后文揭密（reader，拒绝，xfail）
   读者揭示只在已证明展示的原文范围内启用：Scene N 的读者视图不得因
   "无 reveal 策略默认公开"看到后文才揭示的秘密，omissions 报"读者
   视角尚未揭示"且不泄露对象。现状 ReaderRevealDecisionContract 无
   策略默认 revealed=True → 秘密泄露给揭示前的读者视图。
7. uncertain 三值判决（trial，真绿）
   锁三条件全部无法证明（无保管记录、无开启条件记载、无口令知识）且
   无一条明确不满足 → verdict=uncertain + unresolved_outcomes=[actor]；
   有一条明确不满足（所需钥匙记载为另一把）→ failed。裁决已实现，
   此前零断言；本夹具补第三值。

知识期望契约形态决定（B0 钉定，B1 契约单元对齐基准）
====================================================

视角 × 知识条目 × 值绑定 × 揭示判定的期望结构：

1. **知识条目（knowledge payload）**：``{character_id|holder_id, subject_id,
   fields: [str], known_values: {field: value}, false?: bool, knowledge: str}``。
   授予 = (holder, subject, field, stable_hash(value)) 四元组；``fields`` /
   ``known_values`` 缺失即纯 belief（知道"有这么回事"≠知道值）；``false`` /
   ``false_belief`` 标记条目永不授予（误信不是知识）。
2. **值的时间性**：知识条目绑定**记录当时**的值；其后事实变更（口令改写）
   不自动更新知识——旧值授权对新值事实为 knowledge_value_mismatch 拒绝，
   只有新的知识条目（后文获知）才放行，且只放行其后场景的视角。
3. **视角过滤**：character 视角 fact 需四元组授予（唯一例外：本人位置）；
   belief 只见本人条目；observation 不出作者视角。reader 视角 fact 需
   揭示判定通过且 layer=fact；belief/observation/timeline/causality 不出。
4. **逐条拒绝原因（本文件 xfail 钉定的缺口）**：character 视角每个被抑制
   的 fact 应可归因，cause 互斥可区分——``no_knowledge_entry``（在场/未目击/
   纯 belief）、``knowledge_value_mismatch``（知道旧值）、``false_belief``
   （误信条目）。承载形态不限（omissions 内 dict、facts 同级 denied/
   suppressed 结构均可），语义要求是三类原因在同一视角下可区分、可被
   断言（供作者解释"为什么这个角色不知道"），不要求精确字符串。
5. **揭示判定**：reader 视角的默认必须保守——无"已展示原文证明"（揭示
   计划/稿源区间）时不得默认公开秘密；有策略未到揭示章 → 隐藏（既有
   test_reader_view_gates_entities_by_reveal 已覆盖）；到揭示章且可证明
   展示 → 放行。揭示前的读者视图 omissions 只报数量不泄露对象身份。
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from modules.story.continuity.scene_projection import SceneMemoryProjectionService
from modules.story.continuity.scene_state_view import SceneStateViewService
from modules.story.continuity.services import MemoryService
from modules.story.continuity.state_trial import compare_scene_state_trial
from modules.story.contracts import SceneStateTrialRequest
from modules.story.outline_state.models import Scene

_XFAIL = pytest.mark.xfail(reason="P2-B knowledge boundary not implemented", strict=False)


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


def _present(subject: str, name: str, node: str = "雾渡港灯塔") -> dict[str, Any]:
    """同场在场事件（locations 维度）：使人物进入本场状态并携带展示名。"""
    return {
        "dimension": "locations",
        "event_type": "entity_moved",
        "entity_id": subject,
        "snapshot_after": {"node": node, "name": name},
    }


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
        producer_family="p2b_knowledge_fixture",
    )


async def _view(
    db: AsyncSession, novel_id: str, scene: Scene, viewpoint: dict[str, Any]
) -> Any:
    await SceneMemoryProjectionService().ensure_scene(db, novel_id, str(scene.id))
    return await SceneStateViewService().get_view(
        db, novel_id=novel_id, scene_id=str(scene.id), viewpoint=viewpoint
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


def _denial_reasons(view: Any) -> dict[tuple[str, str], Any]:
    """提取 character 视角的逐条拒绝原因结构（B0 期望契约第 4 条）。

    承载形态不限：omissions 内携带 (subject_id, field, cause) 的 dict 项、
    响应 facts 同级的 denied/suppressed 结构均可；当前实现只有维度级计数
    字符串，返回空 dict（对应 xfail 夹具在目标断言处失败）。
    """

    def _cause_of(item: Any) -> Any:
        return getattr(item, "cause", None) or (
            item.get("cause") if isinstance(item, dict) else None
        )

    reasons: dict[tuple[str, str], Any] = {}
    for entry in getattr(view, "omissions", None) or []:
        if not isinstance(entry, dict):
            continue
        subject, field = entry.get("subject_id"), entry.get("field")
        if subject and field and _cause_of(entry):
            reasons[(str(subject), str(field))] = _cause_of(entry)
    for attr in ("denied", "suppressed_facts", "denied_facts"):
        for item in getattr(view, attr, None) or []:
            subject = getattr(item, "subject_id", None) or (
                item.get("subject_id") if isinstance(item, dict) else None
            )
            field = getattr(item, "field", None) or (
                item.get("field") if isinstance(item, dict) else None
            )
            if subject and field and _cause_of(item):
                reasons[(str(subject), str(field))] = _cause_of(item)
    return reasons


# ============================================================
# 类别一/二：旧值 → 新值（口令改写，旧知识不开新锁）
# ============================================================


async def test_p2b_old_value_knowledge_does_not_open_new_passphrase(
    db_session: AsyncSession, test_project_id: str
) -> None:
    """旧口令知识对改写后的口令：视角不可见 + trial 条件 unmet（值不匹配）。"""
    scene = await _scene(db_session, test_project_id, 0, 1)
    jia, lock = str(uuid.uuid4()), str(uuid.uuid4())
    await _character(db_session, test_project_id, jia, "甲")
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
                "snapshot_after": {
                    "name": "三簧锁",
                    "opening_passphrase": "潮落",
                },
            },
            _present(jia, "甲"),
            {
                "dimension": "knowledge",
                "event_type": "knowledge_changed",
                "entity_id": jia,
                "snapshot_after": {
                    "character_id": jia,
                    "subject_id": lock,
                    "fields": ["opening_passphrase"],
                    "known_values": {"opening_passphrase": "潮落"},
                    "knowledge": "甲知道口令",
                },
            },
        ],
    )
    await projection.ensure_scene(db_session, test_project_id, str(scene.id))
    service = SceneStateViewService()

    # 改写前：旧口令知识放行当前口令 fact；授予证据在 belief 条目的
    # known_fields/known_values（知道哪个值）。
    before = await service.get_view(
        db_session,
        novel_id=test_project_id,
        scene_id=str(scene.id),
        viewpoint={"kind": "character", "target_id": jia},
    )
    granted = _facts(before, "entities", "opening_passphrase", lock)
    assert len(granted) == 1 and granted[0].value == "潮落"
    belief = _facts(before, "knowledge", f"knows:{lock}", jia)
    assert len(belief) == 1
    assert belief[0].source.get("known_fields") == ["opening_passphrase"]
    assert belief[0].source.get("known_values", {}).get("opening_passphrase") == "潮落"

    # 改写口令：知识条目仍绑旧值 → 该角色视角下新口令 fact 不可见
    # （值绑定拒绝，不是"没有这条事实"——作者视角仍在）。
    await _record(
        db_session,
        test_project_id,
        scene,
        [
            {
                "dimension": "entities",
                "event_type": "entity_updated",
                "entity_id": lock,
                "snapshot_after": {"opening_passphrase": "潮起"},
            }
        ],
    )
    await projection.ensure_scene(db_session, test_project_id, str(scene.id))
    after = await service.get_view(
        db_session,
        novel_id=test_project_id,
        scene_id=str(scene.id),
        viewpoint={"kind": "character", "target_id": jia},
    )
    assert _facts(after, "entities", "opening_passphrase", lock) == []
    assert any("角色视角未获得依据" in item for item in after.omissions)
    author_after = await service.get_view(
        db_session,
        novel_id=test_project_id,
        scene_id=str(scene.id),
        viewpoint={"kind": "author"},
    )
    assert _facts(author_after, "entities", "opening_passphrase", lock)[0].value == "潮起"

    # trial 端：条件 status=unmet，observed=旧值 expected=新值——拒绝原因是
    # "值不匹配"（知道旧口令），响应携带双方值可解释，而非仅布尔。
    trial = await compare_scene_state_trial(
        db_session,
        test_project_id,
        SceneStateTrialRequest(
            scene_id=scene.id,
            state_fingerprint=author_after.state_fingerprint,
            actor_id=uuid.UUID(jia),
            key_id=uuid.UUID(lock),
            lock_id=uuid.UUID(lock),
            action="open_lock",
        ),
    )
    phrase = next(
        item
        for item in trial["candidate"]["conditions"]
        if item["label"] == "行动者有口令知识依据"
    )
    assert phrase["status"] == "unmet"
    assert phrase["observed"] == "潮落" and phrase["expected"] == "潮起"
    assert trial["candidate"]["outcome"] == "failed"


# ============================================================
# 类别三：误信（false_belief 永不授予事实访问）
# ============================================================


async def test_p2b_false_belief_never_grants_fact_access(
    db_session: AsyncSession, test_project_id: str
) -> None:
    """误信条目：belief 可见带 possibly_false，事实零授予；trial 口令条件 unknown。"""
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
                "snapshot_after": {
                    "name": "三簧锁",
                    "opening_passphrase": "潮落",
                },
            },
            # 误信条目即使带 fields/known_values（结构上可授予）也永不授予。
            _present(yi, "乙"),
            {
                "dimension": "knowledge",
                "event_type": "knowledge_changed",
                "entity_id": yi,
                "snapshot_after": {
                    "character_id": yi,
                    "subject_id": lock,
                    "fields": ["opening_passphrase"],
                    "known_values": {"opening_passphrase": "潮落"},
                    "knowledge": "乙误信口令是潮落",
                    "false": True,
                },
            },
        ],
    )
    await projection.ensure_scene(db_session, test_project_id, str(scene.id))
    service = SceneStateViewService()
    view = await service.get_view(
        db_session,
        novel_id=test_project_id,
        scene_id=str(scene.id),
        viewpoint={"kind": "character", "target_id": yi},
    )

    # 误信以 belief 呈现且带 possibly_false 标记；同 subject 的事实零授予。
    beliefs = _facts(view, "knowledge", f"knows:{lock}", yi)
    assert len(beliefs) == 1 and beliefs[0].possibly_false is True
    assert _facts(view, "entities", "opening_passphrase", lock) == []
    assert any("角色视角未获得依据" in item for item in view.omissions)

    # trial 端：候选知识排除 possibly_false → 条件无法证明（unknown），
    # 绝不因误信而 met。
    author = await service.get_view(
        db_session,
        novel_id=test_project_id,
        scene_id=str(scene.id),
        viewpoint={"kind": "author"},
    )
    trial = await compare_scene_state_trial(
        db_session,
        test_project_id,
        SceneStateTrialRequest(
            scene_id=scene.id,
            state_fingerprint=author.state_fingerprint,
            actor_id=uuid.UUID(yi),
            key_id=uuid.UUID(lock),
            lock_id=uuid.UUID(lock),
            action="open_lock",
        ),
    )
    phrase = next(
        item
        for item in trial["candidate"]["conditions"]
        if item["label"] == "行动者有口令知识依据"
    )
    assert phrase["status"] == "unknown" and phrase["observed"] == "未记载"


# ============================================================
# 类别四：部分知晓（知道身份 ≠ 知道秘密关系）
# ============================================================


async def test_p2b_partial_field_knowledge_grants_only_known_fields(
    db_session: AsyncSession, test_project_id: str
) -> None:
    """fields 部分覆盖：name fact 经授予可见，secret_relation 不可见。"""
    scene = await _scene(db_session, test_project_id, 0, 1)
    wu, ding = str(uuid.uuid4()), str(uuid.uuid4())
    await _character(db_session, test_project_id, wu, "戊")

    await _record(
        db_session,
        test_project_id,
        scene,
        [
            {
                "dimension": "entities",
                "event_type": "entity_created",
                "entity_id": ding,
                "snapshot_after": {
                    "name": "丁",
                    "identity": "港口账房",
                    "secret_relation": "丁是暗桩",
                },
            },
            {
                "dimension": "knowledge",
                "event_type": "knowledge_changed",
                "entity_id": wu,
                "snapshot_after": {
                    "character_id": wu,
                    "subject_id": ding,
                    "fields": ["identity"],
                    "known_values": {"identity": "港口账房"},
                    "knowledge": "戊知道丁的身份",
                },
            },
        ],
    )
    view = await _view(
        db_session,
        test_project_id,
        scene,
        {"kind": "character", "target_id": wu},
    )

    # 授予按 (subject, field, value)：identity 可见，belief 携带已知字段证据。
    identities = _facts(view, "entities", "identity", ding)
    assert len(identities) == 1 and identities[0].value == "港口账房"
    belief = _facts(view, "knowledge", f"knows:{ding}", wu)
    assert belief and belief[0].source.get("known_fields") == ["identity"]
    # 秘密关系无授予链 → 不可见（不知道 ≠ 知道没有），omissions 解释拒绝。
    assert _facts(view, "entities", "secret_relation", ding) == []
    assert any("角色视角未获得依据" in item for item in view.omissions)
    # 作者视角对照：秘密关系对作者可见（视角过滤不改变投影本体）。
    author = await _view(db_session, test_project_id, scene, {"kind": "author"})
    assert _facts(author, "entities", "secret_relation", ding)[0].value == "丁是暗桩"


# ============================================================
# 类别五：同场旁观（在场 witnessing 不授予知识）
# ============================================================


async def test_p2b_same_scene_presence_does_not_grant_knowledge(
    db_session: AsyncSession, test_project_id: str
) -> None:
    """旁观者与交接事件同 Scene 在场：本人位置可见，他人事实零获得。"""
    scene = await _scene(db_session, test_project_id, 0, 1)
    yi, bing, key = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
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
            },
            # 乙同场在场（有位置记录）……
            {
                "dimension": "locations",
                "event_type": "entity_moved",
                "entity_id": yi,
                "snapshot_after": {"node": "雾渡港灯塔", "label": "灯塔下"},
            },
            # ……且交接事件发生在同一 Scene：保管转给丙。乙无知识条目。
            {
                "dimension": "entities",
                "event_type": "entity_updated",
                "entity_id": key,
                "snapshot_after": {"custody_holder": bing},
            },
        ],
    )
    view = await _view(
        db_session,
        test_project_id,
        scene,
        {"kind": "character", "target_id": yi},
    )

    # 在场只证明位置：本人位置可见；保管事实因无知识条目不可见。
    locations = _facts(view, "locations", "location", yi)
    assert locations and locations[0].value["node"] == "雾渡港灯塔"
    assert _facts(view, "entities", "custody_holder", key) == []
    assert any("角色视角未获得依据" in item for item in view.omissions)


@_XFAIL
async def test_p2b_bystander_denial_reason_distinguishes_no_knowledge_entry(
    db_session: AsyncSession, test_project_id: str
) -> None:
    """同一视角下三类拒绝原因互斥可区分：无条目 / 旧值 / 误信（B0 缺口）。"""
    scene = await _scene(db_session, test_project_id, 0, 1)
    yi, key, lock_a, lock_b = (str(uuid.uuid4()) for _ in range(4))
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
            },
            {
                "dimension": "entities",
                "event_type": "entity_created",
                "entity_id": lock_a,
                "snapshot_after": {
                    "name": "甲锁",
                    "opening_passphrase": "新口令",
                },
            },
            {
                "dimension": "entities",
                "event_type": "entity_created",
                "entity_id": lock_b,
                "snapshot_after": {
                    "name": "乙锁",
                    "opening_passphrase": "潮落",
                },
            },
            # 乙知道甲锁的旧口令（事实已改写为"新口令"→ 值不匹配拒绝）。
            {
                "dimension": "knowledge",
                "event_type": "knowledge_changed",
                "entity_id": yi,
                "snapshot_after": {
                    "character_id": yi,
                    "subject_id": lock_a,
                    "fields": ["opening_passphrase"],
                    "known_values": {"opening_passphrase": "旧口令"},
                    "knowledge": "乙知道甲锁的旧口令",
                },
            },
            # 乙对乙锁持误信（结构上可授予但 false 标记 → 误信拒绝）。
            {
                "dimension": "knowledge",
                "event_type": "knowledge_changed",
                "entity_id": yi,
                "snapshot_after": {
                    "character_id": yi,
                    "subject_id": lock_b,
                    "fields": ["opening_passphrase"],
                    "known_values": {"opening_passphrase": "潮落"},
                    "knowledge": "乙误信口令是潮落",
                    "false": True,
                },
            },
        ],
    )
    view = await _view(
        db_session,
        test_project_id,
        scene,
        {"kind": "character", "target_id": yi},
    )

    # 边界本身（见上一用例）+ 前置证明：三条事实确实都被拒绝。
    assert _facts(view, "entities", "custody_holder", key) == []
    assert _facts(view, "entities", "opening_passphrase", lock_a) == []
    assert _facts(view, "entities", "opening_passphrase", lock_b) == []

    # 缺口断言：拒绝原因逐条可归因且三类互斥可区分——
    # 在场无条目 ≠ 知道旧值 ≠ 误信。承载形态不限（见文件头契约第 4 条）。
    reasons = _denial_reasons(view)
    bystander = reasons.get((key, "custody_holder"))
    old_value = reasons.get((lock_a, "opening_passphrase"))
    false_belief = reasons.get((lock_b, "opening_passphrase"))
    assert bystander, "同场旁观（无知识条目）的拒绝原因缺失"
    assert old_value, "旧值不匹配的拒绝原因缺失"
    assert false_belief, "误信的拒绝原因缺失"
    assert len({str(bystander), str(old_value), str(false_belief)}) == 3, (
        "三类拒绝原因必须互斥可区分，不得共用一条维度级计数"
    )


# ============================================================
# 类别六：后文揭密（不回流早场景）
# ============================================================


async def test_p2b_later_scene_reveal_does_not_backflow_character_knowledge(
    db_session: AsyncSession, test_project_id: str
) -> None:
    """Scene 1 揭示的秘密与揭示知识：Scene 0 的角色视角不可见（不回流）。"""
    scene0 = await _scene(db_session, test_project_id, 0, 1)
    scene1 = await _scene(db_session, test_project_id, 1, 2)
    jia, ding = str(uuid.uuid4()), str(uuid.uuid4())
    await _character(db_session, test_project_id, jia, "甲")
    projection = SceneMemoryProjectionService()

    await _record(
        db_session,
        test_project_id,
        scene0,
        [
            {
                "dimension": "entities",
                "event_type": "entity_created",
                "entity_id": ding,
                "snapshot_after": {"name": "丁"},
            }
        ],
    )
    await projection.ensure_scene(db_session, test_project_id, str(scene0.id))
    service = SceneStateViewService()
    before = await service.get_view(
        db_session,
        novel_id=test_project_id,
        scene_id=str(scene0.id),
        viewpoint={"kind": "character", "target_id": jia},
    )
    # 揭示前：甲视角既无秘密事实也无揭示知识。
    assert _facts(before, "entities", "secret_relation", ding) == []
    assert _facts(before, "knowledge", f"knows:{ding}", jia) == []

    # Scene 1（后文）揭示：实体补秘密 + 甲获知（新知识条目只入 Scene 1）。
    await _record(
        db_session,
        test_project_id,
        scene1,
        [
            {
                "dimension": "entities",
                "event_type": "entity_updated",
                "entity_id": ding,
                "snapshot_after": {"secret_relation": "丁是暗桩"},
            },
            {
                "dimension": "knowledge",
                "event_type": "knowledge_changed",
                "entity_id": jia,
                "snapshot_after": {
                    "character_id": jia,
                    "subject_id": ding,
                    "fields": ["secret_relation"],
                    "known_values": {"secret_relation": "丁是暗桩"},
                    "knowledge": "第二章甲识破丁是暗桩",
                },
            },
        ],
    )
    await projection.ensure_scene(db_session, test_project_id, str(scene1.id))

    # 重读 Scene 0：秘密与揭示知识都不回流（checkpoint 按本场截止）。
    after = await service.get_view(
        db_session,
        novel_id=test_project_id,
        scene_id=str(scene0.id),
        viewpoint={"kind": "character", "target_id": jia},
    )
    assert after.state_fingerprint == before.state_fingerprint
    assert _facts(after, "entities", "secret_relation", ding) == []
    assert _facts(after, "knowledge", f"knows:{ding}", jia) == []

    # 对照：Scene 1 的甲视角获知后可见秘密事实（揭示知识只授权其后场景），
    # 获知证据在 belief 条目的 known_fields（知道的是哪个字段）。
    later = await service.get_view(
        db_session,
        novel_id=test_project_id,
        scene_id=str(scene1.id),
        viewpoint={"kind": "character", "target_id": jia},
    )
    granted = _facts(later, "entities", "secret_relation", ding)
    assert len(granted) == 1 and granted[0].value == "丁是暗桩"
    later_belief = _facts(later, "knowledge", f"knows:{ding}", jia)
    assert later_belief and later_belief[0].source.get("known_fields") == [
        "secret_relation"
    ]


@_XFAIL
async def test_p2b_reader_before_reveal_scene_must_not_see_secret(
    db_session: AsyncSession, test_project_id: str
) -> None:
    """读者揭示只在已证明展示的原文范围内启用（B0 缺口：无策略默认公开）。"""
    scene0 = await _scene(db_session, test_project_id, 0, 1)
    scene1 = await _scene(db_session, test_project_id, 1, 2)
    ding = str(uuid.uuid4())
    projection = SceneMemoryProjectionService()

    # 秘密作为世界事实在 Scene 0 就有记录（作者层从开头就知道），
    # 但叙事上要到 Scene 1（第 2 章）才向读者揭示。
    await _record(
        db_session,
        test_project_id,
        scene0,
        [
            {
                "dimension": "entities",
                "event_type": "entity_created",
                "entity_id": ding,
                "snapshot_after": {"name": "丁", "secret_relation": "丁是暗桩"},
            }
        ],
    )
    await projection.ensure_scene(db_session, test_project_id, str(scene0.id))
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
                    "field_path": f"{ding}.secret_relation",
                    "new_value": "第二章末尾向读者揭示丁是暗桩",
                },
            }
        ],
    )
    await projection.ensure_scene(db_session, test_project_id, str(scene1.id))
    service = SceneStateViewService()

    # 揭示 Scene 之前的读者视图不得包含该秘密：无"已展示原文证明"时
    # 不得默认公开（现状无策略 revealed 默认 True → 秘密泄露，xfail 点）。
    early_reader = await service.get_view(
        db_session,
        novel_id=test_project_id,
        scene_id=str(scene0.id),
        viewpoint={"kind": "reader"},
    )
    assert _facts(early_reader, "entities", "secret_relation", ding) == [], (
        "揭示前的读者视图不得看到后文才揭示的秘密"
    )
    # 拒绝原因走读者侧 omission（只报数量，不泄露对象身份）。
    assert any("读者视角尚未揭示" in item for item in early_reader.omissions)


# ============================================================
# uncertain 三值判决（有明确不满足则 failed，无法证明则 uncertain）
# ============================================================


async def test_p2b_uncertain_verdict_when_lock_conditions_unprovable(
    db_session: AsyncSession, test_project_id: str
) -> None:
    """三条件全部无法证明 → uncertain；一条明确不满足 → failed。"""
    scene = await _scene(db_session, test_project_id, 0, 1)
    jia, key, lock_blank, lock_wrong = (str(uuid.uuid4()) for _ in range(4))
    await _character(db_session, test_project_id, jia, "甲")

    await _record(
        db_session,
        test_project_id,
        scene,
        [
            _present(jia, "甲"),
            # 钥匙有登记（人物/对象校验通过）但无保管记录（holder 未记载）。
            {
                "dimension": "entities",
                "event_type": "entity_created",
                "entity_id": key,
                "snapshot_after": {"name": "铜钥匙"},
            },
            # 无条件锁：开启钥匙/月相/口令全部未记载 → 无法证明。
            {
                "dimension": "entities",
                "event_type": "entity_created",
                "entity_id": lock_blank,
                "snapshot_after": {"name": "空锁"},
            },
            # 明确不满足锁：所需钥匙记载为另一把 → unmet。
            {
                "dimension": "entities",
                "event_type": "entity_created",
                "entity_id": lock_wrong,
                "snapshot_after": {
                    "name": "错钥锁",
                    "opening_key_id": str(uuid.uuid4()),
                },
            },
        ],
    )
    view = await _view(db_session, test_project_id, scene, {"kind": "author"})

    unprovable = await compare_scene_state_trial(
        db_session,
        test_project_id,
        SceneStateTrialRequest(
            scene_id=scene.id,
            state_fingerprint=view.state_fingerprint,
            actor_id=uuid.UUID(jia),
            key_id=uuid.UUID(key),
            lock_id=uuid.UUID(lock_blank),
            action="open_lock",
        ),
    )
    # 无一条明确不满足、三条件全部 unknown → 三值裁决第三值 uncertain，
    # 不是 failed（无法证明 ≠ 不满足）。
    assert unprovable["baseline"]["outcome"] == "uncertain"
    statuses = {item["status"] for item in unprovable["baseline"]["conditions"]}
    assert statuses == {"unknown"}
    assert "unmet" not in statuses
    # uncertain 显式挂未决出口，不冒充通过或失败。
    assert unprovable["baseline"]["resolution"]["unresolved_outcomes"] == [jia]
    assert unprovable["baseline"]["candidate_state"]["resource_holders"] == {}

    explicitly_unmet = await compare_scene_state_trial(
        db_session,
        test_project_id,
        SceneStateTrialRequest(
            scene_id=scene.id,
            state_fingerprint=view.state_fingerprint,
            actor_id=uuid.UUID(jia),
            key_id=uuid.UUID(key),
            lock_id=uuid.UUID(lock_wrong),
            action="open_lock",
        ),
    )
    # 有一条明确不满足（所需钥匙是另一把）→ 即使其余条件仍无法证明也 failed。
    wrong_key = next(
        item
        for item in explicitly_unmet["baseline"]["conditions"]
        if item["label"] == "锁所需的钥匙已有明确记录"
    )
    assert wrong_key["status"] == "unmet"
    assert explicitly_unmet["baseline"]["outcome"] == "failed"
    assert explicitly_unmet["baseline"]["resolution"]["unresolved_outcomes"] == []
