"""
World 任务处理器

注册 AI 生成/抽取相关的异步任务处理器。
"""

from __future__ import annotations

import inspect
import logging
from dataclasses import asdict
from typing import Any, cast

from core.container import get as _container_get
from infrastructure.tasks.registry import task_handler
from modules.context import facade as context_facade

logger = logging.getLogger(__name__)

_ALIAS_RELATION_TASK_STATE_KEY = "_alias_relation_task_v2"
_LEGACY_ALIAS_RELATION_TASK_STATE_KEY = "_alias_relation_task_v1"
_ALIAS_RELATION_TASK_TYPE = "world_alias_relation_extraction"
_ALIAS_RELATION_SOURCE_WRITER_TASK_TYPES = {
    "deep_import",
    "scene_auto_extraction",
    "world_object_auto_extraction",
}


def _alias_relation_confirmation_payload(confirmation: Any) -> dict[str, Any]:
    if not hasattr(confirmation, "__dataclass_fields__"):
        raise ValueError("context confirmation contract is invalid")
    return cast(dict[str, Any], asdict(confirmation))


def _validate_alias_relation_task_identity(task: Any) -> None:
    if str(getattr(task, "task_type", "") or "") != _ALIAS_RELATION_TASK_TYPE:
        raise ValueError("world alias/relation task type mismatch")
    if str(getattr(task, "status", "") or "") != "running":
        raise ValueError("world alias/relation task must be running")
    if int(getattr(task, "attempt", 0) or 0) < 1:
        raise ValueError("world alias/relation task attempt is invalid")
    if not str(getattr(task, "lease_id", "") or ""):
        raise ValueError("world alias/relation task lease is required")


def _alias_relation_scene_ids(value: Any) -> list[str] | None:
    if value is None:
        return None
    if not isinstance(value, list):
        raise ValueError("scene_ids must be a list")
    normalized = [str(item).strip() for item in value]
    if any(not item for item in normalized) or len(set(normalized)) != len(normalized):
        raise ValueError("scene_ids must contain unique non-empty ids")
    return normalized


def _require_alias_relation_confirmation_owner(
    confirmation: Any,
    *,
    task_id: str,
) -> None:
    """Fail closed unless this running task still owns the confirmation."""
    if str(getattr(confirmation, "result_status", "") or "") != "running":
        raise ValueError("alias/relation context confirmation is not running")
    if list(getattr(confirmation, "stale_reasons", None) or []):
        raise ValueError("alias/relation context confirmation has stale reasons")
    result_refs = getattr(confirmation, "result_refs", None)
    if not isinstance(result_refs, list):
        raise ValueError("alias/relation context confirmation refs are invalid")
    task_refs = [
        str(ref.get("id") or "")
        for ref in result_refs
        if isinstance(ref, dict) and ref.get("type") == "task"
    ]
    if not task_refs or task_refs[-1] != task_id:
        raise ValueError(
            "alias/relation context confirmation was superseded by another task"
        )


async def _commit_alias_relation_checkpoint(
    db: Any,
    task: Any,
    *,
    result: dict[str, Any],
    progress: float,
) -> None:
    """Persist one detached checkpoint or restore the last durable task state."""
    previous_result = getattr(task, "result", None)
    previous_progress = getattr(task, "progress", None)
    missing = object()
    previous_heartbeat = getattr(task, "heartbeat_at", missing)
    task.result = result
    task.update_progress(progress)
    try:
        await db.commit()
    except BaseException:
        # The worker's detached task object is not reverted by session rollback.
        # Keep terminal cancellation/failure from persisting a checkpoint whose
        # domain transaction was rejected by the project/lease commit fence.
        task.result = previous_result
        task.progress = previous_progress
        if previous_heartbeat is not missing:
            task.heartbeat_at = previous_heartbeat
        raise
    if db.in_transaction():
        raise RuntimeError("alias/relation checkpoint left a transaction")
    db.expire_all()


@task_handler(
    "world_alias_relation_extraction",
    recovery_policy="auto_requeue",
    max_attempts=3,
)
async def handle_world_alias_relation_extraction(db, task):
    """Run manual alias/relation extraction with fenced provider boundaries."""
    from infrastructure.tasks.facade import (
        list_running_task_types_for_novel,
        require_running_task_attempt,
        require_task_checkpoint_session,
    )
    from modules.project.facade import (
        build_project_llm_execution_snapshot,
        require_active_project,
        require_active_project_exclusive,
        restore_project_llm_execution_settings,
    )
    from modules.world.contracts import WorldAliasRelationTaskPort

    require_task_checkpoint_session(db)
    _validate_alias_relation_task_identity(task)
    meta = dict(task.meta or {})
    novel_id = str(meta.get("novel_id") or "")
    confirmation_id = str(meta.get("context_confirmation_id") or "")
    if not novel_id:
        raise ValueError("novel_id is required for world_alias_relation_extraction")
    if not confirmation_id:
        raise ValueError(
            "context_confirmation_id is required for world_alias_relation_extraction"
        )
    start_chapter = int(meta.get("start_chapter", 1))
    end_chapter = int(meta.get("end_chapter", 10))
    if start_chapter < 1 or end_chapter < start_chapter:
        raise ValueError("invalid alias/relation chapter range")
    scene_ids = _alias_relation_scene_ids(meta.get("scene_ids"))
    task_id = str(task.id)

    result_checkpoint = dict(task.result or {})
    if result_checkpoint.get(_LEGACY_ALIAS_RELATION_TASK_STATE_KEY):
        raise ValueError(
            "unfinished alias/relation v1 task cannot resume with the v2 prompt; "
            "submit the task again"
        )
    state = dict(result_checkpoint.get(_ALIAS_RELATION_TASK_STATE_KEY) or {})
    if state and state.get("version") != 2:
        raise ValueError("unsupported alias/relation task checkpoint version")
    if state and state.get("stage") not in {"prepared", "llm_complete", "done"}:
        raise ValueError("alias/relation task checkpoint stage is invalid")
    if state.get("stage") == "done":
        final_result = state.get("final_result")
        if not isinstance(final_result, dict):
            raise ValueError("alias/relation final checkpoint is invalid")
        return dict(final_result)

    # Project lock is deliberately first in every DB phase. Confirmation and
    # profile checks therefore cannot race a project deletion into child writes.
    await require_active_project(db, novel_id)
    confirmation = await context_facade.require_fresh_confirmation(
        db,
        novel_id=novel_id,
        action="world.alias_relations.extract",
        confirmation_id=confirmation_id,
    )
    _require_alias_relation_confirmation_owner(confirmation, task_id=task_id)

    llm_execution_snapshot = meta.get("llm_execution_snapshot")
    if not isinstance(llm_execution_snapshot, dict) or not llm_execution_snapshot:
        # Compatibility for tasks queued before submission-time snapshots.
        llm_execution_snapshot = await build_project_llm_execution_snapshot(
            db,
            novel_id,
        )
        meta = {**meta, "llm_execution_snapshot": llm_execution_snapshot}
        task.meta = meta
        await db.commit()
        if db.in_transaction():
            raise RuntimeError("alias/relation profile checkpoint left a transaction")
        db.expire_all()
        await require_active_project(db, novel_id)
        confirmation = await context_facade.require_fresh_confirmation(
            db,
            novel_id=novel_id,
            action="world.alias_relations.extract",
            confirmation_id=confirmation_id,
        )
        _require_alias_relation_confirmation_owner(confirmation, task_id=task_id)

    project_settings = await restore_project_llm_execution_settings(
        db,
        novel_id,
        llm_execution_snapshot,
    )
    port = cast(
        WorldAliasRelationTaskPort,
        _container_get("world.run_alias_relation_extraction"),
    )
    for method_name in (
        "prepare_alias_relation_task",
        "execute_alias_relation_task",
        "finalize_alias_relation_task",
    ):
        if not callable(getattr(port, method_name, None)):
            raise RuntimeError("world alias/relation task DI port is invalid")

    existing_manifest = state.get("manifest") if state else None
    if existing_manifest is not None and not isinstance(existing_manifest, dict):
        raise ValueError("alias/relation prepared checkpoint is invalid")
    prepared = await port.prepare_alias_relation_task(
        db,
        novel_id=novel_id,
        task_id=task_id,
        confirmation_id=confirmation_id,
        confirmation=_alias_relation_confirmation_payload(confirmation),
        start_chapter=start_chapter,
        end_chapter=end_chapter,
        scene_ids=scene_ids,
        llm_execution_snapshot=llm_execution_snapshot,
        project_settings=project_settings,
        existing_manifest=existing_manifest,
    )
    manifest = prepared.get("manifest")
    runtime_plan = prepared.get("runtime_plan")
    if not isinstance(manifest, dict) or not isinstance(runtime_plan, dict):
        raise ValueError("alias/relation preparation result is invalid")

    receipt = state.get("receipt") if state.get("stage") == "llm_complete" else None
    if receipt is None:
        await _commit_alias_relation_checkpoint(
            db,
            task,
            result={
                **dict(task.result or {}),
                _ALIAS_RELATION_TASK_STATE_KEY: {
                    "version": 2,
                    "stage": "prepared",
                    "manifest": manifest,
                },
            },
            progress=0.25,
        )

        # No AsyncSession is passed across this boundary. The concrete port also
        # owns and closes every project-snapshot LLM client.
        receipt = await port.execute_alias_relation_task(
            runtime_plan=runtime_plan,
            project_settings=project_settings,
            novel_id=novel_id,
        )
        if not isinstance(receipt, dict):
            raise ValueError("alias/relation provider receipt is invalid")
        await _commit_alias_relation_checkpoint(
            db,
            task,
            result={
                **dict(task.result or {}),
                _ALIAS_RELATION_TASK_STATE_KEY: {
                    "version": 2,
                    "stage": "llm_complete",
                    "manifest": manifest,
                    "receipt": receipt,
                },
            },
            progress=0.75,
        )
    else:
        if not isinstance(receipt, dict):
            raise ValueError("alias/relation provider receipt checkpoint is invalid")
        # Close the project/confirmation/source revalidation transaction and
        # fence the current lease before reusing a prior detached receipt.
        await db.commit()
        if db.in_transaction():
            raise RuntimeError("alias/relation retry checkpoint left a transaction")
        db.expire_all()

    # Final lock order is project exclusive -> task/source-writer fences ->
    # confirmation/profile/source reads -> domain writes -> worker CAS commit.
    # All synchronous source writers take the normal project FOR SHARE guard;
    # worker commits take the same guard. Pending/newly claimed writers can run
    # provider work, but their source writes cannot commit ahead of this lock.
    await require_active_project_exclusive(db, novel_id)
    conflicting_writers = await list_running_task_types_for_novel(
        db,
        novel_id=novel_id,
        task_types=_ALIAS_RELATION_SOURCE_WRITER_TASK_TYPES,
        exclude_task_id=task_id,
    )
    if conflicting_writers:
        writers = ", ".join(sorted(set(conflicting_writers)))
        raise RuntimeError(
            "alias/relation finalization deferred while source writer tasks run: "
            f"{writers}"
        )
    await require_running_task_attempt(
        db,
        task_id=task_id,
        task_type=_ALIAS_RELATION_TASK_TYPE,
        novel_id=novel_id,
        lease_id=str(task.lease_id),
        attempt=int(task.attempt),
    )
    confirmation = await context_facade.require_fresh_confirmation(
        db,
        novel_id=novel_id,
        action="world.alias_relations.extract",
        confirmation_id=confirmation_id,
        for_update=True,
    )
    _require_alias_relation_confirmation_owner(confirmation, task_id=task_id)
    project_settings = await restore_project_llm_execution_settings(
        db,
        novel_id,
        llm_execution_snapshot,
    )
    finalized = await port.finalize_alias_relation_task(
        db,
        novel_id=novel_id,
        task_id=task_id,
        confirmation_id=confirmation_id,
        confirmation=_alias_relation_confirmation_payload(confirmation),
        start_chapter=start_chapter,
        end_chapter=end_chapter,
        scene_ids=scene_ids,
        llm_execution_snapshot=llm_execution_snapshot,
        project_settings=project_settings,
        manifest=manifest,
        receipt=receipt,
    )
    result = finalized.get("summary")
    result_refs = finalized.get("result_refs")
    if not isinstance(result, dict) or not isinstance(result_refs, list):
        raise ValueError("alias/relation finalization result is invalid")
    if result_refs:
        await context_facade.attach_result_refs(
            db,
            confirmation_id=confirmation_id,
            result_refs=result_refs,
            status="done",
        )
    else:
        await context_facade.attach_result_ref(
            db,
            confirmation_id=confirmation_id,
            result_type="world_alias_relation_extraction",
            result_id=task_id,
            status="done",
        )
    public_result = {**result, "llm_execution_snapshot": llm_execution_snapshot}
    await _commit_alias_relation_checkpoint(
        db,
        task,
        result={
            **dict(task.result or {}),
            _ALIAS_RELATION_TASK_STATE_KEY: {
                "version": 2,
                "stage": "done",
                "plan_fingerprint": manifest.get("plan_fingerprint"),
                "final_result": public_result,
            },
        },
        progress=1.0,
    )
    return public_result


@task_handler("world_entity_fusion_suggestions", recovery_policy="restart_origin")
async def handle_world_entity_fusion_suggestions(db, task):
    """生成世界对象 LLM 融合/合并建议，不直接改实体。"""
    from modules.world.entity_fusion import WorldEntityFusionService

    meta = task.meta or {}
    novel_id = meta.get("novel_id", "")
    if not novel_id:
        raise ValueError("novel_id is required for world_entity_fusion_suggestions")

    task.update_progress(0.05)

    def _progress(value: float) -> None:
        task.update_progress(max(0.05, min(0.95, value)))

    def _checkpoint(result: dict, progress: float) -> None:
        task.result = result
        _progress(progress)

    def _snapshot(snapshot: dict) -> None:
        task.meta = {**meta, "llm_execution_snapshot": snapshot}

    result = await WorldEntityFusionService().suggest_for_task(
        db,
        novel_id=novel_id,
        entity_type=meta.get("entity_type"),
        status=meta.get("status"),
        limit=int(meta.get("limit", 200)),
        max_suggestions=int(meta.get("max_suggestions", 50)),
        checkpoint_callback=_checkpoint,
        llm_execution_snapshot=meta.get("llm_execution_snapshot"),
        snapshot_callback=_snapshot,
    )
    task.update_progress(1.0)
    return result


@task_handler(
    "world_bible_projection_refresh",
    recovery_policy="auto_requeue",
    max_attempts=2,
)
async def handle_world_bible_projection_refresh(db, task):
    """Refresh a World Bible page projection."""
    from modules.world.services.worldbuilding.worldbuilding_service import (
        WorldBibleService,
    )

    meta = task.meta or {}
    novel_id = str(meta.get("novel_id") or "")
    page_id = str(meta.get("page_id") or "")
    projection_type = str(meta.get("projection_type") or "context_brief")
    if not novel_id or not page_id:
        raise ValueError("novel_id and page_id are required")

    task.update_progress(0.15)
    projection = await WorldBibleService().refresh_projection_now(
        db,
        novel_id=novel_id,
        page_id=page_id,
        projection_type=projection_type,
    )
    task.update_progress(1.0)
    flush = getattr(db, "flush", None)
    if flush is not None:
        result_flush = flush()
        if inspect.isawaitable(result_flush):
            await result_flush
    return {
        "projection_id": projection.id,
        "projection_type": projection.projection_type,
        "status": projection.status,
        "token_estimate": projection.token_estimate,
        "error_kind": projection.error_kind,
        "error_summary": projection.error_summary,
        "stale": projection.stale,
    }


@task_handler(
    "world_bible_synopsis_refresh",
    recovery_policy="auto_requeue",
    max_attempts=2,
)
async def handle_world_bible_synopsis_refresh(db, task):
    """Refresh the immutable author-only World Bible synopsis revision."""
    from modules.world.services.worldbuilding.world_bible_synopsis_service import (
        WorldBibleSynopsisService,
    )

    meta = dict(task.meta or {})
    novel_id = str(meta.get("novel_id") or "")
    source_hash = str(meta.get("source_hash") or "")
    if not novel_id or not source_hash:
        raise ValueError("novel_id and source_hash are required")
    service = WorldBibleSynopsisService()

    def _metadata(snapshot: dict, fence: dict) -> None:
        task.meta = {
            **dict(task.meta or {}),
            "llm_execution_snapshot": snapshot,
            "synopsis_task_fence": fence,
        }

    def _checkpoint(result: dict | None, progress: float) -> None:
        if result is not None:
            task.result = result
        task.update_progress(progress)

    try:
        await service.refresh_for_task(
            db,
            novel_id,
            requested_source_hash=source_hash,
            task_id=str(task.id),
            task_meta=meta,
            metadata_callback=_metadata,
            checkpoint_callback=_checkpoint,
        )
        task.update_progress(1.0)
        return dict(task.result or {})
    except Exception as exc:
        fence = (task.meta or {}).get("synopsis_task_fence")
        await service.record_task_failure(
            db,
            novel_id,
            str(task.id),
            requested_source_hash=source_hash,
            task_fence=fence if isinstance(fence, dict) else None,
            exc=exc,
        )
        raise
