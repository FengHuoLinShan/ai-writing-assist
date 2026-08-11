"""Stable World attention projection for cross-module workspace consumers."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from modules.world.contracts import WorldAttentionSummaryContract
from modules.world.services.attention_summary_service import (
    WorldAttentionSummaryService,
)

_service = WorldAttentionSummaryService()


async def get_author_attention_summary(
    db: AsyncSession,
    novel_id: str,
) -> WorldAttentionSummaryContract:
    """Return review counts in author-facing categories for one novel."""
    return await _service.get_summary(db, novel_id)
