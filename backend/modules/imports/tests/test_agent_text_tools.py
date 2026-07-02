"""Tests for agent-facing novel text search/read tools."""

from __future__ import annotations

import pytest

from modules.imports.agent_text_tools import (
    NovelTextReadTool,
    NovelTextSearchTool,
)
from modules.rag.contracts import RagChunkContract, RagResultBundle
from modules.writing.contracts import WritingDraftContract


def _chunk(**overrides) -> RagChunkContract:
    data = {
        "id": "chunk-1",
        "novel_id": "novel-1",
        "source_type": "chapter_text",
        "chapter_index": 1,
        "chunk_index": 0,
        "start_offset": 2,
        "end_offset": 8,
        "text": "rag text",
        "score": 0.9,
    }
    data.update(overrides)
    return RagChunkContract(**data)


async def _draft(_db, _novel_id: str, chapter_index: int):
    drafts = {
        1: WritingDraftContract(
            novel_id="novel-1",
            chapter_index=1,
            content="aaLATESTbb needle cc",
        ),
        2: WritingDraftContract(
            novel_id="novel-1",
            chapter_index=2,
            content="chapter two content",
        ),
    }
    return drafts.get(chapter_index)


@pytest.mark.asyncio
async def test_search_uses_rag_retrieve_and_returns_anchor() -> None:
    async def retrieve(_db, _novel_id, _query, **_kwargs):
        return RagResultBundle(chunks=[_chunk()], total=1, query="needle")

    result = await NovelTextSearchTool(retrieve_fn=retrieve).search(
        None,
        "novel-1",
        "needle",
    )

    assert result.degraded is False
    assert len(result.items) == 1
    assert result.items[0].anchor.rag_chunk_id == "chunk-1"
    assert result.items[0].anchor.chapter_index == 1


@pytest.mark.asyncio
async def test_search_falls_back_to_keyword_scan_when_rag_has_no_index() -> None:
    async def retrieve(_db, _novel_id, _query, **_kwargs):
        return RagResultBundle(chunks=[], total=0, query="needle")

    async def index_status(_db, _novel_id):
        return {"total": 0, "embedding_failed_count": 0}

    async def list_indices(_db, _novel_id):
        return [1, 2]

    result = await NovelTextSearchTool(
        retrieve_fn=retrieve,
        get_index_status_fn=index_status,
        list_chapter_indices_fn=list_indices,
        get_draft_fn=_draft,
    ).search(None, "novel-1", "needle")

    assert result.degraded is True
    assert result.reason == "no_rag_index"
    assert len(result.items) == 1
    assert result.items[0].anchor.source_type == "writing_draft_keyword"
    assert "needle" in result.items[0].snippet


@pytest.mark.asyncio
async def test_search_records_embedding_failure_before_keyword_fallback() -> None:
    async def retrieve(_db, _novel_id, _query, **_kwargs):
        raise RuntimeError("embedding failed")

    async def list_indices(_db, _novel_id):
        return [1]

    result = await NovelTextSearchTool(
        retrieve_fn=retrieve,
        list_chapter_indices_fn=list_indices,
        get_draft_fn=_draft,
    ).search(None, "novel-1", "needle")

    assert result.degraded is True
    assert result.reason == "embedding_failed"
    assert result.items


@pytest.mark.asyncio
async def test_read_rag_chunk_uses_latest_writing_draft_offsets() -> None:
    async def get_chunk(_db, _novel_id, _chunk_id):
        return _chunk(start_offset=2, end_offset=8, text="old rag")

    result = await NovelTextReadTool(
        get_draft_fn=_draft,
        get_rag_chunk_fn=get_chunk,
    ).read(None, "novel-1", rag_chunk_id="chunk-1")

    assert result.content == "LATEST"
    assert result.degraded is False
    assert result.anchors[0].source_type == "writing_draft"


@pytest.mark.asyncio
async def test_read_stale_offset_falls_back_to_rag_chunk_text() -> None:
    async def get_chunk(_db, _novel_id, _chunk_id):
        return _chunk(start_offset=200, end_offset=220, text="old rag")

    result = await NovelTextReadTool(
        get_draft_fn=_draft,
        get_rag_chunk_fn=get_chunk,
    ).read(None, "novel-1", rag_chunk_id="chunk-1")

    assert result.content == "old rag"
    assert result.degraded is True
    assert result.reason == "stale_offset_fallback"


@pytest.mark.asyncio
async def test_read_anchor_errors_when_unbounded_chapter_exceeds_budget() -> None:
    async def long_draft(_db, _novel_id: str, _chapter_index: int):
        return WritingDraftContract(
            novel_id="novel-1",
            chapter_index=1,
            content="x" * 50,
        )

    result = await NovelTextReadTool(get_draft_fn=long_draft, max_chars=10).read(
        None,
        "novel-1",
        chapter_index=1,
    )

    assert result.error_kind == "context_overflow"
    assert result.reason == "read_scope_exceeds_budget"


@pytest.mark.asyncio
async def test_read_scene_uses_scene_chunks() -> None:
    async def scene(_db, _novel_id, _scene_id):
        return {
            "scene_chunks": [
                {"chapter_index": 1, "start_offset": 2, "end_offset": 8}
            ]
        }

    result = await NovelTextReadTool(
        get_draft_fn=_draft,
        get_scene_fn=scene,
    ).read(None, "novel-1", scene_id="scene-1")

    assert result.content == "LATEST"
    assert result.anchors[0].scene_id == "scene-1"
