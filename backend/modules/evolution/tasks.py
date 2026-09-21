"""演化任务的 async_tasks 挂接（V4 E07.e）。

handler 走真实路径：payload 校验、run 注册（单写者门禁）、预算、
`run_scene_step` 执行与回执摘要。采样器经 ``sampler.resolve_scene_sampler``
解析——未接线时 fail-closed。入口重定向（前端与 deep_import API 改调本
任务）按计划排在 canary 验证之后；当前注册 handler 不产生任何流量。
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
    from modules.evolution.pipeline import run_scene_step
    from modules.evolution.sampler import resolve_scene_sampler
    from modules.evolution.store import PostgresAttemptStore
    from modules.story.continuity.services import MemoryService

    meta = dict(task.meta or {})
    meta.setdefault("novel_id", getattr(task, "novel_id", None) or meta.get("novel_id"))
    request = EvolutionSceneStepRequest(
        **{key: value for key, value in meta.items() if key in _REQUEST_FIELDS}
    )
    sampler = resolve_scene_sampler(
        provider=request.sampler_provider, novel_id=request.novel_id
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
            {**event, "source": "evolution"} for event in frozen.payload["scene_events"]
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
            )
        )

    result = await run_scene_step(
        db,
        store,
        run_key=request.run_key,
        scene_index=request.scene_index,
        scene_text=request.scene_text,
        sampler=sampler,
        applier=applier,
    )
    return {
        "run_key": request.run_key,
        "attempt_id": result.receipt_attempt_id,
        "committed_prefix": result.committed_prefix.model_dump(mode="json"),
        "observation_ids": result.observation_ids,
        "identity_outcomes": result.identity_outcomes,
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
