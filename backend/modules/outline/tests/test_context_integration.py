from __future__ import annotations

import uuid
from unittest import mock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from modules.outline.schemas import OutlineArcCreate, PlotThreadCreate
from modules.outline.services import OutlineArcService, PlotThreadService


def _mock_container_get(name):
    if name == "outline.thread_service":
        return PlotThreadService()
    if name == "outline.arc_service":
        return OutlineArcService()
    if name == "world.list_characters":

        async def _list_chars(db, novel_id, limit=999):
            return [], 0

        return _list_chars
    if name == "world.list_entity_terms":

        async def _list_entity_terms(db, novel_id):
            return []

        return _list_entity_terms
    raise KeyError(name)


_CONTAINER_GET_PATCHES = [
    mock.patch(
        "modules.context.services.loaders.plot_threads_loader._container_get",
        side_effect=_mock_container_get,
    ),
    mock.patch(
        "modules.context.services.loaders.outline_arc_loader._container_get",
        side_effect=_mock_container_get,
    ),
    mock.patch(
        "modules.rag.query_expansion._container_get",
        side_effect=_mock_container_get,
    ),
]


def test_plot_structure_context_markdown_includes_rag_evidence_and_warnings() -> None:
    """结构分析 prompt 应包含 RAG 检索证据和降级提示。"""
    from modules.context.contracts import StructureContextBundle
    from modules.outline.generation.context_builder import PlotStructureContextBuilder

    bundle = StructureContextBundle(
        novel_id="00000000-0000-0000-0000-000000000499",
        task="生成剧情结构",
        scope="full",
        project={"title": "测试项目"},
        rag_chunks=[
            {
                "text": "克莱恩在廷根醒来，发现自己处于陌生世界。",
                "source_type": "chapter_text",
                "chapter_index": 1,
            }
        ],
        warnings=["RAG 检索降级"],
    )

    markdown = PlotStructureContextBuilder()._render_bundle_to_markdown(bundle)

    assert "## RAG 检索证据" in markdown
    assert "克莱恩在廷根醒来" in markdown
    assert "## 上下文警告" in markdown
    assert "RAG 检索降级" in markdown


@pytest.mark.asyncio
async def test_plot_threads_loaded_in_arc_scope(
    db_session: AsyncSession,
    sample_novel_id: str,
) -> None:
    """compile_structure_context(scope='arc') 应包含活跃剧情线"""
    nid = uuid.UUID(hex=sample_novel_id)
    from modules.project.models import Project

    db_session.add(Project(id=nid, title="测试"))
    await db_session.flush()

    thread_svc = PlotThreadService()
    await thread_svc.create(
        db_session,
        sample_novel_id,
        PlotThreadCreate(
            name="主线测试",
            thread_type="main",
            start_chapter=1,
            status="canonical",
        ),
    )

    from modules.context.facade import compile_structure_context

    for p in _CONTAINER_GET_PATCHES:
        p.start()
    try:
        bundle = await compile_structure_context(
            db=db_session,
            novel_id=sample_novel_id,
            task="测试",
            scope="arc",
            chapter_index=1,
        )
    finally:
        for p in _CONTAINER_GET_PATCHES:
            p.stop()

    assert len(bundle.plot_threads) >= 1
    names = [t["name"] for t in bundle.plot_threads]
    assert "主线测试" in names


@pytest.mark.asyncio
async def test_outline_arc_loaded_in_chapter_scope(
    db_session: AsyncSession,
    sample_novel_id: str,
) -> None:
    """compile_structure_context(scope='chapter') 应包含当前章节所属篇章"""
    nid = uuid.UUID(hex=sample_novel_id)
    from modules.project.models import Project

    db_session.add(Project(id=nid, title="测试"))
    await db_session.flush()

    arc_svc = OutlineArcService()
    await arc_svc.create(
        db_session,
        sample_novel_id,
        OutlineArcCreate(
            title="测试卷",
            start_chapter=1,
            end_chapter=10,
            arc_goal="测试目标",
        ),
    )

    from modules.context.facade import compile_structure_context

    for p in _CONTAINER_GET_PATCHES:
        p.start()
    try:
        bundle = await compile_structure_context(
            db=db_session,
            novel_id=sample_novel_id,
            task="测试",
            scope="chapter",
            chapter_index=3,
        )
    finally:
        for p in _CONTAINER_GET_PATCHES:
            p.stop()

    assert bundle.outline_arc is not None
    assert bundle.outline_arc["title"] == "测试卷"
    assert bundle.outline_arc["arc_goal"] == "测试目标"


@pytest.mark.asyncio
async def test_outline_not_loaded_in_world_scope(
    db_session: AsyncSession,
    sample_novel_id: str,
) -> None:
    """scope='world' 不应加载大纲数据"""
    nid = uuid.UUID(hex=sample_novel_id)
    from modules.project.models import Project

    db_session.add(Project(id=nid, title="测试"))
    await db_session.flush()

    from modules.context.facade import compile_structure_context

    bundle = await compile_structure_context(
        db=db_session,
        novel_id=sample_novel_id,
        task="测试",
        scope="world",
    )

    assert bundle.plot_threads == []
    assert bundle.outline_arc is None
