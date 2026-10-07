"""演化失效传播引擎（V4 E05，对应 01-EVOLUTION §6 / 验收 T08/T09）。

正文变更的处理顺序（§6.1）：

1. **物理来源差异**：先算 ``compute_source_change``——同字数替换、标题
   变化都必然改变内容指纹并给出受影响偏移窗口（T08：4000 字后的同长度
   修改也必须被检出，不得因长度未变而漏报）。
2. **显式依赖查询**：受影响章映射到 Scene（outline 权威顺序），无细粒度
   依赖的范围**保守扩大**为"从最早受影响 Scene 起的全部后续"——历史
   状态依赖前缀，宁可多失效也不让旧理解冒充有效；扩大范围记入回执的
   coverage 说明（§6.1 "向 UI 说明范围"）。
3. **失效不是删除历史**：只走软 supersede / 重排队列，原观察、历史回执
   与作者确认全部保留（§6.3）。

已接线消费者：evidence 章节索引（重建触发带新 source hash，旧结果不再
显示有效）、story Scene checkpoint 与稀疏快照（软 supersede）。未接线
消费者（world 知识、地图册、助手建议）在回执中显式列为
``unsupported_consumers``——缺口可见，不以"局部完成"冒充全量失效。

P2-C C2 细化：``apply_source_invalidation`` 组装
``consumption.assess_source_impact``——登记集来自 (a) Scene current
checkpoint 行 ``state_json`` 内嵌的真实登记（``read_consumption_records``，
写入端接线归 story 侧 B 类，见 ``registration.py``）与 (b) 锚定变更章
场景的**结构合成登记**（scene.chapter_ids 锚定是确定性事实，该 (scene,
dimension) 无真实登记时按整章消费合成——不冒充接线，method_version
标识来源）。合成后无登记场景的评估窗口与现状保守扩大逐位一致
（``from_scene_index == earliest_affected_scene_index``），仅回执新增
可解释视图：``affected``（known=登记/锚定命中，unknown=保守扩大，按
``affected_view_entries``）、``unknown_scope``、``receipt_id``、
``recompute_options``（三分类，``derive_recompute_options``）。
"""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from modules.evolution.store import PostgresAttemptStore
from modules.story.outline_state.facade import get_scenes_by_novel

UNSUPPORTED_CONSUMERS: tuple[dict[str, str], ...] = (
    {
        "consumer": "world_knowledge",
        "reason": "世界知识对象尚无来源依赖注册缝；按读取时新鲜度判断，待 G2/MI 接线",
    },
    {
        "consumer": "map_atlas",
        "reason": "地图册 revision 无失效缝；表现资产在生成时绑定来源版本，待 V 系列接线",
    },
)


class SourceChange(BaseModel):
    """一次正文变更的物理差异窗口（新文本坐标，end 为开区间）。"""

    model_config = ConfigDict(extra="forbid")

    changed: bool
    same_length: bool
    first_offset: int | None = None
    last_offset: int | None = None
    old_length: int = Field(ge=0)
    new_length: int = Field(ge=0)


def compute_source_change(
    old_text: str | None,
    new_text: str | None,
) -> SourceChange:
    """确定性物理差异：同字数替换也必须给出非空受影响窗口。"""
    old = old_text or ""
    new = new_text or ""
    if old == new:
        return SourceChange(
            changed=False,
            same_length=True,
            old_length=len(old),
            new_length=len(new),
        )
    same_length = len(old) == len(new)
    first = 0
    limit = min(len(old), len(new))
    while first < limit and old[first] == new[first]:
        first += 1
    if same_length:
        suffix = 0
        while (
            suffix < len(old) - first
            and old[len(old) - 1 - suffix] == new[len(new) - 1 - suffix]
        ):
            suffix += 1
        last = len(new) - suffix
    else:
        # 长度变化：从首个差异到较长一方的结尾，保守覆盖增删尾段。
        last = max(len(old), len(new))
    return SourceChange(
        changed=True,
        same_length=same_length,
        first_offset=first,
        last_offset=last,
        old_length=len(old),
        new_length=len(new),
    )


class InvalidationReceipt(BaseModel):
    """一次失效传播的结果：失效了什么、扩大到哪、哪些消费者未接线。

    P2-C C2 增量字段（全部默认值，旧构造兼容；既有字段语义不变）：

    - ``affected``：受影响条目（``consumption.affected_view_entries`` 形态，
      ``basis=known|unknown``；无关 Scene 不进列表）。
    - ``unknown_scope``：存在登记覆盖不到的保守扩大范围或未接线消费者。
    - ``receipt_id``：回执稳定指纹（``consumption.receipt_fingerprint``）。
    - ``recompute_options``：重算三分类选项
      （``consumption.derive_recompute_options``）。
    - ``impact_assessment``：组装上述视图所用的完整评估对象
      （``impact.attach_impact_view`` 填充；类型即
      ``consumption.ImpactAssessment``，此处以 ``Any`` 声明避免与契约模块
      的顶层环。DI 键 ``EVOLUTION_INVALIDATION_RECEIPT_VIEW`` 的实现经它
      重投影完整作者视图；不参与 ``receipt_fingerprint``）。
    """

    model_config = ConfigDict(extra="forbid")

    novel_id: str
    chapter_index: int | None = None
    source_change: SourceChange | None = None
    earliest_affected_scene_index: int | None = None
    invalidated_consumers: dict[str, dict[str, Any]] = Field(default_factory=dict)
    unsupported_consumers: list[dict[str, str]] = Field(default_factory=list)
    nothing_to_do: bool = False
    coverage_note: str = ""
    affected: list[dict[str, Any]] = Field(default_factory=list)
    unknown_scope: bool = False
    receipt_id: str = ""
    recompute_options: list[dict[str, Any]] = Field(default_factory=list)
    impact_assessment: Any = None


def _scene_chapter_indices(scene: dict[str, Any]) -> set[int]:
    values: set[int] = set()
    for raw in scene.get("chapter_ids") or []:
        try:
            values.add(int(raw))
        except (TypeError, ValueError):
            continue
    for chunk in scene.get("scene_chunks") or []:
        if not isinstance(chunk, dict):
            continue
        raw = chunk.get("chapter_index") or chunk.get("chapter_id")
        try:
            values.add(int(raw))
        except (TypeError, ValueError):
            continue
    return values


async def affected_scene_window(
    db: AsyncSession,
    novel_id: str,
    *,
    chapter_index: int,
) -> int | None:
    """受影响 Scene 窗口起点：锚定该章的最早 Scene（无则 None）。

    保守扩大（后续 Scene 的历史依赖前缀）由调用方在回执中说明，
    supersede 本身从该起点"含起点"向后执行。
    """
    scenes = await get_scenes_by_novel(db, novel_id, status_filter=["canonical", "draft"])
    anchored = [
        int(scene["scene_index"])
        for scene in scenes
        if chapter_index in _scene_chapter_indices(scene)
    ]
    return min(anchored) if anchored else None


#: 锚定结构合成登记的方法版本标识（见 ``impact.ANCHORED_SCENE_IMPLICIT_
#: METHOD_VERSION``；invalidation 侧不再顶层 import，见该模块环说明）。
ANCHORED_SCENE_IMPLICIT_METHOD_VERSION = "anchored-scene-implicit-v1"


async def apply_source_invalidation(
    db: AsyncSession,
    novel_id: str,
    *,
    chapter_index: int,
    change: SourceChange,
    content_mode: str = "working",
) -> InvalidationReceipt:
    """传播一次正文变更：证据索引重建触发 + Scene 派生投影软失效。

    P2-C C2：投影失效范围组装 ``assess_source_impact``（登记集 = checkpoint
    行真实登记 + 锚定结构合成登记）。无登记/登记覆盖不全时评估窗口与现状
    保守扩大逐位一致（``from == earliest``）；登记覆盖完整且证明无关时投影
    失效收窄（evolution runs 失效保持保守锚，不受投影收窄影响）。回执附
    ``affected``/``unknown_scope``/``receipt_id``/``recompute_options``。
    """
    receipt = InvalidationReceipt(
        novel_id=novel_id,
        chapter_index=chapter_index,
        source_change=change,
        unsupported_consumers=[dict(item) for item in UNSUPPORTED_CONSUMERS],
    )
    # 函数内 import：impact 组装层依赖 consumption 契约，而契约模块顶层
    # import 本模块（C1 冻结形态）——顶层互引即环，组装层拆在
    # modules.evolution.impact，本模块仅在使用点解析。
    from modules.evolution.consumption import receipt_fingerprint
    from modules.evolution.impact import (
        anchored_registrations,
        attach_impact_view,
        load_scene_consumption_records,
    )

    if not change.changed:
        receipt.nothing_to_do = True
        receipt.coverage_note = "内容指纹未变化，无失效需要传播"
        receipt.receipt_id = receipt_fingerprint(receipt)
        return receipt

    from modules.evidence.facade import (
        purge_interaction_source_cache,
        request_chapter_index,
    )

    index_state = await request_chapter_index(
        db, novel_id, chapter_index, content_mode=content_mode
    )
    requested_hash = index_state.get("requested_hash")
    receipt.invalidated_consumers["evidence_chapter_index"] = {
        "chapter_index": chapter_index,
        "content_mode": content_mode,
        "requested_source_id": index_state.get("requested_source_id"),
        "requested_hash": requested_hash,
    }
    # M4：来源指纹分叉后立即清理以其为来源的 RP 派生缓存行，
    # 不等 TTL（主计划 §5.1「随后清理」）；拒绝使用仍由门禁/key/证明重放承担。
    # 清理属辅助动作：DB 层失败降级为记录并让 TTL 兜底，不阻断失效传播；
    # 非 DB 异常照常上抛。
    try:
        async with db.begin_nested():
            purged = await purge_interaction_source_cache(db, source_novel_id=novel_id)
        receipt.invalidated_consumers["interaction_source_cache"] = {
            "purged_rows": purged,
        }
    except SQLAlchemyError:
        receipt.invalidated_consumers["interaction_source_cache"] = {
            "purged_rows": None,
            "note": "清理暂时失败；行已因 key 变化不可达，TTL 兜底回收",
        }
    # 建议有效性缝（T17）：来源指纹分叉后，声称旧来源的建议立即失效。
    receipt.invalidated_consumers["assistant_suggestion_validity"] = {
        "mode": "evidence_freshness",
        "chapter_index": chapter_index,
        "content_mode": content_mode,
        "validity_check": "modules.evolution.consumers.check_suggestion_validity",
    }

    scenes = await get_scenes_by_novel(db, novel_id, status_filter=["canonical", "draft"])
    anchored_indexes = [
        int(scene["scene_index"])
        for scene in scenes
        if chapter_index in _scene_chapter_indices(scene)
    ]
    earliest = min(anchored_indexes) if anchored_indexes else None
    receipt.earliest_affected_scene_index = earliest

    # 登记读取（supersede 前，current 行）+ 锚定结构合成 → 影响评估。
    real_records = await load_scene_consumption_records(db, novel_id, scenes)
    records = [
        *real_records,
        *anchored_registrations(
            novel_id,
            chapter_index=chapter_index,
            scenes=scenes,
            real_records=real_records,
        ),
    ]
    from modules.evolution.consumption import assess_source_impact

    assessment = assess_source_impact(
        novel_id=novel_id,
        chapter_index=chapter_index,
        change=change,
        content_mode=content_mode,
        records=records,
        earliest_affected_scene_index=earliest,
        scene_indexes=[int(scene["scene_index"]) for scene in scenes],
    )
    projection_from = assessment.from_scene_index

    runs = await PostgresAttemptStore(db, novel_id).invalidate_sources(
        from_scene_index=earliest, chapter_index=chapter_index, reason="source_changed"
    )
    receipt.invalidated_consumers["evolution_runs"] = {
        "run_keys": runs,
        "recompute_required": bool(runs),
    }
    from modules.story.facade import invalidate_derived_state

    receipt.invalidated_consumers["story_state"] = await invalidate_derived_state(
        db, novel_id, from_scene_index=projection_from, from_chapter=chapter_index
    )
    if projection_from is not None:
        receipt.invalidated_consumers["story_scene_projections"] = (
            receipt.invalidated_consumers["story_state"]
        )
    if assessment.unknown_scope.conservative:
        receipt.coverage_note = (
            "保守扩大：从锚定受影响章的最早 Scene（含）起的全部系统派生投影"
            "已失效；细粒度依赖登记后可收窄"
        )
    elif earliest is not None and projection_from == earliest:
        receipt.coverage_note = (
            "锚定受影响章的场景（含）起派生投影已失效；消费登记覆盖完整，无未知保守范围"
        )
    elif earliest is None:
        receipt.coverage_note = "受影响章未锚定任何 Scene，仅触发证据索引重建"
    else:
        receipt.coverage_note = (
            "消费登记覆盖完整：投影失效范围已按登记收窄"
            f"（from_scene_index={projection_from}，保守锚={earliest}）"
        )
    attach_impact_view(receipt, assessment)
    return receipt


async def record_writing_source_change(
    db: AsyncSession,
    novel_id: str,
    *,
    chapter_index: int,
    old_content: str | None,
    new_content: str | None,
    published_changed: bool = False,
) -> InvalidationReceipt:
    """Writing's mutation boundary; index tasks and invalidation share its transaction."""
    change = compute_source_change(old_content, new_content)
    # This entry is called only for a real version/title/content/lifecycle change.
    # Identical text in a new version still changes the authoritative source identity.
    change.changed = True
    receipt = await apply_source_invalidation(
        db, novel_id, chapter_index=chapter_index, change=change
    )
    if published_changed:
        from modules.evidence.facade import request_chapter_index

        receipt.invalidated_consumers[
            "canonical_chapter_index"
        ] = await request_chapter_index(
            db, novel_id, chapter_index, content_mode="canonical"
        )
    return receipt


async def apply_scene_reorder_invalidation(
    db: AsyncSession,
    novel_id: str,
    *,
    scene_positions: dict[str, int],
    earliest_affected_scene_index: int | None = None,
) -> InvalidationReceipt:
    """场景重排失效（T09 调换场景）：对齐事件序号并从最早移动 Scene 起失效。

    重排不只重写 scene_index——依赖顺序的历史事件、检查点与角色知识
    一并软失效；原事件与作者确认保留（§6.1）。
    """
    from modules.evolution.consumption import receipt_fingerprint
    from modules.story.facade import (
        align_scene_event_indices,
        get_scene_event_order_start,
        invalidate_derived_state,
    )

    receipt = InvalidationReceipt(
        novel_id=str(novel_id),
        unsupported_consumers=[dict(item) for item in UNSUPPORTED_CONSUMERS],
    )
    earliest = await get_scene_event_order_start(db, novel_id, scene_positions)
    if earliest_affected_scene_index is not None:
        earliest = (
            min(earliest, earliest_affected_scene_index)
            if earliest is not None
            else earliest_affected_scene_index
        )
    receipt.earliest_affected_scene_index = earliest
    if earliest is None:
        receipt.nothing_to_do = True
        receipt.coverage_note = "事件序号与权威顺序一致，无失效需要传播"
        receipt.receipt_id = receipt_fingerprint(receipt)
        return receipt
    runs = await PostgresAttemptStore(db, novel_id).invalidate_sources(
        from_scene_index=earliest, chapter_index=None, reason="scene_order_changed"
    )
    # All writers take run rows before event rows, matching apply_frozen's lock order.
    await align_scene_event_indices(db, novel_id, scene_positions)
    receipt.invalidated_consumers["evolution_runs"] = {"run_keys": runs}
    outcome = await invalidate_derived_state(
        db, novel_id, from_scene_index=earliest, from_chapter=None
    )
    receipt.invalidated_consumers["story_scene_projections"] = outcome
    receipt.invalidated_consumers["scene_event_order"] = {
        "aligned_scenes": len(scene_positions),
        "from_scene_index": earliest,
    }
    receipt.coverage_note = "场景重排：事件序号已对齐，最早移动 Scene（含）起派生投影失效"
    receipt.receipt_id = receipt_fingerprint(receipt)
    return receipt


def novel_scope_guard(novel_id: str, owner_novel_id: str | uuid.UUID) -> None:
    """失效传播不跨项目：目标与来源必须同 novel（信任边界不变量）。"""
    if str(owner_novel_id) != str(novel_id):
        raise ValueError("invalidation must stay within one novel scope")
