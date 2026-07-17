"""RevealPlan Repository"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.outline.models import RevealPlan
from modules.outline.repositories import StructurePlanRepository


class RevealPlanRepository(StructurePlanRepository[RevealPlan]):
    model_class = RevealPlan
    order_by = (RevealPlan.created_at,)

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
    ) -> tuple[list[RevealPlan], int]:
        from modules.outline.models import PlotThread
        from modules.outline.repositories import apply_structure_asset_filters

        conditions = [RevealPlan.novel_id == novel_id]
        apply_structure_asset_filters(
            conditions,
            RevealPlan,
            status=status,
            source=source,
            workflow_id=workflow_id,
            needs_review=needs_review,
        )
        plans: Sequence[RevealPlan] = (
            await db.execute(
                select(RevealPlan)
                .where(*conditions)
                .order_by(RevealPlan.created_at, RevealPlan.id)
            )
        ).scalars().all()
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

        def included(plan: RevealPlan) -> bool:
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
