"""P20 滚动规划窗口（BR-6）的确定性规则。

滚动规划只到大纲级：剧情线与篇章层窗口默认 3 章、上限 5 章；计划 Scene 层
只覆盖紧邻 1-2 章。窗口外的层照常可手动用全书范围——本模块的全部规则只在
请求携带 ``rolling_window`` 时生效，手动结构工作台不受影响。

生成后的硬校验是确定性的最后一道门：窗口外或指向已写章节的条目丢弃并在
结果中说明，不是整任务失败。条目丢弃只作用于生成预览，不影响正文与已有
规划；作者仍可逐条取舍。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from modules.story.outline_state.p20_schemas import (
    OutlineLayerGenerateRequest,
    P20ArcDraft,
    P20SceneDraft,
    P20ThreadDraft,
)

P20_WINDOW_POLICY = "p20_rolling_window_v1"

# 剧情线与篇章层：窗口默认 3 章、上限 5 章（计划 §5 BR-6 第 2 项）。
ARC_WINDOW_DEFAULT = 3
ARC_WINDOW_MAX = 5
# 计划 Scene 层：只为紧邻的 1-2 章生成（计划 §5 BR-6 第 4 项）。
SCENE_WINDOW_DEFAULT = 1
SCENE_WINDOW_MAX = 2

_WINDOW_BOUNDS = {
    "plot_thread": (ARC_WINDOW_DEFAULT, ARC_WINDOW_MAX),
    "outline_arc": (ARC_WINDOW_DEFAULT, ARC_WINDOW_MAX),
    "planned_scene": (SCENE_WINDOW_DEFAULT, SCENE_WINDOW_MAX),
}

# 滚动窗口内一次生成允许保留的条数上限；超过上限的条目从尾部丢弃。
# Scene 按每章至多 2 个 Scene 随窗口宽度伸缩。
_FIXED_ENTRY_LIMITS = {"plot_thread": 3, "outline_arc": 3}
_SCENES_PER_CHAPTER = 2

_ENTRY_FIELD = {
    "plot_thread": "threads",
    "outline_arc": "arcs",
    "planned_scene": "scenes",
}


def window_bounds(target: str, start_chapter: int | None) -> tuple[int, int] | None:
    """把“只传起始章”解析为完整窗口；无窗口返回 None。"""
    if start_chapter is None:
        return None
    default, _maximum = _WINDOW_BOUNDS[target]
    return start_chapter, start_chapter + default - 1


def window_limit_violation(target: str, start: int, end: int) -> str | None:
    """窗口宽度超过该层上限时返回作者可读说明。"""
    _default, maximum = _WINDOW_BOUNDS[target]
    if end - start + 1 <= maximum:
        return None
    return f"章节窗口为第 {start} 至 {end} 章，超过当前层 {maximum} 章的上限"


def entry_limit(target: str, start: int, end: int) -> int:
    if target == "planned_scene":
        return _SCENES_PER_CHAPTER * (end - start + 1)
    return _FIXED_ENTRY_LIMITS[target]


def window_prompt_directive(request: OutlineLayerGenerateRequest) -> str:
    """把确认的窗口写成一条确定性的 system 规则；无窗口返回空串。"""
    if not request.rolling_window or request.start_chapter is None:
        return ""
    end = request.end_chapter or request.start_chapter
    return (
        "\n\n本次是滚动规划：作者确认的章节窗口为第 "
        f"{request.start_chapter} 至 {end} 章。"
        "新增条目自身的章节定位（剧情线起始章、篇章起止章、Scene 计划章节范围）"
        "只能落在这个窗口内；剧情线的长期兑现章与信息节点可以指向窗口外的未来，"
        "但不得指向已写成正文的章节冒充已发生内容。"
        "条目数量保持克制，只提出这个窗口需要的条目。"
    )


def _entry_chapters(draft: Any) -> list[int]:
    """条目自身占据的章节；长期兑现章与信息节点不算占位。"""
    if isinstance(draft, P20ThreadDraft):
        return [draft.start_chapter] if draft.start_chapter is not None else []
    if isinstance(draft, P20ArcDraft):
        return [
            value
            for value in (draft.start_chapter, draft.end_chapter)
            if value is not None
        ]
    if isinstance(draft, P20SceneDraft):
        return [
            value
            for value in (draft.planned_start_chapter, draft.planned_end_chapter)
            if value is not None
        ]
    return []


def _entry_label(draft: Any) -> str:
    return str(
        getattr(draft, "name", None) or getattr(draft, "title", None) or ""
    )


def _is_new_entry(draft: Any) -> bool:
    """修订目标是作者显式选中的已有资产，其既有覆盖不算窗口违规。"""
    return (
        getattr(draft, "target_thread_ref", None) is None
        and getattr(draft, "target_arc_ref", None) is None
        and getattr(draft, "target_scene_ref", None) is None
    )


def apply_planning_window(
    request: OutlineLayerGenerateRequest,
    output: BaseModel,
    *,
    written_chapters: frozenset[int] | set[int] = frozenset(),
) -> tuple[BaseModel, dict[str, Any]]:
    """丢弃窗口违规条目并返回说明；请求无窗口时原样返回。

    返回 ``(filtered_output, report)``。report 仅在窗口请求且确有丢弃时
    给出 ``dropped`` 明细；其余情况报告仍携带 policy 以便结果可审计。
    """

    start = request.start_chapter
    end = request.end_chapter or start
    if not request.rolling_window or start is None or end is None:
        return output, {"policy": P20_WINDOW_POLICY, "applied": False}

    field = _ENTRY_FIELD[request.target]
    drafts: list[Any] = list(getattr(output, field))
    dropped: list[dict[str, Any]] = []
    kept: list[tuple[int, Any]] = []
    for index, draft in enumerate(drafts):
        chapters = _entry_chapters(draft)
        # 修订模式更新的是作者显式选中的已有资产；其既有章节覆盖可以超出
        # 窗口（篇章本来就横跨窗口与已写章节），章号硬校验只针对新条目。
        if _is_new_entry(draft):
            outside = [value for value in chapters if not (start <= value <= end)]
            if outside:
                dropped.append(
                    {
                        "index": index,
                        "proposal_ref": draft.proposal_ref,
                        "name": _entry_label(draft),
                        "reason": "chapter_outside_window",
                        "chapters": outside,
                        "detail": (
                            f"章节 {outside} 落在确认窗口（第 {start} 至 {end} 章）之外"
                        ),
                    }
                )
                continue
            if request.mode == "create":
                written = sorted(
                    value for value in chapters if value in written_chapters
                )
                if written:
                    dropped.append(
                        {
                            "index": index,
                            "proposal_ref": draft.proposal_ref,
                            "name": _entry_label(draft),
                            "reason": "chapter_points_to_written",
                            "chapters": written,
                            "detail": (
                                f"章节 {written} 已写成正文；新建规划不得覆盖已写章节"
                            ),
                        }
                    )
                    continue
        kept.append((index, draft))

    limit = entry_limit(request.target, start, end)
    for index, draft in kept[limit:]:
        dropped.append(
            {
                "index": index,
                "proposal_ref": draft.proposal_ref,
                "name": _entry_label(draft),
                "reason": "entry_limit_exceeded",
                "chapters": [],
                "detail": f"超过滚动窗口条数上限 {limit}，仅保留前 {limit} 条",
            }
        )
    survivors = [draft for _index, draft in kept[:limit]]

    report: dict[str, Any] = {
        "policy": P20_WINDOW_POLICY,
        "applied": True,
        "window": {"start": start, "end": end},
        "entry_limit": limit,
        "kept_count": len(survivors),
        "written_chapter_count": len(written_chapters),
    }
    if dropped:
        report["dropped"] = dropped
        filtered = output.model_copy(update={field: survivors})
    else:
        filtered = output
    return filtered, report
