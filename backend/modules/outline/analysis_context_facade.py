"""Stable read-only seam for manual outline-analysis context."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from modules.outline.contracts import OutlineAnalysisContextContract


async def get_outline_analysis_context(
    db: AsyncSession,
    novel_id: str,
    *,
    start_chapter: int,
    end_chapter: int,
) -> OutlineAnalysisContextContract:
    """Return ordered active structure assets overlapping one chapter range."""
    from modules.outline.analysis_context import OutlineAnalysisContextService

    return await OutlineAnalysisContextService().get_range(
        db,
        novel_id,
        start_chapter=start_chapter,
        end_chapter=end_chapter,
    )


__all__ = ["get_outline_analysis_context"]
