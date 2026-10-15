"""Explicitly confirmed, resumable discovery of selected categories on read Scenes."""

import asyncio
from copy import deepcopy
from types import SimpleNamespace
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import update

from core.errors import ConflictError, NotFoundError
from infrastructure.llm.collaboration import content_hash
from infrastructure.tasks.facade import (
    enqueue_operation_task,
    list_task_lifecycle_contracts,
    resume_manual_task,
)
from modules.evolution.budget import run_budget_meta
from modules.evolution.commit import new_attempt_id
from modules.evolution.discovery import (
    apply_discovery,
    finish_scene_discovery,
    method_fingerprint,
    prepare_discovery,
)
from modules.evolution.ledger_contracts import LEDGER_CATEGORY_LABELS, LedgerCategory
from modules.evolution.models import EvolutionFrozenAttempt
from modules.evolution.pipeline import SceneSourceBinding
from modules.evolution.reading import require_current_prefix
from modules.evolution.state_review import (
    has_unreconciled_scene_calls,
    scene_call_journals,
)
from modules.evolution.store import PostgresAttemptStore
from modules.evolution.world_audit_supplement import (
    require_no_active_world_audit_supplement,
)
from modules.project.facade import (
    require_active_project,
    require_active_project_exclusive,
)

TASK_TYPE = "evolution_category_rescan_v1"


class CategoryRescanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation_id: UUID
    from_scene_index: int = Field(ge=0)
    through_scene_index: int = Field(ge=0)
    categories: list[LedgerCategory] = Field(
        min_length=1, max_length=len(LEDGER_CATEGORY_LABELS)
    )
    request_limit: int | None = Field(default=None, ge=1, le=1000)

    @model_validator(mode="after")
    def valid_range(self):
        if self.through_scene_index < self.from_scene_index or len(
            set(self.categories)
        ) != len(self.categories):
            raise ValueError("请选择有效的已读范围与不重复的类别")
        return self


class CategoryRescanStart(CategoryRescanRequest):
    expected_fingerprint: str = Field(pattern="^[0-9a-f]{64}$")
    authorization_confirmed: bool

    @model_validator(mode="after")
    def confirmed(self):
        if self.authorization_confirmed is not True:
            raise ValueError("补扫需要作者明确确认")
        return self


async def category_rescan_states(db, novel_id, run):
    entries = (run.reading_plan_json or {}).get("category_rescans", [])
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
        unknown = any(
            item and has_unreconciled_scene_calls(item.payload) for item in frozen
        )
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
                    "categories",
                    "from_scene_index",
                    "through_scene_index",
                )
            }
            | {"status": status, "can_resume": recoverable and not unknown}
        )
    return views


async def _idle(db, novel_id, run):
    await require_no_active_world_audit_supplement(db, novel_id, run)
    task_id = (run.reading_plan_json or {}).get("task_id")
    if task_id:
        status = (
            await list_task_lifecycle_contracts(
                db, task_ids=[task_id], novel_id=str(novel_id), max_heartbeat_gap=0
            )
        ).get(task_id)
        if status and status.status in {"pending", "running"}:
            raise ConflictError("原理解仍在运行，请完成后再补扫")


async def _plan(db, novel_id, run_key, request):
    store = PostgresAttemptStore(db, novel_id)
    run = await store.load_run(run_key)
    if not run or not run.reading_plan_json:
        raise NotFoundError("未找到已读范围")
    await store.require_project_owner(run_key)
    from modules.evolution.optional_scene import load_pending_optional_stage

    if await load_pending_optional_stage(store, run):
        raise ConflictError("请先恢复原理解的可选阶段，再发起补扫")
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
    plans, calls = [], 0
    for receipt, _ in pairs:
        index = receipt.committed_scene_index
        if not request.from_scene_index <= index <= request.through_scene_index:
            continue
        origin = await store.load_frozen(receipt.run_key, receipt.attempt_key)
        details_journals = {
            key: value
            for key, value in origin.payload.items()
            if key.startswith("scene_discovery_")
        }
        if has_unreconciled_scene_calls(details_journals, frozen=origin):
            raise ConflictError("原发现请求结果尚未核清，不能重新发送")
        await require_current_prefix(db, store, origin, run_key=run_key)
        payload = deepcopy(origin.payload)
        from infrastructure.llm.model_limits import confirmed_scope_eligible

        payload.update(
            discovery_version=2 if confirmed_scope_eligible(run.llm_snapshot_json) else 1,
            discovery_categories=sorted(request.categories),
            category_rescan=True,
            discovery_origin={
                "run_key": origin.run_id,
                "attempt_id": origin.attempt_id,
                "source_manifest_hash": origin.source_manifest_hash,
            },
            operation_parent_scene_index=run.committed_scene_index + 1,
        )
        # Old billing journals remain on their receipt; this operation owns fresh calls.
        for key in scene_call_journals(payload):
            payload.pop(key, None)
        for key in {
            "optional_stage_version",
            "optional_scene_stage",
            "paid_call_receipt",
            "scene_sample",
            "discovery_preparation",
            "discovery_result",
            "discovery_materialization",
        }:
            payload.pop(key, None)
        draft = origin.model_copy(
            update={
                "run_id": run_key,
                "previous_receipt": head.attempt_id,
                "previous_committed_prefix": head.committed_prefix,
                "owner_epoch": run.owner_epoch,
                "payload": payload,
            }
        )
        prepared = await prepare_discovery(db, store, draft)
        count = 1 + sum(
            2 + max(0, len(prepared.get("theme_index_shards", [])) - 1)
            for i in range(len(prepared["batches"]))
            if i not in prepared["unsupported_batches"]
        )
        calls += count
        plans.append(
            {
                "origin": payload["discovery_origin"],
                "frozen": draft,
                "preparation": prepared,
                "call_limit": count,
            }
        )
    if len(plans) != request.through_scene_index - request.from_scene_index + 1:
        raise ConflictError("已读回执范围不完整，不能补扫")
    if (request.request_limit is None) != (run.budget_remaining is None):
        raise ConflictError("补扫须继承原运行预算模式")
    if request.request_limit is not None and calls > request.request_limit:
        raise ConflictError("预计补扫调用超过上限，请缩小范围或增加额度")
    fingerprint = content_hash(
        {
            "request": request.model_dump(
                mode="json", exclude={"expected_fingerprint", "authorization_confirmed"}
            ),
            "owner_epoch": run.owner_epoch,
            "head": head.attempt_id,
            "budget": run.budget_remaining,
            "model": run.llm_snapshot_json,
            "method": method_fingerprint(),
            "scenes": [
                {"origin": item["origin"], "preparation": item["preparation"]}
                for item in plans
            ],
        }
    )
    return store, run, plans, calls, fingerprint


async def preview_category_rescan(db, novel_id, run_key, request):
    await require_active_project(db, str(novel_id))
    _, run, plans, calls, fingerprint = await _plan(db, novel_id, run_key, request)
    return {
        "fingerprint": fingerprint,
        "scene_count": len(plans),
        "call_count": calls,
        "categories": [
            {"key": key, "label": LEDGER_CATEGORY_LABELS[key]}
            for key in request.categories
        ],
        "additional_budget": max(0, request.request_limit - run.budget_remaining)
        if request.request_limit is not None
        else 0,
        "budget_mode": run.reading_plan_json.get("budget_mode", "bounded"),
        "maximum_calls": request.request_limit,
        "budget_remaining": run.budget_remaining,
    }


async def start_category_rescan(db, novel_id, run_key, request):
    await require_active_project_exclusive(db, str(novel_id))
    store = PostgresAttemptStore(db, novel_id)
    run = await store.load_run(run_key, for_update=True)
    if not run:
        raise NotFoundError("未找到理解运行")
    await store.require_project_owner(run_key)
    request_body = request.model_dump(mode="json")
    operations = (run.reading_plan_json or {}).get("category_rescans", [])
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
            raise ConflictError("补扫确认内容已变化，请重新预览")
        return {
            "task_id": existing["task_id"],
            "status": existing["status"],
            "replayed": True,
        }
    store, run, plans, calls, fingerprint = await _plan(db, novel_id, run_key, request)
    if fingerprint != request.expected_fingerprint:
        raise ConflictError("原文、理解或预算已变化，请重新预览补扫")
    attempts = []
    for item in plans:
        frozen = item["frozen"].model_copy(
            update={
                "attempt_id": new_attempt_id(),
                "producer_version": TASK_TYPE,
                "payload": {
                    **item["frozen"].payload,
                    "discovery_preparation": item["preparation"],
                    "rescan_status": "pending",
                    "category_rescan_operation_id": str(request.operation_id),
                },
            }
        )
        await store.save_frozen(frozen)
        attempts.append(frozen.attempt_id)
    added = (
        max(0, request.request_limit - run.budget_remaining)
        if request.request_limit is not None
        else 0
    )
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
        "category_rescans": [
            *operations,
            {
                "operation_id": str(request.operation_id),
                "request_hash": content_hash(request_body),
                "task_id": str(queued.task_id),
                "status": "pending",
                "attempt_ids": attempts,
                "categories": request.categories,
                "from_scene_index": request.from_scene_index,
                "through_scene_index": request.through_scene_index,
                "call_limit": request.request_limit,
                "calls_remaining": request.request_limit,
                "budget_added": added,
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
        "category_rescans": [
            {**item, "status": status} if item["operation_id"] == operation_id else item
            for item in run.reading_plan_json.get("category_rescans", [])
        ],
    }
    await db.commit()


async def resume_category_rescan(db, novel_id, run_key, operation_id):
    await require_active_project_exclusive(db, str(novel_id))
    store = PostgresAttemptStore(db, novel_id)
    run = await store.load_run(run_key, for_update=True)
    await store.require_project_owner(run_key)
    if not run or run.status != "active":
        raise ConflictError("理解来源已失效，不能恢复补扫")
    entry = next(
        (
            item
            for item in run.reading_plan_json.get("category_rescans", [])
            if item["operation_id"] == str(operation_id)
        ),
        None,
    )
    state = next(
        (
            item
            for item in await category_rescan_states(db, novel_id, run)
            if item["operation_id"] == str(operation_id)
        ),
        None,
    )
    if not entry or not state or not state["can_resume"]:
        if state and state["status"] == "needs_reconciliation":
            raise ConflictError("补扫请求结果尚未核清，不能重发")
        raise ConflictError("补扫没有可恢复的已核清中断")
    await _idle(db, novel_id, run)
    for attempt_id in entry["attempt_ids"]:
        frozen = await store.load_frozen(run_key, attempt_id)
        if has_unreconciled_scene_calls(frozen.payload):
            raise ConflictError("补扫请求结果尚未核清，不能重发")
        origin = frozen.payload["discovery_origin"]
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


async def _collect_category_observations(db, store, frozen, origin, source, sampler):
    if frozen.payload.get("category_observations_compiled"):
        return frozen
    from modules.evolution.pipeline import _compile_sample_payload, _run_scene_call
    from modules.evolution.world import bind_scene_identities

    manifest = {
        **origin.payload["input_manifest"],
        "category_rescan_categories": frozen.payload["discovery_categories"],
    }
    frozen = await _run_scene_call(
        db,
        store,
        frozen,
        source,
        journal_key="scene_category_observations",
        inputs={
            "method": "evolution.category_observations.v1",
            "source": origin.source_manifest_hash,
            "scene_text": frozen.payload["scene_text"],
            "input_manifest": manifest,
        },
        call_inputs={
            "scene_text": frozen.payload["scene_text"],
            "input_manifest": manifest,
        },
        call=sampler.sample_categories,
    )
    result = frozen.payload["scene_category_observations"]["result"]
    # Identity candidates come only from the original Scene's host-frozen World scope.
    world = origin.payload.get("world_result") or {}
    context = world.get("context") or {}
    entity_ids = context.get("_entity_ref_map") or {}

    async def identity_candidates(novel_id, surface, entity_type):
        return [
            SimpleNamespace(
                existing_entity_id=entity_ids[item["prompt_ref"]],
                existing_entity_name=item["name"],
                match_method="exact_name",
                similarity_score=1.0,
            )
            for item in context.get("identity_candidates", [])
            if item.get("prompt_ref") in entity_ids
            and item.get("name") == surface
            and item.get("entity_type") == entity_type
        ]

    compiled = await _compile_sample_payload(
        {"observations": result.get("observations", []), "scene_events": []},
        novel_id=frozen.novel_id,
        run_key=origin.run_id,
        scene_index=origin.payload["scene_index"],
        scene_text=frozen.payload["scene_text"],
        source=source,
        manifest_hash=origin.source_manifest_hash,
        content_mode="working",
        observer_contract_version=origin.payload.get("observer_contract_version", 1),
        identity_candidates=identity_candidates,
    )
    if world:
        compiled.update(bind_scene_identities({**origin.payload, **compiled}))
    payload = {
        **frozen.payload,
        **compiled,
        "category_observations_compiled": True,
        "category_observation_coverage": result.get("category_coverage", {}),
        "category_observation_gaps": result.get("unresolved_parts", []),
    }
    payload.pop("discovery_preparation", None)
    payload["discovery_preparation"] = await prepare_discovery(
        db, store, frozen.model_copy(update={"payload": payload})
    )
    await store.require_project_owner(frozen.run_id)
    await store.load_run(frozen.run_id, for_update=True)
    latest = await store.load_frozen(frozen.run_id, frozen.attempt_id)
    await store.replace_frozen_payload(
        latest.model_copy(update={"payload": {**latest.payload, **payload}})
    )
    await db.commit()
    return await store.load_frozen(frozen.run_id, frozen.attempt_id)


async def handle_category_rescan(db, task):
    from modules.evolution.sampler import resolve_scene_sampler

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
        for item in run.reading_plan_json["category_rescans"]
        if item["operation_id"] == operation_id
    )
    await _status(db, store, run_key, operation_id, "running")
    try:
        async with resolve_scene_sampler(
            provider="project_llm",
            novel_id=novel_id,
            db=db,
            llm_snapshot=run.llm_snapshot_json,
        ) as sampler:
            from types import SimpleNamespace

            from modules.evolution.sampler import SceneMethodCaller

            call = SceneMethodCaller(
                db,
                SimpleNamespace(sampler_provider="project_llm", novel_id=novel_id),
                run.llm_snapshot_json,
            )

            for attempt_id in entry["attempt_ids"]:
                frozen = await store.load_frozen(run_key, attempt_id)
                if frozen.payload.get("rescan_status") == "completed":
                    continue
                origin_ref = frozen.payload["discovery_origin"]
                origin = await store.load_frozen(
                    origin_ref["run_key"], origin_ref["attempt_id"]
                )
                await require_current_prefix(db, store, origin, run_key=run_key)
                source = SceneSourceBinding.model_validate(
                    frozen.payload["source_binding"]
                )
                frozen = await _collect_category_observations(
                    db, store, frozen, origin, source, sampler
                )
                frozen = await finish_scene_discovery(db, store, frozen, source, call)
                await require_active_project_exclusive(db, novel_id)
                await store.require_project_owner(run_key)
                await store.load_run(run_key, for_update=True)
                await require_current_prefix(db, store, origin, run_key=run_key)
                await apply_discovery(db, store, frozen)
                frozen = await store.load_frozen(run_key, attempt_id)
                await store.replace_frozen_payload(
                    frozen.model_copy(
                        update={
                            "payload": {**frozen.payload, "rescan_status": "completed"}
                        }
                    )
                )
                await db.execute(
                    update(EvolutionFrozenAttempt)
                    .where(
                        EvolutionFrozenAttempt.novel_id == UUID(novel_id),
                        EvolutionFrozenAttempt.run_key == run_key,
                        EvolutionFrozenAttempt.attempt_key == attempt_id,
                    )
                    .values(status="applied")
                )
                await db.commit()
    except (Exception, asyncio.CancelledError):
        await db.rollback()
        attempts = [
            await store.load_frozen(run_key, attempt_id)
            for attempt_id in entry["attempt_ids"]
        ]
        unknown = any(
            item and has_unreconciled_scene_calls(item.payload) for item in attempts
        )
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
    return {
        "run_key": run_key,
        "operation_id": operation_id,
        "status": "completed",
        "scene_count": len(entry["attempt_ids"]),
    }
