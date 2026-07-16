"""World-side bridge for RAG's rebuildable entity activity projection."""

from __future__ import annotations

import logging
from inspect import isawaitable

from sqlalchemy.ext.asyncio import AsyncSession

from core.container import get as _container_get

logger = logging.getLogger(__name__)


async def request_entity_activity_reannotation(
    db: AsyncSession,
    novel_id: str,
) -> None:
    """Ask the registered RAG port to coalesce a lightweight refresh task."""
    if not isinstance(db, AsyncSession):
        logger.debug("skip entity activity reannotation without AsyncSession")
        return
    try:
        request = _container_get("rag.request_entity_activity_reannotation")
        if isawaitable(request):
            request = await request
    except KeyError:
        logger.info("rag entity activity reannotation port is not registered")
        return
    try:
        await request(db, novel_id)
    except Exception:
        logger.warning(
            "failed to request entity activity reannotation novel_id=%s",
            novel_id,
            exc_info=True,
        )
