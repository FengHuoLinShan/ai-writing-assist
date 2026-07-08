"""Outline Structure Dedup Facade — smart-dedup seam."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession


async def suggest_structure_dedup(
    db: AsyncSession,
    novel_id: str,
    *,
    asset_types: list[str] | None = None,
    limit: int = 1000,
    max_suggestions: int = 80,
    progress_callback: Any | None = None,
) -> dict[str, Any]:
    """Generate outline-owned duplicate suggestions without writing assets."""
    from modules.outline.structure_dedup import OutlineStructureDedupService

    return await OutlineStructureDedupService().suggest(
        db,
        novel_id=novel_id,
        asset_types=asset_types,
        limit=limit,
        max_suggestions=max_suggestions,
        progress_callback=progress_callback,
    )


async def apply_structure_dedup(
    db: AsyncSession,
    novel_id: str,
    *,
    confirmed: bool,
    suggestions: list[dict[str, Any]],
) -> dict[str, Any]:
    """Apply user-confirmed outline duplicate suggestions."""
    from modules.outline.structure_dedup import OutlineStructureDedupService

    return await OutlineStructureDedupService().apply(
        db,
        novel_id=novel_id,
        confirmed=confirmed,
        suggestions=suggestions,
    )


__all__ = [
    "apply_structure_dedup",
    "suggest_structure_dedup",
]
