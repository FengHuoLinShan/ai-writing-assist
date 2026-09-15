"""Task handlers for atlas generation and deletion-safe object cleanup."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from infrastructure.llm.schemas import read_ai_run_envelope
from infrastructure.llm.workflow_budget import AIRunCheckpointError
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


def _map_atlas_run_id(task) -> str:
    return str(uuid.UUID(str((getattr(task, "meta", None) or {}).get("run_id") or "")))


def _map_atlas_request_limit(task) -> int:
    value = int((getattr(task, "meta", None) or {}).get("run_request_limit") or 0)
    if value < 1:
        raise ValueError("map atlas task must freeze a positive run_request_limit")
    return value


async def checkpoint_map_atlas_run_envelope(session, task, envelope: dict) -> None:
    """Mirror the queue receipt into the stable MapAtlasRun identity."""
    from infrastructure.llm.schemas import AI_RUN_ENVELOPE_KEY
    from modules.world.map_atlas_models import MapAtlasRun

    payload = read_ai_run_envelope(envelope)
    if payload is None:
        raise AIRunCheckpointError("map atlas run envelope is missing")
    try:
        run_id = uuid.UUID(str((task.meta or {}).get("run_id") or ""))
        novel_id = uuid.UUID(str((task.meta or {}).get("novel_id") or ""))
    except (TypeError, ValueError) as exc:
        raise AIRunCheckpointError(
            "map atlas run envelope target is invalid", run_id=payload.run_id
        ) from exc
    run = (
        await session.execute(
            select(MapAtlasRun)
            .where(MapAtlasRun.id == run_id, MapAtlasRun.novel_id == novel_id)
            .with_for_update(skip_locked=True)
        )
    ).scalar_one_or_none()
    if run is None:
        raise AIRunCheckpointError(
            "map atlas run envelope target is unavailable", run_id=payload.run_id
        )
    if (
        payload.run_id != str(run.id)
        or payload.operation_id != str(run.id)
        or payload.novel_id != str(run.novel_id)
        or payload.root_capability_id != "world.map_atlas.generate"
    ):
        raise AIRunCheckpointError(
            "map atlas run envelope identity is invalid", run_id=payload.run_id
        )
    if run.task_id != task.id:
        raise AIRunCheckpointError(
            "map atlas run envelope owner is stale", run_id=payload.run_id
        )
    run.context_snapshot = {
        **dict(run.context_snapshot or {}),
        AI_RUN_ENVELOPE_KEY: dict(envelope),
    }
    await session.flush()


@task_handler(
    "world_map_schematic_generate",
    recovery_policy="manual_resume",
    max_attempts=4,
    root_capability_id="world.map_structure.generate",
    # A = ⌈S/5⌉ × [U(1,0)+U(2,0)] = 4 × (6+9) = 60（S≤20 为 schema 校验器上界，
    # R=3）。manual_resume 是新的作者授权动作，A 只覆盖单次 attempt。
    run_request_limit=60,
)
async def handle_map_structure_generate(db, task):
    from modules.world.map_structure_workflow import run_structure

    return await run_structure(db, task)


@task_handler(
    "map_atlas_generate",
    recovery_policy="manual_resume",
    max_attempts=20,
    root_capability_id="world.map_atlas.generate",
    run_request_limit=_map_atlas_request_limit,
    run_id=_map_atlas_run_id,
    run_envelope_checkpoint=checkpoint_map_atlas_run_envelope,
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
