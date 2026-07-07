"""Shared chapter range loading helpers for imports internals."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession


async def load_chapter_range(
    db: AsyncSession,
    novel_id: str,
    start_chapter: int,
    end_chapter: int,
    *,
    include_missing: bool = False,
) -> list[dict[str, Any]]:
    """Load latest writing drafts for a chapter range in one batch."""
    from modules.writing.facade import list_latest_drafts_for_chapters

    chapter_indices = list(range(start_chapter, end_chapter + 1))
    drafts = await list_latest_drafts_for_chapters(db, novel_id, chapter_indices)
    draft_by_chapter = {int(draft.chapter_index): draft for draft in drafts}
    chapters: list[dict[str, Any]] = []

    for chapter_index in chapter_indices:
        draft = draft_by_chapter.get(chapter_index)
        if include_missing:
            chapters.append(
                {
                    "chapter_index": chapter_index,
                    "title": getattr(draft, "title", None) or f"第{chapter_index}章",
                    "content": getattr(draft, "content", "") or "",
                }
            )
            continue

        if draft and draft.content:
            chapters.append(
                {
                    "chapter_index": chapter_index,
                    "title": draft.title or f"第{chapter_index}章",
                    "content": draft.content,
                }
            )

    return chapters


def build_chapters_text(chapters: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for chapter in chapters:
        chapter_index = chapter["chapter_index"]
        title = chapter.get("title") or f"第{chapter_index}章"
        parts.append(
            f"## 第{chapter_index}章 {title}\n\n{chapter.get('content', '')}"
        )
    return "\n\n".join(parts)
