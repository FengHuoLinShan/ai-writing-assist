"""Stable AI map-atlas seams used by other modules."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.tasks.facade import enqueue_task
from modules.world.map_atlas_storage import project_object_prefix
from modules.world.map_structure_service import (
    inspect_map_node as inspect_map_node,
)
from modules.world.map_structure_service import (
    list_adopted_map_continuity_facts as list_adopted_map_continuity_facts,
)
from modules.world.world_object_images import project_image_prefix


async def get_map_scene_context(db, novel_id, node_id, scene_id):
    from modules.world.map_scene_context import get_scene_context

    return await get_scene_context(db, novel_id, node_id, scene_id)


async def map_capabilities(db: AsyncSession, novel_id: str) -> dict:
    from modules.local_agent.facade import selected_executor
    from modules.project.contracts import ProjectImageConfigurationError
    from modules.project.facade import (
        build_project_image_execution_snapshot,
        get_project_context,
        require_active_project,
    )
    from modules.world.map_atlas_storage import storage_configuration_status

    await require_active_project(db, novel_id)
    upload = storage_configuration_status()
    image = dict(upload)
    if image["available"]:
        try:
            await build_project_image_execution_snapshot(db, novel_id)
        except ProjectImageConfigurationError:
            image.update(
                available=False,
                reason="请先在账户设置中连接图片模型。",
                destination="model_settings",
            )
    local_cli = {
        "available": False,
        "kind": None,
        "reason": "请先在项目设置中配对本机 CLI，并选择用于生成图片",
    }
    context = await get_project_context(db, novel_id)
    if context is not None and context.owner_id is not None:
        executor = await selected_executor(db, novel_id, context.owner_id)
        if executor.kind != "gateway":
            local_cli = {"available": True, "kind": executor.kind, "reason": None}
    return {
        "structure": {"available": True, "reason": None},
        "upload": upload,
        "image_generation": image,
        "external_prompt": {"available": True, "reason": None},
        "local_cli": local_cli,
    }


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


async def get_map_review_source(db: AsyncSession, novel_id: str, node_id: str) -> dict:
    """Current saved spatial declarations for explicit author evidence selection."""
    from modules.world.map_atlas_service import MapAtlasService

    return await MapAtlasService().review_source(db, novel_id, node_id)
