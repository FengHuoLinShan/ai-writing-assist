"""滚动规划已规划章覆盖的查询实现（BR-6 补窗检查）。

覆盖只统计已采用的规划资产：篇章（非 deprecated 且带起止章）、计划 Scene
（``structure_meta.planning_state == "planned"`` 且带计划章节范围，不含已落
物理章节的 materialized）、剧情线（非 deprecated 且起始章在窗口内）。供
``planning_window_facade`` 适配为跨模块只读缝；本模块不承载跨模块契约。
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.story.outline_state.models import OutlineArc, PlotThread, Scene


def _overlap(item_start: int, item_end: int, start: int, end: int) -> bool:
    return item_start <= end and item_end >= start


async def planned_chapter_coverage(
    db: AsyncSession,
    novel_id: str,
    *,
    start_chapter: int,
    end_chapter: int,
) -> dict[str, Any]:
    """统计 ``[start_chapter, end_chapter]`` 内已被已采用规划覆盖的章节。"""
    if end_chapter < start_chapter:
        return {
            "chapters": [],
            "arc_count": 0,
            "planned_scene_count": 0,
            "thread_count": 0,
        }
    novel_uuid = uuid.UUID(str(novel_id))
    covered: set[int] = set()

    arcs = (
        await db.scalars(
            select(OutlineArc).where(
                OutlineArc.novel_id == novel_uuid,
                OutlineArc.status != "deprecated",
                OutlineArc.start_chapter.is_not(None),
                OutlineArc.end_chapter.is_not(None),
                OutlineArc.start_chapter <= end_chapter,
                OutlineArc.end_chapter >= start_chapter,
            )
        )
    ).all()
    for arc in arcs:
        lo = max(int(arc.start_chapter), start_chapter)
        hi = min(int(arc.end_chapter), end_chapter)
        covered.update(range(lo, hi + 1))

    scenes = (
        await db.scalars(
            select(Scene).where(
                Scene.novel_id == novel_uuid,
                Scene.status != "deprecated",
            )
        )
    ).all()
    planned_scene_count = 0
    for scene in scenes:
        meta = scene.structure_meta or {}
        if str(meta.get("planning_state") or "") != "planned":
            continue
        range_meta = meta.get("planned_chapter_range") or {}
        range_start, range_end = range_meta.get("start"), range_meta.get("end")
        if range_start is None or range_end is None:
            continue
        lo, hi = int(range_start), int(range_end)
        if _overlap(lo, hi, start_chapter, end_chapter):
            planned_scene_count += 1
            covered.update(range(max(lo, start_chapter), min(hi, end_chapter) + 1))

    threads = (
        await db.scalars(
            select(PlotThread).where(
                PlotThread.novel_id == novel_uuid,
                PlotThread.status != "deprecated",
                PlotThread.start_chapter.is_not(None),
                PlotThread.start_chapter >= start_chapter,
                PlotThread.start_chapter <= end_chapter,
            )
        )
    ).all()
    for thread in threads:
        covered.add(int(thread.start_chapter))

    return {
        "chapters": sorted(covered),
        "arc_count": len(arcs),
        "planned_scene_count": planned_scene_count,
        "thread_count": len(threads),
    }
