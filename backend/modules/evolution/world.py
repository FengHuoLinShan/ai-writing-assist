"""Sequential World/alias/relation candidates in the Scene receipt transaction."""

import json
from copy import deepcopy
from uuid import NAMESPACE_URL, uuid5

from infrastructure.llm.collaboration import content_hash
from infrastructure.llm.profiles import DEEPSEEK_THINKING_MODELS
from modules.evidence.contracts import GroupSource
from modules.evidence.facade import build_group_audit_request, materialize_group_audit
from modules.imports import facade as imports

WORLD_AUDIT_INPUT_CHAR_LIMIT = 45_000


def _known_format_failure(error) -> bool:
    receipt = error.receipt or {}
    details = receipt.get("attempts_detail") or []
    return bool(
        (receipt.get("usage") or {}).get("usage_complete") is True
        and details
        and details[-1].get("error_kind")
        in {"invalid_json", "truncated_json", "schema_validation"}
    )


def _deferred_world_result(context, stage: str) -> dict:
    return {
        "world": {"entities": [], "delta_events": [], "uncertain_items": []},
        "relations": {"aliases": [], "relations": [], "uncertain_items": []},
        "context": context,
        "review": {
            "status": "blocked",
            "review_kind": "extraction_deferred",
            "issues": [
                {"message": f"{stage}格式失败；结果和费用已保留，需另行核对。"}
            ],
        },
    }


def request_spec(request, schema):
    return {
        "request": request.model_dump(mode="json", exclude_unset=True),
        "schema_name": schema.__name__,
        "schema_hash": content_hash(schema.model_json_schema()),
    }


async def freeze_value(db, store, frozen, key, prepare):
    await store.require_project_owner(frozen.run_id)
    await store.load_run(frozen.run_id, for_update=True)
    frozen = await store.load_frozen(frozen.run_id, frozen.attempt_id)
    if key not in frozen.payload:
        value = await prepare(frozen.payload)
        frozen = frozen.model_copy(update={"payload": {**frozen.payload, key: value}})
        await store.replace_frozen_payload(frozen)
    await db.commit()
    return frozen


async def finish_scene_world(db, store, frozen, source, call):
    if frozen.payload.get("world_version", 0) not in {1, 2} or frozen.payload.get(
        "world_result"
    ):
        return frozen
    from modules.evolution.pipeline import _run_scene_call

    async def prepare_world(payload):
        terms = [
            (mention["entity_type"], mention["surface"])
            for item in payload["compiled_observations"]
            for mention in item["mentions"]
            if mention.get("entity_type")
        ]
        context = await imports.prepare_scene_world_context(db, frozen.novel_id, terms)
        context.update(
            committed_parent=payload["input_manifest"],
            _current_scene_text=payload["scene_text"],
        )
        return {
            "context": context,
            "call": request_spec(
                *imports.build_scene_world_request(payload["scene_text"], context)
            ),
        }

    frozen = await freeze_value(db, store, frozen, "world_preparation", prepare_world)

    async def execute(**inputs):
        return await call("execute_world_request", **inputs)

    async def run_call(current, key, spec):
        return await _run_scene_call(
            db,
            store,
            current,
            source,
            journal_key=key,
            inputs={
                "method": f"imports.{key}.v1",
                "attempt_id": frozen.attempt_id,
                "source_manifest_hash": frozen.source_manifest_hash,
                "previous_receipt": frozen.previous_receipt,
                **spec,
            },
            call_inputs=spec,
            call=execute,
        )

    from modules.evolution.state_review import SceneCallFailedError

    try:
        frozen = await run_call(
            frozen, "scene_world", frozen.payload["world_preparation"]["call"]
        )
    except SceneCallFailedError as error:
        if not _known_format_failure(error):
            raise

        async def defer_world(payload):
            return _deferred_world_result(
                payload["world_preparation"]["context"], "世界资料抽取"
            )

        return await freeze_value(db, store, frozen, "world_result", defer_world)

    async def prepare_relations(payload):
        first = payload["world_preparation"]["context"]
        world = imports.materialize_scene_world(
            payload["scene_text"], first, payload["scene_world"]["result"]
        )
        terms = [
            (item["entity_type"], item["name"]) for item in first["_identity_queries"]
        ]
        terms += [(item["entity_type"], item["name"]) for item in world["entities"]]
        context = await imports.prepare_scene_world_context(db, frozen.novel_id, terms)
        context.update(
            committed_parent=payload["input_manifest"],
            _current_scene_text=payload["scene_text"],
        )
        context["_initial_identity_queries"] = first["_identity_queries"]
        context = imports.prepare_scene_relations_context(context, world)
        if payload["world_version"] == 2:
            context.update(await relation_history(store, frozen, context))
        if payload["world_version"] == 2:
            context["_new_entity_ids"] = {
                ref: str(
                    uuid5(
                        NAMESPACE_URL,
                        json.dumps(
                            [
                                "evolution:world",
                                frozen.novel_id,
                                frozen.run_id,
                                frozen.attempt_id,
                                ref,
                            ]
                        ),
                    )
                )
                for ref in context["_new_entity_refs"]
            }
        return {
            "context": context,
            "world": world,
            "call": request_spec(
                *imports.build_scene_relations_request(payload["scene_text"], context)
            )
            if context["identity_candidates"]
            else None,
        }

    frozen = await freeze_value(
        db, store, frozen, "relations_preparation", prepare_relations
    )
    prepared = frozen.payload["relations_preparation"]
    if prepared["call"]:
        try:
            frozen = await run_call(frozen, "scene_relations", prepared["call"])
        except SceneCallFailedError as error:
            if not _known_format_failure(error):
                raise

            async def defer_relations(payload):
                return _deferred_world_result(
                    payload["relations_preparation"]["context"], "别名关系抽取"
                )

            return await freeze_value(
                db, store, frozen, "world_result", defer_relations
            )
    relations = (frozen.payload.get("scene_relations") or {}).get(
        "result", {"aliases": [], "relations": [], "uncertain_items": []}
    )
    output = json.dumps(
        {"world": prepared["world"], "relations": relations},
        ensure_ascii=False,
        sort_keys=True,
    )
    scope = {
        "capability": "imports.entity_extraction",
        "novel_id": frozen.novel_id,
        "group_key": frozen.attempt_id,
        "output": output,
        "sources": [
            GroupSource(
                source_key="scene_source",
                source_type="prior_prose",
                content_hash=content_hash(frozen.payload["scene_text"]),
                dimensions=("prior_prose",),
            ),
            GroupSource(
                source_key="scene_context",
                source_type="imported_assets",
                content_hash=content_hash(prepared["context"]),
                dimensions=("world_entities", "imported_assets"),
            ),
        ],
    }
    has_claims = any(
        prepared["world"].get(key) for key in ("entities", "delta_events")
    ) or any(relations.get(key) for key in ("aliases", "relations"))
    if has_claims:

        async def prepare_review(payload):
            return request_spec(
                *build_group_audit_request(
                    **scope,
                    task_instruction=(
                        "独立核对长期世界对象、别名和关系提案。逐字引用只证明定位；"
                        "核对类型、身份、关系方向及每个描述字段的语义蕴含。传闻不得变成"
                        "客观事实；角色当前不知道的事实不可写成其知识；同名不能证明同一人。"
                        "不可靠身份、超范围否定或凭空补出的事实均以major finding阻断。"
                        "这是分阶段组合提案：world.entities 中的 aliases 为未填占位，"
                        "实际别名以 relations.aliases 单独承载，两者不构成矛盾。"
                        "空关系候选只说明本次资料未提供历史记录，不能证明历史上首次建立。"
                    ),
                    context=json.dumps(
                        {
                            "scene_text": payload["scene_text"],
                            "context": prepared["context"],
                        },
                        ensure_ascii=False,
                    ),
                )
            )

        frozen = await freeze_value(
            db, store, frozen, "world_review_preparation", prepare_review
        )
        spec = frozen.payload["world_review_preparation"]
        run = await store.load_run(frozen.run_id)
        model = ((run.llm_snapshot_json or {}).get("profile") or {}).get("model")
        input_chars = sum(
            len(message.get("content") or "") for message in spec["request"]["messages"]
        )
        # ponytail: defer oversized Flash audits; batch claims if this becomes common.
        deferred = (
            model in DEEPSEEK_THINKING_MODELS
            and input_chars > WORLD_AUDIT_INPUT_CHAR_LIMIT
            and not frozen.payload.get("scene_world_review")
        )
        if deferred:
            review = {
                "status": "blocked",
                "review_kind": "capacity_deferred",
                "audit_input_chars": input_chars,
                "issues": [
                    {"message": "世界资料候选过多，独立审查未运行；需作者核对后采用。"}
                ],
            }
        else:
            frozen = await run_call(frozen, "scene_world_review", spec)
            review = materialize_group_audit(
                **scope, result=frozen.payload["scene_world_review"]["result"]
            )
    else:
        review = None

    async def finish(payload):
        return {
            "world": prepared["world"],
            "relations": relations,
            "context": prepared["context"],
            "review": review,
        }

    return await freeze_value(db, store, frozen, "world_result", finish)


async def relation_history(store, frozen, context):
    """Only actual committed prefix rows may contribute historical relation text."""
    from modules.evolution.contracts import EvolutionReceipt

    refs = {entity_id: ref for ref, entity_id in context["_entity_ref_map"].items()}
    pairs = await store.load_committed_pairs(
        frozen.run_id, descending=True, limit=64, relation_entity_ids=list(refs)
    )
    candidates, mapping = [], {}
    for receipt_row, row in pairs:
        if receipt_row.committed_scene_index >= frozen.payload["scene_index"]:
            continue
        receipt = EvolutionReceipt.model_validate(receipt_row.receipt_json)
        saved = {
            item["id"]
            for item in receipt.world_result_refs
            if item["type"] == "entity_relation"
        }
        for relation in row.payload_json.get("world_materialization", {}).get(
            "relations", []
        ):
            if relation["id"] not in saved or relation["novel_id"] != frozen.novel_id:
                continue
            if relation["source_id"] not in refs or relation["target_id"] not in refs:
                continue
            ref = f"relation_{relation['id']}"
            if ref in mapping:
                continue
            candidates.append(
                {
                    "prompt_ref": ref,
                    "source_ref": refs[relation["source_id"]],
                    "target_ref": refs[relation["target_id"]],
                    **{
                        key: relation[key]
                        for key in (
                            "relation_type",
                            "relation_kind",
                            "description",
                            "quote",
                            "status",
                            "claim_status",
                            "directionality",
                        )
                    },
                    "scene_index": receipt_row.committed_scene_index,
                    "source_receipt": {
                        "run_key": receipt.run_id,
                        "attempt_id": receipt.attempt_id,
                    },
                }
            )
            mapping[ref] = {
                key: relation[key]
                for key in (
                    "id",
                    "novel_id",
                    "source_id",
                    "target_id",
                    "relation_type",
                )
            }
    return {
        "relation_candidates": candidates,
        "relation_history_scope": (
            "最近至多64个相关已提交场景；缺少前例不能据此断言首次建立"
        ),
        "_relation_ref_map": mapping,
    }


def bind_scene_identities(payload):
    """Bind only independently reviewed, same-Scene candidates before state review."""
    from modules.evolution.state_gate import gate_scene_events

    world = payload["world_result"]
    observations = deepcopy(payload["compiled_observations"])
    context = world["context"]
    new_ids = context.get("_new_entity_ids", {})
    candidates = (
        {
            (item["entity_type"], item["name"]): new_ids[item["prompt_ref"]]
            for item in context["identity_candidates"]
            if item["prompt_ref"] in new_ids
        }
        if (world.get("review") or {}).get("status") == "passed"
        else {}
    )
    resolutions, outcomes = [], {}
    for observation in observations:
        for mention in observation["mentions"]:
            entity_id = candidates.get((mention["entity_type"], mention["surface"]))
            resolution = mention.get("resolution")
            if entity_id and (resolution or {}).get("outcome") in {None, "new_candidate"}:
                resolution = mention["resolution"] = {
                    "mention_id": mention["mention_id"],
                    "surface": mention["surface"],
                    "outcome": "reuse",
                    "resolved_entity_id": entity_id,
                    "rationale": "本场独立审查通过的新候选，身份与状态须同事务提交",
                }
            if resolution:
                resolutions.append(resolution)
                outcome = resolution["outcome"]
                outcomes[outcome] = outcomes.get(outcome, 0) + 1
    applied, gated = gate_scene_events(payload["proposed_scene_events"], observations)
    return {
        "compiled_observations": observations,
        "identity_resolutions": resolutions,
        "identity_outcomes": outcomes,
        "scene_events": applied,
        "gated_scene_events": gated,
    }
