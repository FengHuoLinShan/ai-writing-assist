from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from modules.world.services.draft_provider import WritingDraftProvider


@pytest.mark.asyncio
async def test_writing_draft_provider_loads_latest_drafts_in_one_batch() -> None:
    from app.main import _register_container_services
    from core.container import register, reset

    calls: list[Any] = []

    async def _list_latest_drafts(db, novel_id: str, chapter_indices: list[int]):
        calls.append(("list_latest", novel_id, chapter_indices))
        return [
            SimpleNamespace(chapter_index=1, title="第一章", content="正文一"),
            SimpleNamespace(chapter_index=3, title="第三章", content="正文三"),
        ]

    async def _get_latest_draft(*args, **kwargs):
        calls.append(("get_latest", args, kwargs))
        raise AssertionError("chapter range loading should not query drafts one by one")

    async def _index_chapter(db, novel_id: str, chapter_index: int):
        calls.append(("index", chapter_index))
        return SimpleNamespace(warnings=[f"w{chapter_index}"])

    async def _get_chunks(
        db,
        novel_id: str,
        start_chapter: int,
        end_chapter: int | None = None,
    ):
        calls.append(("chunks", start_chapter, end_chapter))
        return [
            SimpleNamespace(chapter_index=1, chunk_index=0, text="切片一"),
            SimpleNamespace(chapter_index=2, chunk_index=0, text="不应进入结果"),
            SimpleNamespace(chapter_index=3, chunk_index=0, text="切片三"),
        ]

    reset()
    register("writing.list_latest_drafts_for_chapters", _list_latest_drafts)
    register("writing.get_latest_draft_for_chapter", _get_latest_draft)
    register("rag.index_chapter", _index_chapter)
    register("rag.get_ordered_chapter_chunks", _get_chunks)
    try:
        chapters = await WritingDraftProvider().load_chapters(
            None,  # type: ignore[arg-type]
            "novel-1",
            1,
            3,
        )
    finally:
        reset()
        _register_container_services()

    assert calls == [
        ("list_latest", "novel-1", [1, 2, 3]),
        ("index", 1),
        ("index", 3),
        ("chunks", 1, 3),
    ]
    assert chapters == [
        {
            "chapter_index": 1,
            "title": "第一章",
            "content": "[RAG chunk 0] 切片一",
            "rag_warnings": ["w1"],
        },
        {
            "chapter_index": 3,
            "title": "第三章",
            "content": "[RAG chunk 0] 切片三",
            "rag_warnings": ["w3"],
        },
    ]
