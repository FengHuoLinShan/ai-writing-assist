"""Best-effort invalidation hook for canonical World Bible synopsis sources."""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def mark_synopsis_source_changed(
    db: AsyncSession,
    novel_id: str,
    *,
    source_type: str,
    source_id: str,
) -> None:
    """Mark derived synopsis state without making the source write fragile."""
    try:
        async with db.begin_nested():
            from modules.world.services.worldbuilding.worldbuilding_service import (
                WorldBibleSynopsisService,
            )

            await WorldBibleSynopsisService().mark_stale(db, novel_id)
    except Exception:
        logger.warning(
            "世界观简介标脏失败 source_type=%s source_id=%s novel_id=%s",
            source_type,
            source_id,
            novel_id,
            exc_info=True,
        )


__all__ = ["mark_synopsis_source_changed"]
