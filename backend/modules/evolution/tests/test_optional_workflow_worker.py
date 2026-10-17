"""Normal author confirmation must preserve the protocol used by its real worker."""

import json
from copy import deepcopy
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.main import app
from core.base import Base
from core.dependencies import get_db
from infrastructure.llm.providers import OpenAIProvider
from infrastructure.llm.schemas import LLMCallResponse, LLMUsage
from infrastructure.llm.secret_store import encrypt_secret, fingerprint_secret
from infrastructure.tasks.models import AsyncTask
from infrastructure.tasks.worker import TaskWorker
from modules.account.settings_constants import (
    ACCOUNT_LLM_PROVIDER_TEMPLATES,
    LOCAL_OWNER_ID,
)
from modules.account.settings_repositories import (
    AccountLLMCredentialRepository,
    GlobalLLMDefaultsRepository,
)
from modules.evolution import workflow
from modules.evolution.facade import read_map_spatial_evaluation_receipts
from modules.evolution.store import PostgresAttemptStore
from modules.evolution.tests.test_workflow import structure_response
from run_worker import _guard_active_task_project_finalize, _require_active_task_project
from tests.support.http import XhrAsyncClient


async def test_asgi_confirmation_persists_optional_protocol_through_exact_worker(
    tmp_path, monkeypatch
):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'reading.sqlite'}")
    sessions = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async def local_db():
        async with sessions() as db:
            yield db
            await db.commit()

    app.dependency_overrides[get_db] = local_db
    planned = []
    real_plan = workflow._plan

    async def capture_actual_plan(*args):
        plan, snapshot = await real_plan(*args)
        planned.append(plan)
        return plan, snapshot

    monkeypatch.setattr(workflow, "_plan", capture_actual_plan)
    text = "城门在钟楼东侧。"
    calls = []

    async def provider(self, prompt, *, complete_stream=False):
        schema = json.loads(prompt.messages[-1].content.split("schema: ", 1)[1])["title"]
        calls.append(schema)
        if response := structure_response(prompt):
            return response
        if schema == "SceneSample":
            async with sessions() as observer:
                pending = await PostgresAttemptStore(observer, nid).load_pending_frozen(
                    run_key, calls.count("SceneSample") - 1
                )
                assert pending.payload["stage"] == "sampling"
                assert pending.payload["optional_stage_version"] == 1
                assert (
                    pending.payload["spatial_method_fingerprint"]
                    == planned[-1]["spatial_method_fingerprint"]
                )
        outputs = {
            "SceneSample": {
                "observations": [
                    {"predicate": text, "quote": text, "modality": "event_observed"}
                ],
                "scene_events": [],
            },
            "StateReview": {"events": []},
            "Phase2aSceneExtractionOutput": {},
            "AliasRelationExtractionOutput": {},
            "SpatialDiscoveryOutput": {
                "clues": [
                    {
                        "kind": "bearing",
                        "subject_surface": "城门",
                        "target_surface": "钟楼",
                        "relation": "东侧",
                        "modality": "event_observed",
                        "quote": text,
                    }
                ],
                "coverage_note": "逐字核对本场方位。",
            },
            "SpatialReviewOutput": {
                "reviews": [
                    {"clue_index": 0, "verdict": "supported", "reason": "原文明确支持。"}
                ],
                "coverage_note": "已独立核对本场原文。",
            },
        }
        assert schema in outputs, schema
        return LLMCallResponse(
            content=json.dumps(outputs[schema], ensure_ascii=False),
            finish_reason="stop",
            usage=LLMUsage(prompt_tokens=10, completion_tokens=10, total_tokens=20),
        )

    monkeypatch.setattr(OpenAIProvider, "generate", provider)
    try:
        async with XhrAsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            project = await client.post(
                "/api/projects", json={"title": "合成阶段协议回归"}
            )
            assert project.status_code == 201, project.text
            nid = project.json()["id"]
            async with sessions() as db:
                key = "unit-test-offline-optional-stage"
                await AccountLLMCredentialRepository().upsert(
                    db,
                    {
                        "owner_id": LOCAL_OWNER_ID,
                        "provider_id": "deepseek",
                        "encrypted_api_key": encrypt_secret(key),
                        "key_fingerprint": fingerprint_secret(
                            key, purpose="account-llm-api-key"
                        ),
                        "verified_at": datetime.now(UTC),
                    },
                )
                await GlobalLLMDefaultsRepository().upsert(
                    db,
                    {
                        "owner_id": LOCAL_OWNER_ID,
                        **ACCOUNT_LLM_PROVIDER_TEMPLATES["deepseek"],
                    },
                )
                await db.commit()
            status = await client.get(f"/api/evolution/reading?novel_id={nid}")
            switched = await client.post(
                f"/api/evolution/engine?novel_id={nid}",
                json={
                    "engine": "evolution",
                    "expected_epoch": status.json()["engine"]["epoch"],
                    "stop_active": False,
                    "authorization_confirmed": True,
                },
            )
            assert switched.status_code == 200, switched.text
            published = await client.post(
                "/api/writing/drafts",
                json={
                    "novel_id": nid,
                    "chapter_index": 1,
                    "title": "合成章",
                    "content": "\n\n".join([text] * 5),
                },
            )
            assert published.status_code == 201, published.text
            draft = published.json()["draft"]
            scene_ids = []
            for index in range(5):
                start = index * (len(text) + 2)
                scene = await client.post(
                    f"/api/outline/scenes?novel_id={nid}",
                    json={
                        "scene_index": index,
                        "chapter_ids": ["1"],
                        "title": f"合成场景{index}",
                        "source": "manual",
                        "status": "canonical",
                        "scene_chunks": [
                            {
                                "chapter_index": 1,
                                "source_draft_id": draft["id"],
                                "source_content_hash": draft["content_hash"],
                                "start_offset": start,
                                "end_offset": start + len(text),
                            }
                        ],
                    },
                )
                assert scene.status_code == 201, scene.text
                scene_ids.append(scene.json()["id"])
            operation_id = str(uuid4())
            request = {
                "operation_id": operation_id,
                "mode": "bootstrap",
                "run_key": None,
                "from_scene_index": None,
                "end_chapter": 1,
                "request_limit": 100,
                "budget_mode": "bounded",
                "discover_details": False,
                "discover_spatial": True,
            }
            preview = await client.post(
                f"/api/evolution/reading/preview?novel_id={nid}", json=request
            )
            assert preview.status_code == 200, preview.text
            started = await client.post(
                f"/api/evolution/reading?novel_id={nid}",
                json={
                    **request,
                    "expected_fingerprint": preview.json()["fingerprint"],
                    "authorization_confirmed": True,
                },
            )
            assert started.status_code == 201, started.text
            assert not calls
            run_key = started.json()["run"]["run_key"]
            task_id = UUID(started.json()["run"]["task_id"])
            async with sessions() as db:
                run = await PostgresAttemptStore(db, nid).load_run(run_key)
                assert run.reading_plan_json["optional_stage_version"] == 1
                for field in (
                    "state_review_version",
                    "enrichment_version",
                    "world_version",
                    "structure_version",
                    "discovery_version",
                    "spatial_version",
                    "optional_stage_version",
                    "spatial_method_fingerprint",
                    "optional_step_quotas",
                    "mandatory_scene_calls",
                ):
                    assert run.reading_plan_json[field] == planned[-1][field], field
                unrelated = set(
                    await db.scalars(select(AsyncTask.id).where(AsyncTask.id != task_id))
                )
                from evals.map_spatial import (
                    domain_method_fingerprints,
                    scene_source_refs,
                )

                common = {
                    "novel_id": nid,
                    "split": "development",
                    "domain_method_fingerprints": domain_method_fingerprints(),
                    "case_bindings": {
                        f"case-{i}": {
                            "scene_id": scene_id,
                            "source_refs": await scene_source_refs(
                                db, nid, scene_id, 1, text
                            ),
                        }
                        for i, scene_id in enumerate(scene_ids)
                    },
                }

            worker = TaskWorker(
                db_manager=SimpleNamespace(engine=engine, session_factory=sessions),
                heartbeat_interval=60,
                task_preflight=_require_active_task_project,
                task_commit_guard=_guard_active_task_project_finalize,
            )
            executed = []
            from evals.map_spatial import _write_private_json
            from evals.map_spatial_guard import digest, read_evolution_product_evidence

            root = tmp_path / "private"
            root.mkdir(mode=0o700)
            for index in range(6):
                async with sessions() as db:
                    task = await db.get(AsyncTask, task_id)
                    assert task.status == "pending" and task.attempt == 0
                    assert task.meta["run_key"] == run_key
                    if index == 5:
                        assert task.meta["operation"] == "structure"
                    else:
                        assert task.meta["scene_index"] == index
                result = await worker.run_once(task_id=task_id, novel_id=nid)
                assert result.status == "done", result.error_message
                executed.append(str(result.id))
                _write_private_json(
                    root / f"task-ledger/evolution/test/{operation_id}/{result.id}.json",
                    {
                        "task_id": str(result.id),
                        "task_type": result.task_type,
                        "status": "completed",
                        "result_hash": digest(result.result),
                    },
                )
                status = await client.get(f"/api/evolution/reading?novel_id={nid}")
                if index < 5:
                    assert status.json()["run"]["status"] == "pending"
                    task_id = UUID(status.json()["run"]["task_id"])
            assert status.json()["run"]["status"] == "completed"
            assert calls.count("SceneSample") == 5
            assert calls.count("SpatialDiscoveryOutput") == 5
            assert calls.count("SpatialReviewOutput") == 5
            async with sessions() as db:
                store = PostgresAttemptStore(db, nid)
                receipt = await store.load_committed_scene_receipt(run_key, 0)
                assert receipt is not None
                frozen = await store.load_frozen(run_key, receipt.attempt_id)
                assert frozen.payload["optional_stage_version"] == 1
                stage = frozen.payload["optional_scene_stage"]
                assert stage["receipt_attempt_id"] == receipt.attempt_id
                assert stage["steps"]["details"]["status"] == "not_run"
                assert stage["steps"]["spatial"]["status"] == "complete"
                assert frozen.payload["scene_spatial_discovery"]["stage"] == "sampled"
                assert frozen.payload["scene_spatial_review"]["stage"] == "sampled"
                evidence = await read_map_spatial_evaluation_receipts(
                    db, nid, run_key, operation_id, scene_ids
                )
                from evals.map_spatial_guard import _validate_evolution_optional_stage

                assert (
                    _validate_evolution_optional_stage(evidence["attempts"][0])["version"]
                    == 1
                )
                record = {
                    "family_id": "test",
                    "run_key": run_key,
                    "operation_id": operation_id,
                    "request": request,
                    "request_sha256": digest(request),
                    "request_limit": request["request_limit"],
                    "preview_fingerprint": preview.json()["fingerprint"],
                    "common_binding_sha256": digest(common),
                    "split": "development",
                    "human_validated": False,
                    "task_ids": executed,
                }
                evidence = await read_evolution_product_evidence(db, root, common, record)
                assert evidence["state"]["status"] == "completed"
                assert len(evidence["attempts"]) == 5
                from evals.map_spatial import MapSpatialEvalError

                tampered = deepcopy(common)
                tampered["case_bindings"]["case-0"]["source_refs"][0]["range_hash"] = (
                    "0" * 64
                )
                with pytest.raises(MapSpatialEvalError, match="原文hash已变化"):
                    await read_evolution_product_evidence(
                        db,
                        root,
                        tampered,
                        {**record, "common_binding_sha256": digest(tampered)},
                    )
                for item in unrelated:
                    assert (await db.get(AsyncTask, item)).status == "pending"
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()
