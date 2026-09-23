"""World proposals share the real gateway, root budget and atomic Scene receipt."""

import json
from uuid import UUID

import pytest
from sqlalchemy import select

from infrastructure.llm.providers import OpenAIProvider
from infrastructure.llm.schemas import LLMCallResponse, LLMMessage, LLMUsage
from infrastructure.tasks.models import AsyncTask
from modules.evolution.store import PostgresAttemptStore
from modules.evolution.tasks import handle_evolution_scene_step
from modules.evolution.tests.test_workflow import request_start, seed, structure_response
from modules.evolution.workflow import start_reading
from modules.world.models import CoreEntity, EntityRelation

TEXT = "林舟又名小舟。林舟和青竹是盟友。"


def world_provider(db, calls, *, blocked=False):
    async def provider(self, request):
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


@pytest.mark.parametrize("failure", [None, "blocked", "domain_write"])
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
    if failure == "domain_write":
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
    result = await handle_evolution_scene_step(db, task)
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
    assert "scene_world_review" not in frozen.payload
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

    async def provider(self, request):
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


async def test_world_identity_change_after_model_preserves_frozen_results(
    db_session, evolution_project_id, account_llm_connection, monkeypatch
):
    from modules.evolution.commit import CommitConflictError

    db, nid = db_session, evolution_project_id
    await seed(db, nid, 1, TEXT)
    calls = []
    base = world_provider(db, calls)

    async def provider(self, request):
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

    async def provider(self, request):
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
        assert not frozen.payload["scene_events"] and len(calls) == 4
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

    async def provider(self, request):
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
    assert len(calls) == 12
