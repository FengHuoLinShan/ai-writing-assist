"""Outline Foreshadowing Facade — foreshadowing read seam."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession


async def get_active_foreshadowing(
    db: AsyncSession,
    novel_id: str,
    *,
    status: str = "seeded",
) -> list[dict[str, Any]]:
    """获取活跃伏笔计划列表，返回 dict 列表。"""
    from modules.story.outline_state.services import ForeshadowingPlanService

    return await ForeshadowingPlanService().get_active_dicts(
        db,
        novel_id,
        status=status,
    )


__all__ = [
    "get_active_foreshadowing",
]
