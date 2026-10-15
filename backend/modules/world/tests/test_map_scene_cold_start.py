"""Synthetic product Scene reads exercise World materialization before map discovery."""

from uuid import UUID

import pytest
from sqlalchemy import select

from modules.evolution.facade import switch_project_engine
from modules.evolution.sampler import register_scene_sampler
from modules.evolution.spatial import _current_endpoints, _endpoint_inputs
from modules.evolution.store import PostgresAttemptStore
from modules.evolution.tasks import handle_evolution_scene_step
from modules.evolution.tests.test_optional_scene import seed
from modules.evolution.tests.test_source_integrity import request
from modules.world.map_spatial_clue_service import read_spatial_discovery_context
from modules.world.models import CoreEntity

TEXT = "栖园紧挨霜台。"


class ColdStartSampler:
    def __init__(self, mentions):
        self.mentions = mentions
        self.calls = []

    async def sample(self, *, scene_text, input_manifest):
        self.calls.append("observe")
        return {
            "observations": [
                {"predicate": TEXT, "quote": TEXT, "mentions": self.mentions}
            ],
            "scene_events": [],
        }

    async def execute_world_request(self, *, request, schema_name, schema_hash):
        self.calls.append(schema_name)
        if schema_name == "Phase2aSceneExtractionOutput":
            result = {
                "entities": [
                    {
                        "name": name,
                        "entity_type": "location",
                        "identity_disposition": "new",
                        "evidence_quotes": [TEXT],
                        "field_evidence": {"entity_type": [TEXT]},
                    }
                    for name in ("栖园", "霜台")
                ]
            }
        elif schema_name == "AliasRelationExtractionOutput":
            result = {}
        else:
            assert schema_name == "AuditVerdictOutput"
            result = {
                "verdict": "pass",
                "findings": [],
                "dimensions": [
                    {"dimension": key, "checked": True}
                    for key in ("prior_prose", "world_entities", "imported_assets")
                ],
            }
        return {"result": result}


async def materialized_world(db, nid, mention_type=None):
    await switch_project_engine(db, nid, to_engine="evolution", expected_epoch=1)
    await db.commit()
    scene_id = await seed(db, nid, {1: TEXT})
    sampler = ColdStartSampler(
        []
        if mention_type is None
        else [
            {"surface": name, "entity_type": mention_type} for name in ("栖园", "霜台")
        ],
    )
    register_scene_sampler("source-integrity", lambda db, novel_id: sampler)
    store = PostgresAttemptStore(db, nid)
    run = await store.register_run("source-integrity", mode="append", budget_total=20)
    run.reading_plan_json = {"steps": [], "optional_stage_version": 1}
    await db.commit()
    result = await handle_evolution_scene_step(
        db,
        request(
            nid, scene_id, TEXT, budget_total=20, world_version=2, state_review_version=0
        ),
    )
    receipt = await store.load_committed_scene_receipt("source-integrity", 0)
    assert receipt is not None and receipt.attempt_id == result["attempt_id"]
    entities = list(
        await db.scalars(select(CoreEntity).where(CoreEntity.novel_id == UUID(nid)))
    )
    assert {item.name for item in entities} == {"栖园", "霜台"}
    assert {item.status for item in entities} == {"candidate"}
    frozen = await store.load_frozen("source-integrity", receipt.attempt_id)
    return store, receipt, frozen, entities, scene_id


@pytest.mark.parametrize("mention_type", [None, "location", "地点"])
@pytest.mark.parametrize("adopted", [False, True])
async def test_materialized_scene_world_locations_reach_spatial_endpoints(
    db_session, test_project_id, mention_type, adopted
):
    db, nid = db_session, test_project_id
    store, receipt, frozen, entities, scene_id = await materialized_world(
        db, nid, mention_type
    )
    if adopted:
        for entity in entities:
            entity.status = "canonical"
        await db.commit()
    by_id, surfaces = _current_endpoints(frozen.payload)
    context = await read_spatial_discovery_context(
        db,
        nid,
        run_id="source-integrity",
        scene_id=scene_id,
        scene_index=0,
        endpoint_ids=list(by_id),
        endpoint_surfaces=list(surfaces),
        world_candidate_ids=[
            key for key, item in by_id.items() if item.get("world_candidate")
        ],
        world_attempt_id=receipt.attempt_id,
        type_limit=32,
        clue_limit=64,
    )
    _ids, _surfaces, endpoints, _refs, allowed, _types, _omitted = _endpoint_inputs(
        frozen.payload, context
    )
    assert {item["surface"] for item in endpoints} == {"栖园", "霜台"}
    assert set(allowed) == {str(item.id) for item in entities}
    assert set(allowed.values()) == {"canonical" if adopted else "candidate"}


@pytest.mark.parametrize("world_type", ["location", "地点"])
async def test_author_reading_materializes_then_extracts_and_reviews_current_locations(
    db_session,
    test_project_id,
    account_llm_connection,
    async_client,
    monkeypatch,
    world_type,
):
    import json
    from uuid import uuid4

    from infrastructure.llm.providers import OpenAIProvider
    from infrastructure.llm.schemas import LLMCallResponse, LLMUsage
    from infrastructure.tasks.models import AsyncTask
    from modules.evolution.tests.test_workflow import structure_response
    from modules.world.map_spatial_clue_models import MapSpatialClueRecord

    db, nid = db_session, test_project_id
    await switch_project_engine(db, nid, to_engine="evolution", expected_epoch=1)
    await db.commit()
    await seed(db, nid, {1: TEXT})
    calls = []
    sampler = ColdStartSampler([])

    async def provider(self, prompt, *, complete_stream=False):
        assert not db.in_transaction()
        schema = json.loads(prompt.messages[-1].content.split("schema: ", 1)[1])["title"]
        calls.append(schema)
        if schema == "SceneSample":
            result = await sampler.sample(scene_text=TEXT, input_manifest={})
        elif schema in {
            "Phase2aSceneExtractionOutput",
            "AliasRelationExtractionOutput",
            "AuditVerdictOutput",
        }:
            result = (
                await sampler.execute_world_request(
                    request=prompt, schema_name=schema, schema_hash=""
                )
            )["result"]
            if schema == "Phase2aSceneExtractionOutput":
                for entity in result["entities"]:
                    entity["entity_type"] = world_type
        elif schema == "SpatialDiscoveryOutput":
            # This is the real frozen provider input, with UUIDs allocated and
            # materialized by the ordinary World handler, not filled by this test.
            inputs = json.loads(
                next(item.content for item in prompt.messages if item.role == "user")
            )
            assert inputs["scene_text"] == TEXT
            refs = {item["surface"]: item["endpoint_ref"] for item in inputs["endpoints"]}
            assert set(refs) == {"栖园", "霜台"}
            entities = list(
                await db.scalars(
                    select(CoreEntity).where(CoreEntity.novel_id == UUID(nid))
                )
            )
            assert {item.status for item in entities} == {"candidate"}
            # Reads here create a transaction; provider callbacks must leave no
            # transaction open before the gateway settles its usage receipt.
            await db.commit()
            result = {
                "clues": [
                    {
                        "kind": "adjacency",
                        "subject_ref": refs["栖园"],
                        "subject_surface": "栖园",
                        "target_ref": refs["霜台"],
                        "target_surface": "霜台",
                        "relation": "紧挨",
                        "modality": "event_observed",
                        "quote": TEXT,
                    }
                ],
                "coverage_note": "逐字原文支持相邻。",
            }
            if world_type == "地点":
                result["clues"][0]["type"] = {
                    "kind": "relation",
                    "name": "紧挨",
                    "description": "正文明确紧邻。",
                    "traits": {},
                }
        elif schema == "SpatialReviewOutput":
            result = {
                "reviews": [
                    {
                        "clue_index": 0,
                        "verdict": "supported",
                        "reason": "逐字引文支持端点和关系。",
                    }
                ],
                "coverage_note": "独立核对原文与候选。",
            }
            if world_type == "地点":
                result["reviews"][0].update(
                    type_verdict="supported", reviewed_evidence_indices=[0]
                )
        elif response := structure_response(prompt):
            return response
        else:
            raise AssertionError(schema)
        return LLMCallResponse(
            content=json.dumps(result, ensure_ascii=False),
            finish_reason="stop",
            usage=LLMUsage(prompt_tokens=10, completion_tokens=10, total_tokens=20),
        )

    monkeypatch.setattr(OpenAIProvider, "generate", provider)
    body = {
        "operation_id": str(uuid4()),
        "end_chapter": 1,
        "request_limit": 20,
        "discover_spatial": True,
    }
    preview = await async_client.post(
        f"/api/evolution/reading/preview?novel_id={nid}", json=body
    )
    assert preview.status_code == 200, preview.text
    response = await async_client.post(
        f"/api/evolution/reading?novel_id={nid}",
        json={
            **body,
            "expected_fingerprint": preview.json()["fingerprint"],
            "authorization_confirmed": True,
        },
    )
    assert response.status_code == 201, response.text
    run = response.json()["run"]
    task = await db.get(AsyncTask, UUID(run["task_id"]))
    result = await handle_evolution_scene_step(db, task)
    store = PostgresAttemptStore(db, nid)
    receipt = await store.load_committed_scene_receipt(run["run_key"], 0)
    frozen = await store.load_frozen(run["run_key"], receipt.attempt_id)
    assert (
        calls.count("SpatialDiscoveryOutput") == calls.count("SpatialReviewOutput") == 1
    ), {
        key: value
        for key, value in frozen.payload.items()
        if "spatial" in key or "optional" in key
    }
    assert frozen.payload["spatial_discovery_result"]["coverage"] == "inspected"
    assert frozen.payload["spatial_discovery_result"]["gaps"] == []
    assert frozen.payload["spatial_discovery_result"]["density"]["lexical"] == []
    assert set(
        frozen.payload["spatial_discovery_result"]["density"]["location_endpoints"]
    ) == {"栖园", "霜台"}
    clues = list(
        await db.scalars(
            select(MapSpatialClueRecord).where(MapSpatialClueRecord.novel_id == UUID(nid))
        )
    )
    assert len(clues) == 1
    assert clues[0].status == "pending_review"
    assert clues[0].source_content_mode == "working"
    # Replaying the same committed task never issues another paid call.
    immutable_receipt = receipt.model_dump(mode="json")
    before = list(calls)
    await handle_evolution_scene_step(db, task)
    assert calls == before
    assert (await store.load_receipt(run["run_key"], receipt.attempt_id)).model_dump(
        mode="json"
    ) == immutable_receipt
    from infrastructure.llm.collaboration import content_hash

    assert (
        frozen.payload["spatial_preparation"]["source_binding"]["content_hash"]
        == clues[0].source_binding["content_hash"]
    )
    assert frozen.payload["spatial_discovery_result"][
        "consumer_read_set"
    ] == content_hash(frozen.payload["spatial_preparation"])
    if world_type == "地点":
        from modules.world.project_vocabulary_models import ProjectVocabularyTerm

        terms = list(
            await db.scalars(
                select(ProjectVocabularyTerm).where(
                    ProjectVocabularyTerm.novel_id == UUID(nid)
                )
            )
        )
        assert len(terms) == 1 and terms[0].status == "emerging"
    # The normal final structure task drains this same run and requests its
    # auto-draft batch. Working-source previews never acquire a saved map head.
    from modules.world.map_atlas_models import MapAtlasNode, MapAtlasRevision
    from modules.world.map_auto_draft_models import MapAutoDraftBatchRecord

    task.status = "done"
    await db.commit()
    await handle_evolution_scene_step(
        db, await db.get(AsyncTask, UUID(result["next_task_id"]))
    )
    batches = list(
        await db.scalars(
            select(MapAutoDraftBatchRecord).where(
                MapAutoDraftBatchRecord.novel_id == UUID(nid)
            )
        )
    )
    assert len(batches) == 1 and batches[0].status == "completed"
    revisions = list(
        await db.scalars(
            select(MapAtlasRevision).where(MapAtlasRevision.novel_id == UUID(nid))
        )
    )
    assert revisions and {item.status for item in revisions} == {"candidate"}
    nodes = list(
        await db.scalars(select(MapAtlasNode).where(MapAtlasNode.novel_id == UUID(nid)))
    )
    assert nodes and all(item.current_revision_id is None for item in nodes)


@pytest.mark.parametrize(
    "mismatch",
    [
        "future_scene",
        "other_scene",
        "other_run",
        "other_attempt",
        "unmaterialized",
        "other_novel",
        "archived",
        "source_changed",
        "owner_changed",
    ],
)
async def test_world_only_endpoints_require_current_materialization_and_receipt(
    db_session, test_project_id, mismatch
):
    from copy import deepcopy
    from uuid import uuid4

    from core.errors import ConflictError, NotFoundError
    from modules.project.models import Project
    from modules.writing.facade import create_draft_only

    db, nid = db_session, test_project_id
    _store, receipt, frozen, entities, scene_id = await materialized_world(db, nid)
    for entity in entities:
        value = deepcopy(entity.content_json)
        if mismatch == "future_scene":
            value["_meta"]["source_scene_index"] = 1
        elif mismatch == "other_scene":
            value["_meta"]["scene_id"] = str(uuid4())
        elif mismatch == "other_novel":
            foreign = Project(title="合成其他作品", settings={})
            db.add(foreign)
            await db.flush()
            entity.novel_id = foreign.id
        elif mismatch == "other_run":
            value["_meta"]["workflow_id"] = "another-run"
        elif mismatch == "other_attempt":
            value["_meta"]["evolution_ref"]["attempt_id"] = str(uuid4())
        elif mismatch == "archived":
            entity.status = "archived"
        entity.content_json = value
    if mismatch == "source_changed":
        await create_draft_only(db, nid, 1, "修订", TEXT + "雾散了。")
    elif mismatch == "owner_changed":
        project = await db.get(Project, UUID(nid))
        project.owner_id = uuid4()
    await db.commit()
    by_id, surfaces = _current_endpoints(frozen.payload)
    ids = list(by_id) if mismatch != "unmaterialized" else [str(uuid4())]
    kwargs = dict(
        run_id="source-integrity",
        scene_id=scene_id,
        scene_index=0,
        endpoint_ids=ids,
        endpoint_surfaces=list(surfaces),
        world_candidate_ids=ids,
        world_attempt_id=receipt.attempt_id,
        type_limit=32,
        clue_limit=64,
    )
    if mismatch in {"source_changed", "owner_changed"}:
        with pytest.raises((ConflictError, NotFoundError)):
            await read_spatial_discovery_context(db, nid, **kwargs)
    else:
        context = await read_spatial_discovery_context(db, nid, **kwargs)
        assert context.endpoint_states == {}
        assert _endpoint_inputs(frozen.payload, context)[4] == {}
