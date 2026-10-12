"""World proposals share the real gateway, root budget and atomic Scene receipt."""

import json
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from infrastructure.llm.providers import OpenAIProvider
from infrastructure.llm.schemas import LLMCallResponse, LLMMessage, LLMUsage
from infrastructure.tasks.models import AsyncTask
from modules.evolution.pipeline import SceneSourceBinding
from modules.evolution.store import PostgresAttemptStore
from modules.evolution.tasks import handle_evolution_scene_step
from modules.evolution.tests.test_workflow import request_start, seed, structure_response
from modules.evolution.workflow import start_reading
from modules.evolution.world import (
    _known_format_failure,
    _quote_source,
    _scene_source_chunks,
    bind_scene_identities,
    prepare_world_audit_groups,
    world_group_apply_inputs,
)
from modules.world.models import CoreEntity, EntityRelation

TEXT = "林舟又名小舟。林舟和青竹是盟友。"


def test_unknown_usage_never_qualifies_for_world_format_deferral():
    error = SimpleNamespace(
        receipt={
            "usage": {"usage_complete": False},
            "attempts_detail": [{"error_kind": "schema_validation"}],
        }
    )
    assert not _known_format_failure(error)


def test_unknown_fee_world_review_failure_is_not_reconciled():
    from modules.evolution.state_review import (
        has_unreconciled_scene_calls,
        settled_output_failure,
    )

    def journal(receipt):
        return {"stage": "failed", "paid_call_receipt": receipt}

    # 只有回执是字典不能证明费用已核清：usage 缺失/未知次数都不是已核清。
    for receipt in (
        None,
        {"outcome": "failed_final"},
        {"outcome": "failed_final", "usage": None, "attempts_detail": []},
        {
            "outcome": "failed_final",
            "usage": {"usage_complete": False, "unknown_attempts": 1},
            "attempts_detail": [{"status": "failed", "error_kind": "invalid_json"}],
        },
        {
            "outcome": "failed_final",
            "usage": {"usage_complete": True, "unknown_attempts": 0},
            "attempts_detail": [{"status": "failed", "error_kind": "timeout"}],
        },
        {
            "outcome": "failed_final",
            "usage": {"usage_complete": True, "unknown_attempts": 0},
            "attempts_detail": [{"status": "succeeded"}],
        },
    ):
        entry = journal(receipt)
        assert not settled_output_failure(entry)
        assert has_unreconciled_scene_calls({"scene_world_review_group_g1": entry})

    settled = journal(
        {
            "outcome": "failed_final",
            "usage": {"usage_complete": True, "unknown_attempts": 0},
            "attempts_detail": [
                {"status": "failed", "error_kind": "invalid_json"},
                {"status": "failed", "error_kind": "schema_validation"},
            ],
        }
    )
    assert settled_output_failure(settled)
    assert not has_unreconciled_scene_calls({"scene_world_review_group_g1": settled})


def test_bound_new_character_speaker_identity_reaches_language_habit_gate():
    from modules.evolution.contracts import SourceRevisionRef
    from modules.evolution.discovery import _compile_change, method_fingerprint
    from modules.evolution.ledger_contracts import LedgerClaim
    from modules.evolution.observations import derive_observation_id

    quote = "林舟说：“我不会忘记。”"
    novel, scene = str(uuid4()), str(uuid4())
    source = SourceRevisionRef(
        novel_id=novel,
        source_kind="chapter_draft",
        draft_id="draft-1",
        content_hash="a" * 64,
        chapter_identity="chapter:1",
        start_offset=0,
        end_offset=len(quote),
        range_hash=SourceRevisionRef.compute_range_hash("a" * 64, 0, len(quote)),
        source_revision=1,
        segmentation_version=1,
        source_visibility="working",
    )
    observation_id = derive_observation_id(
        source_ref=source,
        predicate_or_description=quote,
        modality="character_statement",
        observer_contract_version=2,
    )
    entity_id = str(uuid4())

    def build_payload(group_status):
        speaker = {
            "mention_id": "m-1",
            "surface": "林舟",
            "outcome": "new_candidate",
            "resolved_entity_id": None,
            "rationale": "首次出现，候选待审查",
        }
        return {
            "compiled_observations": [
                {
                    "observation_id": observation_id,
                    "predicate": quote,
                    "quote": quote,
                    "modality": "character_statement",
                    "source_ref": source.model_dump(mode="json"),
                    "position": {"scene_id": scene, "scene_index": 0, "chapter_index": 1},
                    "dependency": {
                        "run_key": "run",
                        "attempt_id": "attempt",
                        "scene_id": scene,
                        "scene_index": 0,
                        "source_manifest_hash": "b" * 64,
                    },
                    "mentions": [
                        {
                            "mention_id": "m-1",
                            "surface": "林舟",
                            "entity_type": "character",
                            "resolution": dict(speaker),
                        }
                    ],
                    "utterance_attribution": {
                        "kind": "direct_dialogue",
                        "speaker_surface": "林舟",
                        "speaker_resolution": dict(speaker),
                    },
                    "evidence_quotes": [
                        {"quote": quote, "source_ref": source.model_dump(mode="json")}
                    ],
                }
            ],
            "proposed_scene_events": [],
            "world_result": {
                "context": {
                    "_new_entity_refs": {"entity_0": 0},
                    "_new_entity_ids": {"entity_0": entity_id},
                    "identity_candidates": [
                        {
                            "prompt_ref": "entity_0",
                            "name": "林舟",
                            "entity_type": "character",
                            "aliases": [],
                        }
                    ],
                },
                "review": {
                    "status": "passed" if group_status == "passed" else "blocked",
                    "groups": [
                        {
                            "status": group_status,
                            "identity_refs": ["entity_0"],
                            "members": [{"path": "entities", "index": 0}],
                        }
                    ],
                },
            },
        }

    bound = bind_scene_identities(build_payload("passed"))["compiled_observations"][0]
    speaker = bound["utterance_attribution"]["speaker_resolution"]
    assert speaker["outcome"] == "reuse"
    assert speaker["resolved_entity_id"] == entity_id

    # 身份同步后，本场台词即可作为语言习惯的合法发生来源。
    prepared = {
        "themes": {},
        "observations": {observation_id: bound},
        "method_fingerprint": method_fingerprint(),
    }
    batch = {"current_observation_ids": [observation_id], "historical_context": []}
    change = {
        "action": "new",
        "category": "language_habit",
        "label": "我不会忘记",
        "statement": "林舟在台词中说“我不会忘记”。",
        "conditions": [],
        "confidence": 0.7,
        "evidence": [
            {
                "observation_id": observation_id,
                "purpose": "occurrence",
                "occurrence_kind": "event",
            }
        ],
    }
    claim = LedgerClaim.model_validate(_compile_change(prepared, change, batch)["claim"])
    assert claim.evidence[0].speaker_entity_id == UUID(entity_id)

    # 审查未通过的候选不得借身份同步认证说话人。
    blocked = bind_scene_identities(build_payload("blocked"))["compiled_observations"][0]
    assert blocked["utterance_attribution"]["speaker_resolution"]["outcome"] == (
        "new_candidate"
    )


def test_world_group_adoption_scopes_cross_group_identity_dependencies():
    entities = [
        {"name": name, "entity_type": "character", "suggested_action": "create_new"}
        for name in ("林舟", "青竹")
    ]
    refs = {"new_0": 0, "new_1": 1}
    ids = {ref: f"candidate-{ref}" for ref in refs}
    candidates = [
        {
            "prompt_ref": ref,
            "name": entities[index]["name"],
            "entity_type": "character",
            "aliases": [],
        }
        for ref, index in refs.items()
    ]
    result = {
        "world": {"entities": entities, "delta_events": [], "uncertain_items": []},
        "relations": {
            "aliases": [{"entity_ref": "new_0"}],
            "relations": [],
            "uncertain_items": [],
        },
        "context": {
            "_new_entity_refs": refs,
            "_new_entity_ids": ids,
            "_entity_ref_map": {},
            "identity_candidates": candidates,
            "_identity_queries": [
                {"entity_type": "character", "name": entity["name"], "matches": []}
                for entity in entities
            ],
            "_initial_identity_queries": [],
            "relation_candidates": [],
        },
    }
    first_entity = {
        "members": [{"path": "entities", "index": 0}],
        "identity_refs": ["new_0", "new_1"],
        "required_refs": ["new_0"],
        "query_keys": [["character", "林舟"], ["character", "青竹"]],
        "apply_query_keys": [["character", "林舟"]],
    }
    first = world_group_apply_inputs(result, first_entity)
    assert first is not None
    assert first["context"]["_new_entity_refs"] == {"new_0": 0}
    assert [item["name"] for item in first["context"]["identity_candidates"]] == ["林舟"]

    alias_group = {
        "members": [{"path": "aliases", "index": 0}],
        "identity_refs": ["new_0", "new_1"],
        "required_refs": ["new_0"],
        "query_keys": [["character", "林舟"], ["character", "青竹"]],
        "apply_query_keys": [["character", "林舟"]],
    }
    assert world_group_apply_inputs(result, alias_group) is None
    alias = world_group_apply_inputs(result, alias_group, {"new_0"})
    assert alias is not None
    assert alias["context"]["_identity_queries"] == [
        {
            "entity_type": "character",
            "name": "林舟",
            "matches": [("candidate-new_0", "林舟")],
        }
    ]


def test_large_world_audit_splits_candidates_and_keeps_exact_source_ranges():
    names = ["角色甲", "角色乙", "角色丙"]
    quotes = [f"{name}留下独立线索。" for name in names]
    scene_text = (
        "甲" * 15_000 + quotes[0] + "乙" * 15_000 + quotes[1] + "丙" * 15_000 + quotes[2]
    )
    entities = [
        {
            "name": name,
            "entity_type": "character",
            "suggested_action": "create_new",
            "summary": "概" * 16_000,
            "public_info": "",
            "hidden_truth": "",
            "quote": quote,
            "evidence_quotes": [quote],
            "field_evidence": {},
        }
        for name, quote in zip(names, quotes, strict=True)
    ]
    candidates = [
        {
            "prompt_ref": f"new_{index}",
            "name": name,
            "entity_type": "character",
            "aliases": [],
        }
        for index, name in enumerate(names)
    ]
    context = {
        "identity_candidates": candidates,
        "_new_entity_refs": {f"new_{index}": index for index in range(len(names))},
        "_entity_ref_map": {},
        "_identity_queries": [
            {"entity_type": "character", "name": name, "matches": []} for name in names
        ],
    }
    payload = {
        "scene_text": scene_text,
        "relations_preparation": {
            "world": {
                "entities": entities,
                "delta_events": [],
                "uncertain_items": [],
            },
            "context": context,
        },
        "world_preparation": {
            "context": {
                "identity_candidates": [],
                "_entity_ref_map": {},
                "_identity_queries": [],
            }
        },
        "scene_relations": {
            "result": {"aliases": [], "relations": [], "uncertain_items": []}
        },
    }
    source = SceneSourceBinding(
        draft_id="draft",
        chapter_index=1,
        content_hash="a" * 64,
        start_offset=0,
        end_offset=len(scene_text),
    )
    prepared = prepare_world_audit_groups(
        payload=payload,
        source=source,
        run=SimpleNamespace(
            llm_snapshot_json={"profile": {"model": "deepseek-v4-flash"}}
        ),
        novel_id="novel",
        attempt_id="attempt",
    )
    groups = prepared["groups"]
    assert len(json.dumps(entities, ensure_ascii=False)) > 45_000
    assert len(groups) == 3
    assert all(group["spec"] and group["audit_input_chars"] < 45_000 for group in groups)
    for group in groups:
        interval = json.loads(group["scope"]["context"])["source_intervals"][0]
        quote_range = interval["occurrences"][0]["quote_ranges"][0]
        excerpt = scene_text[quote_range["start_offset"] : quote_range["end_offset"]]
        assert excerpt == interval["quote"]


def test_world_audit_quote_context_is_retained_for_repeated_evidence():
    scene_text = "前文标记引文后文标记。" * 9
    source = SceneSourceBinding(
        draft_id="draft",
        chapter_index=1,
        content_hash="a" * 64,
        start_offset=0,
        end_offset=len(scene_text),
    )
    _, interval, error = _quote_source(
        scene_text, _scene_source_chunks(source, scene_text), "引文"
    )
    assert error is None
    assert len(interval["occurrences"]) == 9
    assert all(
        "前文标记引文后文标记" in item["excerpt"] for item in interval["occurrences"]
    )

    repeated_text = "标记引文。" * 65
    repeated_source = source.model_copy(update={"end_offset": len(repeated_text)})
    _, interval, error = _quote_source(
        repeated_text,
        _scene_source_chunks(repeated_source, repeated_text),
        "引文",
    )
    assert interval is None and error == "source_occurrence_limit"


def world_provider(db, calls, *, blocked=False):
    async def provider(self, request, *, complete_stream=False):
        assert not db.in_transaction()
        assert request.model
        schema = json.loads(request.messages[-1].content.split("schema: ", 1)[1])["title"]
        prompt = next(item.content for item in request.messages if item.role == "user")
        calls.append((schema, prompt))
        if response := structure_response(request):
            return response
        if schema == "SceneSample":
            result = {
                "observations": [
                    {
                        "predicate": TEXT,
                        "quote": TEXT,
                        "modality": "event_observed",
                        "mentions": [
                            {"surface": name, "entity_type": "character"}
                            for name in ("林舟", "青竹")
                        ],
                    }
                ]
            }
        elif schema == "Phase2aSceneExtractionOutput":
            result = {
                "entities": [
                    {
                        "name": name,
                        "entity_type": "character",
                        "identity_disposition": "new",
                        "evidence_quotes": [TEXT],
                        "field_evidence": {
                            "name": [TEXT],
                            "entity_type": [TEXT],
                            "summary": [TEXT],
                        },
                        "summary": f"{name}是故事中的人物。",
                        "confidence": 0.95,
                    }
                    for name in ("林舟", "青竹")
                ]
            }
        elif schema == "AliasRelationExtractionOutput":
            context = json.loads(
                prompt.split("<untrusted_phase2b_context_json>", 1)[1].split("</", 1)[0]
            )
            refs = {
                item["name"]: item["prompt_ref"]
                for item in context["identity_candidates"]
            }
            result = {
                "aliases": [
                    {
                        "entity_ref": refs["林舟"],
                        "alias": "小舟",
                        "identity_scope": "durable",
                        "identity_basis": "正文明确又名",
                        "evidence_quotes": ["林舟又名小舟。"],
                        "confidence": 0.95,
                    }
                ],
                "relations": [
                    {
                        "source_ref": refs["林舟"],
                        "target_ref": refs["青竹"],
                        "relation_type": "ally",
                        "relation_kind": "social",
                        "persistence_scope": "enduring",
                        "directionality": "symmetric",
                        "claim_status": "established",
                        "description": "林舟和青竹是盟友。",
                        "basis": "原文直述",
                        "evidence_quotes": ["林舟和青竹是盟友。"],
                        "confidence": 0.95,
                    }
                ],
            }
        else:
            assert schema == "AuditVerdictOutput"
            result = {
                "verdict": "blocked" if blocked else "pass",
                "findings": [],
                "dimensions": [
                    {"dimension": key, "checked": True}
                    for key in ("prior_prose", "world_entities", "imported_assets")
                ],
            }
        return LLMCallResponse(
            content=json.dumps(result),
            finish_reason="stop",
            usage=LLMUsage(prompt_tokens=10, completion_tokens=10, total_tokens=20),
        )

    return provider


@pytest.mark.parametrize(
    "failure", [None, "blocked", "domain_write", "review_scope_changed"]
)
async def test_world_candidates_and_receipt_are_atomic_and_replay_free(
    db_session, evolution_project_id, account_llm_connection, monkeypatch, failure
):
    from modules.imports import facade as imports

    db, nid = db_session, evolution_project_id
    await seed(db, nid, 1, TEXT)
    calls = []
    monkeypatch.setattr(
        OpenAIProvider,
        "generate",
        world_provider(db, calls, blocked=failure == "blocked"),
    )
    run = (await start_reading(db, nid, await request_start(db, nid, end_chapter=1)))[
        "run"
    ]
    task_id = UUID(run["task_id"])
    task = await db.get(AsyncTask, task_id)
    store = PostgresAttemptStore(db, nid)
    if failure in {"domain_write", "review_scope_changed"}:
        original = imports.apply_scene_world_candidates

        async def broken(*args, **kwargs):
            await original(*args, **kwargs)
            raise RuntimeError("after world writes")

        monkeypatch.setattr(imports, "apply_scene_world_candidates", broken)
        with pytest.raises(RuntimeError, match="after world writes"):
            await handle_evolution_scene_step(db, task)
        await db.rollback()
        assert not (
            await db.scalars(select(CoreEntity).where(CoreEntity.novel_id == UUID(nid)))
        ).all()
        assert (await store.load_run(run["run_key"])).committed_scene_index == -1
        frozen = await store.load_pending_frozen(run["run_key"], 0)
        assert frozen.payload["world_result"]["review"]["status"] == "passed"
        monkeypatch.setattr(imports, "apply_scene_world_candidates", original)
        task = await db.get(AsyncTask, task_id)
        if failure == "review_scope_changed":
            from copy import deepcopy

            from core.errors import ConflictError

            payload = deepcopy(frozen.payload)
            payload.pop("world_result")
            spec = payload["world_review_preparation"]["groups"][0]["spec"]
            for message in spec["request"]["messages"]:
                message["content"] = message["content"].replace(
                    "initial_world_identity_context", "legacy_identity_context"
                )
            await store.replace_frozen_payload(
                frozen.model_copy(update={"payload": payload})
            )
            await db.commit()
            with pytest.raises(ConflictError) as error:
                await handle_evolution_scene_step(db, task)
            assert error.value.code == "scene_world_review_scope_changed"
            assert len(calls) == 4
            assert not (
                await db.scalars(
                    select(CoreEntity).where(CoreEntity.novel_id == UUID(nid))
                )
            ).all()
            return
    result = await handle_evolution_scene_step(db, task)
    frozen = await store.load_frozen(run["run_key"], result["attempt_id"])
    request = next(
        group["spec"]["request"]
        for group in frozen.payload["world_review_preparation"]["groups"]
        if group["spec"]
    )
    context = json.dumps(request, ensure_ascii=False)
    assert "initial_world_identity_context" in context
    # First stage had no identities; the relation stage receives new local refs.
    assert frozen.payload["world_preparation"]["context"]["identity_candidates"] == []
    assert frozen.payload["relations_preparation"]["context"]["identity_candidates"]
    assert len(calls) == 4
    receipt = await store.load_receipt(run["run_key"], result["attempt_id"])
    assert len(receipt.paid_call_receipts) == 4
    entities = (
        await db.scalars(select(CoreEntity).where(CoreEntity.novel_id == UUID(nid)))
    ).all()
    relations = (
        await db.scalars(
            select(EntityRelation).where(EntityRelation.novel_id == UUID(nid))
        )
    ).all()
    if failure == "blocked":
        assert not entities and not relations
        assert "scene_world_requires_review" in receipt.pending_decisions
    else:
        assert len(entities) == 2 and len(relations) == 1
        assert {item.status for item in [*entities, *relations]} == {"candidate"}
        person = next(item for item in entities if item.name == "林舟")
        assert person.content_json["aliases"][0]["alias"] == "小舟"
        assert person.content_json["aliases"][0]["status"] == "candidate"
        assert "scene_world_candidates_require_adoption" in receipt.pending_decisions
        assert len(receipt.world_result_refs) == 4
    from modules.evolution.workflow import reading_proposals

    proposals = await reading_proposals(db, nid, run["run_key"])
    assert proposals["total"] == 1 and not proposals["items"][0]["stale"]
    assert proposals["items"][0]["entities"][0]["name"] == "林舟"
    assert proposals["items"][0]["review_groups"][0]["status"] == (
        "blocked" if failure == "blocked" else "passed"
    )
    assert not (await reading_proposals(db, nid, run["run_key"], offset=1))["items"]
    await db.commit()
    replay = await handle_evolution_scene_step(db, task)
    assert replay["attempt_id"] == result["attempt_id"] and len(calls) == 4


async def test_world_budget_pause_only_sends_unfinished_calls(
    db_session, evolution_project_id, account_llm_connection, monkeypatch
):
    db, nid = db_session, evolution_project_id
    await seed(db, nid, 1, TEXT)
    calls = []
    monkeypatch.setattr(OpenAIProvider, "generate", world_provider(db, calls))
    run = (
        await start_reading(
            db, nid, await request_start(db, nid, request_limit=2, end_chapter=1)
        )
    )["run"]
    task = await db.get(AsyncTask, UUID(run["task_id"]))
    result = await handle_evolution_scene_step(db, task)
    assert not result["reading_complete"] and len(calls) == 2
    store = PostgresAttemptStore(db, nid)
    frozen = await store.load_pending_frozen(run["run_key"], 0)
    assert frozen.payload["scene_world"]["stage"] == "sampled"
    assert "scene_relations" not in frozen.payload
    assert not (
        await db.scalars(select(CoreEntity).where(CoreEntity.novel_id == UUID(nid)))
    ).all()
    task.status = "done"
    await db.commit()
    continued = (
        await start_reading(
            db,
            nid,
            await request_start(
                db,
                nid,
                request_limit=4,
                end_chapter=1,
                mode="continue",
                run_key=run["run_key"],
            ),
        )
    )["run"]
    result = await handle_evolution_scene_step(
        db, await db.get(AsyncTask, UUID(continued["task_id"]))
    )
    assert not result["reading_complete"] and result["attempt_id"] == frozen.attempt_id
    # The remaining budget finishes the reading through the structure stage.
    structure = await db.get(AsyncTask, UUID(result["next_task_id"]))
    result = await handle_evolution_scene_step(db, structure)
    assert result["reading_complete"]
    assert [schema for schema, _ in calls] == [
        "SceneSample",
        "Phase2aSceneExtractionOutput",
        "AliasRelationExtractionOutput",
        "AuditVerdictOutput",
        "SimpleStructureOutput",
        "StructureEvidenceReviewOutput",
    ]
    assert (await store.load_run(run["run_key"])).budget_remaining == 0


async def test_oversized_flash_world_audit_deferred_without_adopting_candidates(
    db_session, evolution_project_id, account_llm_connection, monkeypatch
):
    from modules.evolution import world as evolution_world

    db, nid = db_session, evolution_project_id
    await seed(db, nid, 1, TEXT)
    calls = []
    monkeypatch.setattr(OpenAIProvider, "generate", world_provider(db, calls))
    original = evolution_world.build_group_audit_request

    def oversized_audit(**kwargs):
        request, schema = original(**kwargs)
        return request.model_copy(
            update={
                "messages": [
                    *request.messages,
                    LLMMessage(role="user", content="x" * 45_001),
                ]
            }
        ), schema

    monkeypatch.setattr(evolution_world, "build_group_audit_request", oversized_audit)
    run = (await start_reading(db, nid, await request_start(db, nid, end_chapter=1)))[
        "run"
    ]
    task = await db.get(AsyncTask, UUID(run["task_id"]))
    result = await handle_evolution_scene_step(db, task)
    store = PostgresAttemptStore(db, nid)
    frozen = await store.load_frozen(run["run_key"], result["attempt_id"])
    receipt = await store.load_receipt(run["run_key"], result["attempt_id"])
    assert frozen.payload["world_result"]["review"]["review_kind"] == "capacity_deferred"
    assert not any(key.startswith("scene_world_review_group_") for key in frozen.payload)
    assert len(calls) == len(receipt.paid_call_receipts) == 3
    assert "scene_world_requires_review" in receipt.pending_decisions
    assert not (
        await db.scalars(select(CoreEntity).where(CoreEntity.novel_id == UUID(nid)))
    ).all()


async def test_known_world_format_failure_defers_only_world_and_keeps_receipt(
    db_session, evolution_project_id, account_llm_connection, monkeypatch
):
    db, nid = db_session, evolution_project_id
    await seed(db, nid, 1, TEXT)
    calls = []
    base = world_provider(db, calls)

    async def provider(self, request, *, complete_stream=False):
        response = await base(self, request)
        if calls[-1][0] == "Phase2aSceneExtractionOutput":
            return LLMCallResponse(
                content="not json",
                finish_reason="stop",
                usage=LLMUsage(prompt_tokens=10, completion_tokens=10, total_tokens=20),
            )
        return response

    monkeypatch.setattr(OpenAIProvider, "generate", provider)
    run = (await start_reading(db, nid, await request_start(db, nid, end_chapter=1)))[
        "run"
    ]
    task = await db.get(AsyncTask, UUID(run["task_id"]))
    result = await handle_evolution_scene_step(db, task)
    store = PostgresAttemptStore(db, nid)
    frozen = await store.load_frozen(run["run_key"], result["attempt_id"])
    receipt = await store.load_receipt(run["run_key"], result["attempt_id"])
    assert frozen.payload["scene_world"]["stage"] == "failed"
    assert (
        frozen.payload["world_result"]["review"]["review_kind"] == "extraction_deferred"
    )
    assert len(receipt.paid_call_receipts) == len(calls) == 2
    assert receipt.paid_call_receipts[-1]["outcome"] == "failed_final"
    assert not receipt.world_result_refs
    assert "scene_world_requires_review" in receipt.pending_decisions
    assert not (
        await db.scalars(select(CoreEntity).where(CoreEntity.novel_id == UUID(nid)))
    ).all()
    replay = await handle_evolution_scene_step(db, task)
    assert replay["attempt_id"] == result["attempt_id"] and len(calls) == 2


async def test_known_relation_format_failure_keeps_observations_and_defers_world(
    db_session, evolution_project_id, account_llm_connection, monkeypatch
):
    db, nid = db_session, evolution_project_id
    await seed(db, nid, 1, TEXT)
    calls = []
    base = world_provider(db, calls)

    async def provider(self, request, *, complete_stream=False):
        response = await base(self, request)
        if calls[-1][0] == "AliasRelationExtractionOutput":
            return LLMCallResponse(
                content="not json",
                finish_reason="stop",
                usage=LLMUsage(prompt_tokens=10, completion_tokens=10, total_tokens=20),
            )
        return response

    monkeypatch.setattr(OpenAIProvider, "generate", provider)
    run = (await start_reading(db, nid, await request_start(db, nid, end_chapter=1)))[
        "run"
    ]
    task = await db.get(AsyncTask, UUID(run["task_id"]))
    result = await handle_evolution_scene_step(db, task)
    store = PostgresAttemptStore(db, nid)
    frozen = await store.load_frozen(run["run_key"], result["attempt_id"])
    receipt = await store.load_receipt(run["run_key"], result["attempt_id"])
    assert frozen.payload["scene_relations"]["stage"] == "failed"
    assert (
        frozen.payload["world_result"]["review"]["review_kind"] == "extraction_deferred"
    )
    assert len(receipt.paid_call_receipts) == len(calls) == 3
    assert not receipt.world_result_refs
    assert "scene_world_requires_review" in receipt.pending_decisions
    replay = await handle_evolution_scene_step(db, task)
    assert replay["attempt_id"] == result["attempt_id"] and len(calls) == 3


async def test_world_identity_change_after_model_preserves_frozen_results(
    db_session, evolution_project_id, account_llm_connection, monkeypatch
):
    from modules.evolution.commit import CommitConflictError

    db, nid = db_session, evolution_project_id
    await seed(db, nid, 1, TEXT)
    calls = []
    base = world_provider(db, calls)

    async def provider(self, request, *, complete_stream=False):
        response = await base(self, request)
        if calls[-1][0] == "AuditVerdictOutput":
            db.add(
                CoreEntity(
                    novel_id=UUID(nid),
                    name="林舟",
                    entity_type="character",
                    status="canonical",
                    summary="作者自己的设定",
                )
            )
            await db.commit()
        return response

    monkeypatch.setattr(OpenAIProvider, "generate", provider)
    run = (await start_reading(db, nid, await request_start(db, nid, end_chapter=1)))[
        "run"
    ]
    with pytest.raises(CommitConflictError, match="world_identity_changed"):
        await handle_evolution_scene_step(
            db, await db.get(AsyncTask, UUID(run["task_id"]))
        )
    await db.rollback()
    store = PostgresAttemptStore(db, nid)
    frozen = await store.load_pending_frozen(run["run_key"], 0)
    assert frozen.payload["world_result"] and len(calls) == 4
    assert (await store.load_run(run["run_key"])).committed_scene_index == -1
    entities = (
        await db.scalars(select(CoreEntity).where(CoreEntity.novel_id == UUID(nid)))
    ).all()
    assert len(entities) == 1 and entities[0].summary == "作者自己的设定"


async def test_world_identity_aliases_share_canonical_materialization_context(
    db_session, evolution_project_id
):
    from copy import deepcopy

    from modules.imports import facade as imports
    from modules.imports.contracts import SceneWorldIdentityChangedError
    from modules.imports.scene_world import require_current_identities

    db, nid = db_session, evolution_project_id
    kinds = {"林舟": "character", "渡口": "location", "铜铃": "item", "石块": "object"}
    for name, kind in kinds.items():
        db.add(
            CoreEntity(
                novel_id=UUID(nid), name=name, entity_type=kind, status="canonical"
            )
        )
    await db.commit()
    context = await imports.prepare_scene_world_context(
        db,
        nid,
        [
            ("人物", "林舟"),
            ("角色", "林舟"),
            ("character_ref", "林舟"),
            ("地点", "渡口"),
            ("物品", "铜铃"),
            ("物体", "石块"),
        ],
    )
    assert {
        item["name"]: item["entity_type"] for item in context["identity_candidates"]
    } == kinds
    assert len(context["_identity_queries"]) == 4
    text = "林舟在渡口握着铜铃，脚边有石块。"
    world = imports.materialize_scene_world(
        text,
        context,
        {
            "entities": [
                {
                    "name": item["name"],
                    "entity_type": item["entity_type"],
                    "identity_disposition": "existing",
                    "matched_existing_ref": item["prompt_ref"],
                    "evidence_quotes": [text],
                }
                for item in context["identity_candidates"]
            ]
        },
    )
    assert len(world["entities"]) == 4
    assert all(
        item["suggested_action"] == "link_to_existing" for item in world["entities"]
    )
    await require_current_identities(db, nid, context)
    legacy = deepcopy(context)
    next(item for item in legacy["_identity_queries"] if item["name"] == "林舟")[
        "entity_type"
    ] = "人物"
    with pytest.raises(SceneWorldIdentityChangedError):
        await require_current_identities(db, nid, legacy)
    custom = await imports.prepare_scene_world_context(
        db, nid, [(kind, "铜铃") for kind in ["物件", "云图节点", "artifact"]]
    )
    assert not custom["identity_candidates"]
    assert {item["entity_type"] for item in custom["_identity_queries"]} == {
        "物件",
        "云图节点",
        "artifact",
    }


async def test_world_identity_labels_cannot_reveal_later_alias_or_merge_new_homonym(
    db_session, evolution_project_id
):
    from modules.imports import facade as imports

    db, nid = db_session, evolution_project_id
    person = CoreEntity(
        novel_id=UUID(nid),
        name="林舟",
        entity_type="character",
        status="canonical",
        content_json={"aliases": [{"alias": "黑衣人", "status": "canonical"}]},
    )
    db.add(person)
    await db.commit()
    context = await imports.prepare_scene_world_context(
        db, nid, [("character", "黑衣人")]
    )
    assert (
        not context["identity_candidates"]
        and not context["_identity_queries"][0]["matches"]
    )
    text = "另一个名叫林舟的人走进房间。"
    context = await imports.prepare_scene_world_context(db, nid, [("character", "林舟")])
    world = imports.materialize_scene_world(
        text,
        context,
        {
            "entities": [
                {
                    "name": "林舟",
                    "entity_type": "character",
                    "identity_disposition": "new",
                    "evidence_quotes": [text],
                    "field_evidence": {"entity_type": [text]},
                }
            ]
        },
    )
    context = {
        **imports.prepare_scene_relations_context(context, world),
        "_current_scene_text": text,
    }
    assert not context["identity_candidates"] and not context["_entity_ref_map"]
    result = await imports.apply_scene_world_candidates(
        db,
        nid,
        scene_id=None,
        scene_index=0,
        chapter_index=1,
        workflow_id="identity-test",
        attempt_id="identity-attempt",
        world=world,
        relations={},
        context=context,
        review={"status": "passed"},
    )
    assert not result["result_refs"]
    assert "world_identity_ambiguous:0" in result["pending"]
    assert (
        len(
            (
                await db.scalars(
                    select(CoreEntity).where(CoreEntity.novel_id == UUID(nid))
                )
            ).all()
        )
        == 1
    )


@pytest.mark.parametrize(
    "path",
    [
        "entity",
        "relation_update",
        "relation_review",
        "alias_canonical",
        "alias_active",
        "alias_published",
        "alias_null",
        "alias_string",
    ],
)
async def test_stale_world_candidate_cannot_be_adopted_through_existing_edit_paths(
    db_session, evolution_project_id, account_llm_connection, monkeypatch, path
):
    from core.errors import ConflictError
    from modules.world.schemas import (
        CoreEntityUpdate,
        EntityPromoteRequest,
        EntityRelationReviewEditRequest,
        EntityRelationUpdate,
    )
    from modules.world.services.core.entity_alias_service import EntityAliasService
    from modules.world.services.core.entity_relation_service import EntityRelationService
    from modules.world.services.core.entity_service import WorldEntityService
    from modules.writing.facade import create_draft_only

    db, nid = db_session, evolution_project_id
    await seed(db, nid, 1, TEXT)
    monkeypatch.setattr(OpenAIProvider, "generate", world_provider(db, []))
    run = (await start_reading(db, nid, await request_start(db, nid, end_chapter=1)))[
        "run"
    ]
    await handle_evolution_scene_step(db, await db.get(AsyncTask, UUID(run["task_id"])))
    person = await db.scalar(
        select(CoreEntity).where(
            CoreEntity.novel_id == UUID(nid), CoreEntity.name == "林舟"
        )
    )
    relation = await db.scalar(
        select(EntityRelation).where(EntityRelation.novel_id == UUID(nid))
    )
    person_id, relation_id = str(person.id), str(relation.id)
    service = WorldEntityService()
    if path == "alias_string":
        await service.promote(db, person_id, EntityPromoteRequest(), novel_id=nid)
        await db.commit()
    if path == "entity":
        reference = person.content_json["_meta"]["evolution_ref"]
        await service.update(
            db,
            person_id,
            CoreEntityUpdate(content_json={"_meta": {"evolution_ref": None}}),
            novel_id=nid,
        )
        assert person.content_json["_meta"]["evolution_ref"] == reference
        await db.commit()
    await create_draft_only(db, nid, 1, "改稿", "林舟独自离开，没有结盟。")
    await db.commit()
    with pytest.raises(ConflictError, match="理解来源"):
        if path == "entity":
            await service.promote(db, person_id, EntityPromoteRequest(), novel_id=nid)
        elif path == "relation_update":
            await EntityRelationService().update(
                db, relation_id, EntityRelationUpdate(status="canonical"), novel_id=nid
            )
        elif path == "relation_review":
            await EntityRelationService().review_edit(
                db, nid, relation_id, EntityRelationReviewEditRequest()
            )
        elif path == "alias_string":
            await service.update(
                db,
                person_id,
                CoreEntityUpdate(content_json={"aliases": ["小舟"]}),
                novel_id=nid,
            )
        else:
            status = path.removeprefix("alias_")
            await EntityAliasService().update_alias(
                db,
                nid,
                person_id,
                "小舟",
                {"status": None if status == "null" else status},
            )
    await db.rollback()


async def test_new_relation_attempt_cannot_relabel_old_candidate_content_as_fresh(
    db_session, evolution_project_id
):
    from modules.world.facade import create_or_merge_relation

    db, nid = db_session, evolution_project_id
    left = CoreEntity(
        novel_id=UUID(nid), name="甲", entity_type="character", status="candidate"
    )
    right = CoreEntity(
        novel_id=UUID(nid), name="乙", entity_type="character", status="candidate"
    )
    db.add_all([left, right])
    await db.flush()
    old_ref = {"run_key": "old", "attempt_id": "before-edit"}
    relation = EntityRelation(
        novel_id=UUID(nid),
        source_id=left.id,
        target_id=right.id,
        relation_type="ally",
        relation_kind="social",
        status="candidate",
        description="旧稿是终身同盟",
        quote="终身同盟",
        review_meta={"evolution_ref": old_ref},
    )
    db.add(relation)
    await db.commit()
    result = await create_or_merge_relation(
        db,
        nid,
        {
            "source_id": str(left.id),
            "target_id": str(right.id),
            "relation_type": "ally",
            "relation_kind": "social",
            "status": "candidate",
            "description": "新稿只是临时合作",
            "quote": "临时合作",
            "review_meta": {
                "evolution_ref": {"run_key": "new", "attempt_id": "after-edit"}
            },
        },
    )
    assert result["reason"] == "candidate_sources_differ"
    await db.refresh(relation)
    assert relation.description == "旧稿是终身同盟" and relation.quote == "终身同盟"
    assert relation.review_meta["evolution_ref"] == old_ref


@pytest.mark.parametrize("failure", [None, "blocked", "domain_write", "ambiguous"])
async def test_first_scene_identity_is_reviewed_before_atomic_presence_commit(
    db_session, evolution_project_id, account_llm_connection, monkeypatch, failure
):
    from modules.story import facade as story
    from modules.story.facade import project_scene_presence

    db, nid = db_session, evolution_project_id
    presence = "林舟出现在渡口。"
    await seed(db, nid, 1, TEXT + presence)
    calls = []
    base = world_provider(db, calls, blocked=failure == "blocked")

    async def provider(self, request, *, complete_stream=False):
        schema = json.loads(request.messages[-1].content.split("schema: ", 1)[1])["title"]
        if failure == "ambiguous" and schema == "AliasRelationExtractionOutput":
            calls.append((schema, request.messages[1].content))
            return LLMCallResponse(content="{}", finish_reason="stop", usage=LLMUsage())
        if schema == "StateReview":
            assert not db.in_transaction()
            calls.append((schema, request.messages[1].content))
            data = json.loads(request.messages[1].content)
            UUID(data["events"][0]["entity_id"])
            assert not (
                await db.scalars(
                    select(CoreEntity).where(CoreEntity.novel_id == UUID(nid))
                )
            ).all()
            await db.rollback()
            return LLMCallResponse(
                content=json.dumps(
                    {
                        "events": [
                            {
                                "event_index": 0,
                                "verdict": "supported",
                                "reason": "原文明示在场",
                                "quotes": [presence],
                            }
                        ]
                    }
                ),
                finish_reason="stop",
                usage=LLMUsage(),
            )
        response = await base(self, request)
        if failure == "ambiguous" and schema == "Phase2aSceneExtractionOutput":
            result = json.loads(response.content)
            result["entities"].append(
                {**result["entities"][0], "summary": "另一位同名人物"}
            )
            response = response.model_copy(update={"content": json.dumps(result)})
        if schema == "SceneSample":
            result = json.loads(response.content)
            result["observations"].append(
                {
                    "predicate": presence,
                    "quote": presence,
                    "modality": "event_observed",
                    "mentions": [{"surface": "林舟", "entity_type": "character"}],
                }
            )
            result["scene_events"] = [
                {
                    "event_type": "entity_moved",
                    "dimension": "locations",
                    "subject_surface": "林舟",
                    "snapshot_after": {"text_state": "渡口"},
                    "source_observation_indices": [1],
                }
            ]
            response = response.model_copy(update={"content": json.dumps(result)})
        return response

    monkeypatch.setattr(OpenAIProvider, "generate", provider)
    run = (await start_reading(db, nid, await request_start(db, nid, end_chapter=1)))[
        "run"
    ]
    task_id = UUID(run["task_id"])
    store = PostgresAttemptStore(db, nid)
    original = story.replace_scene_memory_events
    if failure == "domain_write":

        async def broken(*args, **kwargs):
            await original(*args, **kwargs)
            raise RuntimeError("after state writes")

        monkeypatch.setattr(story, "replace_scene_memory_events", broken)
        with pytest.raises(RuntimeError, match="after state writes"):
            await handle_evolution_scene_step(db, await db.get(AsyncTask, task_id))
        await db.rollback()
        assert not (
            await db.scalars(select(CoreEntity).where(CoreEntity.novel_id == UUID(nid)))
        ).all()
        assert (await store.load_run(run["run_key"])).committed_scene_index == -1
        monkeypatch.setattr(story, "replace_scene_memory_events", original)
    result = await handle_evolution_scene_step(db, await db.get(AsyncTask, task_id))
    frozen = await store.load_frozen(run["run_key"], result["attempt_id"])
    view = await project_scene_presence(db, nid, through_scene_index=0)
    if failure in {"blocked", "ambiguous"}:
        expected_calls = 5 if failure == "ambiguous" else 4
        assert not frozen.payload["scene_events"] and len(calls) == expected_calls
        assert not (
            await db.scalars(select(CoreEntity).where(CoreEntity.name == "林舟"))
        ).all()
    else:
        person = await db.scalar(select(CoreEntity).where(CoreEntity.name == "林舟"))
        assert person.status == "candidate"
        assert frozen.payload["scene_events"][0]["entity_id"] == str(person.id)
        if failure is None:
            assert result["identity_outcomes"] == {"reuse": 3}
        assert len(calls) == 5
        assert "渡口" in str(view)
        assert not frozen.payload["gated_scene_events"]


@pytest.mark.parametrize("failure", ["blocked", "invalid_json"])
async def test_world_audit_group_failure_does_not_block_independent_candidate(
    db_session, evolution_project_id, account_llm_connection, monkeypatch, failure
):
    db, nid = db_session, evolution_project_id
    await seed(db, nid, 1, TEXT)
    calls = []
    base = world_provider(db, calls)

    async def provider(self, request, *, complete_stream=False):
        response = await base(self, request)
        schema, prompt = calls[-1]
        if schema == "AliasRelationExtractionOutput":
            result = {"aliases": [], "relations": [], "uncertain_items": []}
            return response.model_copy(update={"content": json.dumps(result)})
        if schema == "AuditVerdictOutput":
            output = json.loads(prompt.split("【生成输出（待审）】\n", 1)[1])
            blocked = output["world"]["entities"][0]["name"] == "林舟"
            if blocked and failure == "invalid_json":
                return response.model_copy(update={"content": "not json"})
            result = {
                "verdict": "blocked" if blocked and failure == "blocked" else "pass",
                "findings": [],
                "dimensions": [
                    {"dimension": key, "checked": True}
                    for key in ("prior_prose", "world_entities", "imported_assets")
                ],
            }
            return response.model_copy(update={"content": json.dumps(result)})
        return response

    monkeypatch.setattr(OpenAIProvider, "generate", provider)
    run = (await start_reading(db, nid, await request_start(db, nid, end_chapter=1)))[
        "run"
    ]
    task = await db.get(AsyncTask, UUID(run["task_id"]))
    result = await handle_evolution_scene_step(db, task)
    frozen = await PostgresAttemptStore(db, nid).load_frozen(
        run["run_key"], result["attempt_id"]
    )
    groups = frozen.payload["world_result"]["review"]["groups"]
    assert sorted(group["status"] for group in groups) == ["blocked", "passed"]
    failed = next(group for group in groups if group["status"] == "blocked")
    mention_resolutions = {
        mention["surface"]: (mention.get("resolution") or {}).get("outcome")
        for observation in frozen.payload["compiled_observations"]
        for mention in observation["mentions"]
    }
    assert mention_resolutions["青竹"] == "reuse"
    assert mention_resolutions["林舟"] != "reuse"
    if failure == "invalid_json":
        assert failed["review_kind"] == "audit_failed"
        journals = [
            value
            for key, value in frozen.payload.items()
            if key.startswith("scene_world_review_group_")
        ]
        assert any(
            item["stage"] == "failed" and item.get("paid_call_receipt")
            for item in journals
        )
    saved = await db.scalars(select(CoreEntity).where(CoreEntity.novel_id == UUID(nid)))
    assert len(saved.all()) == 1
    receipt = await PostgresAttemptStore(db, nid).load_receipt(
        run["run_key"], result["attempt_id"]
    )
    if failure == "invalid_json":
        assert any(
            item["outcome"] == "failed_final" for item in receipt.paid_call_receipts
        )
    assert len([schema for schema, _ in calls if schema == "AuditVerdictOutput"]) == 2
    await handle_evolution_scene_step(db, task)
    assert len([schema for schema, _ in calls if schema == "AuditVerdictOutput"]) == 2


async def test_world_audit_group_unknown_fee_failure_stays_unreconciled(
    db_session, evolution_project_id, account_llm_connection, monkeypatch
):
    """费用未知的审查失败必须停在待核清门禁：不提交、不重发、不继续付费。"""
    from modules.evolution.pipeline import SamplePendingReconciliationError
    from modules.evolution.state_review import (
        SceneCallFailedError,
        has_unreconciled_scene_calls,
    )

    db, nid = db_session, evolution_project_id
    await seed(db, nid, 1, TEXT)
    calls = []
    base = world_provider(db, calls)

    async def provider(self, request, *, complete_stream=False):
        response = await base(self, request)
        schema, prompt = calls[-1]
        if schema == "AliasRelationExtractionOutput":
            result = {"aliases": [], "relations": [], "uncertain_items": []}
            return response.model_copy(update={"content": json.dumps(result)})
        if schema == "AuditVerdictOutput":
            output = json.loads(prompt.split("【生成输出（待审）】\n", 1)[1])
            if output["world"]["entities"][0]["name"] == "林舟":
                raise TimeoutError("simulated network timeout")
        return response

    monkeypatch.setattr(OpenAIProvider, "generate", provider)
    run = (await start_reading(db, nid, await request_start(db, nid, end_chapter=1)))[
        "run"
    ]
    task = await db.get(AsyncTask, UUID(run["task_id"]))
    with pytest.raises(SceneCallFailedError):
        await handle_evolution_scene_step(db, task)
    await db.rollback()
    store = PostgresAttemptStore(db, nid)
    assert (await store.load_run(run["run_key"])).committed_scene_index == -1
    pending = await store.load_pending_frozen(run["run_key"], 0)
    assert pending is not None
    # 回执是字典但费用未知：必须仍判未核清。
    assert has_unreconciled_scene_calls(pending.payload)
    audits = len([schema for schema, _ in calls if schema == "AuditVerdictOutput"])
    task = await db.get(AsyncTask, UUID(run["task_id"]))
    with pytest.raises(SamplePendingReconciliationError):
        await handle_evolution_scene_step(db, task)
    assert (
        len([schema for schema, _ in calls if schema == "AuditVerdictOutput"]) == audits
    )


@pytest.mark.parametrize("receipt_state", ["sampled", "unknown"])
async def test_legacy_capacity_deferred_supplement_needs_preview_and_confirmation(
    db_session, evolution_project_id, account_llm_connection, monkeypatch, receipt_state
):
    from copy import deepcopy

    from modules.evolution.workflow import reading_proposals
    from modules.evolution.world_audit_supplement import (
        WorldAuditSupplementStart,
        handle_world_audit_supplement,
        preview_world_audit_supplement,
        resume_world_audit_supplement,
        start_world_audit_supplement,
    )

    db, nid = db_session, evolution_project_id

    async def checkpoint_task_progress(_self):
        return True

    monkeypatch.setattr(
        type(db), "checkpoint_task_progress", checkpoint_task_progress, raising=False
    )
    await seed(db, nid, 1, TEXT)
    calls = []
    monkeypatch.setattr(
        OpenAIProvider,
        "generate",
        world_provider(db, calls, blocked=True),
    )
    run = (await start_reading(db, nid, await request_start(db, nid, end_chapter=1)))[
        "run"
    ]
    task = await db.get(AsyncTask, UUID(run["task_id"]))
    result = await handle_evolution_scene_step(db, task)
    origin_attempt_id = result["attempt_id"]
    task.mark_done(result)
    await db.commit()
    store = PostgresAttemptStore(db, nid)
    next_task_id = result.get("next_task_id")
    while next_task_id:
        task = await db.get(AsyncTask, UUID(next_task_id))
        result = await handle_evolution_scene_step(db, task)
        task.mark_done(result)
        await db.commit()
        next_task_id = result.get("next_task_id")
    origin = await store.load_frozen(run["run_key"], origin_attempt_id)
    payload = deepcopy(origin.payload)
    for key in list(payload):
        if key.startswith("scene_world_review_group_"):
            payload.pop(key)
    payload.pop("world_review_preparation", None)
    payload["world_result"]["review"] = {
        "status": "blocked",
        "review_kind": "capacity_deferred",
        "issues": [{"message": "旧版本整场审查容量不足。"}],
    }
    await store.replace_frozen_payload(origin.model_copy(update={"payload": payload}))
    await db.commit()
    calls_before_preview = len(calls)
    origin_run = await store.load_run(run["run_key"])
    budget_before = origin_run.budget_remaining

    preview = await preview_world_audit_supplement(
        db, nid, run["run_key"], origin_attempt_id
    )
    assert preview["group_count"] == preview["call_count"] == 1
    assert preview["additional_budget"] == 0
    assert len(calls) == calls_before_preview
    start_request = WorldAuditSupplementStart(
        operation_id=uuid4(),
        expected_fingerprint=preview["fingerprint"],
        authorization_confirmed=True,
    )
    from core.errors import ConflictError

    original_task = await db.get(AsyncTask, UUID(origin_run.reading_plan_json["task_id"]))
    original_status = original_task.status
    original_task.status = "pending"
    await db.commit()
    with pytest.raises(ConflictError, match="原理解任务仍在运行"):
        await start_world_audit_supplement(
            db, nid, run["run_key"], origin_attempt_id, start_request
        )
    await db.rollback()
    origin_run = await store.load_run(run["run_key"])
    assert origin_run.budget_remaining == budget_before
    assert not origin_run.reading_plan_json.get("world_audit_supplements")
    original_task = await db.get(AsyncTask, UUID(origin_run.reading_plan_json["task_id"]))
    original_task.status = original_status
    await db.commit()
    queued = await start_world_audit_supplement(
        db, nid, run["run_key"], origin_attempt_id, start_request
    )
    replayed = await start_world_audit_supplement(
        db, nid, run["run_key"], origin_attempt_id, start_request
    )
    assert replayed["task_id"] == queued["task_id"]
    assert len(calls) == calls_before_preview
    from core.errors import ConflictError
    from modules.evolution.workflow import ReadingRequest, preview_reading

    with pytest.raises(ConflictError, match="补审或类别补扫仍在运行"):
        await preview_reading(
            db,
            nid,
            ReadingRequest(
                operation_id=uuid4(),
                mode="continue",
                run_key=run["run_key"],
                end_chapter=1,
                request_limit=2,
            ),
        )
    monkeypatch.setattr(OpenAIProvider, "generate", world_provider(db, calls))
    supplement_task = await db.get(AsyncTask, UUID(queued["task_id"]))
    if receipt_state == "unknown":
        frozen_supplement = await store.load_frozen(run["run_key"], queued["attempt_id"])
        group_id = frozen_supplement.payload["world_review_preparation"]["groups"][0][
            "group_id"
        ]
        payload = deepcopy(frozen_supplement.payload)
        payload[f"scene_world_review_group_{group_id}"] = {"stage": "failed"}
        await store.replace_frozen_payload(
            frozen_supplement.model_copy(update={"payload": payload})
        )
        await db.commit()
        from modules.evolution.pipeline import SamplePendingReconciliationError

        with pytest.raises(SamplePendingReconciliationError):
            await handle_world_audit_supplement(db, supplement_task)
        assert supplement_task.meta["recovery_required"] is False
        assert supplement_task.result["recovery_required"] is False
        supplement_task.mark_failed("unknown receipt")
        await db.commit()
        proposals = await reading_proposals(db, nid, run["run_key"])
        assert proposals["items"][0]["supplement"]["status"] == "needs_reconciliation"
        assert proposals["items"][0]["supplement"]["can_resume"] is False
        from core.errors import ConflictError

        with pytest.raises(ConflictError, match="尚未核清"):
            await resume_world_audit_supplement(
                db, nid, run["run_key"], origin_attempt_id
            )
        assert len(calls) == calls_before_preview
        return

    from modules.evolution import world

    materialize = world.materialize_world_audit_group

    def interrupt_after_paid_receipt(*_args, **_kwargs):
        raise RuntimeError("interrupted after sampled result was saved")

    monkeypatch.setattr(
        world, "materialize_world_audit_group", interrupt_after_paid_receipt
    )
    with pytest.raises(RuntimeError, match="after sampled result"):
        await handle_world_audit_supplement(db, supplement_task)
    assert supplement_task.meta["recovery_required"] is True
    assert supplement_task.result["recovery_required"] is True
    assert len(calls) == calls_before_preview + 1
    supplement_task.mark_failed("interrupted")
    await db.commit()
    proposals = await reading_proposals(db, nid, run["run_key"])
    assert proposals["items"][0]["supplement"]["can_resume"] is True
    # Lifecycle recovery remains authoritative after a worker crash.
    crashed = await store.load_frozen(run["run_key"], queued["attempt_id"])
    await store.replace_frozen_payload(
        crashed.model_copy(
            update={"payload": {**crashed.payload, "world_audit_status": "running"}}
        )
    )
    await db.commit()
    resumed = await resume_world_audit_supplement(
        db, nid, run["run_key"], origin_attempt_id
    )
    assert resumed == {"task_id": queued["task_id"], "status": "pending"}
    monkeypatch.setattr(world, "materialize_world_audit_group", materialize)
    outcome = await handle_world_audit_supplement(db, supplement_task)
    assert len(calls) == calls_before_preview + 1
    supplement_task.mark_done(outcome)
    await db.commit()

    supplemental = await store.load_frozen(run["run_key"], queued["attempt_id"])
    original = await store.load_frozen(run["run_key"], origin_attempt_id)
    receipt = await store.load_receipt(run["run_key"], origin_attempt_id)
    current_run = await store.load_run(run["run_key"])
    assert supplemental.payload["world_audit_status"] == "completed"
    reviewed = list(supplemental.payload["world_audit_reviews"].values())[0]
    assert reviewed["status"] == "passed"
    assert (
        original.payload["world_result"]["review"]["review_kind"] == "capacity_deferred"
    )
    assert current_run.budget_remaining == budget_before - 1
    assert len(supplemental.payload["world_audit_result_refs"]) == 4
    assert not receipt.world_result_refs
    proposals = await reading_proposals(db, nid, run["run_key"])
    assert proposals["items"][0]["review_status"] == "passed"
    assert proposals["items"][0]["supplement"]["status"] == "completed"
    assert proposals["items"][0]["review_groups"][0]["status"] == "passed"


async def test_relation_history_uses_real_prefix_and_not_mutated_world_rows(
    db_session, evolution_project_id, account_llm_connection, monkeypatch
):
    db, nid = db_session, evolution_project_id
    ended = "林舟和青竹宣布不再结盟。"
    await seed(db, nid, 1, TEXT)
    await seed(db, nid, 2, ended)
    calls, history = [], []
    base = world_provider(db, calls)
    second = False

    async def provider(self, request, *, complete_stream=False):
        response = await base(self, request)
        if not second:
            return response
        schema, prompt = calls[-1]
        result = json.loads(response.content)
        assert "后文才揭示的秘密" not in prompt
        if schema == "SceneSample":
            result["observations"][0].update(predicate=ended, quote=ended)
        elif schema == "Phase2aSceneExtractionOutput":
            context = json.loads(
                prompt.split("<untrusted_scene_context_json>", 1)[1].split("</", 1)[0]
            )
            refs = {
                item["name"]: item["prompt_ref"]
                for item in context["identity_candidates"]
            }
            for item in result["entities"]:
                item.update(
                    identity_disposition="existing",
                    matched_existing_ref=refs[item["name"]],
                    evidence_quotes=[ended],
                    field_evidence={"name": [ended]},
                )
                item.pop("summary")
        elif schema == "AliasRelationExtractionOutput":
            context = json.loads(
                prompt.split("<untrusted_phase2b_context_json>", 1)[1].split("</", 1)[0]
            )
            assert len(context["relation_candidates"]) == 1
            previous = context["relation_candidates"][0]
            assert previous["description"] == "林舟和青竹是盟友。"
            assert previous["scene_index"] == 0
            history.append(previous)
            result["aliases"] = []
            result["relations"][0].update(
                claim_status="ended",
                previous_relation_ref=previous["prompt_ref"],
                description=ended,
                evidence_quotes=[ended],
            )
        return response.model_copy(update={"content": json.dumps(result)})

    monkeypatch.setattr(OpenAIProvider, "generate", provider)
    run = (await start_reading(db, nid, await request_start(db, nid, end_chapter=2)))[
        "run"
    ]
    task = await db.get(AsyncTask, UUID(run["task_id"]))
    first = await handle_evolution_scene_step(db, task)
    task.status = "done"
    relation = await db.scalar(
        select(EntityRelation).where(EntityRelation.novel_id == UUID(nid))
    )
    relation_id = relation.id
    relation.description = "后文才揭示的秘密"
    await db.commit()
    second = True
    task = await db.get(AsyncTask, UUID(first["next_task_id"]))
    result = await handle_evolution_scene_step(db, task)
    task.status = "done"
    # Settle the queued structure stage so the scoped recompute can take over.
    structure = await db.get(AsyncTask, UUID(result["next_task_id"]))
    structure.status = "done"
    await db.commit()
    store = PostgresAttemptStore(db, nid)
    frozen = await store.load_frozen(run["run_key"], result["attempt_id"])
    reasons = {
        item["reason"] for item in frozen.payload["world_materialization"]["diagnostics"]
    }
    assert "relation_change_requires_author_review" in reasons
    assert "unknown_previous_relation_ref" not in reasons
    assert (await db.get(EntityRelation, relation_id)).description == "后文才揭示的秘密"
    assert history[0]["source_receipt"] == {
        "run_key": run["run_key"],
        "attempt_id": first["attempt_id"],
    }
    updated = (
        await start_reading(
            db,
            nid,
            await request_start(
                db,
                nid,
                mode="scoped_recompute",
                run_key=run["run_key"],
                from_scene_index=1,
                end_chapter=2,
            ),
        )
    )["run"]
    await handle_evolution_scene_step(
        db, await db.get(AsyncTask, UUID(updated["task_id"]))
    )
    assert len(history) == 2 and history[1] == history[0]
    assert len(calls) == 10  # unchanged sampler and World extraction reused
