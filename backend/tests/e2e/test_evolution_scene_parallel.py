"""Real PostgreSQL journals join independent Scene branches without lost updates."""

import asyncio
import json
from dataclasses import asdict
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from infrastructure.llm.tests.test_luna_context_scope import luna_snapshot
from modules.evolution import sampler
from modules.evolution.commit import FrozenAttempt
from modules.evolution.enrichment import needs_enrichment
from modules.evolution.facade import switch_project_engine
from modules.evolution.llm_sampler import ProjectLLMSampler
from modules.evolution.pipeline import (
    SceneSourceBinding,
    _compile_sample_payload,
    _finish_scene_results,
    compute_scene_manifest_hash,
    prepare_scene_input,
)
from modules.evolution.sampler import SceneMethodCaller
from modules.evolution.state_review import paid_call_receipts
from modules.evolution.store import PostgresAttemptStore
from modules.project.models import Project
from modules.story.facade import get_scene_contract
from modules.story.outline_state.models import Scene
from modules.writing.facade import create_draft_only
from tests.e2e.config import DATABASE_URL

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e]

TEXT = "天亮了，甲紧张地摸戒指。"
RUN, ATTEMPT = "scene-parallel-pg", "scene-0"


async def seed(db, nid):
    db.add(
        Project(
            id=nid,
            title="同场并行合成验收",
            genre="奇幻",
            tone="测试",
            language="zh",
            target_length="novel",
            current_stage="writing",
        )
    )
    await db.flush()
    await switch_project_engine(db, str(nid), to_engine="evolution", expected_epoch=1)
    draft = await create_draft_only(db, str(nid), 1, "第一章", TEXT)
    source = SceneSourceBinding(
        draft_id=str(draft.id),
        chapter_index=1,
        content_hash=draft.content_hash,
        start_offset=0,
        end_offset=len(TEXT),
    )
    scene = Scene(
        novel_id=nid,
        scene_index=0,
        title="晨起",
        goal="确认天色",
        status="draft",
        source="evolution",
        chapter_ids=["1"],
        scene_chunks=[
            {
                "chapter_index": 1,
                "start_offset": 0,
                "end_offset": len(TEXT),
                "source_draft_id": str(draft.id),
                "source_content_hash": draft.content_hash,
            }
        ],
        structure_meta={
            "auto_ingested": True,
            "semantic_origin": "boundary_only",
            "core_conflict_status": "not_applicable",
            "phase1a_confidence": 0.95,
            "boundary_status": "complete",
        },
    )
    db.add(scene)
    await db.flush()
    card = asdict(await get_scene_contract(db, str(nid), str(scene.id)))
    assert needs_enrichment(card)
    await db.commit()
    snapshot = luna_snapshot()
    store = PostgresAttemptStore(db, str(nid))
    await store.register_run(
        RUN, mode="bootstrap", budget_total=None, llm_snapshot=snapshot
    )
    run = await store.load_run(RUN)
    run.reading_plan_json = {"budget_mode": "confirmed_scope"}
    manifest = compute_scene_manifest_hash(RUN, 0, TEXT, source)
    parent = await prepare_scene_input(
        store, run_key=RUN, scene_index=0, source_manifest_hash=manifest
    )
    payload = {
        "stage": "compiled",
        "scene_index": 0,
        "scene_id": str(scene.id),
        "scene_card": card,
        "scene_text": TEXT,
        "source_binding": source.model_dump(mode="json"),
        "input_manifest": parent.model_dump(mode="json"),
        "enrichment_version": 1,
        "world_version": 3,
        "state_review_version": 1,
        "optional_stage_version": 1,
        "observations": [
            {"predicate": "天亮了", "quote": TEXT, "modality": "event_observed"}
        ],
        "scene_events": [
            {
                "dimension": "timeline",
                "event_type": "time_advanced",
                "source_observation_indices": [0],
                "snapshot_after": {"text_state": "天亮了"},
            }
        ],
    }
    payload.update(
        await _compile_sample_payload(
            payload,
            novel_id=str(nid),
            run_key=RUN,
            scene_index=0,
            scene_text=TEXT,
            source=source,
            manifest_hash=manifest,
            content_mode="canonical",
            observer_contract_version=1,
            identity_candidates=None,
        )
    )
    frozen = FrozenAttempt(
        novel_id=str(nid),
        run_id=RUN,
        attempt_id=ATTEMPT,
        owner_epoch=1,
        producer_version="pg-scene-parallel-fixture",
        source_manifest_hash=manifest,
        payload=payload,
    )
    await store.save_frozen(frozen)
    await db.commit()
    return store, frozen, source, snapshot


class ControlledProvider:
    provider_id = "fixture"
    model_name = "gpt-6-luna"

    def __init__(self, db, sessions, nid):
        self.db, self.sessions, self.nid = db, sessions, str(nid)
        self.started = {
            name: asyncio.Event()
            for name in ("SceneEnrichmentOutput", "Phase2aSceneExtractionOutput")
        }
        self.release = {name: asyncio.Event() for name in self.started}
        self.calls, self.completed = [], []
        self.active = self.peak = 0
        self.review_joined = False

    async def generate_structured(self, request, schema, *, diagnostics, **options):
        assert not self.db.in_transaction(), "provider I/O must release DB locks"
        assert options["max_fix_attempts"] == 0
        assert options["transport_retries"] is False
        name = schema.__name__
        self.calls.append(name)
        self.active += 1
        self.peak = max(self.peak, self.active)
        try:
            if name in self.started:
                self.started[name].set()
                await self.release[name].wait()
            if name == "SceneEnrichmentOutput":
                result = {
                    "must_happen": TEXT,
                    "field_evidence": {"must_happen": [TEXT]},
                    "confidence": 0.95,
                }
            elif name == "Phase2aSceneExtractionOutput":
                result = {}
            elif name == "AuditVerdictOutput":
                result = {
                    "verdict": "pass",
                    "dimensions": [
                        {"dimension": dimension, "checked": True}
                        for dimension in ("prior_prose", "scene_state", "imported_assets")
                    ],
                }
            else:
                assert name == "StateReview" and self.active == 1
                async with self.sessions() as reader:
                    frozen = await PostgresAttemptStore(reader, self.nid).load_frozen(
                        RUN, ATTEMPT
                    )
                assert frozen.payload["world_result"]
                assert frozen.payload["enrichment_result"]
                value = json.loads(request.messages[-1].content)
                assert len(value["events"]) == 1
                self.review_joined = True
                result = {
                    "events": [
                        {
                            "event_index": 0,
                            "verdict": "supported",
                            "reason": "合成正文明确说明天亮。",
                            "quotes": [TEXT],
                        }
                    ]
                }
            diagnostics.append(
                {
                    "kind": "structured_usage",
                    "status": "succeeded",
                    "prompt_tokens": 10,
                    "completion_tokens": 5,
                    "total_tokens": 15,
                }
            )
            self.completed.append(name)
            return schema.model_validate(result)
        finally:
            self.active -= 1


async def test_real_journals_join_reverse_completion_and_replay_without_provider(
    monkeypatch,
):
    engine = create_async_engine(DATABASE_URL, pool_size=3, max_overflow=0)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    nid = uuid4()
    job = None
    provider = None
    try:
        async with sessions() as db:
            store, frozen, source, snapshot = await seed(db, nid)
            provider = ControlledProvider(db, sessions, nid)
            client = ProjectLLMSampler(provider)
            monkeypatch.setitem(
                sampler._SAMPLER_REGISTRY, "scene-parallel-pg", lambda *_: client
            )
            caller = SceneMethodCaller(
                db,
                SimpleNamespace(novel_id=str(nid), sampler_provider="scene-parallel-pg"),
                snapshot,
            )
            caller.discovery_parallelism = 2
            job = asyncio.create_task(
                _finish_scene_results(
                    db, store, frozen, source, client.verify_state_events, caller
                )
            )
            async with asyncio.timeout(10):
                for started in provider.started.values():
                    await started.wait()
                assert provider.peak == 2 and not job.done()
                async with sessions() as reader:
                    pending = await PostgresAttemptStore(reader, str(nid)).load_frozen(
                        RUN, ATTEMPT
                    )
                assert all(
                    pending.payload[key]["stage"] == "sampling"
                    for key in ("scene_enrichment", "scene_world")
                )
                provider.release["Phase2aSceneExtractionOutput"].set()
                while True:
                    async with sessions() as reader:
                        pending = await PostgresAttemptStore(
                            reader, str(nid)
                        ).load_frozen(RUN, ATTEMPT)
                    if pending.payload.get("world_result"):
                        break
                    assert not job.done(), "Scene join failed before World settled"
                assert pending.payload["stage"] == "compiled"
                assert pending.payload["scene_world"]["stage"] == "sampled"
                assert pending.payload["scene_enrichment"]["stage"] == "sampling"
                assert "state_review" not in pending.payload
                assert not provider.review_joined
                provider.release["SceneEnrichmentOutput"].set()
                await asyncio.shield(job)
            assert provider.completed[:2] == [
                "Phase2aSceneExtractionOutput",
                "SceneEnrichmentOutput",
            ]
            assert provider.review_joined and provider.active == 0
        # A fresh connection must see both branches and the real joined review.
        async with sessions() as db:
            store = PostgresAttemptStore(db, str(nid))
            durable = await store.load_frozen(RUN, ATTEMPT)
            assert durable.payload["stage"] == "verified"
            assert durable.payload["enrichment_result"]["review"]["status"] == "passed"
            for key in (
                "scene_enrichment",
                "scene_enrichment_review",
                "scene_world",
                "state_review",
            ):
                journal = durable.payload[key]
                assert journal["stage"] == "sampled"
                assert journal["paid_call_receipt"]["usage"]["total_tokens"] == 15
            assert len(paid_call_receipts(durable.payload)) == 4
            assert (await store.load_run(RUN)).budget_remaining is None
            prior_calls = list(provider.calls)
            await db.commit()
            replay = await _finish_scene_results(db, store, durable, source, None, None)
            assert replay.payload == durable.payload and provider.calls == prior_calls
    finally:
        if provider is not None:
            for release in provider.release.values():
                release.set()
        try:
            if job is not None:
                await job
        finally:
            try:
                async with sessions() as db:
                    await db.execute(delete(Project).where(Project.id == nid))
                    await db.commit()
            finally:
                await engine.dispose()
