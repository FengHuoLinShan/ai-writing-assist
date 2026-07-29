"""Stable interaction seams used by the application composition root."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from modules.interaction.services import InteractionService


async def reconcile_interaction_task_owners(db: AsyncSession) -> int:
    """Converge persisted story attempts after queue-level stale recovery."""

    return await InteractionService().reconcile_task_owners(db)
