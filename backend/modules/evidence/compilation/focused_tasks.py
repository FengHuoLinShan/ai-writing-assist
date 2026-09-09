"""Owner-scoped, textless task receipts for resumable focused evidence reads."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Literal

from pydantic import Field

from core.errors import NotFoundError, ValidationError
from infrastructure.tasks.facade import (
    enqueue_coalesced_task,
    get_completed_task_payload,
    list_task_lifecycle_contracts,
    require_running_task_attempt,
    require_task_checkpoint_session,
    resume_manual_task,
)
from infrastructure.tasks.registry import task_handler
from modules.evidence.compilation.contracts import CompileOptions
from modules.evidence.compilation.focused_contracts import (
    FocusedEvidenceRequest,
    FocusedEvidenceResult,
    FocusedEvidenceRoot,
    FocusedModel,
)
from modules.evidence.compilation.schemas import ContextSelectionRefRequest
from modules.evidence.compilation.services.focused_evidence import (
    NOMINATION_TIMEOUT_SECONDS,
    FocusedEvidenceService,
    _digest,
    _visibility,
)
from modules.project.contracts import ProjectLLMConfigurationError
from modules.project.facade import (
    build_project_llm_execution_snapshot,
    create_project_snapshot_llm_client,
    require_active_project,
    require_active_project_exclusive,
    restore_project_llm_execution_settings,
)
from shared.constants import TASK_MAX_HEARTBEAT_GAP

FOCUSED_TASK = "evidence_focused_search"


class FocusedSearchSubmit(FocusedModel):
    novel_id: str
    roots: list[FocusedEvidenceRoot] = Field(min_length=1, max_length=1000)
    question: str = Field(min_length=1, max_length=2000)
    chapter_from: int | None = Field(default=None, ge=1)
    chapter_to: int | None = Field(default=None, ge=1)
    content_mode: Literal["canonical", "working"] = "canonical"
    scene_id: str | None = None
    chapter_index: int | None = Field(default=None, ge=1)
    max_depth: Literal[0, 1] = 1
    consumer: Literal["writing", "map", "author"] = "author"
    sources: list[Literal["manuscript", "world", "outline"]] = Field(
        default_factory=lambda: ["manuscript", "world", "outline"], min_length=1
    )
    excluded_refs: list[ContextSelectionRefRequest] = Field(
        default_factory=list, max_length=1000
    )
    pinned_refs: list[ContextSelectionRefRequest] = Field(
        default_factory=list, max_length=1000
    )


async def submit_focused_search(db, data: FocusedSearchSubmit):
    await require_active_project(db, data.novel_id)
    character_id = None
    if data.scene_id:
        from modules.story.facade import get_scene_contract, get_scene_spans_for_scene

        scene = await get_scene_contract(db, data.novel_id, data.scene_id)
        if scene is None:
            raise NotFoundError("Scene not found")
        scene = asdict(scene) if is_dataclass(scene) else scene
        chapters = {
            int(value) for value in scene.get("chapter_ids", []) if str(value).isdigit()
        }
        chapters.update(
            int(span["chapter_index"])
            for span in scene.get("scene_chunks", [])
            if isinstance(span, dict) and str(span.get("chapter_index", "")).isdigit()
        )
        spans = await get_scene_spans_for_scene(
            db, data.novel_id, data.scene_id, content_mode=data.content_mode
        )
        chapters.update(span.chapter_index for span in spans)
        if data.chapter_index is None or data.chapter_index not in chapters:
            raise ValidationError("当前章节与场景不一致或尚无可验证映射")
        if data.consumer == "writing":
            character_id = scene.get("pov_character_id")
    action = {
        "writing": "writing.focused_search",
        "map": "world.map_atlas.focused_search",
        "author": "evidence.focused_search",
    }[data.consumer]
    options = CompileOptions(
        novel_id=data.novel_id,
        task=data.question,
        scope="scene" if data.scene_id else "full",
        consumer_action=action,
        content_mode=data.content_mode,
        context_mode=data.content_mode,
        include_pending_objects=False,
        scene_id=data.scene_id,
        chapter_index=data.chapter_index,
        reveal_mode="character" if character_id else "author_safe",
        viewpoint_character_id=character_id,
        visible_until_chapter=data.chapter_index if data.consumer == "writing" else None,
        visible_until_scene_id=data.scene_id,
        pinned_refs=[item.model_dump() for item in data.pinned_refs],
        excluded_refs=[item.model_dump() for item in data.excluded_refs],
    )
    request = FocusedEvidenceRequest(
        novel_id=data.novel_id,
        roots=data.roots,
        question=data.question,
        compile_options=options,
        chapter_from=data.chapter_from,
        chapter_to=data.chapter_to,
        max_depth=data.max_depth,
        sources=data.sources,
    )
    service = FocusedEvidenceService()
    visibility, _ = await service.evidence.resolve_visibility_cursor(
        db,
        novel_id=request.novel_id,
        content_mode=options.content_mode,
        visibility=_visibility(request),
    )
    descriptors = await service._manifest(db, request, visibility)
    request.compile_options.source_manifest = {
        item["draft_id"]: item["source_hash"] for item in descriptors
    }
    snapshot = None
    if data.max_depth:
        try:
            snapshot = await build_project_llm_execution_snapshot(db, data.novel_id)
        except ProjectLLMConfigurationError:
            # Literal and database retrieval remain useful without a model connection.
            pass
    return await _enqueue(db, request, snapshot)


async def _enqueue(db, request, snapshot, *, predecessor=None, prior_evidence=None):
    payload = request.model_dump(mode="json")
    receipt = await enqueue_coalesced_task(
        db,
        task_type=FOCUSED_TASK,
        novel_id=request.novel_id,
        scope=("focused", _digest(payload), predecessor or "initial"),
        meta={
            "_focused_request": payload,
            "_llm_execution_snapshot": snapshot,
            "_focused_prior_evidence": prior_evidence or [],
        },
    )
    await db.flush()
    return {"task_id": receipt.task_id, "status": receipt.status}


async def _lifecycle(db, novel_id, task_id):
    await require_active_project(db, novel_id)
    rows = await list_task_lifecycle_contracts(
        db,
        task_ids=[task_id],
        novel_id=novel_id,
        max_heartbeat_gap=TASK_MAX_HEARTBEAT_GAP,
    )
    task = rows.get(task_id)
    if task is None or task.task_type != FOCUSED_TASK:
        raise NotFoundError("专项查阅记录不存在")
    return task


async def get_focused_search(db, novel_id: str, task_id: str):
    lifecycle = await _lifecycle(db, novel_id, task_id)
    result = None
    can_resume = lifecycle.status in {"recoverable", "failed"}
    payload = await get_completed_task_payload(
        db, task_id=task_id, task_type=FOCUSED_TASK, novel_id=novel_id
    )
    if payload is not None:
        stored = payload.result
        request = FocusedEvidenceRequest.model_validate(stored["_focused_request"])
        result_model = FocusedEvidenceResult.model_validate(stored["_focused_result"])
        result_model = await FocusedEvidenceService().hydrate(db, request, result_model)
        can_resume = result_model.continuation is not None
        result = result_model.model_dump(mode="json", exclude={"continuation"})
        result["has_more"] = can_resume
        result["compiled_context"] = result_model.compiled_context
    return {
        "task_id": task_id,
        "status": ("recoverable" if can_resume else "completed")
        if payload is not None
        else lifecycle.status,
        "can_resume": can_resume,
        "result": result,
        "error": "专项查阅中断，可继续查阅"
        if lifecycle.status in {"failed", "recoverable"}
        else None,
    }


async def resume_focused_search(db, novel_id: str, task_id: str):
    lifecycle = await _lifecycle(db, novel_id, task_id)
    if lifecycle.status in {"pending", "running"}:
        return {"task_id": task_id, "status": lifecycle.status}
    payload = await get_completed_task_payload(
        db, task_id=task_id, task_type=FOCUSED_TASK, novel_id=novel_id
    )
    if payload is not None:
        stored = payload.result
        request = FocusedEvidenceRequest.model_validate(stored["_focused_request"])
        result = FocusedEvidenceResult.model_validate(stored["_focused_result"])
        if result.continuation is None:
            raise ValidationError("专项查阅已结束")
        await FocusedEvidenceService().revalidate(db, request, result)
        request.continuation = result.continuation
        return await _enqueue(
            db,
            request,
            stored.get("_llm_execution_snapshot"),
            predecessor=task_id,
            prior_evidence=[
                item.model_dump(mode="json", exclude={"text"}) for item in result.evidence
            ],
        )
    resumed = await resume_manual_task(
        db, task_id=task_id, task_types={FOCUSED_TASK}, novel_id=novel_id
    )
    return {"task_id": resumed.task_id, "status": resumed.status}


@task_handler(FOCUSED_TASK, recovery_policy="manual_resume", max_attempts=5)
async def handle_focused_search(db, task):
    require_task_checkpoint_session(db)
    request = FocusedEvidenceRequest.model_validate(
        (task.meta or {}).get("_focused_request")
    )
    if str(task.novel_id) != request.novel_id:
        raise ValidationError("focused search task scope mismatch")
    snapshot = (task.meta or {}).get("_llm_execution_snapshot")
    client = None
    if request.max_depth:
        try:
            if snapshot is None:
                snapshot = await build_project_llm_execution_snapshot(
                    db, request.novel_id
                )
            settings = await restore_project_llm_execution_settings(
                db, request.novel_id, snapshot
            )
            client = create_project_snapshot_llm_client(
                settings,
                novel_id=request.novel_id,
                timeout_override=NOMINATION_TIMEOUT_SECONDS - 60,
            )
        except ProjectLLMConfigurationError:
            # Restore failure never changes the frozen provider.
            # Deterministic retrieval can proceed without a model client.
            client = None

    async def checkpoint():
        await require_active_project(db, request.novel_id)
        await require_running_task_attempt(
            db,
            task_id=str(task.id),
            task_type=FOCUSED_TASK,
            novel_id=request.novel_id,
            lease_id=str(task.lease_id),
            attempt=int(task.attempt),
        )
        task.meta = {**dict(task.meta or {}), "_llm_execution_snapshot": snapshot}
        await db.commit()

    try:
        result = await FocusedEvidenceService().retrieve(
            db,
            request,
            llm_client=client,
            before_llm=checkpoint,
            nomination_enabled=client is not None,
        )
        await require_active_project_exclusive(db, request.novel_id)
        await require_running_task_attempt(
            db,
            task_id=str(task.id),
            task_type=FOCUSED_TASK,
            novel_id=request.novel_id,
            lease_id=str(task.lease_id),
            attempt=int(task.attempt),
        )
        await FocusedEvidenceService().revalidate(db, request, result)
        prior = (task.meta or {}).get("_focused_prior_evidence") or []
        from modules.evidence.compilation.focused_contracts import FocusedEvidenceItem

        all_items = {
            item["key"]: FocusedEvidenceItem.model_validate(item) for item in prior
        }
        all_items.update({item.key: item for item in result.evidence})
        result.evidence = list(all_items.values())
        result.selection_refs = [
            item.selection_ref for item in result.evidence if item.selection_ref
        ]
        serialized = result.model_dump(
            mode="json", exclude={"evidence": {"__all__": {"text"}}}
        )
        task.update_progress(1.0)
        return {
            "_focused_request": request.model_dump(mode="json"),
            "_focused_result": serialized,
            "_llm_execution_snapshot": snapshot,
        }
    finally:
        if client:
            await client.close()
