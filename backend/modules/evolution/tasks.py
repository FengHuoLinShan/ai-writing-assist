"""演化任务的 async_tasks 挂接（V4 E07.e）。

handler 走真实路径（返修 R2/R4/R6）：

- 来源绑定真实 Writing 草稿：按 ``chapter_index`` 取当前 working 草稿，
  内容指纹来自数据库而非任务负载声称；提交时再经同一来源重验。
- 身份候选经 world facade 精确名召回（只产生精确证据，模糊留作者裁定）。
- 恢复优先：本 Scene 已有冻结 attempt 时先重放（T10 不重采样），没有
  才走全新采样步。
- 采样器经 ``sampler.resolve_scene_sampler`` 以 async context manager
  持有；provider 计量回执进入 ApplierResult 的 paid_call_receipts。

入口重定向（前端与 deep_import API 改调本任务）按计划排在 canary 验证
之后；当前注册 handler 不产生任何流量。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.tasks.facade import enqueue_coalesced_task
from infrastructure.tasks.registry import task_handler


class EvolutionSceneStepRequest(BaseModel):
    """evolution_scene_step 任务的 secret-free 请求负载。"""

    model_config = ConfigDict(extra="forbid")

    novel_id: str = Field(min_length=1)
    run_key: str = Field(min_length=1, max_length=120)
    scene_index: int = Field(ge=0)
    scene_text: str = Field(min_length=1)
    scene_id: str = Field(min_length=1)
    chapter_index: int = Field(ge=1)
    budget_total: int = Field(default=10, ge=0)
    execution_mode: str = Field(default="live", pattern="^(live|shadow)$")
    sampler_provider: str = Field(default="project_llm")


@task_handler("evolution_scene_step", recovery_policy="manual_resume")
async def handle_evolution_scene_step(db: AsyncSession, task) -> dict[str, Any]:
    """执行一个演化场景步并返回回执摘要（真实路径，采样器 fail-closed）。"""
    from modules.evolution.commit import ApplierResult
    from modules.evolution.contracts import CommittedPrefix
    from modules.evolution.pipeline import (
        PipelineStepResult,
        SceneSourceBinding,
        exact_name_candidate_lookup,
        recover_scene_step,
        run_scene_step,
    )
    from modules.evolution.sampler import resolve_scene_sampler
    from modules.evolution.store import PostgresAttemptStore
    from modules.story.continuity.services import MemoryService
    from modules.writing.facade import get_latest_draft_for_chapter

    meta = dict(task.meta or {})
    meta.setdefault("novel_id", getattr(task, "novel_id", None) or meta.get("novel_id"))
    request = EvolutionSceneStepRequest(
        **{key: value for key, value in meta.items() if key in _REQUEST_FIELDS}
    )

    # 真实来源绑定（返修 R2）：指纹来自当前 working 草稿，不信任务负载。
    draft = await get_latest_draft_for_chapter(
        db, request.novel_id, request.chapter_index
    )
    if draft is None:
        raise ValueError(
            f"chapter {request.chapter_index} has no working draft; "
            "refusing to sample unbound scene text"
        )
    binding = SceneSourceBinding(
        draft_id=str(draft.id),
        chapter_index=request.chapter_index,
        content_hash=str(draft.content_hash),
    )

    store = PostgresAttemptStore(db, request.novel_id)
    await store.register_run(
        request.run_key,
        mode="append",
        budget_total=request.budget_total,
        execution_mode=request.execution_mode,
    )

    async def applier(db_session, frozen) -> ApplierResult:
        events = [
            {**event, "source": "evolution"}
            for event in (frozen.payload or {}).get("scene_events") or []
        ]
        await MemoryService().record_scene_events(
            db_session,
            request.novel_id,
            scene_id=request.scene_id,
            scene_index=request.scene_index,
            chapter_index=request.chapter_index,
            events=events,
            producer_family="evolution",
        )
        return ApplierResult(
            committed_prefix=CommittedPrefix(
                through_scene_index=request.scene_index,
                through_source_revision=request.chapter_index,
            ),
            pending_decisions=[
                f"gated_scene_event:{event.get('event_type', 'unknown')}"
                for event in (frozen.payload or {}).get("gated_scene_events") or []
            ],
            paid_call_receipts=[
                frozen.payload["paid_call_receipt"]
                for _ in [1]
                if (frozen.payload or {}).get("paid_call_receipt")
            ],
        )

    # 恢复优先（返修 R4）：本 Scene 已提交时幂等重放原回执（T11）；
    # 已冻结未应用时重放冻结负载（T10 不重采样）；都没有才走全新采样步。
    committed = await store.load_scene_receipt(
        request.run_key, request.scene_index
    )
    if committed is not None:
        return {
            "run_key": request.run_key,
            "attempt_id": committed.attempt_id,
            "recovered": True,
            "committed_prefix": committed.committed_prefix.model_dump(mode="json"),
        }
    replayed = await recover_scene_step(
        db,
        store,
        run_key=request.run_key,
        scene_index=request.scene_index,
        applier=applier,
    )
    if replayed is not None:
        return {
            "run_key": request.run_key,
            "attempt_id": replayed.attempt_id,
            "recovered": True,
            "committed_prefix": replayed.committed_prefix.model_dump(mode="json"),
        }

    async with resolve_scene_sampler(
        provider=request.sampler_provider, novel_id=request.novel_id, db=db
    ) as sampler:
        result: PipelineStepResult = await run_scene_step(
            db,
            store,
            run_key=request.run_key,
            scene_index=request.scene_index,
            scene_text=request.scene_text,
            source=binding,
            sampler=sampler,
            applier=applier,
            identity_candidates=exact_name_candidate_lookup(db),
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
    enqueued = await enqueue_coalesced_task(
        db,
        task_type="evolution_scene_step",
        novel_id=request.novel_id,
        scope=[
            "evolution",
            request.run_key,
            str(request.scene_index),
            request.scene_text[:64],
        ],
        meta=request.model_dump(mode="json"),
        mode="reuse_active",
    )
    return {"task_id": str(enqueued.task_id), "status": str(enqueued.status)}
