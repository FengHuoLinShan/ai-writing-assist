"""Source-pinned Scene preparation sharing the reading run's budget and owner."""

from core.errors import ConflictError, ValidationError
from infrastructure.llm.collaboration import content_hash
from infrastructure.llm.workflow_budget import AIRunEnvelopeError
from infrastructure.tasks.facade import enqueue_coalesced_task
from modules.evolution.llm_sampler import build_call_receipt
from modules.evolution.pipeline import SceneSourceBinding, load_current_source
from modules.evolution.store import BudgetExhaustedError, PostgresAttemptStore
from modules.imports import facade as imports
from modules.project.facade import (
    open_project_snapshot_llm_client,
    require_active_project_exclusive,
    require_understanding_writer,
)
from modules.story.facade import get_scenes_by_novel
from modules.writing.facade import list_latest_drafts_for_chapters


async def plan_preparation(db, novel_id, chapters, start_index):
    drafts = await list_latest_drafts_for_chapters(db, novel_id, chapters)
    by_chapter = {draft.chapter_index: draft for draft in drafts}
    sources = []
    for chapter in chapters:
        draft = by_chapter.get(chapter)
        if not draft or not draft.content or not draft.content.strip():
            raise ConflictError("场景准备需要完整、已保存的正文")
        sources.append(
            {
                "chapter_index": chapter,
                "draft_id": str(draft.id),
                "content_hash": draft.content_hash,
                "start_offset": 0,
                "end_offset": len(draft.content),
                "title": draft.title,
            }
        )
    preparation = {
        "version": "evolution_boundaries.v1",
        "sources": sources,
        "start_scene_index": start_index,
        "stage": "pending",
        "calls": {},
    }
    boundary_drafts = (
        await list_latest_drafts_for_chapters(db, novel_id, [chapters[0] - 1])
        if chapters[0] > 1
        else []
    )
    preparation["context_sources"] = [
        {
            "chapter_index": draft.chapter_index,
            "draft_id": str(draft.id),
            "content_hash": draft.content_hash,
            "start_offset": 0,
            "end_offset": len(draft.content),
            "title": draft.title,
        }
        for draft in boundary_drafts
    ]
    texts = await read_preparation_sources(db, novel_id, preparation)
    preparation["plan"] = imports.plan_scene_boundaries(
        texts,
        [
            {"chapter_index": draft.chapter_index, "content": draft.content}
            for draft in boundary_drafts
        ],
    )
    return preparation


async def read_preparation_sources(db, novel_id, preparation):
    chapters = []
    for part in preparation["sources"]:
        source = SceneSourceBinding(**{k: v for k, v in part.items() if k != "title"})
        loaded = await load_current_source(db, novel_id, source)
        if loaded is None:
            raise ConflictError("准备场景的正文版本已变化，请重新选择范围")
        chapters.append(
            {
                "chapter_index": part["chapter_index"],
                "title": part["title"],
                "content": loaded[1],
                "source_draft_id": part["draft_id"],
                "source_content_hash": part["content_hash"],
            }
        )
    for part in preparation.get("context_sources", []):
        source = SceneSourceBinding(**{k: v for k, v in part.items() if k != "title"})
        if await load_current_source(db, novel_id, source) is None:
            raise ConflictError("场景衔接参考的正文已变化，请重新准备")
    return chapters


async def enqueue_preparation(db, novel_id, run):
    plan = run.reading_plan_json
    if plan["preparation"]["stage"] == "needs_scene_review":
        return {"reading_complete": False}
    if plan.get("pause_reason") == "budget":
        return {"reading_complete": False}
    queued = await enqueue_coalesced_task(
        db,
        task_type="evolution_scene_step_v2",
        novel_id=novel_id,
        scope=["evolution", run.run_key, "prepare_scenes"],
        mode="reuse_active",
        meta={
            "operation": "prepare_scenes",
            "novel_id": novel_id,
            "run_key": run.run_key,
            "execution_mode": "live",
            "_understanding_owner": await require_understanding_writer(
                db, novel_id, engine="evolution"
            ),
        },
    )
    run.reading_plan_json = {**plan, "task_id": str(queued.task_id)}
    await db.flush()
    return {"next_task_id": str(queued.task_id), "reading_complete": False}


async def prepare_scenes(db, novel_id, run_key):
    store = PostgresAttemptStore(db, novel_id)
    await require_active_project_exclusive(db, novel_id)
    await store.require_project_owner(run_key)
    run = await store.load_run(run_key, for_update=True)
    if not run or run.status != "active":
        raise ConflictError("理解已停止或来源已变化")
    preparation = run.reading_plan_json["preparation"]
    if preparation["version"] != "evolution_boundaries.v1":
        raise ConflictError("场景准备协议不兼容，请保留历史并重新准备")
    if preparation["stage"] == "complete":
        return {"run_key": run_key}
    snapshot = run.llm_snapshot_json
    chapters = await read_preparation_sources(db, novel_id, preparation)
    await db.commit()

    async def call(payload):
        request, schema = imports.build_scene_boundary_request(payload)
        key = content_hash(
            {
                "request": request.model_dump(mode="json"),
                "schema": schema.model_json_schema(),
            }
        )
        await require_active_project_exclusive(db, novel_id)
        await store.require_project_owner(run_key)
        current = await store.load_run(run_key, for_update=True)
        if current.status != "active":
            raise AIRunEnvelopeError("正文或理解流程已变化，停止准备场景")
        prep = current.reading_plan_json["preparation"]
        await read_preparation_sources(db, novel_id, prep)
        frozen = prep["calls"].get(key)
        if frozen:
            await db.commit()
            if frozen["stage"] != "sampled":
                raise AIRunEnvelopeError("上次场景准备请求需要核对，不能重复计费")
            return schema.model_validate(frozen["result"])
        try:
            await store.reserve_budget(run_key, 1)
        except BudgetExhaustedError as exc:
            raise AIRunEnvelopeError("本次调用额度已用完") from exc
        frozen = {
            "stage": "sampling",
            "request": request.model_dump(mode="json"),
            "schema": schema.__name__,
        }
        current.reading_plan_json = {
            **current.reading_plan_json,
            "preparation": {**prep, "calls": {**prep["calls"], key: frozen}},
        }
        await db.commit()
        diagnostics = []
        async with open_project_snapshot_llm_client(db, novel_id, snapshot) as client:
            # Snapshot resolution may read current credentials; close that read
            # transaction before provider I/O while retaining the frozen model.
            await db.commit()
            try:
                result = await client.generate_structured(
                    request,
                    schema,
                    diagnostics=diagnostics,
                    max_fix_attempts=0,
                    transport_retries=False,
                )
            except Exception as exc:
                frozen = {
                    **frozen,
                    "stage": "failed",
                    "error_kind": type(exc).__name__,
                    "paid_call_receipt": build_call_receipt(
                        client,
                        diagnostics,
                        schema="evolution_boundaries.v1",
                        outcome="failed_final",
                    ),
                }
                await _save_call(db, store, run_key, key, frozen)
                raise AIRunEnvelopeError(
                    "场景准备请求未取得可用结果，已保留费用记录，请先核对"
                ) from exc
            frozen = {
                **frozen,
                "stage": "sampled",
                "result": result.model_dump(mode="json"),
                "paid_call_receipt": build_call_receipt(
                    client,
                    diagnostics,
                    schema="evolution_boundaries.v1",
                    outcome="succeeded",
                ),
            }
            await _save_call(db, store, run_key, key, frozen)
            return result

    if "result" not in preparation:
        try:
            result = await imports.slice_scene_boundaries(
                preparation["plan"], chapters, call
            )
        except AIRunEnvelopeError:
            await db.rollback()
            await require_active_project_exclusive(db, novel_id)
            run = await store.load_run(run_key, for_update=True)
            calls = run.reading_plan_json["preparation"]["calls"]
            if (
                run.status == "active"
                and run.budget_remaining == 0
                and all(item["stage"] == "sampled" for item in calls.values())
            ):
                run.reading_plan_json = {
                    **run.reading_plan_json,
                    "pause_reason": "budget",
                }
                await db.commit()
                return {"run_key": run_key}
            raise
        await require_active_project_exclusive(db, novel_id)
        run = await store.load_run(run_key, for_update=True)
        run.reading_plan_json = {
            **run.reading_plan_json,
            "preparation": {**run.reading_plan_json["preparation"], "result": result},
        }
        await db.commit()

    await require_active_project_exclusive(db, novel_id)
    await store.require_project_owner(run_key)
    run = await store.load_run(run_key, for_update=True)
    if run.status != "active":
        raise ConflictError("正文或理解流程已变化，已采样结果保留")
    prep = run.reading_plan_json["preparation"]
    await read_preparation_sources(db, novel_id, prep)
    if prep["stage"] == "pending":
        scenes = await get_scenes_by_novel(
            db, novel_id, status_filter=["draft", "canonical"]
        )
        if any(scene["scene_index"] >= prep["start_scene_index"] for scene in scenes):
            raise ConflictError("场景已由其他操作修改，请先核对边界")
        committed = await imports.commit_scene_boundaries(
            db,
            novel_id,
            prep["result"],
            workflow_id=run_key,
            start=prep["sources"][0]["chapter_index"],
            end=prep["sources"][-1]["chapter_index"],
        )
        run.reading_plan_json = {
            **run.reading_plan_json,
            "preparation": {**prep, "stage": "prepared", "commit": committed},
        }
        await db.commit()
    try:
        await finish_preparation(db, novel_id, run)
    except (ConflictError, ValidationError) as exc:
        # Exact fallback spans remain editable drafts, never a valid Scene prefix.
        run = await store.load_run(run_key)
        run.reading_plan_json = {
            **run.reading_plan_json,
            "preparation": {
                **run.reading_plan_json["preparation"],
                "stage": "needs_scene_review",
                "review_reason": str(exc),
            },
        }
        await db.commit()
    return {"run_key": run_key}


async def _save_call(db, store, run_key, key, frozen):
    await require_active_project_exclusive(db, str(store.novel_id))
    run = await store.load_run(run_key, for_update=True)
    prep = run.reading_plan_json["preparation"]
    run.reading_plan_json = {
        **run.reading_plan_json,
        "preparation": {**prep, "calls": {**prep["calls"], key: frozen}},
    }
    await db.commit()


async def finish_preparation(db, novel_id, run):
    from modules.evolution.workflow import collect_scene_steps

    await require_active_project_exclusive(db, novel_id)
    prep = run.reading_plan_json["preparation"]
    await read_preparation_sources(db, novel_id, prep)
    scenes = await get_scenes_by_novel(db, novel_id, status_filter=["draft", "canonical"])
    selected = [
        scene for scene in scenes if scene["scene_index"] >= prep["start_scene_index"]
    ]
    steps = await collect_scene_steps(
        db,
        novel_id,
        selected,
        prep["start_scene_index"],
        [source["chapter_index"] for source in prep["sources"]],
    )
    run.reading_plan_json = {
        **run.reading_plan_json,
        "steps": [*run.reading_plan_json["steps"], *steps],
        "preparation": {**prep, "stage": "complete"},
    }
    await db.flush()
