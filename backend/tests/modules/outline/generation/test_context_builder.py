"""PlotStructureContextBuilder 单元测试。"""

from __future__ import annotations

from unittest import mock

import pytest

from modules.context.contracts import StructureContextBundle
from modules.outline.generation.context_builder import PlotStructureContextBuilder
from modules.writing.contracts import WritingDraftContract


@pytest.fixture
def builder() -> PlotStructureContextBuilder:
    return PlotStructureContextBuilder()


@pytest.fixture
def sample_bundle() -> StructureContextBundle:
    return StructureContextBundle(
        novel_id="test-novel",
        task="test",
        scope="full",
        project={"title": "测试小说"},
        world_entities=[
            {"name": "霜华剑", "entity_type": "item", "entity_id": "ent-1"},
        ],
        characters=[
            {"name": "白砚", "role": "protagonist", "character_id": "char-1"},
        ],
    )


@pytest.mark.asyncio
async def test_build_renders_markdown_and_name_maps(
    builder: PlotStructureContextBuilder,
    sample_bundle: StructureContextBundle,
) -> None:
    """builder 正确渲染 markdown 并输出名称→ID 映射。"""
    with (
        mock.patch(
            "modules.outline.generation.context_builder.context_facade.compile_structure_context",
            return_value=sample_bundle,
        ) as mock_compile,
        mock.patch(
            "modules.outline.generation.context_builder.writing_facade.get_latest_draft_for_chapter",
            return_value=None,
        ) as mock_draft,
    ):
        ctx = await builder.build(
            db=mock.AsyncMock(),
            novel_id="test-novel",
            start_chapter=1,
            end_chapter=2,
        )

    mock_compile.assert_awaited_once()
    mock_draft.assert_awaited()

    assert "## 项目" in ctx.markdown
    assert "霜华剑" in ctx.markdown
    assert "白砚" in ctx.markdown
    assert ctx.entity_name_to_id == {"霜华剑": "ent-1"}
    assert ctx.character_name_to_id == {"白砚": "char-1"}


@pytest.mark.asyncio
async def test_build_loads_chapter_texts_via_facade(
    builder: PlotStructureContextBuilder,
    sample_bundle: StructureContextBundle,
) -> None:
    """章节正文通过 writing.facade 加载，不直接访问 WritingDraft model。"""
    draft = WritingDraftContract(
        novel_id="test-novel",
        chapter_index=1,
        content="第一章正文",
    )

    with (
        mock.patch(
            "modules.outline.generation.context_builder.context_facade.compile_structure_context",
            return_value=sample_bundle,
        ),
        mock.patch(
            "modules.outline.generation.context_builder.writing_facade.get_latest_draft_for_chapter",
            side_effect=[draft, None],
        ) as mock_draft,
    ):
        ctx = await builder.build(
            db=mock.AsyncMock(),
            novel_id="test-novel",
            start_chapter=1,
            end_chapter=2,
        )

    assert "## 章节原文" in ctx.markdown
    assert "第一章正文" in ctx.markdown
    assert mock_draft.await_count == 2
