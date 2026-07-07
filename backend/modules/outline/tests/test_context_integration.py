from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest import mock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from modules.outline.schemas import OutlineArcCreate, PlotThreadCreate
from modules.outline.services import OutlineArcService, PlotThreadService
from modules.writing.contracts import WritingDraftContract


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
async def test_plot_structure_context_loads_chapter_texts_in_one_batch(
    db_session: AsyncSession,
    sample_novel_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """生成结构上下文时，章节正文范围应通过 writing facade 批量加载。"""
    from modules.outline.generation import context_builder

    batch_calls: list[list[int]] = []

    async def fail_single_fetch(db, novel_id, chapter_index):
        raise AssertionError("should not fetch latest drafts one chapter at a time")

    async def fake_batch_fetch(db, novel_id, chapter_indices, *, content_limit=None):
        batch_calls.append(list(chapter_indices))
        assert content_limit == context_builder._CHAPTER_TEXT_LIMIT + 1
        return [
            WritingDraftContract(
                novel_id=novel_id,
                chapter_index=2,
                content="第二章正文",
            ),
            WritingDraftContract(
                novel_id=novel_id,
                chapter_index=3,
                content="",
            ),
            WritingDraftContract(
                novel_id=novel_id,
                chapter_index=4,
                content="第四章正文",
            ),
        ]

    monkeypatch.setattr(
        context_builder.writing_facade,
        "get_latest_draft_for_chapter",
        fail_single_fetch,
    )
    monkeypatch.setattr(
        context_builder.writing_facade,
        "list_latest_drafts_for_chapters",
        fake_batch_fetch,
    )

    texts = await context_builder.PlotStructureContextBuilder()._load_chapter_texts(
        db_session,
        sample_novel_id,
        2,
        4,
    )

    assert batch_calls == [[2, 3, 4]]
    assert texts == [(2, "第二章正文"), (4, "第四章正文")]


@pytest.mark.asyncio
async def test_plot_structure_context_loads_scene_summaries_by_chapter_range(
    db_session: AsyncSession,
    sample_novel_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """已有 Scene 摘要应按章节范围查询，不应全量加载后 Python 过滤。"""
    from modules.outline import services as outline_services
    from modules.outline.generation.context_builder import PlotStructureContextBuilder

    range_calls: list[tuple[str, int, int]] = []

    class FakeSceneService:
        async def get_ordered(self, db, novel_id):
            raise AssertionError("should not load all scenes for range summaries")

        async def get_by_chapter_range_models(
            self,
            db,
            novel_id,
            start_chapter,
            end_chapter,
        ):
            range_calls.append((novel_id, start_chapter, end_chapter))
            return [
                SimpleNamespace(
                    scene_index=3,
                    title="范围内 Scene",
                    goal="推进主线",
                    core_conflict="正面对抗",
                    emotional_beat=None,
                    status="draft",
                    chapter_ids=["2", "3"],
                    scene_chunks=[],
                )
            ]

    monkeypatch.setattr(outline_services, "SceneService", FakeSceneService)

    markdown = await PlotStructureContextBuilder()._load_scene_summaries(
        db_session,
        sample_novel_id,
        2,
        4,
    )

    assert range_calls == [(sample_novel_id, 2, 4)]
    assert "S3 第2-3章《范围内 Scene》" in markdown


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
