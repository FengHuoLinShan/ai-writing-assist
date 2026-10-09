"""试改 patch 的状态影响有限列表（M5 契约 §3）。

确定性锚定、不重投影（M4 已分离失效与昂贵重算）：只列出能从被改资源确定性
推导到的 Scene 状态维度；其余影响面显式进 not_checked，不推算、不冒充「无影响」。
世界正典类修订不自动改写场景观察（M4 unsupported_dependencies 语义），影响评估
走既有检查流水线与 World 复核。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import DomainError
from modules.story import facade as story_facade

_WORLD_CANON_NOTE = (
    "世界正典修订不自动改写场景观察（观察层记录「当时所见」）；"
    "规则影响经检查流水线评估，核对待走 World 复核"
)
_UNANCHORED_NOTE = "该资源对状态事实的影响无法确定性锚定，未列入 affected"

_WORLD_LIKE_KINDS = frozenset({"world_bible_draft"})


async def trial_state_impact(
    db: AsyncSession,
    novel_id: str,
    *,
    kind: str,
    resource_id: str,
    chapter_index: int | None,
    get_scenes=None,  # noqa: ANN001 —— 测试注入缝；缺省经 story facade
    get_scene_checkpoints=None,  # noqa: ANN001
) -> dict[str, Any]:
    """返回 {affected, not_checked, notes}；纯读，不写任何领域行。"""
    scene_reader = get_scenes or story_facade.get_scenes_by_novel
    checkpoint_reader = get_scene_checkpoints or story_facade.get_scene_checkpoints

    notes: list[str] = []
    not_checked: list[str] = []
    anchored: list[tuple[str, str]] = []  # (scene_id, reason)

    if kind == "scene":
        anchored.append((str(resource_id), "试改直接锚定该 Scene"))
    elif kind == "writing_draft":
        if chapter_index is None:
            not_checked.append("该正文资源缺少章节信息，无法锚定 Scene")
        else:
            scenes = await scene_reader(db, novel_id)
            hit = [
                scene
                for scene in scenes
                if str(chapter_index)
                in {str(value) for value in scene.get("chapter_ids") or []}
                or any(
                    str(chunk.get("chapter_index", chunk.get("chapter_id")))
                    == str(chapter_index)
                    for chunk in scene.get("scene_chunks") or []
                    if isinstance(chunk, dict)
                )
            ]
            if not hit:
                not_checked.append(f"第 {chapter_index} 章未锚定任何 Scene")
            if hit:
                notes.append(
                    f"这份正文已锚定 {len(hit)} 个场景；具体状态影响须由来源依赖证明"
                )
            for scene in hit:
                anchored.append((str(scene["id"]), f"第 {chapter_index} 章正文的 Scene"))
    else:
        affected: list[dict[str, Any]] = []
        if kind in _WORLD_LIKE_KINDS:
            notes.append(_WORLD_CANON_NOTE)
        not_checked.append(_UNANCHORED_NOTE)
        return {"affected": affected, "not_checked": not_checked, "notes": notes}

    affected = []
    for scene_id, reason in anchored:
        try:
            checkpoint_set = await checkpoint_reader(db, novel_id, scene_id)
        except DomainError:
            not_checked.append("场景状态暂时不可读，无法核对")
            continue
        for item in checkpoint_set.items:
            label = {
                "entities": "对象",
                "relations": "关系",
                "locations": "位置",
                "knowledge": "知识",
                "timeline": "时间",
                "causality": "因果",
            }.get(item.dimension, "相关")
            if item.status != "ready":
                not_checked.append(f"该场景的{label}状态尚无可靠依据")
                continue
            if kind == "writing_draft":
                refs = list(getattr(item, "evidence_refs", None) or [])
                direct = any(
                    str(ref.get("draft_id") or ref.get("id") or "") == resource_id
                    and ref.get("type") in {"writing_draft", "manuscript", "chapter_text"}
                    for ref in refs
                )
                if not direct:
                    not_checked.append(f"该场景的{label}未登记对这份正文的直接依赖")
                    continue
            affected.append(
                {
                    "scene_id": scene_id,
                    "dimension": item.dimension,
                    "status": item.status,
                    "reason": reason,
                }
            )
        if not checkpoint_set.items:
            not_checked.append("该场景尚未建立状态投影")
    not_checked.append("未锚定到的维度不做影响推断；候选状态在采用后经失效/重建产生")
    return {"affected": affected, "not_checked": not_checked, "notes": notes}
