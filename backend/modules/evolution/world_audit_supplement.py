"""Author-confirmed audits for legacy World results deferred as one full scene."""

import asyncio
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from core.errors import ConflictError, NotFoundError
from infrastructure.llm.collaboration import content_hash
from infrastructure.tasks.facade import (
    enqueue_operation_task,
    list_task_lifecycle_contracts,
    resume_manual_task,
)
from modules.evolution.commit import FrozenAttempt, new_attempt_id
from modules.evolution.pipeline import SceneSourceBinding
from modules.evolution.state_review import (
    has_unreconciled_scene_calls,
    settled_output_failure,
)
from modules.evolution.store import PostgresAttemptStore
from modules.evolution.world import prepare_world_audit_groups
from modules.imports.facade import apply_scene_world_candidates
from modules.project.facade import (
    require_active_project,
    require_active_project_exclusive,
)


class WorldAuditSupplementStart(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation_id: UUID
    expected_fingerprint: str = Field(pattern="^[0-9a-f]{64}$")
    authorization_confirmed: Literal[True]


def _has_unknown_world_audit_result(payload):
    return any(
        (payload.get(key) or {}).get("stage") == "sampling"
        or (
            (payload.get(key) or {}).get("stage") == "failed"
            and not settled_output_failure(payload.get(key) or {})
        )
        for key in payload
        if key.startswith("scene_world_review_group_")
    )


async def require_no_active_world_audit_supplement(db, novel_id, run):
    task_ids = [
        item.get("task_id")
        for item in [
            *(run.reading_plan_json or {}).get("world_audit_supplements", []),
            *(run.reading_plan_json or {}).get("category_rescans", []),
        ]
        if item.get("task_id")
    ]
    if not task_ids:
        return
    lifecycle = await list_task_lifecycle_contracts(
        db,
        task_ids=task_ids,
        novel_id=str(novel_id),
        max_heartbeat_gap=120,
    )
    if any(item and item.status in {"pending", "running"} for item in lifecycle.values()):
        raise ConflictError("补审或类别补扫仍在运行，请完成后再继续读取")


async def _load_plan(db, novel_id, run_key, origin_attempt_id):
    from modules.evolution.reading import require_current_world_candidate

    store = PostgresAttemptStore(db, novel_id)
    run = await store.load_run(run_key)
    origin = await store.load_frozen(run_key, origin_attempt_id)
    if not run or not run.reading_plan_json or not origin:
        raise NotFoundError("未找到可补审的世界资料")
    await require_no_active_world_audit_supplement(db, novel_id, run)
    task_id = run.reading_plan_json.get("task_id")
    if task_id:
        lifecycle = (
            await list_task_lifecycle_contracts(
                db, task_ids=[task_id], novel_id=str(novel_id), max_heartbeat_gap=0.0
            )
        ).get(task_id)
        if lifecycle and lifecycle.status in {"pending", "running"}:
            raise ConflictError("原理解任务仍在运行，完成后再预览补审")
    review = (origin.payload.get("world_result") or {}).get("review") or {}
    if review.get("review_kind") != "capacity_deferred" or review.get("groups"):
        raise ConflictError("此场景不需要旧版整场审查补审")
    if not origin.payload.get("source_binding") or not origin.payload.get("scene_text"):
        raise ConflictError("原文范围缺失，不能补审")
    if run.status != "active" or run.execution_mode != "live":
        raise ConflictError("理解运行已停止或失效，不能补审")
    if not run.llm_snapshot_json:
        raise ConflictError("原模型连接快照缺失，不能补审")
    await store.require_project_owner(run_key)
    await require_current_world_candidate(
        db,
        str(novel_id),
        {"run_key": run_key, "attempt_id": origin_attempt_id},
    )
    source = SceneSourceBinding.model_validate(origin.payload["source_binding"])
    prepared = prepare_world_audit_groups(
        payload=origin.payload,
        source=source,
        run=run,
        novel_id=str(novel_id),
        attempt_id=origin_attempt_id,
    )
    groups = prepared["groups"]
    call_groups = [
        item for item in groups if item.get("spec") and not item.get("deferred_reason")
    ]
    if not call_groups:
        raise ConflictError("候选无法拆成可执行审查组，请结合原文逐项核对")
    fingerprint = content_hash(
        {
            "run_key": run_key,
            "owner_epoch": run.owner_epoch,
            "head_attempt_id": str(run.head_attempt_id or ""),
            "committed_scene_index": run.committed_scene_index,
            "budget_remaining": run.budget_remaining,
            "origin_attempt_id": origin_attempt_id,
            "source_manifest_hash": origin.source_manifest_hash,
            "preparation": prepared,
        }
    )
    return store, run, origin, source, prepared, call_groups, fingerprint


async def preview_world_audit_supplement(db, novel_id, run_key, origin_attempt_id):
    await require_active_project(db, str(novel_id))
    store, run, _, _, prepared, call_groups, fingerprint = await _load_plan(
        db, novel_id, run_key, origin_attempt_id
    )
    plan = run.reading_plan_json or {}
    existing = next(
        (
            item
            for item in plan.get("world_audit_supplements", [])
            if item.get("origin_attempt_id") == origin_attempt_id
        ),
        None,
    )
    if existing:
        raise ConflictError("此旧场景已发起过补审，请刷新提案状态")
    return {
        "fingerprint": fingerprint,
        "group_count": len(prepared["groups"]),
        "call_count": len(call_groups),
        "deferred_count": len(prepared["groups"]) - len(call_groups),
        "budget_remaining": run.budget_remaining,
        "additional_budget": max(0, len(call_groups) - run.budget_remaining),
        "groups": [
            {
                "candidate_count": item["candidate_count"],
                "audit_input_chars": item["audit_input_chars"],
                "will_call": item in call_groups,
            }
            for item in prepared["groups"]
        ],
    }


async def start_world_audit_supplement(
    db, novel_id, run_key, origin_attempt_id, request: WorldAuditSupplementStart
):
    await require_active_project_exclusive(db, str(novel_id))
    store = PostgresAttemptStore(db, novel_id)
    run = await store.load_run(run_key, for_update=True)
    if not run:
        raise NotFoundError("未找到理解记录")
    plan = run.reading_plan_json or {}
    operation_id = str(request.operation_id)
    existing = next(
        (
            item
            for item in plan.get("world_audit_supplements", [])
            if item.get("operation_id") == operation_id
        ),
        None,
    )
    if existing:
        if existing.get("fingerprint") != request.expected_fingerprint:
            raise ConflictError("补审授权与已提交操作不一致")
        return {
            "task_id": existing["task_id"],
            "status": existing.get("status", "pending"),
            "attempt_id": existing["supplement_attempt_id"],
        }
    store, run, origin, source, prepared, call_groups, fingerprint = await _load_plan(
        db, novel_id, run_key, origin_attempt_id
    )
    if fingerprint != request.expected_fingerprint:
        raise ConflictError("原文、理解前缀或预算已变化，请重新预览补审")
    if any(
        item.get("origin_attempt_id") == origin_attempt_id
        for item in plan.get("world_audit_supplements", [])
    ):
        raise ConflictError("此旧场景已发起过补审，请刷新提案状态")

    supplemental_attempt_id = new_attempt_id()
    head = await store.load_head_receipt(run_key)
    scene_index = run.committed_scene_index + 1
    manifest_hash = content_hash(
        {
            "kind": "world_audit_supplement.v1",
            "origin_attempt_id": origin_attempt_id,
            "origin_manifest_hash": origin.source_manifest_hash,
            "operation_id": operation_id,
            "preparation": prepared,
        }
    )
    frozen = FrozenAttempt(
        novel_id=str(novel_id),
        run_id=run_key,
        attempt_id=supplemental_attempt_id,
        owner_epoch=run.owner_epoch,
        producer_version="evolution_world_audit_supplement_v1",
        source_manifest_hash=manifest_hash,
        previous_receipt=head.attempt_id if head else None,
        previous_committed_prefix=head.committed_prefix if head else None,
        payload={
            "world_audit_supplement": True,
            "world_audit_origin_attempt_id": origin_attempt_id,
            "scene_index": scene_index,
            "scene_text": origin.payload["scene_text"],
            "source_binding": source.model_dump(mode="json"),
            "world_review_preparation": prepared,
            "world_audit_reviews": {},
            "world_audit_applied_groups": {},
            "world_audit_result_refs": [],
            "world_audit_status": "pending",
        },
    )
    await store.save_frozen(frozen)
    added_budget = max(0, len(call_groups) - run.budget_remaining)
    run.budget_total += added_budget
    run.budget_remaining += added_budget
    queued = await enqueue_operation_task(
        db,
        operation_id=operation_id,
        task_type="evolution_world_audit_supplement_v1",
        novel_id=str(novel_id),
        request_payload={
            "run_key": run_key,
            "origin_attempt_id": origin_attempt_id,
            "attempt_id": supplemental_attempt_id,
            "fingerprint": fingerprint,
        },
        meta={
            "novel_id": str(novel_id),
            "run_key": run_key,
            "origin_attempt_id": origin_attempt_id,
            "supplement_attempt_id": supplemental_attempt_id,
        },
    )
    run.reading_plan_json = {
        **plan,
        "world_audit_supplements": [
            *plan.get("world_audit_supplements", []),
            {
                "operation_id": operation_id,
                "origin_attempt_id": origin_attempt_id,
                "supplement_attempt_id": supplemental_attempt_id,
                "fingerprint": fingerprint,
                "task_id": str(queued.task_id),
                "status": "pending",
                "call_count": len(call_groups),
                "group_count": len(prepared["groups"]),
                "budget_added": added_budget,
            },
        ],
    }
    await db.commit()
    return {
        "task_id": str(queued.task_id),
        "attempt_id": supplemental_attempt_id,
        "status": str(queued.status),
        "budget_added": added_budget,
    }


async def resume_world_audit_supplement(db, novel_id, run_key, origin_attempt_id):
    await require_active_project_exclusive(db, str(novel_id))
    store = PostgresAttemptStore(db, novel_id)
    run = await store.load_run(run_key, for_update=True)
    if not run or run.status != "active":
        raise ConflictError("理解运行已停止或失效，不能恢复补审")
    await store.require_project_owner(run_key)
    entry = next(
        (
            item
            for item in (run.reading_plan_json or {}).get("world_audit_supplements", [])
            if item.get("origin_attempt_id") == origin_attempt_id
        ),
        None,
    )
    if not entry or not entry.get("task_id"):
        raise NotFoundError("未找到可恢复的延后场景补审")
    frozen = await store.load_frozen(run_key, entry["supplement_attempt_id"])
    origin = await store.load_frozen(run_key, origin_attempt_id)
    lifecycle = (
        await list_task_lifecycle_contracts(
            db, task_ids=[entry["task_id"]], novel_id=str(novel_id), max_heartbeat_gap=120
        )
    ).get(entry["task_id"])
    crashed_recoverable = bool(
        lifecycle
        and lifecycle.recovery_required
        and lifecycle.status not in {"pending", "running"}
    )
    if (
        not frozen
        or not origin
        or (
            frozen.payload.get("world_audit_status") != "failed"
            and not crashed_recoverable
        )
        or has_unreconciled_scene_calls(frozen.payload)
        or _has_unknown_world_audit_result(frozen.payload)
    ):
        raise ConflictError("补审结果尚未核清或不可恢复，请先核对请求状态")
    from modules.evolution.reading import require_current_world_candidate

    await require_current_world_candidate(
        db,
        str(novel_id),
        {"run_key": run_key, "attempt_id": origin_attempt_id},
    )
    lifecycle = await resume_manual_task(
        db,
        task_id=entry["task_id"],
        task_types={"evolution_world_audit_supplement_v1"},
        novel_id=str(novel_id),
    )
    await db.commit()
    return {"task_id": entry["task_id"], "status": lifecycle.status}


async def _save_payload(db, store, run_key, attempt_id, update):
    await store.require_project_owner(run_key)
    await store.load_run(run_key, for_update=True)
    frozen = await store.load_frozen(run_key, attempt_id)
    frozen = frozen.model_copy(update={"payload": update(frozen.payload)})
    await store.replace_frozen_payload(frozen)
    await db.commit()
    return frozen


async def _save_run_status(db, store, run_key, attempt_id, status):
    run = await store.load_run(run_key, for_update=True)
    plan = dict(run.reading_plan_json or {})
    plan["world_audit_supplements"] = [
        {
            **item,
            "status": status,
        }
        if item.get("supplement_attempt_id") == attempt_id
        else item
        for item in plan.get("world_audit_supplements", [])
    ]
    run.reading_plan_json = plan
    await db.commit()


async def handle_world_audit_supplement(db, task) -> dict[str, Any]:
    from modules.evolution.pipeline import _run_scene_call
    from modules.evolution.reading import require_current_world_candidate
    from modules.evolution.state_review import SceneCallFailedError
    from modules.evolution.store import BudgetExhaustedError
    from modules.evolution.world import (
        _world_group_issue,
        materialize_world_audit_group,
        world_group_apply_inputs,
    )

    meta = dict(task.meta or {})
    task_result = dict(task.result or {})
    novel_id = str(meta["novel_id"])
    run_key = meta["run_key"]
    origin_attempt_id = meta["origin_attempt_id"]
    attempt_id = meta["supplement_attempt_id"]
    store = PostgresAttemptStore(db, novel_id)
    frozen = await store.load_frozen(run_key, attempt_id)
    origin = await store.load_frozen(run_key, origin_attempt_id)
    if not frozen or not origin:
        raise NotFoundError("补审冻结记录已失效")
    source = SceneSourceBinding.model_validate(origin.payload["source_binding"])
    run = await store.load_run(run_key)
    if not run:
        raise NotFoundError("理解运行已失效")
    await _save_payload(
        db,
        store,
        run_key,
        attempt_id,
        lambda payload: {**payload, "world_audit_status": "running"},
    )
    await _save_run_status(db, store, run_key, attempt_id, "running")
    frozen = await store.load_frozen(run_key, attempt_id)
    prepared = frozen.payload["world_review_preparation"]

    async def call(**inputs):
        from modules.evolution.sampler import resolve_scene_sampler

        async with resolve_scene_sampler(
            provider="project_llm",
            novel_id=novel_id,
            db=db,
            llm_snapshot=run.llm_snapshot_json,
        ) as caller:
            await db.commit()
            return await caller.execute_world_request(**inputs)

    review_groups = dict(frozen.payload.get("world_audit_reviews") or {})
    budget_exhausted = False
    try:
        for planned in prepared["groups"]:
            group_id = planned["group_id"]
            if group_id in review_groups:
                continue
            if planned.get("deferred_reason"):
                review_groups[group_id] = {
                    "group_id": group_id,
                    "status": "blocked",
                    "review_kind": planned["deferred_reason"],
                    "candidate_count": planned["candidate_count"],
                    "audit_input_chars": planned["audit_input_chars"],
                    "issues": [
                        {"message": _world_group_issue(planned["deferred_reason"])}
                    ],
                }
            elif budget_exhausted:
                review_groups[group_id] = {
                    "group_id": group_id,
                    "status": "blocked",
                    "review_kind": "budget_exhausted",
                    "candidate_count": planned["candidate_count"],
                    "audit_input_chars": planned["audit_input_chars"],
                    "issues": [{"message": _world_group_issue("budget_exhausted")}],
                }
            else:
                journal_key = f"scene_world_review_group_{group_id}"
                journal = frozen.payload.get(journal_key) or {}
                if journal.get("stage") == "failed":
                    if not settled_output_failure(journal):
                        from modules.evolution.pipeline import (
                            SamplePendingReconciliationError,
                        )

                        raise SamplePendingReconciliationError(
                            journal_key,
                            "补审请求结果未知，先核对请求和费用，不能重发",
                        )
                    review_groups[group_id] = {
                        "group_id": group_id,
                        "status": "blocked",
                        "review_kind": "audit_failed",
                        "candidate_count": planned["candidate_count"],
                        "audit_input_chars": planned["audit_input_chars"],
                        "issues": [{"message": _world_group_issue("audit_failed")}],
                    }
                else:
                    await require_current_world_candidate(
                        db,
                        novel_id,
                        {"run_key": run_key, "attempt_id": origin_attempt_id},
                    )
                    if journal.get("stage") != "sampled":
                        try:
                            frozen = await _run_scene_call(
                                db,
                                store,
                                frozen,
                                source,
                                journal_key=journal_key,
                                inputs={
                                    "method": "imports.scene_world_review.group.v3",
                                    "attempt_id": attempt_id,
                                    "source_manifest_hash": frozen.source_manifest_hash,
                                    "previous_receipt": frozen.previous_receipt,
                                    **planned["spec"],
                                },
                                call_inputs=planned["spec"],
                                call=call,
                            )
                        except BudgetExhaustedError:
                            budget_exhausted = True
                            review_groups[group_id] = {
                                "group_id": group_id,
                                "status": "blocked",
                                "review_kind": "budget_exhausted",
                                "candidate_count": planned["candidate_count"],
                                "audit_input_chars": planned["audit_input_chars"],
                                "issues": [
                                    {"message": _world_group_issue("budget_exhausted")}
                                ],
                            }
                        except SceneCallFailedError:
                            frozen = await store.load_frozen(run_key, attempt_id)
                            if not settled_output_failure(
                                frozen.payload.get(journal_key) or {}
                            ):
                                raise
                            review_groups[group_id] = {
                                "group_id": group_id,
                                "status": "blocked",
                                "review_kind": "audit_failed",
                                "candidate_count": planned["candidate_count"],
                                "audit_input_chars": planned["audit_input_chars"],
                                "issues": [
                                    {"message": _world_group_issue("audit_failed")}
                                ],
                            }
                    if group_id not in review_groups:
                        journal = frozen.payload[journal_key]
                        review = materialize_world_audit_group(planned, journal["result"])
                        review_groups[group_id] = {
                            "group_id": group_id,
                            "status": review["status"],
                            "review_kind": "completed"
                            if review["status"] == "passed"
                            else "blocked",
                            "candidate_count": planned["candidate_count"],
                            "audit_input_chars": planned["audit_input_chars"],
                            "issues": review.get("issues", []),
                            "review": review,
                        }
            frozen = await _save_payload(
                db,
                store,
                run_key,
                attempt_id,
                lambda payload: {
                    **payload,
                    "world_audit_reviews": review_groups,
                },
            )

        applied = dict(frozen.payload.get("world_audit_applied_groups") or {})
        resolved_new_refs = {
            ref for item in applied.values() for ref in item.get("resolved_new_refs", [])
        }
        origin_result = origin.payload["world_result"]
        for planned in sorted(
            prepared["groups"],
            key=lambda item: (
                not any(member["path"] == "entities" for member in item["members"]),
                item["group_id"],
            ),
        ):
            group_id = planned["group_id"]
            review = review_groups[group_id]
            if review["status"] != "passed" or group_id in applied:
                continue
            await require_current_world_candidate(
                db,
                novel_id,
                {"run_key": run_key, "attempt_id": origin_attempt_id},
            )
            inputs = world_group_apply_inputs(origin_result, planned, resolved_new_refs)
            if inputs is None:
                applied[group_id] = {
                    "pending": ["scene_world_group_dependency_pending"],
                    "result_refs": [],
                    "resolved_new_refs": [],
                }
            else:
                result = await apply_scene_world_candidates(
                    db,
                    novel_id,
                    scene_id=origin.payload["scene_id"],
                    scene_index=origin.payload["scene_index"],
                    chapter_index=source.ranges()[-1].chapter_index,
                    workflow_id=run_key,
                    attempt_id=origin_attempt_id,
                    **inputs,
                )
                new_refs = list(inputs["context"].get("_new_entity_refs", {}))
                resolved_new_refs.update(new_refs)
                applied[group_id] = {
                    "pending": result["pending"],
                    "result_refs": result["result_refs"],
                    "resolved_new_refs": new_refs,
                }
            frozen = await _save_payload(
                db,
                store,
                run_key,
                attempt_id,
                lambda payload: {
                    **payload,
                    "world_audit_applied_groups": applied,
                    "world_audit_result_refs": list(
                        {
                            (ref.get("type"), ref.get("id")): ref
                            for item in applied.values()
                            for ref in item.get("result_refs", [])
                        }.values()
                    ),
                },
            )

        frozen = await _save_payload(
            db,
            store,
            run_key,
            attempt_id,
            lambda payload: {**payload, "world_audit_status": "completed"},
        )
        await _save_run_status(db, store, run_key, attempt_id, "completed")
    except (Exception, asyncio.CancelledError) as error:
        await db.rollback()
        current = await store.load_frozen(run_key, attempt_id)
        current_run = await store.load_run(run_key)
        unreconciled = bool(
            current
            and (
                has_unreconciled_scene_calls(current.payload)
                or _has_unknown_world_audit_result(current.payload)
            )
        )
        status = "needs_reconciliation" if unreconciled else "failed"
        await _save_payload(
            db,
            store,
            run_key,
            attempt_id,
            lambda payload: {**payload, "world_audit_status": status},
        )
        await _save_run_status(db, store, run_key, attempt_id, status)
        recoverable = bool(
            status == "failed"
            and current_run
            and current_run.status == "active"
            and not isinstance(error, (ConflictError, NotFoundError))
        )
        task.meta = {**meta, "recovery_required": recoverable}
        task.result = {
            **task_result,
            "recovery_required": recoverable,
            "recoverable": recoverable,
        }
        if not await db.checkpoint_task_progress():
            raise asyncio.CancelledError
        if recoverable and isinstance(error, asyncio.CancelledError):
            raise RuntimeError("补审任务中断，已保存结果可恢复") from error
        raise
    return {
        "run_key": run_key,
        "origin_attempt_id": origin_attempt_id,
        "supplement_attempt_id": attempt_id,
        "status": frozen.payload["world_audit_status"],
        "reviewed_groups": len(review_groups),
        "world_result_refs": frozen.payload["world_audit_result_refs"],
    }
