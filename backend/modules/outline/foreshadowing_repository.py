"""ForeshadowingPlan Repository"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from modules.outline.models import ForeshadowingPlan
from modules.outline.repositories import apply_structure_asset_filters


class ForeshadowingPlanRepository:
    async def create(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        data: dict,
    ) -> ForeshadowingPlan:
        plan = ForeshadowingPlan(novel_id=novel_id, **data)
        db.add(plan)
        await db.flush()
        return plan

    async def create_batch(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        items: list[dict],
    ) -> list[ForeshadowingPlan]:
        plans = [ForeshadowingPlan(novel_id=novel_id, **d) for d in items]
        db.add_all(plans)
        await db.flush()
        return plans

    async def get(self, db: AsyncSession, plan_id: uuid.UUID) -> ForeshadowingPlan | None:
        stmt = select(ForeshadowingPlan).where(ForeshadowingPlan.id == plan_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_novel(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        *,
        skip: int = 0,
        limit: int = 50,
        status: str | None = None,
        source: str | None = None,
        workflow_id: str | None = None,
        needs_review: bool | None = None,
    ) -> tuple[list[ForeshadowingPlan], int]:
        conditions = [ForeshadowingPlan.novel_id == novel_id]
        apply_structure_asset_filters(
            conditions,
            ForeshadowingPlan,
            status=status,
            source=source,
            workflow_id=workflow_id,
            needs_review=needs_review,
        )
        count_stmt = select(func.count(ForeshadowingPlan.id)).where(*conditions)
        total = (await db.execute(count_stmt)).scalar() or 0
        stmt = (
            select(ForeshadowingPlan)
            .where(*conditions)
            .offset(skip)
            .limit(limit)
            .order_by(ForeshadowingPlan.planned_seed_chapter)
        )
        result = await db.execute(stmt)
        items: Sequence[ForeshadowingPlan] = result.scalars().all()
        return list(items), total

    async def update(
        self,
        db: AsyncSession,
        plan_id: uuid.UUID,
        data: dict,
    ) -> ForeshadowingPlan | None:
        plan = await self.get(db, plan_id)
        if plan is None:
            return None
        stmt = (
            update(ForeshadowingPlan)
            .where(ForeshadowingPlan.id == plan_id)
            .values(**data)
        )
        await db.execute(stmt)
        await db.flush()
        return await self.get(db, plan_id)

    async def delete(self, db: AsyncSession, plan_id: uuid.UUID) -> bool:
        stmt = delete(ForeshadowingPlan).where(ForeshadowingPlan.id == plan_id)
        result = await db.execute(stmt)
        await db.flush()
        return result.rowcount > 0

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
