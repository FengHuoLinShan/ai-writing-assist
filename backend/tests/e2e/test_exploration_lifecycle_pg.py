"""Real PostgreSQL/Evidence/TaskWorker lifecycle with synthetic model I/O only."""

from __future__ import annotations

import asyncio
import copy
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from httpx import ASGITransport
from sqlalchemy import delete, inspect, select, text, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.main import app
from core.config import get_settings
from infrastructure.llm.client import LLMClient
from infrastructure.llm.limits import reset_llm_limiter_for_tests
from infrastructure.llm.schemas import read_ai_run_envelope
from infrastructure.llm.secret_store import encrypt_secret, fingerprint_secret
from infrastructure.tasks.worker import TaskWorker
from modules.account.settings_constants import (
    ACCOUNT_LLM_PROVIDER_TEMPLATES,
    LOCAL_OWNER_ID,
)
from modules.account.settings_models import AccountLLMCredential, GlobalLLMDefaults
from modules.account.settings_repositories import (
    AccountLLMCredentialRepository,
    GlobalLLMDefaultsRepository,
)
from modules.project.models import Project
from modules.story.exploration_service import create_exploration_root
from modules.story.models import StorySceneDirectorRoot
from modules.story.tests.exploration_test_support import ExplorationOfflineProvider
from modules.story.world_progression_models import StoryWorldProgressionRoot
from tests.e2e.config import DATABASE_URL
from tests.support.http import XhrAsyncClient

pytestmark = [pytest.mark.e2e, pytest.mark.asyncio]
PREFIX = "/api/story/exploration"
QUESTIONS = {
    "sandbox": "这个城镇每天只有一小时重力减半，面包师的一天会怎样？",
    "event": "信使不知道地址，却当天把信送到了本人手里，只要求找缺口。",
    "scene_line": "A 刚失业；B 不知此事，只看见 A 很疲惫，要求 B 真诚回应一句。",
}
ACTIONS = {
    "sandbox": "story.exploration.sandbox.generate",
    "event": "story.exploration.event.diagnose",
    "scene_line": "story.exploration.scene_line.generate",
}


def _start(scale):
    return {
        "kind": "provisional",
        "question": QUESTIONS[scale],
        "assumptions": [{"kind": "state", "text": "本次只检验问题中给出的条件"}],
        "candidates": [{"ref_id": "c_b", "label": "B", "role": "character"}],
        "knowledge": [
            {
                "subject_ref": "c_b",
                "knows": [],
                "observed": ["A 很疲惫"],
                "misbelieves": [],
            }
        ],
        "time_basis": "assumed_now",
    }


@pytest_asyncio.fixture
async def pg_flow(monkeypatch):
    settings = replace(get_settings(), story_exploration_enabled=True)
    monkeypatch.setattr(
        "modules.story.exploration_feature.get_settings", lambda: settings
    )
    provider = ExplorationOfflineProvider()

    @asynccontextmanager
    async def offline_client(_db, _novel_id, _snapshot):
        reset_llm_limiter_for_tests()
        client = LLMClient.from_project_settings(
            {"llm": {"provider_id": "deepseek", "model": "deepseek-flash"}}
        )
        client._provider = provider
        yield client

    monkeypatch.setattr(
        "modules.story.exploration_tasks.open_project_snapshot_llm_client", offline_client
    )
    engine = create_async_engine(DATABASE_URL, pool_size=3, max_overflow=0)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    novel_id = uuid4()
    previous = []
    async with sessions.begin() as db:
        for model in (AccountLLMCredential, GlobalLLMDefaults):
            query = select(model).where(model.owner_id == LOCAL_OWNER_ID)
            if model is AccountLLMCredential:
                query = query.where(model.provider_id == "deepseek")
            row = await db.scalar(query)
            previous.append(
                (
                    model,
                    {
                        column.name: getattr(row, column.name)
                        for column in model.__table__.columns
                    }
                    if row
                    else None,
                )
            )
        db.add(
            Project(
                id=novel_id, owner_id=LOCAL_OWNER_ID, title="探索 PostgreSQL 合成生命周期"
            )
        )
        await db.flush()
        key = "synthetic-exploration-pg-key"
        await AccountLLMCredentialRepository().upsert(
            db,
            {
                "owner_id": LOCAL_OWNER_ID,
                "provider_id": "deepseek",
                "encrypted_api_key": encrypt_secret(key),
                "key_fingerprint": fingerprint_secret(key, purpose="account-llm-api-key"),
                "verified_at": datetime.now(UTC),
            },
        )
        await GlobalLLMDefaultsRepository().upsert(
            db, {"owner_id": LOCAL_OWNER_ID, **ACCOUNT_LLM_PROVIDER_TEMPLATES["deepseek"]}
        )
    try:
        async with XhrAsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield SimpleNamespace(
                client=client,
                sessions=sessions,
                novel_id=str(novel_id),
                provider=provider,
                worker=TaskWorker(
                    db_manager=SimpleNamespace(engine=engine, session_factory=sessions),
                    heartbeat_interval=60.0,
                ),
            )
    finally:
        async with sessions.begin() as db:
            await db.execute(delete(Project).where(Project.id == novel_id))
            for model, payload in previous:
                query = model.owner_id == LOCAL_OWNER_ID
                if model is AccountLLMCredential:
                    query = query & (model.provider_id == "deepseek")
                if payload is None:
                    await db.execute(delete(model).where(query))
                else:
                    await db.execute(update(model).where(query).values(**payload))
        await engine.dispose()


async def _post(client, path, body, status=200):
    response = await client.post(PREFIX + path, json=body)
    assert response.status_code == status, response.text
    return response.json()


@pytest.mark.parametrize("scale", QUESTIONS)
async def test_provisional_exploration_full_lifecycle(pg_flow, scale, monkeypatch):
    flow = pg_flow
    body = {
        "novel_id": flow.novel_id,
        "scale": scale,
        "start": _start(scale),
        "focus": "",
    }
    preview = await _post(flow.client, "/preview", body)
    confirmation_body = {**body, "action": ACTIONS[scale]}
    material_preview = await _post(
        flow.client, "/confirmation/preview", confirmation_body
    )
    confirmed = await _post(
        flow.client,
        "/confirmation",
        {
            **confirmation_body,
            "expected_context_fingerprint": material_preview["context_fingerprint"],
        },
    )
    assert flow.provider.calls == 0
    start_body = {
        **confirmation_body,
        "operation_id": str(uuid4()),
        "context_confirmation_id": confirmed["confirmation_id"],
        "budget_preview_hash": preview["budget"]["preview_hash"],
    }
    started = await _post(flow.client, "/start", start_body, 202)
    replayed = await _post(flow.client, "/start", start_body, 202)
    assert replayed == started

    async def run(receipt):
        await flow.worker.run_once(
            task_id=UUID(receipt["task_id"]), novel_id=flow.novel_id
        )
        response = await flow.client.get(
            f"/api/tasks/{receipt['task_id']}", params={"novel_id": flow.novel_id}
        )
        assert response.status_code == 200, response.text
        task = response.json()
        assert task["status"] == "done", task
        assert task["result"]["output_kind"] == f"story.exploration.{scale}"
        return task["result"]

    original = await run(started)
    assert flow.provider.calls == 3
    original_payload = copy.deepcopy(original["payload"])
    detail = await _post(
        flow.client,
        f"/results/{original['result_id']}/detail",
        {
            "novel_id": flow.novel_id,
            "operation_id": str(uuid4()),
            "focus": "保留条件，解释依据",
        },
        202,
    )
    detailed = await run(detail)
    paths = {"sandbox": "chain:0", "event": "gap:0", "scene_line": "line"}
    revised = await run(
        await _post(
            flow.client,
            f"/results/{detailed['result_id']}/revise",
            {
                "novel_id": flow.novel_id,
                "operation_id": str(uuid4()),
                "item_path": paths[scale],
                "instruction": "只改这条表达，保留其余条件与未知",
            },
            202,
        )
    )
    assert flow.provider.calls == 9
    edited = copy.deepcopy(revised["payload"])
    if scale == "sandbox":
        edited["influence_chain"][0]["effect"] = "作者保存的影响"
    elif scale == "event":
        edited["gaps"][0]["description"] = "作者保存的缺口"
    else:
        edited["line"] = "作者保存的一句回应"
    edit_body = {
        "novel_id": flow.novel_id,
        "base_output_kind": revised["output_kind"],
        "edited_payload": edited,
    }
    saved = await _post(
        flow.client, f"/results/{revised['result_id']}/save-edit", edit_body
    )
    saved_again = await _post(
        flow.client, f"/results/{revised['result_id']}/save-edit", edit_body
    )
    assert saved_again["result_id"] == saved["result_id"]
    assert saved["result_id"] != revised["result_id"]
    assert saved["payload"]["edited_payload"] == edited
    comparison = await _post(
        flow.client,
        "/compare",
        {
            "novel_id": flow.novel_id,
            "first_result_id": revised["result_id"],
            "second_result_id": saved["result_id"],
            "mode": "same_start",
        },
    )
    assert comparison["relation"] == "parent_child"
    assert comparison["second"]["payload"]["edited_payload"] == edited

    root_model = (
        StorySceneDirectorRoot if scale == "scene_line" else StoryWorldProgressionRoot
    )
    async with flow.sessions() as db:
        root = await db.get(root_model, UUID(started["root_id"]))
        assert root.source_kind == "provisional" and root.scene_id is None
        ledger = read_ai_run_envelope(root.run_envelope_json)
        assert ledger.requests_started == 9 and ledger.requests_unknown == 0
    # Disabling execution keeps saved history readable, including immutable originals.
    from modules.story import exploration_feature

    monkeypatch.setattr(
        exploration_feature,
        "get_settings",
        lambda: replace(get_settings(), story_exploration_enabled=False),
    )
    history_response = await flow.client.get(
        PREFIX + "/history",
        params={"novel_id": flow.novel_id, "root_id": started["root_id"]},
    )
    assert history_response.status_code == 200, history_response.text
    history = {row["result_id"]: row for row in history_response.json()["items"]}
    assert set(history) == {
        original["result_id"],
        detailed["result_id"],
        revised["result_id"],
        saved["result_id"],
    }
    assert history[original["result_id"]]["payload"] == original_payload
    assert flow.provider.calls == 9
    disabled = await flow.client.post(
        PREFIX + "/start", json={**start_body, "operation_id": str(uuid4())}
    )
    assert disabled.status_code == 503


async def test_same_project_three_scale_starts_do_not_upgrade_shared_locks(pg_flow):
    from modules.project.facade import require_active_project
    from modules.story.exploration_api import (
        ExplorationStartApiRequest,
        start_exploration_task,
    )

    flow = pg_flow
    requests = []
    for scale in QUESTIONS:
        body = {
            "novel_id": flow.novel_id,
            "scale": scale,
            "start": _start(scale),
            "focus": "",
        }
        preview = await _post(flow.client, "/preview", body)
        confirmation_body = {**body, "action": ACTIONS[scale]}
        material = await _post(flow.client, "/confirmation/preview", confirmation_body)
        confirmation = await _post(
            flow.client,
            "/confirmation",
            {
                **confirmation_body,
                "expected_context_fingerprint": material["context_fingerprint"],
            },
        )
        requests.append(
            ExplorationStartApiRequest(
                **confirmation_body,
                operation_id=uuid4(),
                context_confirmation_id=confirmation["confirmation_id"],
                budget_preview_hash=preview["budget"]["preview_hash"],
            )
        )

    admitted = asyncio.Barrier(len(requests))

    async def start(data, *, synchronize=False):
        async with flow.sessions.begin() as db:
            # Match api_start: all callers hold the shared active-project fence.
            await require_active_project(db, flow.novel_id)
            if synchronize:
                await asyncio.wait_for(admitted.wait(), timeout=5)
            return await start_exploration_task(db, data=data)

    results = await asyncio.gather(
        *(start(data, synchronize=True) for data in requests), return_exceptions=True
    )
    errors = [
        {
            "scale": data.scale,
            "error": type(result).__name__,
            "sqlstate": getattr(getattr(result, "orig", None), "sqlstate", None),
            "detail": str(result),
        }
        for data, result in zip(requests, results, strict=True)
        if isinstance(result, Exception)
    ]
    # Reuse the same IDs: failed transactions can retry, accepted ones stay idempotent.
    replayed = [await start(data) for data in requests]
    assert len({receipt["task_id"] for receipt in replayed}) == 3
    for concurrent, replay in zip(results, replayed, strict=True):
        if not isinstance(concurrent, Exception):
            assert concurrent["task_id"] == replay["task_id"]
    assert flow.provider.calls == 0
    assert not errors, "\n\n".join(
        f"{error['scale']}: {error['error']}, SQLSTATE={error['sqlstate']}\n"
        f"{error['detail']}"
        for error in errors
    )


@pytest.mark.parametrize("scale", ["sandbox", "scene_line"])
async def test_provisional_history_refuses_migration_downgrade(db_session, scale):
    from modules.evidence.contracts import ProvisionalStart

    project = Project(owner_id=LOCAL_OWNER_ID, title="临时探索历史拒绝降级")
    db_session.add(project)
    await db_session.flush()
    root, _ = await create_exploration_root(
        db_session,
        novel_id=str(project.id),
        owner_id=str(LOCAL_OWNER_ID),
        scale=scale,
        start=ProvisionalStart.model_validate(_start(scale)),
        context_confirmation_id=str(uuid4()),
    )
    migration = (
        ScriptDirectory.from_config(Config("alembic.ini"))
        .get_revision("20261017_exploration_start_kind")
        .module
    )
    connection = await db_session.connection()

    def refuse_downgrade(connection):
        def schema():
            inspector = inspect(connection)
            return {
                table: (
                    [
                        (column["name"], str(column["type"]), column["nullable"])
                        for column in inspector.get_columns(table)
                    ],
                    inspector.get_indexes(table),
                    inspector.get_check_constraints(table),
                )
                for table in (
                    "story_scene_director_roots",
                    "story_world_progression_roots",
                )
            }

        before = schema()
        heads = list(
            connection.execute(text("SELECT version_num FROM alembic_version")).scalars()
        )
        with Operations.context(MigrationContext.configure(connection)):
            with pytest.raises(
                RuntimeError, match="存在.*临时起点探索记录.*拒绝破坏性降级"
            ):
                migration.downgrade()
        assert schema() == before
        assert (
            list(
                connection.execute(
                    text("SELECT version_num FROM alembic_version")
                ).scalars()
            )
            == heads
        )

    await connection.run_sync(refuse_downgrade)
    await db_session.refresh(root)
    assert root.source_kind == "provisional" and root.scene_id is None
