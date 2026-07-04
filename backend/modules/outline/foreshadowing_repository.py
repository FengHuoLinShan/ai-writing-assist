"""ForeshadowingPlan Repository"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.outline.models import ForeshadowingPlan
from modules.outline.repositories import StructurePlanRepository


class ForeshadowingPlanRepository(StructurePlanRepository[ForeshadowingPlan]):
    model_class = ForeshadowingPlan
    order_by = (ForeshadowingPlan.planned_seed_chapter,)

    async def count_by_novel_and_range(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        start_chapter: int,
        end_chapter: int,
    ) -> int:
        stmt = select(func.count(ForeshadowingPlan.id)).where(
            ForeshadowingPlan.novel_id == novel_id,
            ForeshadowingPlan.planned_seed_chapter >= start_chapter,
            ForeshadowingPlan.planned_seed_chapter <= end_chapter,
        )
        result = await db.execute(stmt)
        return result.scalar() or 0
