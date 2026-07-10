"""RevealPlan Repository"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.outline.models import RevealPlan
from modules.outline.repositories import StructurePlanRepository


class RevealPlanRepository(StructurePlanRepository[RevealPlan]):
    model_class = RevealPlan
    order_by = (RevealPlan.created_at,)

    async def get_for_target(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        *,
        target_type: str,
        target_id: uuid.UUID,
    ) -> list[RevealPlan]:
        stmt = (
            select(RevealPlan)
            .where(
                RevealPlan.novel_id == novel_id,
                RevealPlan.target_id == target_id,
                RevealPlan.status != "deprecated",
            )
            .order_by(RevealPlan.created_at, RevealPlan.id)
        )
        return list((await db.execute(stmt)).scalars().all())
