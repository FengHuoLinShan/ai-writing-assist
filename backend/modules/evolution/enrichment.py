"""Per-Scene semantic enrichment after its real parent receipt has committed."""

import json

from infrastructure.llm.collaboration import content_hash
from modules.evidence.contracts import GroupSource
from modules.evidence.facade import materialize_group_audit
from modules.imports import facade as imports


def needs_enrichment(scene):
    meta = scene.get("structure_meta") or {}
    return (
        scene.get("status") == "draft"
        and scene.get("source") == "evolution"
        and meta.get("auto_ingested") is True
        and meta.get("semantic_origin") in {"boundary_only", "phase1b_enrichment"}
        and meta.get("user_edited") is not True
    )


async def finish_scene_enrichment(db, store, frozen, source, call):
    if frozen.payload.get("enrichment_version", 0) != 1:
        return frozen
    if frozen.payload.get("enrichment_result"):
        return frozen
    from modules.evolution.pipeline import _run_scene_call

    payload = frozen.payload
    prepared = imports.prepare_scene_enrichment(
        payload["scene_card"],
        [part.model_dump(mode="json") for part in source.ranges()],
        payload["scene_text"],
        payload["input_manifest"],
    )
    identity = {
        "attempt_id": frozen.attempt_id,
        "source_manifest_hash": frozen.source_manifest_hash,
        "owner_epoch": frozen.owner_epoch,
        "previous_receipt": frozen.previous_receipt,
        "input": prepared,
    }

    async def generate(**inputs):
        return await call("enrich_scene", **inputs)

    frozen = await _run_scene_call(
        db,
        store,
        frozen,
        source,
        journal_key="scene_enrichment",
        inputs={"method": "imports.scene_enrichment.v1", **identity},
        call_inputs={"payload": prepared},
        call=generate,
    )
    candidate = imports.materialize_scene_enrichment(
        prepared, frozen.payload["scene_enrichment"]["result"]
    )
    output = json.dumps(candidate, ensure_ascii=False, sort_keys=True)
    scope = {
        "capability": "imports.scene_enrichment",
        "novel_id": frozen.novel_id,
        "group_key": frozen.attempt_id,
        "output": output,
        "sources": [
            GroupSource(
                source_key="scene_source",
                source_type="prior_prose",
                content_hash=content_hash(prepared["scene_source"]),
                dimensions=("prior_prose",),
            ),
            GroupSource(
                source_key="scene_context",
                source_type="imported_assets",
                content_hash=content_hash(prepared),
                dimensions=("scene_state", "imported_assets"),
            ),
        ],
    }

    async def review(**inputs):
        return await call("review_scene_enrichment", **inputs)

    frozen = await _run_scene_call(
        db,
        store,
        frozen,
        source,
        journal_key="scene_enrichment_review",
        inputs={
            "method": "imports.scene_enrichment.audit.v1",
            **identity,
            "output": output,
        },
        call_inputs={
            **scope,
            "task_instruction": (
                "独立回读当前场景，核对叙事字段与引用；导演判断不作为角色已知事实。"
                "尤其检查否定、量词、时间与知识范围：未亲眼确认不能扩成任何方式均未得知，"
                "未叙述行程不能扩成没有行程或未来禁止披露。超出原文的强制约束属于重大问题，"
                "须用 major finding 阻断，不能因引文匹配而放过。"
            ),
            "context": json.dumps(prepared, ensure_ascii=False, sort_keys=True),
        },
        call=review,
    )
    await store.require_project_owner(frozen.run_id)
    await store.load_run(frozen.run_id, for_update=True)
    frozen = await store.load_frozen(frozen.run_id, frozen.attempt_id)
    if frozen.payload.get("enrichment_result"):
        await db.commit()
        return frozen
    review_result = materialize_group_audit(
        **scope, result=frozen.payload["scene_enrichment_review"]["result"]
    )
    frozen = frozen.model_copy(
        update={
            "payload": {
                **frozen.payload,
                "enrichment_result": {"candidate": candidate, "review": review_result},
            }
        }
    )
    await store.replace_frozen_payload(frozen)
    await db.commit()
    return frozen
