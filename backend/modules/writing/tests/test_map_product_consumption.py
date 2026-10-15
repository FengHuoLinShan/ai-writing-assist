"""Synthetic five-Scene map consumption through the product API and TaskWorker."""

from __future__ import annotations

import hashlib
import json
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.main import app
from core.config import get_settings
from core.database import isolated_database_manager_for_testing
from infrastructure.llm.schemas import LLMCallResponse, LLMToolCall, LLMUsage
from infrastructure.llm.secret_store import encrypt_secret, fingerprint_secret
from infrastructure.tasks.models import AsyncTask
from modules.account.models import Account
from modules.account.settings_constants import (
    ACCOUNT_LLM_PROVIDER_TEMPLATES,
    LOCAL_OWNER_ID,
)
from modules.account.settings_repositories import (
    AccountLLMCredentialRepository,
    GlobalLLMDefaultsRepository,
)
from modules.assistant.models import AssistantRun
from modules.project.models import Project
from modules.story.outline_state.models import Scene, SceneSpan
from modules.writing.models import WritingDraft
from run_worker import _build_task_worker, _configure_worker_process


@asynccontextmanager
async def _product(tmp_path, monkeypatch, *, capabilities: str):
    monkeypatch.setenv(
        "DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'product.sqlite'}"
    )
    monkeypatch.setenv("MAP_SPATIAL_ENABLED_CAPABILITIES", capabilities)
    monkeypatch.setenv("ASSISTANT_ENABLED", "true")
    get_settings.cache_clear()
    try:
        async with isolated_database_manager_for_testing(get_settings()) as manager:
            await manager.create_tables()
            _configure_worker_process()
            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test",
                headers={"X-Requested-With": "XMLHttpRequest"},
            ) as client:
                yield manager, client
    finally:
        get_settings.cache_clear()


async def _seed_five_scenes(manager):
    novel_id = uuid.uuid4()
    async with manager.session() as db:
        db.add(
            Account(id=LOCAL_OWNER_ID, support_code=f"synthetic-{uuid.uuid4().hex[:16]}")
        )
        db.add(Project(id=novel_id, title="五场合成稿"))
        text = "第一场：潮声。第二场：小路。第三场：门前。第四场：院中。第五场：暮色。"
        draft = WritingDraft(
            novel_id=novel_id,
            chapter_index=1,
            title="第一章",
            content=text,
            content_hash=hashlib.sha256(text.encode()).hexdigest(),
            version_number=1,
            status="canonical",
        )
        db.add(draft)
        await db.flush()
        chunks = [
            "第一场：潮声。",
            "第二场：小路。",
            "第三场：门前。",
            "第四场：院中。",
            "第五场：暮色。",
        ]
        cursor = 0
        scenes = []
        for index, chunk in enumerate(chunks):
            start = text.index(chunk, cursor)
            end = start + len(chunk)
            scene = Scene(
                novel_id=novel_id,
                scene_index=index,
                title=f"第{index + 1}场",
                status="canonical",
                source="manual",
                chapter_ids=["1"],
                structure_meta={},
            )
            db.add(scene)
            await db.flush()
            db.add(
                SceneSpan(
                    novel_id=novel_id,
                    scene_id=scene.id,
                    chapter_index=1,
                    content_mode="canonical",
                    source_draft_id=draft.id,
                    source_content_hash=draft.content_hash,
                    start_offset=start,
                    end_offset=end,
                    part_no=0,
                    mapping_status="exact",
                    status="canonical",
                    source="manual",
                )
            )
            scenes.append(scene.id)
            cursor = end
        await AccountLLMCredentialRepository().upsert(
            db,
            {
                "owner_id": LOCAL_OWNER_ID,
                "provider_id": "deepseek",
                "encrypted_api_key": encrypt_secret("unit-test-account-key"),
                "key_fingerprint": fingerprint_secret(
                    "unit-test-account-key", purpose="account-llm-api-key"
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
    return str(novel_id), [str(scene_id) for scene_id in scenes]


async def _fake_writing_provider(_self, request):
    messages = [message.content for message in request.messages]
    if "DirectorShardPlan" in "\n".join(messages):
        keys = [
            line[2:].split("|", 1)[0].strip()
            for line in messages[1].splitlines()
            if line.startswith("- ") and "|" in line
        ]
        payload = {
            "dispositions": [
                {"source_key": key, "disposition": "required_for_generation"}
                for key in keys
            ]
        }
    elif "AuditVerdictOutput" in "\n".join(messages):
        dimensions = []
        for line in "\n".join(messages).splitlines():
            if line.startswith("必查维度："):
                dimensions = [
                    part.strip()
                    for part in line.split("：", 1)[1].split(",")
                    if part.strip()
                ]
                break
        payload = {
            "findings": [],
            "dimensions": [
                {"dimension": dimension, "checked": True} for dimension in dimensions
            ],
            "verdict": "pass",
        }
    else:
        return LLMCallResponse(content="第五场的合成候选正文。", model="deepseek-flash")
    return LLMCallResponse(content=json.dumps(payload), model="deepseek-flash")


async def _seed_map(manager, novel_id, scene_id):
    from modules.world.map_structure_schemas import (
        MapDocument,
        MapNodeCreate,
        MapSaveRequest,
    )
    from modules.world.map_structure_service import (
        MapStructureService,
        source_digest,
        source_payload,
    )
    from modules.world.models import CoreEntity

    async with manager.session() as db:
        place = CoreEntity(
            novel_id=uuid.UUID(novel_id),
            entity_type="location",
            name="北门",
            summary="北门的已采用资料。",
            status="canonical",
        )
        source = CoreEntity(
            novel_id=uuid.UUID(novel_id),
            entity_type="item",
            name="城道志",
            summary="城道志的已采用资料。",
            status="canonical",
        )
        db.add_all([place, source])
        await db.flush()
        scene = await db.get(Scene, uuid.UUID(scene_id))
        scene.structure_meta = {"location_entity_id": str(place.id)}
        service = MapStructureService()
        node = await service.create_node(
            db,
            novel_id,
            MapNodeCreate(title="北门地图", level="region", location_entity_id=place.id),
        )
        anchor = {
            "kind": "entity",
            "id": str(source.id),
            "source_hash": source_digest(source_payload(source)),
            "quote": "城道志的已采用资料。",
        }
        document = MapDocument.model_validate(
            {
                "schema_version": 2,
                "features": [
                    {
                        "id": "north-gate",
                        "kind": "location",
                        "label": "北门",
                        "entity_id": str(place.id),
                        "sources": [anchor],
                    }
                ],
            }
        )
        saved = await service.save(
            db,
            novel_id,
            node["id"],
            MapSaveRequest(
                base_revision_id=node["current_revision_id"], document=document
            ),
        )
    return node["id"], saved.id, document


@pytest.mark.asyncio
async def test_five_scene_writing_without_location_reaches_real_worker(
    tmp_path, monkeypatch
):
    async with _product(tmp_path, monkeypatch, capabilities="writing.generate") as (
        manager,
        client,
    ):
        novel_id, scenes = await _seed_five_scenes(manager)
        confirmed = await client.post(
            "/api/evidence/compilation/confirm",
            json={
                "novel_id": novel_id,
                "action": "writing.generate",
                "task": "续写第五场",
                "scope": "scene",
                "chapter_index": 1,
                "scene_id": scenes[-1],
                "content_mode": "canonical",
                "context_mode": "canonical",
            },
        )
        assert confirmed.status_code == 201, confirmed.text
        async with manager.session() as db:
            from modules.evidence.compilation.models import ContextConfirmation

            row = await db.get(ContextConfirmation, uuid.UUID(confirmed.json()["id"]))
            assert row.compile_options["map_spatial_baseline"] == []
        submitted = await client.post(
            "/api/writing/generate",
            json={
                "novel_id": novel_id,
                "chapter_index": 1,
                "context_confirmation_id": confirmed.json()["id"],
            },
        )
        assert submitted.status_code == 201, submitted.text
        task_id = uuid.UUID(submitted.json()["task_id"])

        monkeypatch.setattr(
            "infrastructure.llm.providers.OpenAIProvider.generate", _fake_writing_provider
        )
        task = await _build_task_worker().run_once(
            task_id=task_id, novel_id=uuid.UUID(novel_id)
        )
        assert task is not None and task.status == "done", task.status if task else None
        async with manager.session() as db:
            stored = await db.get(AsyncTask, task_id)
            assert stored.status == "done"
            drafts = (
                await db.scalars(
                    select(WritingDraft).where(
                        WritingDraft.novel_id == uuid.UUID(novel_id),
                        WritingDraft.status == "candidate",
                    )
                )
            ).all()
            assert len(drafts) == 1


@pytest.mark.asyncio
async def test_five_scene_writing_map_arm_changes_only_map_context(tmp_path, monkeypatch):
    from modules.evidence.compilation.models import ContextConfirmation

    async with _product(tmp_path, monkeypatch, capabilities="") as (manager, client):
        novel_id, scenes = await _seed_five_scenes(manager)
        node_id, revision_id, document = await _seed_map(manager, novel_id, scenes[-1])

        arms = []
        monkeypatch.setattr(
            "infrastructure.llm.providers.OpenAIProvider.generate", _fake_writing_provider
        )
        for enabled in (False, True):
            monkeypatch.setenv(
                "MAP_SPATIAL_ENABLED_CAPABILITIES", "writing.generate" if enabled else ""
            )
            get_settings.cache_clear()
            confirmed = await client.post(
                "/api/evidence/compilation/confirm",
                json={
                    "novel_id": novel_id,
                    "action": "writing.generate",
                    "task": "续写第五场",
                    "scope": "scene",
                    "chapter_index": 1,
                    "scene_id": scenes[-1],
                    "content_mode": "canonical",
                    "context_mode": "canonical",
                },
            )
            assert confirmed.status_code == 201, confirmed.text
            async with manager.session() as db:
                row = await db.get(ContextConfirmation, uuid.UUID(confirmed.json()["id"]))
                options = row.compile_options
                arms.append(
                    (
                        options["compiled_context_core_fingerprint"],
                        options["map_spatial_baseline"],
                    )
                )
            submitted = await client.post(
                "/api/writing/generate",
                json={
                    "novel_id": novel_id,
                    "chapter_index": 1,
                    "context_confirmation_id": confirmed.json()["id"],
                },
            )
            assert submitted.status_code == 201, submitted.text
            task_id = uuid.UUID(submitted.json()["task_id"])
            task = await _build_task_worker().run_once(
                task_id=task_id, novel_id=uuid.UUID(novel_id)
            )
            assert task is not None and task.status == "done", (
                task.status if task else None
            )
        assert arms[0][0] == arms[1][0]
        assert arms[0][1] == []
        assert len(arms[1][1]) == 1

        excluded = await client.post(
            "/api/evidence/compilation/confirm",
            json={
                "novel_id": novel_id,
                "action": "writing.generate",
                "task": "续写第五场",
                "scope": "scene",
                "chapter_index": 1,
                "scene_id": scenes[-1],
                "content_mode": "canonical",
                "context_mode": "canonical",
                "excluded_asset_ids": {"map_spatial": [node_id]},
            },
        )
        assert excluded.status_code == 201, excluded.text
        async with manager.session() as db:
            row = await db.get(ContextConfirmation, uuid.UUID(excluded.json()["id"]))
            assert row.compile_options["map_spatial_baseline"] == []

        fresh = await client.post(
            "/api/evidence/compilation/confirm",
            json={
                "novel_id": novel_id,
                "action": "writing.generate",
                "task": "续写第五场",
                "scope": "scene",
                "chapter_index": 1,
                "scene_id": scenes[-1],
                "content_mode": "canonical",
                "context_mode": "canonical",
            },
        )
        assert fresh.status_code == 201, fresh.text
        assert any(
            section["key"] == "map_spatial" and section["status"] == "adopted"
            for section in fresh.json()["sections"]
        )
        from modules.world.map_structure_schemas import MapDocument, MapSaveRequest
        from modules.world.map_structure_service import MapStructureService

        changed = document.model_dump(mode="json")
        changed["features"][0]["note"] = "作者更新了北门地图"
        async with manager.session() as db:
            await MapStructureService().save(
                db,
                novel_id,
                node_id,
                MapSaveRequest(
                    base_revision_id=revision_id,
                    document=MapDocument.model_validate(changed),
                ),
            )
            from modules.evidence.facade import prepare_confirmed_ai_action

            current = await prepare_confirmed_ai_action(
                db,
                novel_id=novel_id,
                action="writing.generate",
                confirmation_id=fresh.json()["id"],
            )
            assert all(
                section.key != "map_spatial" for section in current.compiled.sections
            )
            assert (
                current.compiled.selection_trace["map_spatial_staleness"]["status"]
                == "changed"
            )


@pytest.mark.asyncio
async def test_assistant_map_enabled_submit_and_exact_worker(tmp_path, monkeypatch):
    async with _product(tmp_path, monkeypatch, capabilities="assistant.turn") as (
        manager,
        client,
    ):
        novel_id, scenes = await _seed_five_scenes(manager)
        await _seed_map(manager, novel_id, scenes[-1])
        created = await client.post(
            "/api/assistant/sessions", json={"novel_id": novel_id}
        )
        assert created.status_code == 201, created.text
        session_id = created.json()["id"]
        submitted = await client.post(
            f"/api/assistant/sessions/{session_id}/turns",
            json={
                "novel_id": novel_id,
                "operation_id": str(uuid.uuid4()),
                "message": "根据已采用地图，北门在哪里？",
                "allow_web": False,
                "context": {"scene_id": scenes[-1], "chapter_index": 1, "page": "map"},
            },
        )
        assert submitted.status_code == 202, submitted.text
        run_id = uuid.UUID(submitted.json()["id"])
        async with manager.session() as db:
            run = await db.get(AssistantRun, run_id)
            task = await db.get(AsyncTask, run_id)
            assert run.request_json["runtime_version"] == "6"
            assert "map_spatial_brief" in run.request_json["read_tools"]
            assert task is not None and task.status == "pending"

        calls = []

        async def fake_assistant_provider(_self, request):
            calls.append([tool.name for tool in request.tools or []])
            if len(calls) == 1:
                return LLMCallResponse(
                    tool_calls=[
                        LLMToolCall(
                            id="map-1",
                            name="map_spatial_brief",
                            arguments='{"query":"北门"}',
                        )
                    ],
                    usage=LLMUsage(
                        prompt_tokens=20, completion_tokens=10, total_tokens=30
                    ),
                    model="deepseek-flash",
                )
            output = next(
                tool
                for tool in request.tools
                if "answer" in tool.parameters.get("properties", {})
            )
            return LLMCallResponse(
                tool_calls=[
                    LLMToolCall(
                        id=f"final-{len(calls)}",
                        name=output.name,
                        arguments=json.dumps(
                            {"answer": "北门是已采用地图中的地点。", "actions": []},
                            ensure_ascii=False,
                        ),
                    )
                ],
                usage=LLMUsage(prompt_tokens=20, completion_tokens=10, total_tokens=30),
                model="deepseek-flash",
            )

        monkeypatch.setattr(
            "infrastructure.llm.providers.OpenAIProvider.generate",
            fake_assistant_provider,
        )
        task = await _build_task_worker().run_once(
            task_id=run_id, novel_id=uuid.UUID(novel_id)
        )
        assert task is not None and task.status == "done", task.status if task else None
        assert len(calls) >= 2 and "map_spatial_brief" in calls[0]
        async with manager.session() as db:
            run = await db.get(AssistantRun, run_id)
            assert run.status == "completed"
            assert run.result_json.get("knowledge_scope_receipt")
            assert "map_spatial" in json.dumps(run.result_json["knowledge_scope_receipt"])
