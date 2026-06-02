from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from modules.outline.schemas import OutlineArcCreate, PlotThreadCreate
from modules.outline.services import OutlineArcService, PlotThreadService


@pytest.mark.asyncio
async def test_plot_threads_loaded_in_arc_scope(
    db_session: AsyncSession, sample_novel_id: str,
) -> None:
    """compile_structure_context(scope='arc') 应包含活跃剧情线"""
    nid = uuid.UUID(hex=sample_novel_id)
    from modules.project.models import Project

    db_session.add(Project(id=nid, title="测试"))
    await db_session.flush()

    thread_svc = PlotThreadService()
    await thread_svc.create(db_session, sample_novel_id, PlotThreadCreate(
        name="主线测试", thread_type="main", start_chapter=1, status="canonical",
    ))

    from modules.context.facade import compile_structure_context

    bundle = await compile_structure_context(
        db=db_session, novel_id=sample_novel_id,
        task="测试", scope="arc", chapter_index=1,
    )

    assert len(bundle.plot_threads) >= 1
    names = [t["name"] for t in bundle.plot_threads]
    assert "主线测试" in names


@pytest.mark.asyncio
async def test_outline_arc_loaded_in_chapter_scope(
    db_session: AsyncSession, sample_novel_id: str,
) -> None:
    """compile_structure_context(scope='chapter') 应包含当前章节所属篇章"""
    nid = uuid.UUID(hex=sample_novel_id)
    from modules.project.models import Project

    db_session.add(Project(id=nid, title="测试"))
    await db_session.flush()

    arc_svc = OutlineArcService()
    await arc_svc.create(db_session, sample_novel_id, OutlineArcCreate(
        title="测试卷", start_chapter=1, end_chapter=10, arc_goal="测试目标",
    ))

    from modules.context.facade import compile_structure_context

    bundle = await compile_structure_context(
        db=db_session, novel_id=sample_novel_id,
        task="测试", scope="chapter", chapter_index=3,
    )

    assert bundle.outline_arc is not None
    assert bundle.outline_arc["title"] == "测试卷"
    assert bundle.outline_arc["arc_goal"] == "测试目标"


@pytest.mark.asyncio
async def test_outline_not_loaded_in_world_scope(
    db_session: AsyncSession, sample_novel_id: str,
) -> None:
    """scope='world' 不应加载大纲数据"""
    nid = uuid.UUID(hex=sample_novel_id)
    from modules.project.models import Project

    db_session.add(Project(id=nid, title="测试"))
    await db_session.flush()

    from modules.context.facade import compile_structure_context

    bundle = await compile_structure_context(
        db=db_session, novel_id=sample_novel_id,
        task="测试", scope="world",
    )

    assert bundle.plot_threads == []
    assert bundle.outline_arc is None
