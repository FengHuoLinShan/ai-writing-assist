"""Explicitly confirmed, ordered spatial discovery for already-read Scenes."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import update

from core.errors import ConflictError, NotFoundError, ValidationError
from infrastructure.llm.collaboration import content_hash
from infrastructure.tasks.facade import (
    enqueue_operation_task,
    list_task_lifecycle_contracts,
    resume_manual_task,
)
from modules.evolution.budget import run_budget_meta
from modules.evolution.commit import new_attempt_id
from modules.evolution.models import EvolutionFrozenAttempt
from modules.evolution.pipeline import SceneSourceBinding
from modules.evolution.reading import require_current_prefix
from modules.evolution.state_review import settled_output_failure
from modules.evolution.store import PostgresAttemptStore
from modules.evolution.world_audit_supplement import (
    require_no_active_world_audit_supplement,
)
from modules.project.facade import (
    require_active_project,
    require_active_project_exclusive,
)

TASK_TYPE = "evolution_spatial_rescan_v1"


def _additional_budget(remaining: int | None, reserve: int, calls: int) -> int:
    if remaining is None:
        return 0
    return max(0, int(reserve) + int(calls) - int(remaining))


async def _resolve_source_content_mode(
    db, novel_id, step, source, scene_text, frozen_mode
):
    """Infer a legacy Scene mode only when one exact Story validation succeeds."""
    from modules.evolution.workflow import _read_step

    if frozen_mode is not None and frozen_mode not in {"working", "canonical"}:
        raise ConflictError("历史空间来源模式无效，不能补扫")
    modes = [frozen_mode] if frozen_mode else ["working", "canonical"]
    matches = []
    for mode in modes:
        try:
            current, current_text = await _read_step(
                db,
                novel_id,
                {**step, "source_content_mode": mode},
            )
        except (ConflictError, ValidationError):
            continue
        if (
            current.model_dump(mode="json") == source.model_dump(mode="json")
            and current_text == scene_text
        ):
            matches.append(mode)
    if len(matches) != 1:
        raise ConflictError("历史 Scene 正文来源模式无法唯一验证，请先重新核对来源")
    return matches[0]


class SpatialRescanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation_id: UUID
    from_scene_index: int = Field(ge=0)
    through_scene_index: int = Field(ge=0)
    request_limit: int | None = Field(default=None, ge=1, le=1000)

    @model_validator(mode="after")
    def valid_range(self):
        if self.through_scene_index < self.from_scene_index:
            raise ValueError("请选择有效的已读范围")
        return self


class SpatialRescanStart(SpatialRescanRequest):
    expected_fingerprint: str = Field(pattern="^[0-9a-f]{64}$")
    authorization_confirmed: Literal[True]

    @model_validator(mode="after")
    def confirmed(self):
        if self.authorization_confirmed is not True:
            raise ValueError("空间补扫需要作者明确确认")
        return self


def _unknown_spatial_call(payload):
    for key in ("scene_spatial_discovery", "scene_spatial_review"):
        journal = payload.get(key) or {}
        if journal.get("stage") not in {"sampling", "failed"}:
            continue
        if settled_output_failure(journal):
            continue
        return True
    return False


async def _unresolved_rescan_scenes(store, run_key, plan):
    unresolved = set()
    for operation in plan.get("spatial_rescans", []):
        for attempt_id in operation.get("attempt_ids", []):
            frozen = await store.load_frozen(run_key, attempt_id)
            if frozen and _unknown_spatial_call(frozen.payload):
                unresolved.add(int(frozen.payload["scene_index"]))
    return unresolved


async def spatial_rescan_states(db, novel_id, run):
    entries = (run.reading_plan_json or {}).get("spatial_rescans", [])
    lifecycles = await list_task_lifecycle_contracts(
        db,
        task_ids=[item["task_id"] for item in entries],
        novel_id=str(novel_id),
        max_heartbeat_gap=120,
    )
    store = PostgresAttemptStore(db, novel_id)
    views = []
    for entry in entries:
        lifecycle = lifecycles.get(entry["task_id"])
        status = entry["status"]
        frozen = [
            await store.load_frozen(run.run_key, attempt_id)
            for attempt_id in entry["attempt_ids"]
        ]
        unknown = any(item and _unknown_spatial_call(item.payload) for item in frozen)
        recoverable = bool(
            lifecycle
            and lifecycle.recovery_required
            and lifecycle.status not in {"pending", "running"}
            and run.status == "active"
        )
        if unknown and (not lifecycle or lifecycle.status not in {"pending", "running"}):
            status = "needs_reconciliation"
        elif recoverable:
            status = "failed"
        elif lifecycle and lifecycle.status in {"pending", "running"}:
            status = lifecycle.status
        views.append(
            {
                key: entry[key]
                for key in (
                    "operation_id",
                    "from_scene_index",
                    "through_scene_index",
                    "scene_count",
                    "call_limit",
                )
            }
            | {"status": status, "can_resume": recoverable and not unknown}
        )
    return views


async def _idle(db, novel_id, run):
    await require_no_active_world_audit_supplement(db, novel_id, run)
    from modules.evolution.optional_scene import load_pending_optional_stage

    if await load_pending_optional_stage(PostgresAttemptStore(db, novel_id), run):
        raise ConflictError("请先恢复原理解的可选阶段，再发起补扫")
    task_id = (run.reading_plan_json or {}).get("task_id")
    if task_id:
        status = (
            await list_task_lifecycle_contracts(
                db, task_ids=[task_id], novel_id=str(novel_id), max_heartbeat_gap=0
            )
        ).get(task_id)
        if status and status.status in {"pending", "running"}:
            raise ConflictError("原理解仍在运行，请完成后再补扫")
    active_operations = await spatial_rescan_states(db, novel_id, run)
    if any(item["status"] in {"pending", "running"} for item in active_operations):
        raise ConflictError("已有空间补扫仍在运行")


async def _plan(db, novel_id, run_key, request):
    from modules.evolution.spatial import SPATIAL_VERSION, spatial_method_fingerprint

    store = PostgresAttemptStore(db, novel_id)
    run = await store.load_run(run_key)
    if not run or not run.reading_plan_json:
        raise NotFoundError("未找到已读范围")
    await store.require_project_owner(run_key)
    if (
        run.status != "active"
        or run.execution_mode != "live"
        or not run.llm_snapshot_json
    ):
        raise ConflictError("当前理解不可补扫，请重新核对来源")
    await _idle(db, novel_id, run)
    if request.through_scene_index > run.committed_scene_index:
        raise ConflictError("只能补扫已经完成读取的场景")

    pairs = await store.load_committed_pairs(run_key)
    head = await store.load_head_receipt(run_key)
    plan_steps = {
        int(item["scene_index"]): item for item in run.reading_plan_json.get("steps", [])
    }
    unresolved_scenes = await _unresolved_rescan_scenes(
        store, run_key, run.reading_plan_json
    )
    plans = []
    for receipt, _ in pairs:
        index = receipt.committed_scene_index
        if not request.from_scene_index <= index <= request.through_scene_index:
            continue
        origin = await store.load_frozen(receipt.run_key, receipt.attempt_key)
        if origin is None:
            raise ConflictError("已读 Scene 冻结来源缺失，不能补扫")
        await require_current_prefix(db, store, origin, run_key=run_key)
        payload = origin.payload or {}
        if index in unresolved_scenes:
            raise ConflictError("该 Scene 的补扫请求结果尚未核清，不能再次发送")
        if _unknown_spatial_call(payload):
            raise ConflictError("原空间请求结果尚未核清，不能重新发送")
        old_result = payload.get("spatial_discovery_result") or {}
        old_coverage = (payload.get("optional_step_coverage") or {}).get("spatial") or {}
        if (
            payload.get("spatial_version") == SPATIAL_VERSION
            and old_result.get("method_fingerprint") == spatial_method_fingerprint()
            and old_result.get("status") == "inspected"
            and old_coverage.get("status") == "inspected"
            and not old_result.get("gaps")
        ):
            continue
        source_data = payload.get("source_binding")
        scene_text = payload.get("scene_text")
        if not source_data or not isinstance(scene_text, str) or not scene_text:
            raise ConflictError("已读 Scene 缺少可验证的正文来源")
        source = SceneSourceBinding.model_validate(source_data)
        step = plan_steps.get(index)
        if not step or step.get("scene_id") != payload.get("scene_id"):
            raise ConflictError("已读 Scene 与原阅读计划不一致")
        frozen_mode = step.get("source_content_mode")
        if frozen_mode is None:
            frozen_mode = payload.get("source_content_mode")
        content_mode = await _resolve_source_content_mode(
            db,
            novel_id,
            step,
            source,
            scene_text,
            frozen_mode,
        )
        clone_payload = deepcopy(payload)
        for key in ("scene_spatial_discovery", "scene_spatial_review"):
            clone_payload.pop(key, None)
        for key in (
            "optional_stage_version",
            "optional_scene_stage",
            "spatial_preparation",
            "spatial_discovery_result",
            "spatial_stage_result",
        ):
            clone_payload.pop(key, None)
        coverage = dict(clone_payload.get("optional_step_coverage") or {})
        coverage.pop("spatial", None)
        clone_payload["optional_step_coverage"] = coverage
        clone_payload.update(
            {
                "stage": "verified",
                "spatial_version": SPATIAL_VERSION,
                "spatial_method_fingerprint": spatial_method_fingerprint(),
                "source_content_mode": content_mode,
                "spatial_rescan": True,
                "spatial_rescan_operation_id": str(request.operation_id),
                "spatial_rescan_origin": {
                    "run_key": origin.run_id,
                    "attempt_id": origin.attempt_id,
                    "source_manifest_hash": origin.source_manifest_hash,
                },
                "operation_parent_scene_index": run.committed_scene_index + 1,
            }
        )
        draft = origin.model_copy(
            update={
                "run_id": run_key,
                "previous_receipt": head.attempt_id,
                "previous_committed_prefix": head.committed_prefix,
                "owner_epoch": run.owner_epoch,
                "payload": clone_payload,
            }
        )
        plans.append({"origin": clone_payload["spatial_rescan_origin"], "frozen": draft})

    selected_count = sum(
        request.from_scene_index
        <= receipt.committed_scene_index
        <= request.through_scene_index
        for receipt, _ in pairs
    )
    if selected_count != request.through_scene_index - request.from_scene_index + 1:
        raise ConflictError("已读回执范围不完整，不能补扫")
    if not plans:
        raise ConflictError("所选范围已按当前空间方法完整检查")
    calls = 2 * len(plans)
    if request.request_limit is not None and calls > request.request_limit:
        raise ConflictError("预计空间补扫请求超过上限，请缩小范围或提高上限")
    reserve = 0
    if run.budget_remaining is not None:
        from modules.evolution.optional_step_budget import mandatory_requests_remaining

        reserve = mandatory_requests_remaining(run)
    budget_added = _additional_budget(run.budget_remaining, reserve, calls)
    fingerprint = content_hash(
        {
            "request": request.model_dump(
                mode="json", exclude={"expected_fingerprint", "authorization_confirmed"}
            ),
            "owner_epoch": run.owner_epoch,
            "head": head.attempt_id,
            "budget_remaining": run.budget_remaining,
            "mandatory_reserve": reserve,
            "budget_added": budget_added,
            "model": run.llm_snapshot_json,
            "method": spatial_method_fingerprint(),
            "scenes": [
                {
                    "origin": item["origin"],
                    "source_manifest_hash": item["frozen"].source_manifest_hash,
                    "source_binding": item["frozen"].payload["source_binding"],
                    "content_mode": item["frozen"].payload["source_content_mode"],
                }
                for item in plans
            ],
            "calls": calls,
        }
    )
    return store, run, plans, calls, reserve, budget_added, fingerprint


async def preview_spatial_rescan(db, novel_id, run_key, request):
    await require_active_project(db, str(novel_id))
    _, run, plans, calls, reserve, added, fingerprint = await _plan(
        db, novel_id, run_key, request
    )
    return {
        "fingerprint": fingerprint,
        "from_scene_index": request.from_scene_index,
        "through_scene_index": request.through_scene_index,
        "scene_count": len(plans),
        "request_range": {"minimum": 0, "maximum": calls},
        "call_count": calls,
        "quota": calls,
        "additional_budget": added,
        "mandatory_request_reserve": reserve,
        "budget_mode": run.reading_plan_json.get("budget_mode", "bounded"),
        "budget_remaining": run.budget_remaining,
        "model": (run.llm_snapshot_json or {}).get("profile", {}).get("model"),
    }


async def start_spatial_rescan(db, novel_id, run_key, request):
    await require_active_project_exclusive(db, str(novel_id))
    store = PostgresAttemptStore(db, novel_id)
    run = await store.load_run(run_key, for_update=True)
    if not run:
        raise NotFoundError("未找到理解运行")
    await store.require_project_owner(run_key)
    request_body = request.model_dump(mode="json")
    operations = (run.reading_plan_json or {}).get("spatial_rescans", [])
    existing = next(
        (
            item
            for item in operations
            if item["operation_id"] == str(request.operation_id)
        ),
        None,
    )
    if existing:
        if existing["request_hash"] != content_hash(request_body):
            raise ConflictError("空间补扫确认内容已变化，请重新预览")
        return {
            "task_id": existing["task_id"],
            "status": existing["status"],
            "replayed": True,
        }
    store, run, plans, calls, reserve, added, fingerprint = await _plan(
        db, novel_id, run_key, request
    )
    if fingerprint != request.expected_fingerprint:
        raise ConflictError("原文、理解、模型或预算已变化，请重新预览空间补扫")
    attempts = []
    for item in plans:
        frozen = item["frozen"].model_copy(
            update={
                "attempt_id": new_attempt_id(),
                "producer_version": TASK_TYPE,
                "payload": {**item["frozen"].payload, "spatial_rescan_status": "pending"},
            }
        )
        await store.save_frozen(frozen)
        attempts.append(frozen.attempt_id)
    if run.budget_remaining is not None:
        run.budget_total += added
        run.budget_remaining += added
    queued = await enqueue_operation_task(
        db,
        operation_id=str(request.operation_id),
        task_type=TASK_TYPE,
        novel_id=str(novel_id),
        request_payload=request_body,
        meta={
            **run_budget_meta(run),
            "novel_id": str(novel_id),
            "run_key": run_key,
            "operation_id": str(request.operation_id),
        },
    )
    run.reading_plan_json = {
        **run.reading_plan_json,
        "spatial_rescans": [
            *operations,
            {
                "operation_id": str(request.operation_id),
                "request_hash": content_hash(request_body),
                "task_id": str(queued.task_id),
                "status": "pending",
                "attempt_ids": attempts,
                "from_scene_index": request.from_scene_index,
                "through_scene_index": request.through_scene_index,
                "scene_count": len(plans),
                "call_limit": calls,
                "calls_remaining": calls,
                "budget_added": added,
                "mandatory_reserve": reserve,
            },
        ],
    }
    await db.commit()
    return {
        "task_id": str(queued.task_id),
        "status": str(queued.status),
        "budget_added": added,
    }


async def _status(db, store, run_key, operation_id, status):
    await store.require_project_owner(run_key)
    run = await store.load_run(run_key, for_update=True)
    run.reading_plan_json = {
        **run.reading_plan_json,
        "spatial_rescans": [
            {**item, "status": status} if item["operation_id"] == operation_id else item
            for item in run.reading_plan_json.get("spatial_rescans", [])
        ],
    }
    await db.commit()


async def resume_spatial_rescan(db, novel_id, run_key, operation_id):
    await require_active_project_exclusive(db, str(novel_id))
    store = PostgresAttemptStore(db, novel_id)
    run = await store.load_run(run_key, for_update=True)
    await store.require_project_owner(run_key)
    if not run or run.status != "active":
        raise ConflictError("理解来源已失效，不能恢复空间补扫")
    entry = next(
        (
            item
            for item in run.reading_plan_json.get("spatial_rescans", [])
            if item["operation_id"] == str(operation_id)
        ),
        None,
    )
    state = next(
        (
            item
            for item in await spatial_rescan_states(db, novel_id, run)
            if item["operation_id"] == str(operation_id)
        ),
        None,
    )
    if not entry or not state or not state["can_resume"]:
        if state and state["status"] == "needs_reconciliation":
            raise ConflictError("空间补扫请求结果尚未核清，不能重发")
        raise ConflictError("空间补扫没有可恢复的已核清中断")
    await _idle(db, novel_id, run)
    for attempt_id in entry["attempt_ids"]:
        frozen = await store.load_frozen(run_key, attempt_id)
        if _unknown_spatial_call(frozen.payload):
            raise ConflictError("空间补扫请求结果尚未核清，不能重发")
        origin = frozen.payload["spatial_rescan_origin"]
        await require_current_prefix(
            db,
            store,
            await store.load_frozen(origin["run_key"], origin["attempt_id"]),
            run_key=run_key,
        )
    lifecycle = await resume_manual_task(
        db, task_id=entry["task_id"], task_types={TASK_TYPE}, novel_id=str(novel_id)
    )
    await _status(db, store, run_key, str(operation_id), "pending")
    return {"task_id": entry["task_id"], "status": lifecycle.status}


async def _stage_rescan_result(db, store, frozen):
    from modules.evolution.spatial import apply_spatial_discovery

    await require_active_project_exclusive(db, frozen.novel_id)
    stage_result = None
    stage_error = None
    try:
        async with db.begin_nested():
            stage_result = await apply_spatial_discovery(db, frozen.novel_id, frozen)
    except Exception as exc:
        stage_error = exc
    latest = await store.load_frozen(frozen.run_id, frozen.attempt_id)
    payload = dict(latest.payload)
    if stage_error:
        payload["spatial_stage_result"] = {
            "status": "failed",
            "reason": f"{type(stage_error).__name__}: {stage_error}"[:500],
        }
        payload.setdefault("spatial_discovery_result", {}).setdefault("gaps", []).append(
            {"reason": "world_stage_failed", "detail": str(stage_error)[:300]}
        )
        coverage = dict(payload.get("optional_step_coverage") or {})
        spatial = dict(coverage.get("spatial") or {})
        spatial.update(
            status="inspected",
            gaps=[
                *spatial.get("gaps", []),
                {
                    "reason": "world_stage_failed",
                    "detail": str(stage_error)[:300],
                },
            ],
        )
        coverage["spatial"] = spatial
        payload["optional_step_coverage"] = coverage
    elif stage_result is not None:
        dumped = stage_result.model_dump(mode="json")
        payload["spatial_stage_result"] = dumped
        source_stale = any(
            item.get("code") == "source_binding_invalid"
            for item in dumped.get("rejected", [])
        )
        coverage = dict(payload.get("optional_step_coverage") or {})
        spatial = dict(coverage.get("spatial") or {})
        if dumped.get("rejected"):
            spatial["gaps"] = [
                *spatial.get("gaps", []),
                *(
                    {
                        "reason": "world_stage_rejected",
                        "clue_key": item.get("clue_key"),
                        "code": item.get("code"),
                    }
                    for item in dumped["rejected"]
                ),
            ]
        if source_stale:
            spatial["status"] = "stale"
        coverage["spatial"] = spatial
        payload["optional_step_coverage"] = coverage
    payload["spatial_rescan_status"] = "completed"
    await store.replace_frozen_payload(latest.model_copy(update={"payload": payload}))
    await db.execute(
        update(EvolutionFrozenAttempt)
        .where(
            EvolutionFrozenAttempt.novel_id == UUID(frozen.novel_id),
            EvolutionFrozenAttempt.run_key == frozen.run_id,
            EvolutionFrozenAttempt.attempt_key == frozen.attempt_id,
        )
        .values(status="applied")
    )
    await db.commit()
    return await store.load_frozen(frozen.run_id, frozen.attempt_id)


async def handle_spatial_rescan(db, task):
    from modules.evolution.sampler import SceneMethodCaller
    from modules.evolution.spatial import finish_scene_spatial

    meta = dict(task.meta or {})
    novel_id, run_key, operation_id = (
        meta["novel_id"],
        meta["run_key"],
        meta["operation_id"],
    )
    store = PostgresAttemptStore(db, novel_id)
    run = await store.load_run(run_key)
    entry = next(
        item
        for item in run.reading_plan_json["spatial_rescans"]
        if item["operation_id"] == operation_id
    )
    await _status(db, store, run_key, operation_id, "running")
    try:
        from types import SimpleNamespace

        caller = SceneMethodCaller(
            db,
            SimpleNamespace(sampler_provider="project_llm", novel_id=novel_id),
            run.llm_snapshot_json,
        )
        for attempt_id in entry["attempt_ids"]:
            frozen = await store.load_frozen(run_key, attempt_id)
            if frozen.payload.get("spatial_rescan_status") == "completed":
                continue
            origin_ref = frozen.payload["spatial_rescan_origin"]
            origin = await store.load_frozen(
                origin_ref["run_key"], origin_ref["attempt_id"]
            )
            if origin is None:
                raise ConflictError("空间补扫原回执已丢失")
            await require_current_prefix(db, store, origin, run_key=run_key)
            source = SceneSourceBinding.model_validate(frozen.payload["source_binding"])
            frozen = await finish_scene_spatial(db, store, frozen, source, caller)
            if _unknown_spatial_call(frozen.payload):
                raise ConflictError("空间补扫请求结果尚未核清，禁止重发")
            await _stage_rescan_result(db, store, frozen)
    except (Exception, asyncio.CancelledError):
        await db.rollback()
        attempts = [await store.load_frozen(run_key, key) for key in entry["attempt_ids"]]
        unknown = any(item and _unknown_spatial_call(item.payload) for item in attempts)
        status = "needs_reconciliation" if unknown else "failed"
        await _status(db, store, run_key, operation_id, status)
        run = await store.load_run(run_key)
        recoverable = not unknown and run.status == "active"
        task.meta = {**meta, "recovery_required": recoverable}
        task.result = {"recovery_required": recoverable, "recoverable": recoverable}
        if not await db.checkpoint_task_progress():
            raise asyncio.CancelledError
        raise
    await _status(db, store, run_key, operation_id, "completed")
    run = await store.load_run(run_key)
    from modules.evolution.workflow import _build_spatial_auto_draft_batch

    auto_draft_build = await _build_spatial_auto_draft_batch(
        db,
        novel_id,
        run,
        build_key=f"spatial-rescan-{operation_id}",
        through_scene_index=entry["through_scene_index"],
    )
    return {
        "run_key": run_key,
        "operation_id": operation_id,
        "status": "completed",
        "scene_count": len(entry["attempt_ids"]),
        "auto_draft_build": auto_draft_build,
    }


__all__ = [
    "SpatialRescanRequest",
    "SpatialRescanStart",
    "handle_spatial_rescan",
    "preview_spatial_rescan",
    "resume_spatial_rescan",
    "spatial_rescan_states",
    "start_spatial_rescan",
]
