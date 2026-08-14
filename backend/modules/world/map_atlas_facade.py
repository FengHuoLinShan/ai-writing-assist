"""Stable AI map-atlas seams used by other modules."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.tasks.facade import enqueue_task
from modules.world.map_atlas_storage import project_object_prefix
from modules.world.world_object_images import project_image_prefix


async def enqueue_map_atlas_project_cleanup(
    db: AsyncSession,
    novel_ids: list[str],
) -> None:
    """Create global cleanup tasks that survive project/task FK deletion."""
    for novel_id in dict.fromkeys(novel_ids):
        enqueue_task(
            db,
            "map_atlas_storage_cleanup",
            meta={
                "cleanup_kind": "project_prefix",
                "object_prefix": project_object_prefix(novel_id),
                "delete_batch": str(uuid.uuid4()),
            },
            novel_id=None,
        )
        enqueue_task(
            db,
            "world_object_image_cleanup",
            meta={
                "cleanup_kind": "project_prefix",
                "object_prefix": project_image_prefix(novel_id),
                "delete_batch": str(uuid.uuid4()),
            },
            novel_id=None,
        )


async def reconcile_map_atlas_task_owners(db: AsyncSession) -> int:
    """Converge atlas-owned checkpoints after queue recovery."""
    from modules.world.map_atlas_workflow import (
        reconcile_map_atlas_task_owners as reconcile,
    )

    return await reconcile(db)
