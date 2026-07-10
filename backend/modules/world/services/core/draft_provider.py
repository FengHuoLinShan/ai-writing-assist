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
        _index_chapter_with_report = _container_get("rag.index_chapter")
        _list_latest_drafts = _container_get("writing.list_latest_drafts_for_chapters")

        chapter_indices = list(range(start_chapter, end_chapter + 1))
        drafts = await _list_latest_drafts(db, novel_id, chapter_indices)
        content_drafts = [draft for draft in drafts if draft and draft.content]
        warnings_by_chapter: dict[int, list[str]] = {}
        for draft in content_drafts:
            report = await _index_chapter_with_report(db, novel_id, draft.chapter_index)
            warnings_by_chapter[draft.chapter_index] = report.warnings

        chapters: list[dict[str, Any]] = []
        for draft in content_drafts:
            idx = draft.chapter_index
            chapters.append(
                {
                    "chapter_index": idx,
                    "title": draft.title or f"第{idx}章",
                    # RAG is a derived candidate index. Extraction always consumes
                    # the authoritative writing draft text, never cached chunk text.
                    "content": draft.content,
                    "rag_warnings": warnings_by_chapter.get(idx, []),
                }
            )
        return chapters
