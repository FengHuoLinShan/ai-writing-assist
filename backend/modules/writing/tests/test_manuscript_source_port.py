"""Writing 正文稿只读 SPI 适配器（AO-5 / ADR-0031）。

evidence 编译经组合根注册的 ``writing.manuscript_source`` port 消费稿源
区间/清单/字面扫描，不再顶层 import writing facade。本文件锁定 adapter
的委托行为与空态语义。
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from modules.evidence.source_ref_contracts import (
    ManuscriptScanCursor,
    SourceRangeRefContract,
)
from modules.writing.manuscript_source_port import ManuscriptSourcePort


def _ref() -> SourceRangeRefContract:
    return SourceRangeRefContract(
        draft_id="draft-1",
        chapter_index=2,
        version_number=5,
        content_mode="working",
        start_offset=10,
        end_offset=40,
        source_hash="a" * 64,
        range_hash="b" * 64,
    )


@pytest.mark.asyncio
async def test_manuscript_port_delegates_read_only_calls(monkeypatch) -> None:
    db = SimpleNamespace()
    ref = _ref()
    read = AsyncMock(
        return_value=SimpleNamespace(text="正文", highlight_start=0, highlight_end=2)
    )
    build = AsyncMock(return_value=ref)
    manifest = AsyncMock(return_value=[{"draft_id": "draft-1"}])
    scan = AsyncMock(
        return_value=SimpleNamespace(hits=[], cursor=None, scanned_chapters=[2])
    )
    monkeypatch.setattr("modules.writing.facade.read_manuscript_range", read)
    monkeypatch.setattr("modules.writing.facade.build_manuscript_range_ref", build)
    monkeypatch.setattr(
        "modules.writing.facade.get_manuscript_source_manifest", manifest
    )
    monkeypatch.setattr("modules.writing.facade.scan_manuscript_terms", scan)
    port = ManuscriptSourcePort()

    ranged = await port.read_range(db, "novel-1", ref, before=0, after=0)
    built = await port.build_range_ref(
        db,
        "novel-1",
        draft_id="draft-1",
        start_offset=10,
        end_offset=40,
        content_mode="working",
    )
    sources = await port.source_manifest(
        db, "novel-1", content_mode="working", chapter_from=1, chapter_to=3
    )
    page = await port.scan_terms(
        db,
        "novel-1",
        ["词条"],
        cursor=ManuscriptScanCursor(2, 0),
        content_mode="working",
    )

    assert ranged.text == "正文"
    assert built is ref
    assert sources == [{"draft_id": "draft-1"}]
    assert page.scanned_chapters == [2]
    read.assert_awaited_once_with(
        db, "novel-1", ref, before=0, after=0, max_end_offset=None
    )
    build.assert_awaited_once_with(
        db,
        "novel-1",
        draft_id="draft-1",
        start_offset=10,
        end_offset=40,
        content_mode="working",
    )
    manifest.assert_awaited_once_with(
        db, "novel-1", content_mode="working", chapter_from=1, chapter_to=3
    )
    scan.assert_awaited_once_with(
        db, "novel-1", ["词条"], cursor=ManuscriptScanCursor(2, 0), content_mode="working"
    )


@pytest.mark.asyncio
async def test_manuscript_port_empty_states(monkeypatch) -> None:
    monkeypatch.setattr(
        "modules.writing.facade.read_manuscript_range",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        "modules.writing.facade.get_manuscript_source_manifest",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        "modules.writing.facade.scan_manuscript_terms",
        AsyncMock(
            return_value=SimpleNamespace(
                hits=[], cursor=None, scanned_chapters=[], total_chapters=0
            )
        ),
    )
    port = ManuscriptSourcePort()
    db = SimpleNamespace()

    assert await port.read_range(db, "novel-1", _ref()) is None
    assert await port.source_manifest(db, "novel-1") == []
    page = await port.scan_terms(db, "novel-1", [])
    assert page.hits == [] and page.cursor is None
