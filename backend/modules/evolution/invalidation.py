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
"""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

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
    """一次失效传播的结果：失效了什么、扩大到哪、哪些消费者未接线。"""

    model_config = ConfigDict(extra="forbid")

    novel_id: str
    chapter_index: int | None = None
    source_change: SourceChange | None = None
    earliest_affected_scene_index: int | None = None
    invalidated_consumers: dict[str, dict[str, Any]] = Field(default_factory=dict)
    unsupported_consumers: list[dict[str, str]] = Field(default_factory=list)
    nothing_to_do: bool = False
    coverage_note: str = ""


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
    from modules.story.outline_state.facade import get_scenes_by_novel

    scenes = await get_scenes_by_novel(db, novel_id, status_filter=["canonical", "draft"])
    anchored = [
        int(scene["scene_index"])
        for scene in scenes
        if chapter_index in _scene_chapter_indices(scene)
    ]
    return min(anchored) if anchored else None


async def apply_source_invalidation(
    db: AsyncSession,
    novel_id: str,
    *,
    chapter_index: int,
    change: SourceChange,
    content_mode: str = "working",
) -> InvalidationReceipt:
    """传播一次正文变更：证据索引重建触发 + Scene 派生投影软失效。"""
    receipt = InvalidationReceipt(
        novel_id=novel_id,
        chapter_index=chapter_index,
        source_change=change,
        unsupported_consumers=[dict(item) for item in UNSUPPORTED_CONSUMERS],
    )
    if not change.changed:
        receipt.nothing_to_do = True
        receipt.coverage_note = "内容指纹未变化，无失效需要传播"
        return receipt

    from modules.evidence.facade import request_chapter_index

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
    # 建议有效性缝（T17）：来源指纹分叉后，声称旧来源的建议立即失效。
    receipt.invalidated_consumers["assistant_suggestion_validity"] = {
        "mode": "evidence_freshness",
        "chapter_index": chapter_index,
        "content_mode": content_mode,
        "validity_check": "modules.evolution.consumers.check_suggestion_validity",
    }

    earliest = await affected_scene_window(db, novel_id, chapter_index=chapter_index)
    receipt.earliest_affected_scene_index = earliest
    if earliest is not None:
        from modules.story.facade import supersede_scene_projections_from

        outcome = await supersede_scene_projections_from(
            db, novel_id, from_scene_index=earliest
        )
        receipt.invalidated_consumers["story_scene_projections"] = outcome
        receipt.coverage_note = (
            "保守扩大：从锚定受影响章的最早 Scene（含）起的全部系统派生投影"
            "已失效；细粒度依赖登记后可收窄"
        )
    else:
        receipt.coverage_note = "受影响章未锚定任何 Scene，仅触发证据索引重建"
    return receipt


async def apply_scene_reorder_invalidation(
    db: AsyncSession,
    novel_id: str,
    *,
    scene_positions: dict[str, int],
) -> InvalidationReceipt:
    """场景重排失效（T09 调换场景）：对齐事件序号并从最早移动 Scene 起失效。

    重排不只重写 scene_index——依赖顺序的历史事件、检查点与角色知识
    一并软失效；原事件与作者确认保留（§6.1）。
    """
    from modules.story.continuity.repositories import EventRepository
    from modules.story.facade import supersede_scene_projections_from
    from shared.utils import parse_uuid

    nid = parse_uuid(novel_id, "novel_id")
    receipt = InvalidationReceipt(
        novel_id=str(novel_id),
        unsupported_consumers=[dict(item) for item in UNSUPPORTED_CONSUMERS],
    )
    positions = {
        parse_uuid(scene_id, "scene_id"): int(index)
        for scene_id, index in scene_positions.items()
    }
    earliest = await EventRepository().align_scene_indices(db, nid, positions)
    receipt.earliest_affected_scene_index = earliest
    if earliest is None:
        receipt.nothing_to_do = True
        receipt.coverage_note = "事件序号与权威顺序一致，无失效需要传播"
        return receipt
    outcome = await supersede_scene_projections_from(
        db, novel_id, from_scene_index=earliest
    )
    receipt.invalidated_consumers["story_scene_projections"] = outcome
    receipt.invalidated_consumers["scene_event_order"] = {
        "aligned_scenes": len(positions),
        "from_scene_index": earliest,
    }
    receipt.coverage_note = "场景重排：事件序号已对齐，最早移动 Scene（含）起派生投影失效"
    return receipt


def novel_scope_guard(novel_id: str, owner_novel_id: str | uuid.UUID) -> None:
    """失效传播不跨项目：目标与来源必须同 novel（信任边界不变量）。"""
    if str(owner_novel_id) != str(novel_id):
        raise ValueError("invalidation must stay within one novel scope")
