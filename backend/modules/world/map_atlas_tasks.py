"""Task handlers for atlas generation and deletion-safe object cleanup."""

from __future__ import annotations

from infrastructure.tasks.registry import task_handler
from modules.world.map_atlas_storage import (
    MapAtlasStorage,
    delete_unreferenced_page_object,
    require_project_object_prefix,
)
from modules.world.map_atlas_workflow import run_map_atlas_workflow
from modules.world.world_object_images import (
    WorldObjectImageStorage,
    delete_unreferenced_image_version,
    require_project_image_prefix,
)


@task_handler(
    "map_atlas_generate",
    recovery_policy="manual_resume",
    max_attempts=20,
)
async def handle_map_atlas_generate(db, task):
    return await run_map_atlas_workflow(db, task)


@task_handler(
    "map_atlas_storage_cleanup",
    recovery_policy="auto_requeue",
    # Effectively persistent while preserving the generic queue's bounded contract.
    max_attempts=2_147_483_647,
    owner_scope="global",
)
async def handle_map_atlas_storage_cleanup(db, task):
    """Idempotently remove one exact object or one deleted-project prefix."""
    meta = dict(task.meta or {})
    cleanup_kind = str(meta.get("cleanup_kind") or "")
    storage = MapAtlasStorage()
    if cleanup_kind == "object":
        deleted = int(
            await delete_unreferenced_page_object(
                db,
                storage,
                str(meta.get("object_key") or ""),
            )
        )
    elif cleanup_kind == "project_prefix":
        prefix = require_project_object_prefix(str(meta.get("object_prefix") or ""))
        deleted = await storage.delete_prefix(prefix)
    else:
        raise ValueError("invalid map atlas cleanup kind")
    return {
        "cleanup_kind": cleanup_kind,
        "deleted_objects": deleted,
        "delete_batch": meta.get("delete_batch"),
    }


@task_handler(
    "world_object_image_cleanup",
    recovery_policy="auto_requeue",
    max_attempts=2_147_483_647,
    owner_scope="global",
)
async def handle_world_object_image_cleanup(db, task):
    """Idempotently clean a replaced image version or a deleted-project prefix."""
    meta = dict(task.meta or {})
    cleanup_kind = str(meta.get("cleanup_kind") or "")
    storage = WorldObjectImageStorage()
    if cleanup_kind == "image_version":
        deleted = await delete_unreferenced_image_version(
            db,
            storage,
            novel_id=str(meta.get("project_id") or ""),
            entity_id=str(meta.get("entity_id") or ""),
            image_version=str(meta.get("image_version") or ""),
        )
    elif cleanup_kind == "project_prefix":
        deleted = await storage.delete_prefix(
            require_project_image_prefix(str(meta.get("object_prefix") or ""))
        )
    else:
        raise ValueError("invalid world object image cleanup kind")
    return {"cleanup_kind": cleanup_kind, "deleted_objects": int(deleted)}
