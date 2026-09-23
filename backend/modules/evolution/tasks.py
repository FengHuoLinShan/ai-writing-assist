"""演化任务的 async_tasks 挂接（V4 E07.e）。

handler 走真实路径（返修 R2/R4/R6 + 2026-09-22 审查 A02/A08）：

- 来源绑定真实 Writing 草稿：按 ``chapter_index`` 取当前 working 草稿，
  内容指纹来自数据库而非任务负载声称；Scene/章映射经 outline_state 权威
  校验（scene_id 声称的章必须与请求章一致）；提交时再经同一来源重验。
- Scene 来源区间（A02）：``start_offset``/``end_offset`` 是章稿内码点
  区间，服务端按权威草稿切片与 scene_text 逐字比对，同一章可分多 Scene。
- 身份候选经 world facade 精确名召回（只产生精确证据，模糊留作者裁定）。
- 恢复优先（A08）：本 Scene 已提交且请求来源指纹一致时幂等重放原回执
  （T11 不重采样不扣费）；已冻结未应用时按阶段重放（T10）；修订请求
  指纹不同，不套用旧回执。
- 采样器经 ``sampler.resolve_scene_sampler`` 以 async context manager
  持有；provider 计量回执进入 ApplierResult 的 paid_call_receipts。

显式启用的逐场景理解入口调用本任务；旧 deep_import API 的全面重定向
仍在 canary 和兼容验收之后。
"""

from __future__ import annotations

import asyncio
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.tasks.facade import enqueue_coalesced_task
from infrastructure.tasks.registry import task_handler
from modules.evolution.state_review import SCENE_CALL_JOURNALS


class EvolutionSourceRange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chapter_index: int = Field(ge=1)
    start_offset: int = Field(default=0, ge=0)
    end_offset: int | None = Field(default=None, ge=0)


class EvolutionSceneStepRequest(EvolutionSourceRange):
    """evolution_scene_step 任务的 secret-free 请求负载。

    ``start_offset``/``end_offset`` 是 Scene 正文在章稿内的码点区间
    （A02；``end_offset=None`` 表示至章稿末尾，缺省绑定整章）。scene_text
    必须逐字等于服务端按权威草稿取出的该区间切片，请求独立声称的正文
    不作数。
    """

    model_config = ConfigDict(extra="forbid")

    novel_id: str = Field(min_length=1)
    run_key: str = Field(min_length=1, max_length=120)
    run_mode: Literal["bootstrap", "append", "revise", "scoped_recompute"] = "append"
    scene_index: int = Field(ge=0)
    scene_text: str = Field(min_length=1)
    scene_id: str = Field(min_length=1)
    additional_sources: list[EvolutionSourceRange] = Field(
        default_factory=list, max_length=15
    )
    budget_total: int = Field(default=10, ge=0)
    execution_mode: str = Field(default="live", pattern="^(live|shadow)$")
    sampler_provider: str = Field(default="project_llm")
    source_revisions: list[dict[str, str]] = Field(default_factory=list, max_length=16)
    state_review_version: Literal[0, 1] = 1
    enrichment_version: Literal[0, 1] = 0
    world_version: Literal[0, 1, 2] = 0


@task_handler("evolution_scene_step_v2", recovery_policy="manual_resume")
async def handle_evolution_scene_step(db: AsyncSession, task) -> dict[str, Any]:
    meta = dict(task.meta or {})
    novel_id = str(meta.get("novel_id") or task.novel_id)
    try:
        if meta.get("operation") == "prepare_scenes":
            from modules.evolution.preparation import prepare_scenes

            result = await prepare_scenes(db, novel_id, meta["run_key"])
        elif meta.get("operation") == "structure":
            from modules.evolution.structure import prepare_structure

            result = await prepare_structure(db, novel_id, meta["run_key"])
        else:
            result = await _execute_scene_step(db, task)
        from modules.evolution.workflow import advance_reading

        result.update(await advance_reading(db, novel_id, result["run_key"]))
        return result
    except (Exception, asyncio.CancelledError) as error:
        from modules.evolution.store import BudgetExhaustedError, PostgresAttemptStore

        if isinstance(error, BudgetExhaustedError):
            await db.rollback()
            store = PostgresAttemptStore(db, novel_id)
            await store.require_project_owner(meta["run_key"])
            run = await store.load_run(meta["run_key"], for_update=True)
            if run and run.reading_plan_json:
                run.reading_plan_json = {
                    **run.reading_plan_json,
                    "pause_reason": "budget",
                }
                await db.commit()
                return {"run_key": run.run_key, "reading_complete": False}
        if getattr(db, "task_progress_checkpoint_enabled", False) is True:
            from modules.evolution.commit import CommitConflictError
            from modules.evolution.store import PostgresAttemptStore

            # Domain rollback must precede the worker's independent, lease-fenced
            # checkpoint: task is detached, so assigning flags alone loses them.
            await db.rollback()
            store = PostgresAttemptStore(db, novel_id)
            run = await store.load_run(meta["run_key"])
            preparing = meta.get("operation") in {"prepare_scenes", "structure"}
            pending = (
                await store.load_pending_frozen(meta["run_key"], meta["scene_index"])
                if not preparing
                else None
            )
            committed = (
                await store.load_committed_scene_receipt(
                    meta["run_key"], meta["scene_index"]
                )
                if not preparing
                else None
            )
            recoverable = bool(
                run
                and run.status == "active"
                and not (
                    isinstance(error, CommitConflictError)
                    and error.code
                    in {
                        "invalid_observation_source",
                        "scene_changed",
                        "world_identity_changed",
                    }
                )
                and (
                    committed
                    or (
                        pending
                        and pending.payload.get("stage")
                        in {"sampled", "compiled", "verified"}
                        and all(
                            (pending.payload.get(key) or {}).get("stage")
                            not in {"sampling", "failed"}
                            for key in SCENE_CALL_JOURNALS
                        )
                    )
                    or (
                        not pending and run.budget_remaining > 0 and run.llm_snapshot_json
                    )
                )
            )
            if preparing and run and run.status == "active":
                stage = run.reading_plan_json.get(
                    "structure"
                    if meta.get("operation") == "structure"
                    else "preparation",
                    {},
                )
                calls = (
                    (stage.get("current") or {}).get("calls", {})
                    if meta.get("operation") == "structure"
                    else stage.get("calls", {})
                )
                recoverable = bool(run.llm_snapshot_json) and all(
                    item["stage"] not in {"sampling", "failed"} for item in calls.values()
                )
            await db.rollback()
            task.meta = {**meta, "recovery_required": recoverable}
            task.result = {
                **(task.result or {}),
                "recovery_required": recoverable,
                "recoverable": recoverable,
            }
            if not await db.checkpoint_task_progress():
                raise asyncio.CancelledError
            if recoverable and isinstance(error, asyncio.CancelledError):
                # Shutdown interrupted a still-owned task. A user/owner stop
                # revokes its lease and fails the checkpoint above instead.
                raise RuntimeError("理解任务中断，已保存结果可恢复") from error
        raise


async def _execute_scene_step(db: AsyncSession, task) -> dict[str, Any]:
    """执行一个演化场景步并返回回执摘要（真实路径，采样器 fail-closed）。"""
    from infrastructure.llm.collaboration import content_hash
    from modules.evolution.commit import ApplierResult, CommitConflictError
    from modules.evolution.contracts import CommittedPrefix
    from modules.evolution.pipeline import (
        PipelineStepResult,
        SceneSourceBinding,
        SceneSourceRange,
        compute_scene_manifest_hash,
        exact_name_candidate_lookup,
        recover_scene_step,
        run_scene_step,
    )
    from modules.evolution.sampler import resolve_scene_sampler
    from modules.evolution.store import PostgresAttemptStore
    from modules.story.facade import replace_scene_memory_events
    from modules.story.outline_state.facade import get_scene_contract
    from modules.writing.facade import get_latest_draft_for_chapter

    meta = dict(task.meta or {})
    meta.setdefault("novel_id", getattr(task, "novel_id", None) or meta.get("novel_id"))
    request = EvolutionSceneStepRequest(
        **{
            "state_review_version": 0,
            **{key: value for key, value in meta.items() if key in _REQUEST_FIELDS},
        }
    )

    # Scene/章映射权威校验（A02）：不信任请求独立声称的 scene_id 与章号
    # 组合——场景在 outline_state 里的章归属是权威。
    scene = await get_scene_contract(db, request.novel_id, request.scene_id)
    if scene is None:
        raise ValueError(
            f"scene {request.scene_id} not found; refusing unbound scene step"
        )
    if scene.scene_index != request.scene_index:
        raise ValueError("scene_index does not match Scene")
    requested_sources = [
        EvolutionSourceRange(
            chapter_index=request.chapter_index,
            start_offset=request.start_offset,
            end_offset=request.end_offset,
        ),
        *request.additional_sources,
    ]
    scene_chapters = {str(chapter) for chapter in scene.chapter_ids or []}
    if any(str(part.chapter_index) not in scene_chapters for part in requested_sources):
        raise ValueError(
            f"requested chapter is not part of scene "
            f"{request.scene_id} (chapters={scene.chapter_ids}); refusing "
            "scene/chapter mismatch"
        )

    # 真实来源绑定（返修 R2 + A02）：指纹与区间锚定当前 working 草稿，
    # 不信任务负载；scene_text 是否逐字等于权威切片由管线判定。
    bindings = []
    for part in requested_sources:
        draft = await get_latest_draft_for_chapter(
            db, request.novel_id, part.chapter_index
        )
        if draft is None:
            raise ValueError(
                f"chapter {part.chapter_index} has no working draft; "
                "refusing to sample unbound scene text"
            )
        bindings.append(
            SceneSourceRange(
                draft_id=str(draft.id),
                content_hash=str(draft.content_hash),
                **part.model_dump(),
            )
        )
    binding = SceneSourceBinding(
        **bindings[0].model_dump(), additional_sources=bindings[1:]
    )
    if request.source_revisions and request.source_revisions != [
        {"draft_id": part.draft_id, "content_hash": part.content_hash}
        for part in bindings
    ]:
        raise CommitConflictError("source_changed", "queued source revision changed")

    store = PostgresAttemptStore(db, request.novel_id)
    run = await store.register_run(
        request.run_key,
        mode=request.run_mode,
        budget_total=request.budget_total,
        execution_mode=request.execution_mode,
    )

    async def applier(db_session, frozen) -> ApplierResult:
        from modules.evolution.state_review import paid_call_receipts

        gated = frozen.payload.get("gated_scene_events") or []
        enrichment = frozen.payload.get("enrichment_result")
        enrichment_pending = []
        if enrichment:
            from modules.imports.facade import scene_enrichment_update
            from modules.story.facade import apply_scene_understanding_enrichment

            card = frozen.payload["scene_card"]
            update = scene_enrichment_update(card, enrichment, request.run_key)
            await apply_scene_understanding_enrichment(
                db_session,
                request.novel_id,
                request.scene_id,
                expected_scene_hash=content_hash(card),
                data=update,
            )
            if set(update) == {"structure_meta"}:
                enrichment_pending = ["scene_enrichment_requires_review"]
        world_result = {"result_refs": [], "pending": []}
        if frozen.payload.get("world_result"):
            from modules.imports.contracts import SceneWorldIdentityChangedError
            from modules.imports.facade import apply_scene_world_candidates

            try:
                world_result = await apply_scene_world_candidates(
                    db_session,
                    request.novel_id,
                    scene_id=request.scene_id,
                    scene_index=request.scene_index,
                    chapter_index=requested_sources[-1].chapter_index,
                    workflow_id=request.run_key,
                    attempt_id=frozen.attempt_id,
                    **frozen.payload["world_result"],
                )
            except SceneWorldIdentityChangedError as error:
                raise CommitConflictError("world_identity_changed", str(error)) from error
            # Domain identities and their content become history only alongside
            # this Scene's receipt, never from later reads of mutable World rows.
            await store.replace_frozen_payload(
                frozen.model_copy(
                    update={
                        "payload": {
                            **frozen.payload,
                            "world_materialization": {
                                "relations": world_result.get("relation_snapshots", []),
                                "diagnostics": world_result.get("diagnostics", []),
                            },
                        }
                    }
                )
            )

        events = [
            {**event, "source": "evolution"}
            for event in (frozen.payload or {}).get("scene_events") or []
        ]
        await replace_scene_memory_events(
            db_session,
            request.novel_id,
            scene_id=request.scene_id,
            scene_index=request.scene_index,
            chapter_index=requested_sources[-1].chapter_index,
            events=events,
            producer_family="evolution",
        )
        pending = (
            [
                f"gated_scene_event:{event.get('event_type', 'unknown')}"
                for event in gated[:62]
            ]
            + (
                [f"gated_scene_events_remaining:{len(gated) - 62}"]
                if len(gated) > 62
                else []
            )
            + enrichment_pending
            + world_result["pending"]
        )
        if len(pending) > 64:
            pending = [*pending[:63], f"pending_decisions_remaining:{len(pending) - 63}"]
        return ApplierResult(
            committed_prefix=CommittedPrefix(
                through_scene_index=request.scene_index,
                through_source_revision=requested_sources[-1].chapter_index,
            ),
            world_result_refs=world_result["result_refs"],
            pending_decisions=pending,
            paid_call_receipts=paid_call_receipts(frozen.payload),
        )

    # 恢复优先（返修 R4 + A08）：本 Scene 已提交且来源指纹一致时幂等重放
    # 原回执（T11 不重采样不扣费；修订请求指纹不同不套用旧回执）；已冻结
    # 未应用时按阶段重放（T10）；都没有才走全新采样步。
    request_hash = compute_scene_manifest_hash(
        request.run_key,
        request.scene_index,
        request.scene_text,
        binding,
    )
    committed = await store.load_committed_scene_receipt(
        request.run_key,
        request.scene_index,
        source_manifest_hash=request_hash,
    )
    if committed is not None:
        frozen = await store.load_frozen(request.run_key, committed.attempt_id)
        if frozen is None or frozen.payload.get("scene_id") not in {
            None,
            request.scene_id,
        }:
            raise CommitConflictError(
                "request_changed", "receipt belongs to another scene"
            )
        return {
            "run_key": request.run_key,
            "attempt_id": committed.attempt_id,
            "recovered": True,
            "committed_prefix": committed.committed_prefix.model_dump(mode="json"),
        }

    async def review_states(**inputs):
        async with resolve_scene_sampler(
            provider=request.sampler_provider,
            novel_id=request.novel_id,
            db=db,
            llm_snapshot=run.llm_snapshot_json,
        ) as reviewer:
            await db.commit()  # resolving the frozen project connection reads the DB
            return await reviewer.verify_state_events(**inputs)

    async def call_scene_method(method, **inputs):
        async with resolve_scene_sampler(
            provider=request.sampler_provider,
            novel_id=request.novel_id,
            db=db,
            llm_snapshot=run.llm_snapshot_json,
        ) as caller:
            await db.commit()
            return await getattr(caller, method)(**inputs)

    replayed = await recover_scene_step(
        db,
        store,
        run_key=request.run_key,
        scene_index=request.scene_index,
        applier=applier,
        identity_candidates=exact_name_candidate_lookup(db),
        source_manifest_hash=request_hash,
        scene_id=request.scene_id,
        state_reviewer=review_states,
        scene_method_caller=call_scene_method,
    )
    if replayed is not None:
        return {
            "run_key": request.run_key,
            "attempt_id": replayed.attempt_id,
            "recovered": True,
            "committed_prefix": replayed.committed_prefix.model_dump(mode="json"),
        }

    async with resolve_scene_sampler(
        provider=request.sampler_provider,
        novel_id=request.novel_id,
        db=db,
        llm_snapshot=run.llm_snapshot_json,
    ) as sampler:
        from dataclasses import asdict

        from modules.evolution.enrichment import needs_enrichment

        card = asdict(scene)
        enrich = request.enrichment_version == 1 and needs_enrichment(card)
        result: PipelineStepResult = await run_scene_step(
            db,
            store,
            run_key=request.run_key,
            scene_index=request.scene_index,
            scene_text=request.scene_text,
            source=binding,
            scene_id=request.scene_id,
            sampler=sampler,
            applier=applier,
            identity_candidates=exact_name_candidate_lookup(db),
            state_review_version=request.state_review_version,
            state_reviewer=review_states,
            enrichment_version=1 if enrich else 0,
            world_version=request.world_version,
            scene_card=card if enrich else None,
            scene_method_caller=call_scene_method,
        )
    return {
        "run_key": request.run_key,
        "attempt_id": result.receipt_attempt_id,
        "committed_prefix": result.committed_prefix.model_dump(mode="json"),
        "observation_ids": result.observation_ids,
        "identity_outcomes": result.identity_outcomes,
        "gated_scene_events": len(result.gated_scene_events),
    }


_REQUEST_FIELDS = set(EvolutionSceneStepRequest.model_fields)


async def enqueue_evolution_scene_step(
    db: AsyncSession,
    request: EvolutionSceneStepRequest,
) -> dict[str, str]:
    """入队一个演化场景步（E07.e；实际入口重定向待 canary 后开放）。"""
    from infrastructure.llm.collaboration import content_hash
    from modules.evolution.commit import CommitConflictError
    from modules.evolution.store import PostgresAttemptStore
    from modules.project.facade import (
        build_project_llm_execution_snapshot,
        require_understanding_writer,
    )

    meta = request.model_dump(mode="json")
    if request.execution_mode == "live":
        meta["_understanding_owner"] = await require_understanding_writer(
            db, request.novel_id, engine="evolution"
        )
    store = PostgresAttemptStore(db, request.novel_id)
    existing = await store.load_run(request.run_key)
    snapshot = existing.llm_snapshot_json if existing else None
    if request.sampler_provider == "project_llm":
        if existing and not snapshot:
            raise CommitConflictError(
                "model_snapshot_missing", "旧运行没有冻结模型连接，请保留原成果并新建运行"
            )
        if not existing:
            snapshot = await build_project_llm_execution_snapshot(db, request.novel_id)
    await store.register_run(
        request.run_key,
        mode=request.run_mode,
        budget_total=request.budget_total,
        execution_mode=request.execution_mode,
        llm_snapshot=snapshot,
    )

    enqueued = await enqueue_coalesced_task(
        db,
        task_type="evolution_scene_step_v2",
        novel_id=request.novel_id,
        scope=[
            "evolution",
            request.run_key,
            str(request.scene_index),
            content_hash(request.model_dump(mode="json")),
        ],
        meta=meta,
        mode="reuse_active",
    )
    return {"task_id": str(enqueued.task_id), "status": str(enqueued.status)}
