"""DraftProvider — 反转 world→writing 依赖

EntityExtractionService 通过此协议获取正文草稿，不直接依赖 writing 模块。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from core.container import get as _container_get
from shared.protocols import DraftProvider


class WritingDraftProvider(DraftProvider):

    async def load_chapters(
        self,
        db: AsyncSession,
        novel_id: str,
        start_chapter: int,
        end_chapter: int,
    ) -> list[dict[str, Any]]:
        _get_ordered_chapter_chunks = _container_get("rag.get_ordered_chapter_chunks")
        _index_chapter_with_report = _container_get("rag.index_chapter")
        _get_latest_draft = _container_get("writing.get_latest_draft_for_chapter")

        chapters: list[dict[str, Any]] = []
        for idx in range(start_chapter, end_chapter + 1):
            draft = await _get_latest_draft(db, novel_id, idx)
            if draft and draft.content:
                report = await _index_chapter_with_report(db, novel_id, idx)
                rag_chunks = await _get_ordered_chapter_chunks(db, novel_id, idx)
                content = "\n\n".join(
                    f"[RAG chunk {chunk.chunk_index}] {chunk.text}"
                    for chunk in rag_chunks
                ) or draft.content
                chapters.append({
                    "chapter_index": idx,
                    "title": draft.title or f"第{idx}章",
                    "content": content,
                    "rag_warnings": report.warnings,
                })
        return chapters
