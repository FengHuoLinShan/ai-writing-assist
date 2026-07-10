"""PlotStructureGenerator 单元测试。"""

from __future__ import annotations

from unittest import mock

import pytest

from modules.outline.generation.context_builder import PlotStructureContext
from modules.outline.generation.models import GeneratedThread
from modules.outline.generation.parser import ParsedPlotStructure
from modules.outline.generation.persister import PersistResult
from modules.outline.generator import PlotStructureGenerator


@pytest.mark.asyncio
async def test_generate_returns_persist_result() -> None:
    """正常路径：build → parse → persist → 返回 dict。"""
    ctx = PlotStructureContext(
        markdown="ctx",
        entity_name_to_id={},
        character_name_to_id={},
    )
    parsed = ParsedPlotStructure(
        threads=[],
        arcs=[],
        scenes=[],
        foreshadowing_plans=[],
        reveal_plans=[],
        offscreen_progress=[],
        risks=[],
        questions_for_user=[],
    )
    persist_result = PersistResult(
        total_threads=1,
        total_arcs=2,
        total_scenes=3,
    )

    builder = mock.MagicMock()
    builder.build = mock.AsyncMock(return_value=ctx)
    parser = mock.MagicMock()
    parser.parse = mock.AsyncMock(return_value=parsed)
    persister = mock.MagicMock()
    persister.persist = mock.AsyncMock(return_value=persist_result)

    generator = PlotStructureGenerator(
        context_builder=builder,
        llm_client=mock.AsyncMock(),
        persister=persister,
    )

    with mock.patch("modules.outline.generator.PlotStructureParser", return_value=parser):
        result = await generator.generate(
            db=mock.AsyncMock(),
            novel_id="12345678-1234-5678-1234-567812345678",
            start_chapter=1,
            end_chapter=3,
            persist=True,
        )

    builder.build.assert_awaited_once()
    parser.parse.assert_awaited_once()
    persister.persist.assert_awaited_once()
    assert result["total_threads"] == 1
    assert result["total_arcs"] == 2
    assert result["total_scenes"] == 3


@pytest.mark.asyncio
async def test_generate_preview_does_not_persist() -> None:
    """Manual generation can return editable review content without writes."""
    ctx = PlotStructureContext(
        markdown="ctx",
        warnings=["context warning"],
        entity_name_to_id={},
        character_name_to_id={},
    )
    parsed = ParsedPlotStructure(
        threads=[GeneratedThread(name="主线", thread_type="main")],
        arcs=[],
        scenes=[],
        foreshadowing_plans=[],
        reveal_plans=[],
        offscreen_progress=[],
        risks=[],
        questions_for_user=[],
    )
    builder = mock.MagicMock()
    builder.build = mock.AsyncMock(return_value=ctx)
    parser = mock.MagicMock()
    parser.parse = mock.AsyncMock(return_value=parsed)
    persister = mock.MagicMock()
    persister.persist = mock.AsyncMock()
    generator = PlotStructureGenerator(
        context_builder=builder,
        llm_client=mock.AsyncMock(),
        persister=persister,
    )

    with mock.patch("modules.outline.generator.PlotStructureParser", return_value=parser):
        result = await generator.generate(
            db=mock.AsyncMock(),
            novel_id="12345678-1234-5678-1234-567812345678",
            start_chapter=1,
            end_chapter=3,
            persist=False,
        )

    persister.persist.assert_not_awaited()
    assert result["requires_apply"] is True
    assert result["display_state"] == "review"
    assert result["threads"][0]["name"] == "主线"
    assert result["threads"][0]["needs_review"] is True
    assert result["draft_structure"]["threads"] == result["threads"]
    assert result["warnings"] == ["context warning"]


@pytest.mark.asyncio
async def test_generate_returns_empty_on_parse_failure() -> None:
    """parse 返回 None 时返回空结果警告。"""
    ctx = PlotStructureContext(
        markdown="ctx",
        entity_name_to_id={},
        character_name_to_id={},
    )

    builder = mock.MagicMock()
    builder.build = mock.AsyncMock(return_value=ctx)
    parser = mock.MagicMock()
    parser.parse = mock.AsyncMock(return_value=None)
    persister = mock.MagicMock()
    persister.persist = mock.AsyncMock()

    generator = PlotStructureGenerator(
        context_builder=builder,
        llm_client=mock.AsyncMock(),
        persister=persister,
    )

    with mock.patch("modules.outline.generator.PlotStructureParser", return_value=parser):
        result = await generator.generate(
            db=mock.AsyncMock(),
            novel_id="12345678-1234-5678-1234-567812345678",
            start_chapter=1,
            end_chapter=3,
        )

    assert result["total_threads"] == 0
    assert result["warnings"] == ["LLM 多次返回空结果，请重试"]
    persister.persist.assert_not_awaited()


def test_apply_preview_rejects_blank_persisted_asset_names() -> None:
    with pytest.raises(ValueError, match="require non-empty name"):
        PlotStructureGenerator._parse_preview_structure(
            {"threads": [{"name": "  ", "thread_type": "main"}]}
        )
