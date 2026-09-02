"""Stable interaction seams used by the application composition root."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from modules.interaction.repositories import InteractionRepository
from modules.interaction.services import InteractionService
from shared.utils import parse_uuid


async def reconcile_interaction_task_owners(db: AsyncSession) -> int:
    """Converge persisted story attempts after queue-level stale recovery."""

    return await InteractionService().reconcile_task_owners(db)


async def count_source_project_references(
    db: AsyncSession,
    source_novel_id: str,
) -> int:
    """Count journeys that keep an author source project undeletable."""
    return await InteractionRepository().source_reference_count(
        db,
        source_novel_id=parse_uuid(source_novel_id, "source_novel_id"),
    )
