"""Author-authorized, source-pinned sequential reading on the existing Scene queue."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select

from core.errors import ConflictError, NotFoundError
from infrastructure.llm.collaboration import content_hash
from infrastructure.tasks.facade import (
    list_task_lifecycle_contracts,
    resume_manual_task,
)
from modules.evolution.models import EvolutionRun
from modules.evolution.pipeline import SceneSourceBinding, load_current_source
from modules.evolution.state_review import SCENE_CALL_JOURNALS
from modules.evolution.store import PostgresAttemptStore
from modules.project.facade import (
    build_project_llm_execution_snapshot,
    get_understanding_engine,
    require_active_project,
    require_active_project_exclusive,
    require_understanding_writer,
)
from modules.story.facade import (
    get_scene_spans_for_scene,
    get_scenes_by_novel,
    validate_scene_source_ranges,
)
from modules.writing.facade import (
    list_effective_chapter_indices,
    list_latest_drafts_for_chapters,
)


class ReadingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation_id: UUID
    mode: Literal["bootstrap", "append", "continue", "revise", "scoped_recompute"] = (
        "bootstrap"
    )
    run_key: str | None = Field(default=None, min_length=1, max_length=120)
    from_scene_index: int | None = Field(default=None, ge=0)
    entity_id: UUID | None = None
    observation_id: str | None = Field(default=None, pattern="^[0-9a-f]{64}$")
    end_chapter: int = Field(ge=1)
    request_limit: int = Field(ge=1, le=1000)

    @model_validator(mode="after")
    def validate_scope(self):
        targets = sum(
            value is not None
            for value in (self.from_scene_index, self.entity_id, self.observation_id)
        )
        if targets and self.mode not in {"scoped_recompute", "revise"}:
            raise ValueError("重新核对目标只用于 scoped_recompute")
        if (self.entity_id or self.observation_id) and self.mode != "scoped_recompute":
            raise ValueError("对象与观察核对只用于 scoped_recompute")
        if self.mode == "scoped_recompute" and targets != 1:
            raise ValueError("请选择一个场景、对象或观察作为核对目标")
        return self


class ReadingStart(ReadingRequest):
    expected_fingerprint: str = Field(min_length=64, max_length=64)
    authorization_confirmed: Literal[True]


def _last_chapter(steps):
    return max(
        part.chapter_index
        for step in steps
        for part in SceneSourceBinding.model_validate(step["source_binding"]).ranges()
    )


async def _plan(db, novel_id, request):
    await require_understanding_writer(db, novel_id, engine="evolution")
    store = PostgresAttemptStore(db, novel_id)
    run = await store.load_run(request.run_key) if request.run_key else None
    if request.mode in {"revise", "scoped_recompute"}:
        return await _plan_recompute(db, novel_id, request, run, store)
    if request.mode == "continue":
        state = await reading_status(db, novel_id, request.run_key)
        if not run or state["run"]["status"] != "needs_budget":
            raise ConflictError("当前理解不需要追加额度，请读取最新进度")
        if request.end_chapter != state["run"]["end_chapter"]:
            raise ConflictError("追加额度不能改变已确认的正文范围")
        await store.require_project_owner(run.run_key)
        for step in run.reading_plan_json["steps"]:
            await _read_step(db, novel_id, step)
        from modules.evolution.preparation import read_preparation_sources

        if run.reading_plan_json.get("preparation"):
            await read_preparation_sources(
                db, novel_id, run.reading_plan_json["preparation"]
            )
        return {
            **run.reading_plan_json,
            "state_review_version": run.reading_plan_json.get("state_review_version", 0),
            "enrichment_version": run.reading_plan_json.get("enrichment_version", 0),
            "world_version": run.reading_plan_json.get("world_version", 0),
            "request": request.model_dump(
                mode="json", exclude={"expected_fingerprint", "authorization_confirmed"}
            ),
            "model_profile": run.llm_snapshot_json["profile"],
            "project_owner": await require_understanding_writer(
                db, novel_id, engine="evolution"
            ),
            "budget_remaining": run.budget_remaining,
        }, run.llm_snapshot_json
    if request.mode == "append":
        if not run or not run.reading_plan_json or run.status != "active":
            raise ConflictError("原理解已失效或不支持继续，请重新准备正文范围")
        await store.require_project_owner(run.run_key)
        previous = run.reading_plan_json
        if (
            not previous["steps"]
            or run.committed_scene_index != previous["steps"][-1]["scene_index"]
            or previous.get("preparation", {}).get("stage") not in {None, "complete"}
        ):
            raise ConflictError("请先完成或恢复当前理解范围")
        # Appending must retain the exact original prefix, including its Scene mapping.
        for step in previous["steps"]:
            await _read_step(db, novel_id, step)
        start_index = run.committed_scene_index + 1
        snapshot = run.llm_snapshot_json
        if not snapshot:
            raise ConflictError("旧理解没有冻结模型连接，请保留成果并重新准备")
    else:
        if request.run_key:
            raise ConflictError("首次理解不能复用另一运行的身份")
        start_index = 0
        snapshot = await build_project_llm_execution_snapshot(db, novel_id)
    plan = {
        "version": "evolution_reading.v1",
        "state_review_version": previous.get("state_review_version", 0) if run else 1,
        "enrichment_version": previous.get("enrichment_version", 0) if run else 1,
        "world_version": previous.get("world_version", 0) if run else 2,
        "request": request.model_dump(
            mode="json", exclude={"expected_fingerprint", "authorization_confirmed"}
        ),
        "steps": [],
        "model_profile": snapshot["profile"],
        "project_owner": await require_understanding_writer(
            db, novel_id, engine="evolution"
        ),
    }
    start_chapter = _last_chapter(previous["steps"]) + 1 if run else 1
    expected_chapters = [
        index
        for index in await list_effective_chapter_indices(db, novel_id)
        if start_chapter <= index <= request.end_chapter
    ]
    scenes = await get_scenes_by_novel(db, novel_id, status_filter=["draft", "canonical"])
    selected = []
    for scene in scenes:
        if scene["scene_index"] < start_index:
            continue
        chapters = [int(value) for value in scene["chapter_ids"]]
        if not chapters or min(chapters) > request.end_chapter:
            break
        if max(chapters) > request.end_chapter:
            raise ConflictError("所选范围截断了一个场景，请包含该场景的全部章节")
        selected.append(scene)
    chapter_indices = sorted({int(c) for scene in selected for c in scene["chapter_ids"]})
    if not expected_chapters:
        raise ConflictError("所选范围没有可读取的正文")
    if chapter_indices != expected_chapters[: len(chapter_indices)]:
        raise ConflictError("所选章节中间存在未整理的场景，不能跳过正文继续理解")
    plan["steps"] = await collect_scene_steps(
        db, novel_id, selected, start_index, chapter_indices
    )
    missing = expected_chapters[len(chapter_indices) :]
    if missing:
        next_index = start_index + len(selected)
        if any(scene["scene_index"] >= next_index for scene in scenes):
            raise ConflictError("正文中已有后续场景，请先核对缺失范围与场景顺序")
        from modules.evolution.preparation import plan_preparation

        plan["preparation"] = await plan_preparation(db, novel_id, missing, next_index)
        if len(plan["preparation"]["plan"]["windows"]) > request.request_limit:
            raise ConflictError("仅准备场景已超过本次调用上限，请缩小章节范围或调整上限")
    elif len(selected) > request.request_limit:
        raise ConflictError("所选场景超过本次调用上限，请缩小章节范围或调整上限")
    return plan, snapshot


async def _plan_recompute(db, novel_id, request, run, store):
    if (
        not run
        or not run.reading_plan_json
        or run.status not in {"active", "source_stale"}
    ):
        raise ConflictError("原理解不可用于重新核对，请读取最新进度")
    if not run.llm_snapshot_json or not run.reading_plan_json.get("steps"):
        raise ConflictError("原理解缺少冻结的来源或模型，不能继承")
    await store.require_project_owner(run.run_key)
    pairs = await store.load_committed_pairs(run.run_key)
    requested_start = request.from_scene_index
    target = None
    if request.entity_id or request.observation_id:
        kind = "entity" if request.entity_id else "observation"
        target_id = str(request.entity_id or request.observation_id)
        target = next(
            (item for item in _recompute_targets(pairs, kind) if item["id"] == target_id),
            None,
        )
        if target is None:
            raise ConflictError("所选对象或观察不在本次已提交的理解中，请重新选择")
        requested_start = target["scene_index"]
    old_steps = run.reading_plan_json["steps"]
    if request.end_chapter != (
        run.reading_plan_json.get("preparation", {})
        .get("sources", [{}])[-1]
        .get("chapter_index")
        if run.reading_plan_json.get("preparation")
        else _last_chapter(old_steps)
    ):
        raise ConflictError("重新核对须覆盖原理解的完整章节范围")
    scenes = await get_scenes_by_novel(db, novel_id, status_filter=["draft", "canonical"])
    selected = []
    for scene in scenes:
        chapters = [int(value) for value in scene["chapter_ids"]]
        if not chapters or min(chapters) > request.end_chapter:
            break
        if max(chapters) > request.end_chapter:
            raise ConflictError("所选范围截断了一个场景，请包含该场景的全部章节")
        selected.append(scene)
    expected_chapters = [
        index
        for index in await list_effective_chapter_indices(db, novel_id)
        if index <= request.end_chapter
    ]
    chapter_indices = sorted({int(c) for scene in selected for c in scene["chapter_ids"]})
    if chapter_indices != expected_chapters[: len(chapter_indices)]:
        raise ConflictError("所选章节中间存在未整理的场景，不能跳过正文")
    steps = await collect_scene_steps(db, novel_id, selected, 0, chapter_indices)
    first_change = next(
        (index for index, (old, new) in enumerate(zip(old_steps, steps)) if old != new),
        min(len(old_steps), len(steps)),
    )
    if request.mode == "revise" and first_change == len(old_steps) == len(steps):
        raise ConflictError("正文与场景未变化；如需重新核对，请指定场景范围")
    start_index = min(
        first_change,
        requested_start if requested_start is not None else first_change,
    )
    if start_index >= len(steps):
        raise ConflictError("没有可重新核对的场景")
    if len(pairs) < start_index:
        raise ConflictError("原理解尚未提交到可继承的前缀")
    latest = await store.latest_scene_attempts(
        {frozen.payload_json.get("scene_id") for _, frozen in pairs[:start_index]}
    )
    inherited, previous, observation_ids = [], None, set()
    for index, (receipt, frozen) in enumerate(pairs[:start_index]):
        payload = frozen.payload_json
        inputs = payload.get("input_manifest") or {}
        if (
            receipt.committed_scene_index != index
            or payload.get("scene_id") != steps[index]["scene_id"]
            or payload.get("source_binding") != steps[index]["source_binding"]
            or latest.get(payload.get("scene_id"))
            != (receipt.run_key, receipt.attempt_key)
            or payload.get("execution_mode") != "live"
            or inputs.get("run_key") != receipt.run_key
            or inputs.get("scene_index") != index
            or inputs.get("dependency_status") != "committed"
            or inputs.get("source_manifest_hash") != frozen.source_manifest_hash
            or frozen.previous_receipt != previous
            or inputs.get("previous_scene_attempt_id") != previous
            or any(
                item.get("observation_id") not in observation_ids
                for item in inputs.get("previous_observations", [])
            )
        ):
            raise ConflictError("原回执前缀或来源已变化，不能继承")
        previous = receipt.attempt_key
        observation_ids.update(
            item["observation_id"] for item in payload.get("compiled_observations", [])
        )
        inherited.append({"run_key": receipt.run_key, "attempt_id": receipt.attempt_key})
    missing = expected_chapters[len(chapter_indices) :]
    plan = {
        "version": "evolution_reading.v1",
        "state_review_version": 1,
        "enrichment_version": 1,
        "world_version": 2,
        "request": request.model_dump(
            mode="json", exclude={"expected_fingerprint", "authorization_confirmed"}
        ),
        "steps": steps,
        "inherited_receipts": inherited,
        "recompute_from_scene_index": start_index,
        "expanded_scope": requested_start is not None and start_index < requested_start,
        "recompute_target": target,
        "model_profile": run.llm_snapshot_json["profile"],
        "project_owner": await require_understanding_writer(
            db, novel_id, engine="evolution"
        ),
    }
    if missing:
        from modules.evolution.preparation import plan_preparation

        plan["preparation"] = await plan_preparation(db, novel_id, missing, len(steps))
    planned_calls = (
        len(steps)
        - start_index
        + len(plan.get("preparation", {}).get("plan", {}).get("windows", []))
    )
    if planned_calls > request.request_limit:
        raise ConflictError("依赖后续场景也需重新核对，请增大调用上限或缩小原范围")
    return plan, run.llm_snapshot_json


def _recompute_targets(pairs, kind):
    # ponytail: scan frozen receipts; add a derived index if long-book lookup is slow.
    targets = {}
    for receipt, frozen in pairs:
        for observation in frozen.payload_json.get("compiled_observations", []):
            if kind == "observation":
                candidates = [(observation["observation_id"], observation["predicate"])]
            else:
                candidates = [
                    (mention["resolution"]["resolved_entity_id"], mention["surface"])
                    for mention in observation.get("mentions", [])
                    if (mention.get("resolution") or {}).get("outcome") == "reuse"
                    and mention["resolution"].get("resolved_entity_id")
                ]
            for target_id, label in candidates:
                targets.setdefault(
                    target_id,
                    {
                        "id": target_id,
                        "kind": kind,
                        "label": label,
                        "scene_index": receipt.committed_scene_index,
                        "modality": observation["modality"],
                        "quote": observation["evidence_quotes"][0]["quote"],
                    },
                )
    return list(targets.values())


async def reading_targets(db, novel_id, run_key, *, kind, query="", offset=0, limit=50):
    await require_active_project(db, novel_id)
    store = PostgresAttemptStore(db, novel_id)
    run = await store.load_run(run_key)
    if not run or not run.reading_plan_json or run.execution_mode != "live":
        raise NotFoundError("未找到理解记录")
    items = _recompute_targets(await store.load_committed_pairs(run_key), kind)
    needle = query.strip().casefold()
    items = [item for item in items if needle in item["label"].casefold()]
    return {"items": items[offset : offset + limit], "total": len(items)}


async def collect_scene_steps(db, novel_id, selected, start_index, chapter_indices):
    if [item["scene_index"] for item in selected] != list(
        range(start_index, start_index + len(selected))
    ):
        raise ConflictError("场景顺序不连续，请先核对场景顺序")
    if (
        sorted({int(c) for scene in selected for c in scene["chapter_ids"]})
        != chapter_indices
    ):
        raise ConflictError("场景对应的章节与已确认范围不一致")
    drafts = {
        draft.chapter_index: draft
        for draft in await list_latest_drafts_for_chapters(db, novel_id, chapter_indices)
    }
    steps, coverage = [], {chapter: [] for chapter in chapter_indices}
    previous_end = (0, 0)
    for scene in selected:
        spans = await get_scene_spans_for_scene(
            db, novel_id, scene["id"], content_mode="working"
        )
        if not spans:
            spans = await get_scene_spans_for_scene(db, novel_id, scene["id"])
        parts = []
        for chapter in sorted(int(c) for c in scene["chapter_ids"]):
            draft = drafts.get(chapter)
            if not draft or not draft.content:
                raise ConflictError("场景对应的正文尚未保存")
            chapter_spans = [span for span in spans if span.chapter_index == chapter]
            if len(chapter_spans) > 1:
                raise ConflictError("场景在同章存在多个范围，请先核对场景边界")
            span = chapter_spans[0] if chapter_spans else None
            if span and span.mapping_status not in {
                "exact",
                "reanchored",
                "chapter_only",
            }:
                raise ConflictError("场景边界待修复，不能自动猜测正文范围")
            start = span.start_offset if span and span.start_offset is not None else 0
            end = (
                span.end_offset
                if span and span.end_offset is not None
                else len(draft.content)
            )
            if (chapter, start) < previous_end:
                raise ConflictError("场景顺序与正文位置不一致，请先核对场景边界")
            previous_end = (chapter, end)
            parts.append(
                {
                    "chapter_index": chapter,
                    "draft_id": str(draft.id),
                    "content_hash": draft.content_hash,
                    "start_offset": start,
                    "end_offset": end,
                }
            )
            coverage[chapter].append((start, end))
        binding = SceneSourceBinding(**parts[0], additional_sources=parts[1:])
        step = {
            "scene_id": scene["id"],
            "scene_index": scene["scene_index"],
            "source_binding": binding.model_dump(mode="json"),
        }
        await _read_step(db, novel_id, step)
        steps.append(step)
    for chapter, ranges in coverage.items():
        cursor = 0
        for start, end in sorted(ranges):
            if start < cursor or drafts[chapter].content[cursor:start].strip():
                raise ConflictError("场景之间有重叠或未覆盖正文，请先核对场景边界")
            cursor = end
        if drafts[chapter].content[cursor:].strip():
            raise ConflictError("场景尚未覆盖本章全部正文，请先核对场景边界")
    return steps


async def _read_step(db, novel_id, step):
    binding = SceneSourceBinding.model_validate(step["source_binding"])
    source = await load_current_source(db, novel_id, binding)
    if source is None:
        raise ConflictError("已选正文版本发生变化，请重新准备", code="source_changed")
    await validate_scene_source_ranges(
        db,
        novel_id,
        step["scene_id"],
        step["scene_index"],
        [part.model_dump(mode="json") for part in source[0].ranges()],
    )
    return source


async def preview_reading(db, novel_id, request):
    await require_active_project(db, novel_id)
    plan, _ = await _plan(db, novel_id, request)
    return {
        "fingerprint": content_hash(plan),
        "recompute_from_scene_index": plan.get("recompute_from_scene_index"),
        "inherited_scene_count": len(plan.get("inherited_receipts", [])),
        "expanded_scope": plan.get("expanded_scope", False),
        "recompute_target": plan.get("recompute_target"),
        "scene_count": None
        if plan.get("preparation", {}).get("stage") != "complete"
        and plan.get("preparation")
        else len(plan["steps"]),
        "preparation_windows": len(
            plan.get("preparation", {}).get("plan", {}).get("windows", [])
        ),
        "end_chapter": plan["preparation"]["sources"][-1]["chapter_index"]
        if plan.get("preparation")
        else _last_chapter(plan["steps"]),
        "request_limit": request.request_limit,
        "model": plan["model_profile"]["model"],
    }


async def start_reading(db, novel_id, request):
    await require_active_project_exclusive(db, novel_id)
    store = PostgresAttemptStore(db, novel_id)
    recompute = request.mode in {"revise", "scoped_recompute"}
    key = (
        f"reading-{request.operation_id}"
        if recompute
        else request.run_key or f"reading-{request.operation_id}"
    )
    existing = await store.load_run(key)
    segments = (existing.reading_plan_json or {}).get("segments", []) if existing else []
    for segment in segments:
        if segment["operation_id"] == str(request.operation_id):
            if ReadingStart.model_validate(segment["request"]).model_dump(
                mode="json"
            ) != request.model_dump(mode="json"):
                raise ConflictError("同一次操作的范围或授权已变化，请重新准备")
            return await reading_status(db, novel_id, key)
    plan, snapshot = await _plan(db, novel_id, request)
    if content_hash(plan) != request.expected_fingerprint:
        raise ConflictError("正文、场景、模型或理解进度已变化，请重新查看范围")
    if recompute:
        source = await store.load_run(request.run_key, for_update=True)
        old_task = (source.reading_plan_json or {}).get("task_id")
        if old_task:
            lifecycle = (
                await list_task_lifecycle_contracts(
                    db,
                    task_ids=[old_task],
                    novel_id=novel_id,
                    max_heartbeat_gap=120,
                )
            ).get(old_task)
            if lifecycle and lifecycle.status in {"pending", "running"}:
                raise ConflictError("原理解任务仍在运行或等待执行，请先结束它")
        if source.status == "active":
            await store.drain_run(source.run_key)
    run = await store.register_run(
        key,
        mode=existing.mode if existing else request.mode,
        budget_total=request.request_limit,
        llm_snapshot=snapshot,
    )
    previous = run.reading_plan_json or {}
    if existing:
        # Only a new append/continuation authorization adds budget; retries add nothing.
        run.budget_total += request.request_limit
        run.budget_remaining += request.request_limit
    run.reading_plan_json = {
        "version": plan["version"],
        "state_review_version": plan["state_review_version"],
        "enrichment_version": plan["enrichment_version"],
        "world_version": plan["world_version"],
        "preparation_history": [
            *previous.get("preparation_history", []),
            *(
                [previous["preparation"]]
                if request.mode == "append" and previous.get("preparation")
                else []
            ),
        ],
        "steps": plan["steps"]
        if request.mode == "continue"
        else [*previous.get("steps", []), *plan["steps"]]
        if not recompute
        else plan["steps"],
        **(
            {"inherited_receipts": plan["inherited_receipts"]}
            if recompute
            else {"inherited_receipts": previous["inherited_receipts"]}
            if previous.get("inherited_receipts")
            else {}
        ),
        **({"preparation": plan["preparation"]} if plan.get("preparation") else {}),
        "segments": [
            *segments,
            {
                "operation_id": str(request.operation_id),
                "request": request.model_dump(mode="json"),
                "project_owner": plan["project_owner"],
                "recompute_target": plan.get("recompute_target"),
                "expanded_scope": plan.get("expanded_scope", False),
                "first_scene_index": plan.get(
                    "recompute_from_scene_index", plan["steps"][0]["scene_index"]
                )
                if plan["steps"]
                else None,
                "last_scene_index": plan["steps"][-1]["scene_index"]
                if plan["steps"]
                else None,
            },
        ],
    }
    if recompute and plan["inherited_receipts"]:
        head = (await store.load_committed_pairs(request.run_key))[
            len(plan["inherited_receipts"]) - 1
        ][0]
        run.committed_scene_index = head.committed_scene_index
        run.committed_source_revision = head.committed_source_revision
        run.head_attempt_id = head.id
    await db.flush()
    await advance_reading(db, novel_id, key)
    return await reading_status(db, novel_id, key)


async def advance_reading(db, novel_id, run_key):
    store = PostgresAttemptStore(db, novel_id)
    run = await store.load_run(run_key)
    if not run or not run.reading_plan_json:
        return {}
    await require_active_project_exclusive(db, novel_id)
    await store.require_project_owner(run_key)
    run = await store.load_run(run_key, for_update=True)
    if run.status != "active":
        raise ConflictError("理解已停止或来源变化，请重新准备")
    plan = run.reading_plan_json
    if plan.get("preparation", {}).get("stage") not in {None, "complete"}:
        from modules.evolution.preparation import enqueue_preparation

        return await enqueue_preparation(db, novel_id, run)
    next_step = next(
        (
            step
            for step in plan["steps"]
            if step["scene_index"] > run.committed_scene_index
        ),
        None,
    )
    if next_step is None:
        if plan.get("structure_version") == 1:
            from modules.evolution.structure import enqueue_structure

            return await enqueue_structure(db, novel_id, run)
        return {"reading_complete": True}
    if run.budget_remaining <= 0:
        run.reading_plan_json = {**plan, "pause_reason": "budget"}
        await db.flush()
        return {"reading_complete": False}
    binding, scene_text = await _read_step(db, novel_id, next_step)
    from modules.evolution.tasks import (
        EvolutionSceneStepRequest,
        enqueue_evolution_scene_step,
    )

    parts = binding.ranges()
    request = EvolutionSceneStepRequest(
        novel_id=novel_id,
        run_key=run_key,
        run_mode=run.mode,
        scene_index=next_step["scene_index"],
        scene_id=next_step["scene_id"],
        scene_text=scene_text,
        budget_total=run.budget_total,
        state_review_version=plan.get("state_review_version", 0),
        enrichment_version=plan.get("enrichment_version", 0),
        world_version=plan.get("world_version", 0),
        chapter_index=parts[0].chapter_index,
        start_offset=parts[0].start_offset,
        end_offset=parts[0].end_offset,
        additional_sources=[
            {
                "chapter_index": part.chapter_index,
                "start_offset": part.start_offset,
                "end_offset": part.end_offset,
            }
            for part in parts[1:]
        ],
        source_revisions=[
            {"draft_id": part.draft_id, "content_hash": part.content_hash}
            for part in parts
        ],
    )
    queued = await enqueue_evolution_scene_step(db, request)
    run.reading_plan_json = {**plan, "task_id": queued["task_id"]}
    await db.flush()
    return {"next_task_id": queued["task_id"], "reading_complete": False}


async def reading_status(db, novel_id, run_key=None):
    await require_active_project(db, novel_id)
    engine = await get_understanding_engine(db, novel_id)
    query = select(EvolutionRun).where(
        EvolutionRun.novel_id == UUID(novel_id),
        EvolutionRun.reading_plan_json.is_not(None),
    )
    if run_key:
        query = query.where(EvolutionRun.run_key == run_key)
    run = await db.scalar(query.order_by(EvolutionRun.created_at.desc()).limit(1))
    if not run:
        if run_key:
            raise NotFoundError("未找到理解记录")
        return {"engine": engine, "run": None}
    plan = run.reading_plan_json
    preparation = plan.get("preparation", {})
    structure = plan.get("structure", {})
    task_id = plan.get("task_id")
    lifecycle = (
        await list_task_lifecycle_contracts(
            db,
            task_ids=[task_id] if task_id else [],
            novel_id=novel_id,
            max_heartbeat_gap=120,
        )
    ).get(task_id)
    completed = sum(
        step["scene_index"] <= run.committed_scene_index for step in plan["steps"]
    )
    pending = await PostgresAttemptStore(db, novel_id).load_pending_frozen(
        run.run_key, run.committed_scene_index + 1
    )
    reconcile = bool(
        (
            (
                pending
                and (
                    pending.payload.get("stage") in {"sampling", "failed"}
                    or any(
                        (pending.payload.get(key) or {}).get("stage")
                        in {"sampling", "failed"}
                        for key in SCENE_CALL_JOURNALS
                    )
                )
            )
            or any(
                call["stage"] in {"sampling", "failed"}
                for call in preparation.get("calls", {}).values()
            )
            or any(
                call["stage"] in {"sampling", "failed"}
                for call in (structure.get("current") or {}).get("calls", {}).values()
            )
        )
        and (not lifecycle or lifecycle.status not in {"pending", "running"})
    )
    if run.status != "active":
        status = "source_changed" if run.status == "source_stale" else "stopped"
    elif reconcile:
        status = "needs_reconciliation"
    elif preparation.get("stage") == "needs_scene_review":
        status = "needs_scene_review"
    elif plan.get("pause_reason") == "budget":
        status = (
            lifecycle.status
            if lifecycle and lifecycle.status in {"pending", "running"}
            else "needs_budget"
        )
    elif (
        completed == len(plan["steps"])
        and preparation.get("stage") in {None, "complete"}
        and (plan.get("structure_version", 0) == 0 or structure.get("complete"))
    ):
        status = "completed"
    else:
        status = lifecycle.status if lifecycle else "interrupted"
    return {
        "engine": engine,
        "run": {
            "run_key": run.run_key,
            "task_id": task_id,
            "status": status,
            "completed_scenes": completed,
            "total_scenes": len(plan["steps"]),
            "budget_total": run.budget_total,
            "budget_remaining": run.budget_remaining,
            "end_chapter": preparation["sources"][-1]["chapter_index"]
            if preparation
            else _last_chapter(plan["steps"]),
            "preparing_scenes": bool(
                preparation and preparation.get("stage") != "complete"
            ),
            "preparing_structure": bool(
                plan.get("structure_version") == 1
                and not structure.get("complete")
                and completed == len(plan["steps"])
            ),
            "model": (run.llm_snapshot_json or {}).get("profile", {}).get("model"),
            "can_resume": run.status == "active"
            and not reconcile
            and status != "needs_budget"
            and (
                status == "needs_scene_review"
                or bool(lifecycle and lifecycle.recovery_required)
            ),
        },
    }


async def resume_reading(db, novel_id, run_key):
    await require_active_project_exclusive(db, novel_id)
    state = await reading_status(db, novel_id, run_key)
    if not state["run"]["can_resume"]:
        raise ConflictError("当前理解不能直接重试；已发生的请求和成果会保留")
    store = PostgresAttemptStore(db, novel_id)
    await store.require_project_owner(run_key)
    run = await store.load_run(run_key)
    if run.reading_plan_json.get("preparation", {}).get("stage") == "needs_scene_review":
        from modules.evolution.preparation import finish_preparation

        await finish_preparation(db, novel_id, run)
        await advance_reading(db, novel_id, run_key)
        return await reading_status(db, novel_id, run_key)
    for step in run.reading_plan_json["steps"]:
        await _read_step(db, novel_id, step)
    await resume_manual_task(
        db,
        task_id=state["run"]["task_id"],
        novel_id=novel_id,
        task_types={"evolution_scene_step_v2"},
    )
    return await reading_status(db, novel_id, run_key)


async def reading_proposals(db, novel_id, run_key, *, offset=0, limit=20):
    """Page frozen author-visible proposals; this view never adopts or resamples."""
    from sqlalchemy import func

    from modules.evolution.models import EvolutionFrozenAttempt
    from modules.evolution.reading import require_current_world_candidate

    await require_active_project(db, novel_id)
    store = PostgresAttemptStore(db, novel_id)
    run = await store.load_run(run_key)
    if not run or not run.reading_plan_json or run.execution_mode != "live":
        raise NotFoundError("未找到理解记录")
    filters = (
        EvolutionFrozenAttempt.novel_id == UUID(novel_id),
        EvolutionFrozenAttempt.run_key == run_key,
    )
    total = await db.scalar(
        select(func.count()).select_from(EvolutionFrozenAttempt).where(*filters)
    )
    rows = (
        await db.scalars(
            select(EvolutionFrozenAttempt)
            .where(*filters)
            .order_by(EvolutionFrozenAttempt.created_at.desc(), EvolutionFrozenAttempt.id)
            .offset(offset)
            .limit(limit)
        )
    ).all()
    items = []
    for row in rows:
        payload = row.payload_json
        result = payload.get("world_result") or payload.get("relations_preparation")
        if not result:
            continue
        stale = row.status != "applied"
        if not stale:
            try:
                await require_current_world_candidate(
                    db, novel_id, {"run_key": run_key, "attempt_id": row.attempt_key}
                )
            except ConflictError:
                stale = True
        context = result["context"]
        labels = {
            item["prompt_ref"]: item["name"] for item in context["identity_candidates"]
        }
        relations = result.get("relations", {})
        world = result["world"]
        items.append(
            {
                "scene_index": payload["scene_index"],
                "stale": stale,
                "review_status": (result.get("review") or {}).get(
                    "status", "not_required"
                ),
                "entities": [
                    {
                        key: item.get(key)
                        for key in (
                            "name",
                            "summary",
                            "public_info",
                            "hidden_truth",
                            "evidence_quotes",
                        )
                    }
                    for item in world["entities"]
                ],
                "aliases": [
                    {
                        "entity": labels.get(item["entity_ref"], "身份待核对"),
                        "alias": item["alias"],
                        "evidence_quotes": item["evidence_quotes"],
                    }
                    for item in relations.get("aliases", [])
                ],
                "relations": [
                    {
                        "source": labels.get(item["source_ref"], "身份待核对"),
                        "target": labels.get(item["target_ref"], "身份待核对"),
                        "description": item["description"],
                        "evidence_quotes": item["evidence_quotes"],
                    }
                    for item in relations.get("relations", [])
                ],
                "findings": [
                    item["message"]
                    for item in (result.get("review") or {}).get("issues", [])
                ],
                "uncertainties": [
                    item["reason"] for item in world.get("uncertain_items", [])
                ],
            }
        )
    return {"items": items, "total": total, "offset": offset, "limit": limit}
