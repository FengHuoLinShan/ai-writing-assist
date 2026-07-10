"""Stable reveal-policy facade."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from modules.outline.contracts import ReaderRevealDecisionContract
from modules.outline.reveal_visibility import ReaderRevealPolicyService

_service = ReaderRevealPolicyService()


async def get_reader_reveal_decision(
    db: AsyncSession,
    *,
    novel_id: str,
    target_type: str,
    target_id: str,
    cutoff_chapter: int,
) -> ReaderRevealDecisionContract:
    return await _service.evaluate(
        db,
        novel_id=novel_id,
        target_type=target_type,
        target_id=target_id,
        cutoff_chapter=cutoff_chapter,
    )
