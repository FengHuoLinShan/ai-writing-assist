"""ForeshadowingPlan Repository"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.story.outline_state.models import ForeshadowingPlan
from modules.story.outline_state.repositories import StructurePlanRepository


class ForeshadowingPlanRepository(StructurePlanRepository[ForeshadowingPlan]):
    model_class = ForeshadowingPlan
    order_by = (ForeshadowingPlan.planned_seed_chapter,)

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
        related_thread_id: uuid.UUID | None = None,
        unassigned: bool | None = None,
    ) -> tuple[list[ForeshadowingPlan], int]:
        from modules.story.outline_state.models import PlotThread
        from modules.story.outline_state.repositories import apply_structure_asset_filters

        conditions = [ForeshadowingPlan.novel_id == novel_id]
        apply_structure_asset_filters(
            conditions,
            ForeshadowingPlan,
            status=status,
            source=source,
            workflow_id=workflow_id,
            needs_review=needs_review,
        )
        plans = list(
            (
                await db.execute(
                    select(ForeshadowingPlan)
                    .where(*conditions)
                    .order_by(
                        ForeshadowingPlan.planned_seed_chapter,
                        ForeshadowingPlan.id,
                    )
                )
            ).scalars().all()
        )
        active_thread_ids = {
            str(value)
            for value in (
                await db.scalars(
                    select(PlotThread.id).where(
                        PlotThread.novel_id == novel_id,
                        PlotThread.status != "deprecated",
                    )
                )
            ).all()
        }
        requested = str(related_thread_id) if related_thread_id else None

        def included(plan: ForeshadowingPlan) -> bool:
            related = {str(value) for value in (plan.related_thread_ids or [])}
            valid = related & active_thread_ids
            if requested is not None and requested not in valid:
                return False
            if unassigned is True and valid:
                return False
            if unassigned is False and not valid:
                return False
            return True

        filtered = [plan for plan in plans if included(plan)]
        return filtered[skip : skip + limit], len(filtered)

    async def get_active_by_status(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        *,
        status: str,
    ) -> list[ForeshadowingPlan]:
        stmt = (
            select(ForeshadowingPlan)
            .where(
                ForeshadowingPlan.novel_id == novel_id,
                ForeshadowingPlan.status == status,
            )
            .order_by(ForeshadowingPlan.planned_seed_chapter)
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

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
