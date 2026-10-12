"""已规划章覆盖只读缝（BR-6 补窗检查）的确定性规则。"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from modules.story.outline_state.models import OutlineArc, PlotThread, Scene
from modules.story.outline_state.planning_window_facade import (
    get_planned_chapter_coverage,
)


@pytest.mark.asyncio
async def test_empty_project_has_no_coverage(db_session: AsyncSession):
    from modules.project.models import Project

    novel_id = uuid.uuid4()
    db_session.add(Project(id=novel_id, title="覆盖空项目"))
    await db_session.flush()
    coverage = await get_planned_chapter_coverage(
        db_session, str(novel_id), start_chapter=2, end_chapter=4
    )
    assert coverage == {
        "chapters": [],
        "arc_count": 0,
        "planned_scene_count": 0,
        "thread_count": 0,
    }


@pytest.mark.asyncio
async def test_coverage_counts_arcs_planned_scenes_and_threads(db_session: AsyncSession):
    from modules.project.models import Project

    novel_id = uuid.uuid4()
    db_session.add(Project(id=novel_id, title="覆盖样本"))
    await db_session.flush()
    db_session.add_all(
        [
            OutlineArc(
                novel_id=novel_id,
                title="卷一",
                start_chapter=2,
                end_chapter=3,
                status="draft",
            ),
            # 已废弃篇章不计入。
            OutlineArc(
                novel_id=novel_id,
                title="废卷",
                start_chapter=2,
                end_chapter=4,
                status="deprecated",
            ),
            PlotThread(
                novel_id=novel_id,
                name="复仇线",
                thread_type="main",
                start_chapter=4,
                status="draft",
            ),
            # 窗口外的剧情线不计入。
            PlotThread(
                novel_id=novel_id,
                name="远处线",
                thread_type="sub",
                start_chapter=9,
                status="draft",
            ),
            Scene(
                novel_id=novel_id,
                scene_index=0,
                narrative_tag="draft",
                status="draft",
                structure_meta={
                    "semantic_origin": "p20_planned_scene",
                    "planning_state": "planned",
                    "planned_chapter_range": {"start": 3, "end": 4},
                },
            ),
            # materialized（已落物理章节）不算"前方规划"。
            Scene(
                novel_id=novel_id,
                scene_index=1,
                narrative_tag="draft",
                status="draft",
                structure_meta={
                    "planning_state": "materialized",
                    "planned_chapter_range": {"start": 2, "end": 4},
                },
            ),
        ]
    )
    await db_session.flush()

    coverage = await get_planned_chapter_coverage(
        db_session, str(novel_id), start_chapter=2, end_chapter=4
    )
    assert coverage["chapters"] == [2, 3, 4]
    assert coverage["arc_count"] == 1
    assert coverage["planned_scene_count"] == 1
    assert coverage["thread_count"] == 1

    # 部分窗口只统计窗口内的章节。
    partial = await get_planned_chapter_coverage(
        db_session, str(novel_id), start_chapter=3, end_chapter=3
    )
    assert partial["chapters"] == [3]


@pytest.mark.asyncio
async def test_invalid_window_returns_empty_coverage(db_session: AsyncSession):
    coverage = await get_planned_chapter_coverage(
        db_session, str(uuid.uuid4()), start_chapter=5, end_chapter=2
    )
    assert coverage["chapters"] == []
