"""Stable AI map-atlas seams used by other modules."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.tasks.facade import enqueue_task
from modules.world.map_atlas_storage import project_object_prefix
from modules.world.world_object_images import project_image_prefix


async def map_capabilities(db: AsyncSession, novel_id: str) -> dict:
    from modules.project.contracts import ProjectImageConfigurationError
    from modules.project.facade import (
        build_project_image_execution_snapshot,
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
    return {
        "structure": {"available": True, "reason": None},
        "upload": upload,
        "image_generation": image,
        "external_prompt": {"available": True, "reason": None},
    }


async def inspect_map_node(db: AsyncSession, novel_id: str, node_id: str) -> dict:
    """Read the adopted structured map, never private image URLs or Prompt state."""
    from core.errors import ConflictError, ValidationError
    from modules.world.map_atlas_models import MapAtlasPage
    from modules.world.map_structure_service import MapStructureService

    service = MapStructureService()
    node = await service.node(db, novel_id, node_id)
    pages = list(
        (
            await db.scalars(
                select(MapAtlasPage)
                .where(
                    MapAtlasPage.novel_id == uuid.UUID(novel_id),
                    MapAtlasPage.node_id == node.id,
                )
                .order_by(MapAtlasPage.created_at.desc(), MapAtlasPage.id.desc())
                .limit(20)
            )
        ).all()
    )
    material = {
        "id": str(node.id),
        "title": node.title,
        "level": node.level,
        "revision": None,
        "image_results": [
            {
                "type": "map_atlas_page",
                "id": str(page.id),
                "node_id": str(node.id),
                "run_id": str(page.run_id),
                "title": page.title,
                "generation_status": page.generation_status,
                "review_status": page.review_status,
            }
            for page in pages
        ],
        "image_coverage": "最近20张图片的状态与恢复入口；图片内容未读取",
        "history": [
            {
                "id": item.id,
                "status": item.status,
                "base_revision_id": item.base_revision_id,
                "created_at": item.created_at.isoformat() if item.created_at else None,
            }
            for item in await service.history(db, novel_id, node_id)
        ],
    }
    if not node.current_revision_id:
        return {**material, "warnings": ["这张地图尚无采用的空间版本，不能推断地理"]}
    row = await service.revision(db, novel_id, node_id, node.current_revision_id)
    response = service.response(row)
    warnings = []
    for item in [*response.document.features, *response.document.constraints]:
        for source in item.sources:
            try:
                await service.source(db, novel_id, source)
            except (ConflictError, ValidationError):
                warnings.append("部分地理依据已变化，此地图仅作历史参考")
                break
    return {
        **material,
        "revision": response.model_dump(mode="json"),
        "warnings": sorted(set(warnings)),
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
