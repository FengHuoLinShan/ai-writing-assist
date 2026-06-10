"""RevealPlan Repository"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from modules.outline.models import RevealPlan


class RevealPlanRepository:
    async def create(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        data: dict,
    ) -> RevealPlan:
        plan = RevealPlan(novel_id=novel_id, **data)
        db.add(plan)
        await db.flush()
        return plan

    async def create_batch(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        items: list[dict],
    ) -> list[RevealPlan]:
        plans = [RevealPlan(novel_id=novel_id, **d) for d in items]
        db.add_all(plans)
        await db.flush()
        return plans

    async def get(self, db: AsyncSession, plan_id: uuid.UUID) -> RevealPlan | None:
        stmt = select(RevealPlan).where(RevealPlan.id == plan_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_novel(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        *,
        skip: int = 0,
        limit: int = 50,
    ) -> tuple[list[RevealPlan], int]:
        conditions = [RevealPlan.novel_id == novel_id]
        count_stmt = select(func.count(RevealPlan.id)).where(*conditions)
        total = (await db.execute(count_stmt)).scalar() or 0
        stmt = (
            select(RevealPlan)
            .where(*conditions)
            .offset(skip)
            .limit(limit)
            .order_by(RevealPlan.created_at)
        )
        result = await db.execute(stmt)
        items: Sequence[RevealPlan] = result.scalars().all()
        return list(items), total

    async def update(
        self,
        db: AsyncSession,
        plan_id: uuid.UUID,
        data: dict,
    ) -> RevealPlan | None:
        plan = await self.get(db, plan_id)
        if plan is None:
            return None
        stmt = (
            update(RevealPlan)
            .where(RevealPlan.id == plan_id)
            .values(**data)
        )
        await db.execute(stmt)
        await db.flush()
        return await self.get(db, plan_id)

    async def delete(self, db: AsyncSession, plan_id: uuid.UUID) -> bool:
        stmt = delete(RevealPlan).where(RevealPlan.id == plan_id)
        result = await db.execute(stmt)
        await db.flush()
        return result.rowcount > 0
