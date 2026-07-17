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
    exclusions: list[dict[str, Any]] | None = None,
    llm_client: Any | None = None,
) -> dict[str, Any]:
    """Generate outline-owned duplicate suggestions without writing assets."""
    from modules.outline.structure_dedup import OutlineStructureDedupService

    return await OutlineStructureDedupService(llm_client=llm_client).suggest(
        db,
        novel_id=novel_id,
        asset_types=asset_types,
        limit=limit,
        max_suggestions=max_suggestions,
        progress_callback=progress_callback,
        exclusions=exclusions,
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


async def apply_structure_dedup_group(
    db: AsyncSession,
    novel_id: str,
    *,
    asset_type: str,
    primary_asset_id: str,
    operations: list[dict[str, Any]],
    validate_only: bool = False,
    execution_fingerprints_prevalidated: bool = False,
) -> list[dict[str, Any]]:
    """Strict, caller-transactional outline dedup group apply."""
    from modules.outline.structure_dedup import OutlineStructureDedupService

    return await OutlineStructureDedupService().apply_group(
        db,
        novel_id=novel_id,
        asset_type=asset_type,
        primary_asset_id=primary_asset_id,
        operations=operations,
        validate_only=validate_only,
        execution_fingerprints_prevalidated=execution_fingerprints_prevalidated,
    )


__all__ = [
    "apply_structure_dedup",
    "apply_structure_dedup_group",
    "suggest_structure_dedup",
]
