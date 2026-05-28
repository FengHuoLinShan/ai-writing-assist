"""DraftProvider — 反转 world→writing 依赖

EntityExtractionService 通过此协议获取正文草稿，不直接依赖 writing 模块。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession


class DraftProvider(ABC):
    """正文草稿提供者协议"""

    @abstractmethod
    async def load_chapters(
        self,
        db: AsyncSession,
        novel_id: str,
        start_chapter: int,
        end_chapter: int,
    ) -> list[dict[str, Any]]:
        """加载指定范围的章节正文"""
        ...


class WritingDraftProvider(DraftProvider):
    """从 writing 模块加载正文草稿"""

    async def load_chapters(
        self,
        db: AsyncSession,
        novel_id: str,
        start_chapter: int,
        end_chapter: int,
    ) -> list[dict[str, Any]]:
        from modules.rag.facade import (
            get_ordered_chapter_chunks,
            index_chapter_with_report,
        )
        from modules.writing.facade import get_latest_draft_for_chapter

        chapters: list[dict[str, Any]] = []
        for idx in range(start_chapter, end_chapter + 1):
            draft = await get_latest_draft_for_chapter(db, novel_id, idx)
            if draft and draft.content:
                report = await index_chapter_with_report(db, novel_id, idx)
                rag_chunks = await get_ordered_chapter_chunks(db, novel_id, idx)
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
