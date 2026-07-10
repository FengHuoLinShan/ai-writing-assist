"""Outline Deep Import Repair Facade — repair and cleanup seam."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession


async def deprecate_deep_import_scenes_by_workflow(
    db: AsyncSession,
    novel_id: str,
    workflow_id: str,
) -> int:
    """Soft-deprecate auto-ingested Scenes created by one deep import workflow."""
    from modules.outline.services import SceneService

    return await SceneService().deprecate_deep_import_scenes_by_workflow(
        db,
        novel_id,
        workflow_id,
    )


async def deprecate_deep_import_structure_assets_by_workflow(
    db: AsyncSession,
    novel_id: str,
    workflow_id: str,
) -> int:
    """Soft-deprecate outline structure assets from one deep import workflow."""
    from modules.outline.services import OutlineStructureCleanupService

    service = OutlineStructureCleanupService()
    return await service.deprecate_deep_import_structure_assets_by_workflow(
        db,
        novel_id,
        workflow_id,
    )


async def reindex_scenes_for_deep_import_repair(
    db: AsyncSession,
    novel_id: str,
) -> int:
    """Reorder Scenes by chapter membership for deterministic deep-import display."""
    from modules.outline.deep_import_repair_service import (
        OutlineDeepImportRepairService,
    )

    return await OutlineDeepImportRepairService().reindex_scenes(db, novel_id)


async def get_deep_import_structure_counts(
    db: AsyncSession,
    novel_id: str,
) -> dict[str, int]:
    """Count outline-owned structure assets for deep-import display repair."""
    from modules.outline.deep_import_repair_service import (
        OutlineDeepImportRepairService,
    )

    return await OutlineDeepImportRepairService().structure_counts(db, novel_id)


async def get_deep_import_structure_payload(
    db: AsyncSession,
    novel_id: str,
) -> dict[str, Any]:
    """Return the structure-analysis payload shape consumed by import fallback logic."""
    from modules.outline.deep_import_repair_service import (
        OutlineDeepImportRepairService,
    )

    return await OutlineDeepImportRepairService().structure_payload(db, novel_id)


async def ensure_deep_import_structure_outputs(
    db: AsyncSession,
    novel_id: str,
    start_chapter: int,
    end_chapter: int,
    result: dict[str, Any],
    *,
    workflow_id: str | None,
    service_resolver: Any | None = None,
    small_sample_target_count: int | None = None,
) -> dict[str, Any]:
    from modules.outline.deep_import_repair_service import (
        SMALL_SAMPLE_STRUCTURE_TARGET_COUNT,
        OutlineDeepImportRepairService,
    )

    return await OutlineDeepImportRepairService(
        service_resolver=service_resolver,
    ).ensure_minimum_structure_outputs(
        db,
        novel_id,
        start_chapter,
        end_chapter,
        result,
        workflow_id=workflow_id,
        small_sample_target_count=(
            small_sample_target_count or SMALL_SAMPLE_STRUCTURE_TARGET_COUNT
        ),
    )


def get_deep_import_structure_category_targets(
    chapter_count: int,
    *,
    small_sample_target_count: int,
) -> dict[str, int]:
    from modules.outline.deep_import_repair_service import (
        minimum_structure_category_targets,
    )

    return minimum_structure_category_targets(
        chapter_count,
        small_sample_target_count=small_sample_target_count,
    )


def get_deep_import_structure_category_counts(
    result: dict[str, Any],
) -> dict[str, int]:
    from modules.outline.deep_import_repair_service import structure_category_counts

    return structure_category_counts(result)


def get_deep_import_structure_output_count(result: dict[str, Any]) -> int:
    from modules.outline.deep_import_repair_service import structure_output_count

    return structure_output_count(result)


def get_deep_import_fallback_thread_type(index: int) -> str:
    from modules.outline.deep_import_repair_service import fallback_thread_type

    return fallback_thread_type(index)


async def ensure_deep_import_structure_minimums(
    db: AsyncSession,
    novel_id: str,
    start_chapter: int,
    end_chapter: int,
    workflow_id: str | None,
) -> dict[str, int]:
    """Ensure outline structure minimums for repaired deep-import runs."""
    from modules.outline.deep_import_repair_service import (
        OutlineDeepImportRepairService,
    )

    return await OutlineDeepImportRepairService().ensure_structure_minimum_counts(
        db,
        novel_id,
        start_chapter,
        end_chapter,
        workflow_id=workflow_id,
    )


async def select_deep_import_fallback_reveal_target(
    db: AsyncSession,
    novel_id: str,
    *,
    list_entities: Any | None = None,
) -> dict[str, Any] | None:
    """Select a fallback reveal target without exposing outline internals."""
    from modules.outline.deep_import_repair_service import OutlineDeepImportRepairService

    return await OutlineDeepImportRepairService(
        list_entities=list_entities,
    ).select_fallback_reveal_target(db, novel_id)


__all__ = [
    "deprecate_deep_import_scenes_by_workflow",
    "deprecate_deep_import_structure_assets_by_workflow",
    "ensure_deep_import_structure_minimums",
    "ensure_deep_import_structure_outputs",
    "get_deep_import_fallback_thread_type",
    "get_deep_import_structure_category_counts",
    "get_deep_import_structure_category_targets",
    "get_deep_import_structure_counts",
    "get_deep_import_structure_output_count",
    "get_deep_import_structure_payload",
    "reindex_scenes_for_deep_import_repair",
    "select_deep_import_fallback_reveal_target",
]
