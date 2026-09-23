"""Bounded Story structure batches after the requested Scene prefix is committed."""

import asyncio

from core.errors import ConflictError
from infrastructure.llm.collaboration import content_hash
from infrastructure.tasks.facade import enqueue_coalesced_task
from modules.evolution.pipeline import SceneSourceBinding, _source_verifier
from modules.evolution.sampler import resolve_scene_sampler
from modules.evolution.store import PostgresAttemptStore
from modules.evolution.world import request_spec
from modules.project.facade import (
    require_active_project_exclusive,
    require_understanding_writer,
)
from modules.story import facade as story
from modules.story.contracts import reading_structure_schema


async def enqueue_structure(db, novel_id, run):
    plan = run.reading_plan_json
    if plan.get("structure", {}).get("complete"):
        return {"reading_complete": True}
    if run.budget_remaining <= 0:
        run.reading_plan_json = {**plan, "pause_reason": "budget"}
        await db.flush()
        return {"reading_complete": False}
    queued = await enqueue_coalesced_task(
        db,
        task_type="evolution_scene_step_v2",
        novel_id=novel_id,
        scope=[
            "evolution",
            run.run_key,
            "structure",
            str(plan.get("structure", {}).get("through_scene_index", -1)),
        ],
        mode="reuse_active",
        meta={
            "operation": "structure",
            "novel_id": novel_id,
            "run_key": run.run_key,
            "execution_mode": "live",
            "_understanding_owner": await require_understanding_writer(
                db,
                novel_id,
                engine="evolution",
            ),
        },
    )
    run.reading_plan_json = {**plan, "task_id": str(queued.task_id)}
    await db.flush()
    return {"next_task_id": str(queued.task_id), "reading_complete": False}


async def _locked_run(db, store, run_key, *, active=True):
    await require_active_project_exclusive(db, str(store.novel_id))
    if active:
        await store.require_project_owner(run_key)
    run = await store.load_run(run_key, for_update=True)
    if not run or (active and run.status != "active"):
        raise ConflictError("正文或理解流程已变化，结构结果已保留")
    return run


async def verify_structure_sources(db, store, refs):
    latest = await store.latest_scene_attempts([item["scene_id"] for item in refs])
    for ref in refs:
        identity = (ref["run_key"], ref["attempt_id"])
        receipt = await store.load_receipt(*identity)
        frozen = await store.load_frozen(*identity)
        if (
            receipt is None
            or frozen is None
            or latest.get(ref["scene_id"]) != identity
            or frozen.source_manifest_hash != ref["source_manifest_hash"]
        ):
            raise ConflictError("结构依据的场景理解已变化，请重新准备")
        # Auto enrichment legitimately changes the card during the Scene commit.
        # The original prose, exact boundaries and latest receipt remain mandatory.
        source = SceneSourceBinding.model_validate(frozen.payload["source_binding"])
        await _source_verifier(source)(
            db,
            frozen.model_copy(
                update={
                    "payload": {**frozen.payload, "scene_card": None},
                }
            ),
        )


def _save_stage(run, stage):
    run.reading_plan_json = {**run.reading_plan_json, "structure": stage}


async def require_current_structure_candidate(db, novel_id, reference, asset_id):
    from sqlalchemy.exc import DBAPIError

    if (
        not isinstance(reference, dict)
        or not reference.get("run_key")
        or not reference.get("batch_key")
    ):
        raise ConflictError("结构理解来源记录不完整，请重新核对")
    try:
        await require_active_project_exclusive(db, novel_id, nowait=True)
    except DBAPIError as error:
        if getattr(error.orig, "sqlstate", None) != "55P03":
            raise
        raise ConflictError("正文或结构正在更新，请刷新后再采用") from error
    store = PostgresAttemptStore(db, novel_id)
    run = await store.load_run(reference["run_key"])
    if run is None or run.status not in {"active", "drained", "stopped"}:
        raise ConflictError("结构理解来源已变化，请重新核对")
    batch = next(
        (
            item
            for item in run.reading_plan_json.get("structure", {}).get("batches", [])
            if item["batch_key"] == reference["batch_key"]
        ),
        None,
    )
    if not batch or str(asset_id) not in {item["id"] for item in batch["result_refs"]}:
        raise ConflictError("结构不属于该理解回执，请重新核对")
    await verify_structure_sources(db, store, batch["sources"])


async def _prepare_batch(db, store, run_key):
    run = await _locked_run(db, store, run_key)
    stage = run.reading_plan_json.get(
        "structure",
        {
            "version": 1,
            "through_scene_index": -1,
            "batches": [],
            "current": None,
        },
    )
    if stage.get("complete") or stage.get("current"):
        await db.commit()
        return
    pairs = await store.load_committed_pairs(
        run_key,
        after_scene_index=stage["through_scene_index"],
        limit=16,
    )
    if not pairs:
        _save_stage(run, {**stage, "complete": True})
        await db.commit()
        return
    cards, refs = [], []
    for receipt, frozen in pairs:
        payload = frozen.payload_json
        refs.append(
            {
                "run_key": receipt.run_key,
                "attempt_id": receipt.attempt_key,
                "scene_id": payload["scene_id"],
                "source_manifest_hash": frozen.source_manifest_hash,
            }
        )
        source = SceneSourceBinding.model_validate(payload["source_binding"])
        observations = "\n".join(
            f"[{item['modality']}] {item['predicate']}"
            for item in payload.get("compiled_observations", [])
        )
        cards.append(
            {
                "scene_id": payload["scene_id"],
                "scene_index": payload["scene_index"],
                "start_chapter": source.ranges()[0].chapter_index,
                "end_chapter": source.ranges()[-1].chapter_index,
                "summary": observations[:6000],
                "summary_omitted": len(observations) > 6000,
                "summary_scope": "带模态的观察摘要；完整正文仅用于独立逐项复核",
                "_evidence": {
                    "status": "exact",
                    "sources": [{"text": payload["scene_text"]}],
                },
            }
        )
    await verify_structure_sources(db, store, refs)
    context = {
        "scope": "本批已提交场景，未覆盖的章节不得补写成已发生情节",
        "scene_range": [cards[0]["scene_index"], cards[-1]["scene_index"]],
    }
    current = {
        "key": content_hash(refs),
        "sources": refs,
        "cards": cards,
        "calls": {
            "generate": {
                **request_spec(*story.build_reading_structure_request(cards, context)),
                "stage": "planned",
            }
        },
    }
    _save_stage(run, {**stage, "current": current})
    await db.commit()


async def _call(db, store, run_key, batch_key, call_key):
    run = await _locked_run(db, store, run_key)
    stage = run.reading_plan_json["structure"]
    current = stage["current"]
    if current["key"] != batch_key:
        raise ConflictError("结构批次已推进，请读取最新进度")
    await verify_structure_sources(db, store, current["sources"])
    call = current["calls"][call_key]
    schema = reading_structure_schema(call["schema_name"])
    if content_hash(schema.model_json_schema()) != call["schema_hash"]:
        raise ConflictError("结构输出契约已变化，请保留旧结果并重新准备")
    if call["stage"] == "sampled":
        await db.commit()
        return
    if call["stage"] != "planned":
        raise ConflictError("上次结构请求需要核对，不能重复计费")
    await store.reserve_budget(run_key, 1)
    call = {**call, "stage": "sampling"}
    _save_stage(
        run,
        {
            **stage,
            "current": {
                **current,
                "calls": {**current["calls"], call_key: call},
            },
        },
    )
    snapshot = run.llm_snapshot_json
    await db.commit()
    async with resolve_scene_sampler(
        provider="project_llm",
        novel_id=str(store.novel_id),
        db=db,
        llm_snapshot=snapshot,
    ) as client:
        await db.commit()
        try:
            result = await client.execute_structure_request(
                **{name: call[name] for name in ("request", "schema_name", "schema_hash")}
            )
        except (Exception, asyncio.CancelledError) as error:
            call = {
                **call,
                "stage": "failed",
                "error_kind": type(error).__name__,
                "paid_call_receipt": getattr(error, "receipt", None),
            }
            await _save_call(db, store, run_key, batch_key, call_key, call)
            raise
        call = {**call, "stage": "sampled", **result}
        await _save_call(db, store, run_key, batch_key, call_key, call)


async def _save_call(db, store, run_key, batch_key, call_key, call):
    # Preserve returned results even if the author revoked this run during I/O.
    run = await _locked_run(db, store, run_key, active=False)
    stage = run.reading_plan_json["structure"]
    current = stage["current"]
    if current["key"] != batch_key:
        raise ConflictError("结构批次已变化，不能覆盖另一批结果")
    _save_stage(
        run,
        {
            **stage,
            "current": {
                **current,
                "calls": {**current["calls"], call_key: call},
            },
        },
    )
    await db.commit()


async def prepare_structure(db, novel_id, run_key):
    store = PostgresAttemptStore(db, novel_id)
    await _prepare_batch(db, store, run_key)
    run = await store.load_run(run_key)
    current = run.reading_plan_json["structure"].get("current")
    if current is None:
        return {"run_key": run_key}
    key = current["key"]
    await _call(db, store, run_key, key, "generate")
    run = await _locked_run(db, store, run_key)
    stage = run.reading_plan_json["structure"]
    current = stage["current"]
    if "review_keys" not in current:
        requests = story.prepare_reading_structure_review(
            current["calls"]["generate"]["result"],
            current["cards"],
        )
        reviews = {
            f"review:{index}": {**request_spec(*request), "stage": "planned"}
            for index, request in enumerate(requests)
        }
        current = {
            **current,
            "review_keys": list(reviews),
            "calls": {**current["calls"], **reviews},
        }
        _save_stage(run, {**stage, "current": current})
    await db.commit()
    for call_key in current["review_keys"]:
        await _call(db, store, run_key, key, call_key)
    run = await _locked_run(db, store, run_key)
    stage = run.reading_plan_json["structure"]
    current = stage["current"]
    await verify_structure_sources(db, store, current["sources"])
    result = await story.persist_reading_structure_drafts(
        db,
        novel_id,
        raw=current["calls"]["generate"]["result"],
        scene_cards=current["cards"],
        reviews=[current["calls"][name]["result"] for name in current["review_keys"]],
        provenance={"evolution_structure_ref": {"run_key": run_key, "batch_key": key}},
    )
    receipt = {
        "batch_key": key,
        "sources": current["sources"],
        "through_scene_index": current["cards"][-1]["scene_index"],
        **result,
        "calls": current["calls"],
    }
    # This is a Story draft batch, not a new Scene-state prefix. Keep the Scene
    # receipts immutable and leave their cursor and dependency chain unchanged.
    _save_stage(
        run,
        {
            **stage,
            "current": None,
            "through_scene_index": receipt["through_scene_index"],
            "complete": receipt["through_scene_index"] == run.committed_scene_index,
            "batches": [*stage["batches"], receipt],
        },
    )
    await db.commit()
    return {"run_key": run_key}
