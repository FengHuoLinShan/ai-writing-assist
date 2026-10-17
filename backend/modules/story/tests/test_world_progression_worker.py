"""Exercise the real TaskWorker and LLMClient with a synthetic offline provider."""

from __future__ import annotations

import json
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from core.base import Base
from infrastructure.llm.client import LLMClient
from infrastructure.llm.limits import reset_llm_limiter_for_tests
from infrastructure.llm.schemas import LLMCallResponse, LLMUsage
from infrastructure.llm.workflow_budget import new_ai_run_envelope
from infrastructure.tasks.enqueuer import enqueue_task
from infrastructure.tasks.models import AsyncTask
from infrastructure.tasks.worker import TaskWorker
from modules.story import world_progression_tasks as progression
from modules.story.world_progression_models import (
    StoryWorldProgressionBranch,
    StoryWorldProgressionRoot,
    StoryWorldProgressionStep,
)


class _Provider:
    name = "offline"

    def __init__(self):
        self.calls = 0

    async def generate(self, request):
        self.calls += 1
        payload = json.loads(
            next(item.content for item in request.messages if item.role == "user")
        )
        if "actor_id" in payload:
            actor = payload["actor_id"]
            result = {
                "intent": {
                    "actor_id": actor,
                    "kind": "action",
                    "action": "在原地观察",
                    "reason": "离线测试",
                    "basis_ids": ["basis-1"],
                    "effect": "none",
                }
            }
        else:
            intent_id = next(iter(payload["intent_ids"].values()))
            result = {
                "story_time_text": "约一天",
                "narrative_summary": "人物继续观察。",
                "rolling_summary": "人物仍在原地观察。",
                "outcomes": {intent_id: "succeeded"},
            }
        return LLMCallResponse(
            content=json.dumps(result, ensure_ascii=False),
            finish_reason="stop",
            usage=LLMUsage(prompt_tokens=5, completion_tokens=5, total_tokens=10),
            model="deepseek-flash",
            provider="offline",
        )


class _Manager:
    def __init__(self, engine, sessions):
        self.engine = engine
        self.session_factory = sessions


@pytest_asyncio.fixture
async def isolated_worker_engine():
    """The worker commits, so it must not leak rows into the shared test engine."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine.sync_engine, "connect")
    def disable_implicit_transactions(connection, _record):
        connection.isolation_level = None

    @event.listens_for(engine.sync_engine, "begin")
    def begin_transaction(connection):
        connection.exec_driver_sql("BEGIN")

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_world_progression_worker_persists_offline_steps(
    isolated_worker_engine, monkeypatch, *, seed_project=False, step_count=1
):
    expected_calls = 2 * step_count
    actor, novel_id, scene_id, root_id, branch_id = [uuid.uuid4() for _ in range(5)]
    source = {
        "source_hash": "a" * 64,
        "scene_id": str(scene_id),
        "simulation_context": {
            "participants": [{"kind": "object", "id": str(actor)}],
            "locations": [],
            "positions": [],
            "resources": [],
            "routes": [],
            "assumptions": [],
        },
        "role_briefs": {
            str(actor): {
                "viewpoint": {"kind": "character", "character_id": str(actor)},
                "brief": {"world_items": []},
                "source_ids": ["basis-1"],
                "known_participant_ids": [str(actor)],
                "known_entity_ids": [str(actor)],
                "known_route_ids": [],
            }
        },
        "map_state": {"coverage": "not_available", "routes": [], "unknowns": []},
        "author_brief": {"coverage": "complete", "world_items": []},
        "author_source_ids": ["basis-1"],
        "time_basis": {"facts": []},
        "targets": [],
        "life_state_checks": [],
        "object_validity_notices": [],
    }

    source_read_kwargs = {}

    async def read_source(_db, **kwargs):
        source_read_kwargs.update(kwargs)
        return source

    async def validate_refs(_db, _novel_id, _context):
        return None

    confirmed_context = SimpleNamespace(compiled=object())

    async def confirmed(_db, **_kwargs):
        return SimpleNamespace(
            compiled=confirmed_context.compiled,
            compile_options={
                "scene_id": str(scene_id),
                "character_ids": [str(actor)],
                "entity_ids": [],
            },
        )

    provider = _Provider()

    @asynccontextmanager
    async def offline_client(_db, _novel_id, _snapshot):
        reset_llm_limiter_for_tests()
        client = LLMClient.from_project_settings(
            {"llm": {"provider_id": "deepseek", "model": "deepseek-flash"}}
        )
        client._provider = provider
        yield client

    monkeypatch.setattr(progression, "read_progression_source", read_source)
    monkeypatch.setattr(progression, "validate_simulation_context_refs", validate_refs)
    monkeypatch.setattr(progression, "prepare_confirmed_ai_action", confirmed)
    monkeypatch.setattr(progression, "open_project_snapshot_llm_client", offline_client)
    monkeypatch.setattr(
        progression,
        "capability_from_execution_snapshot",
        lambda _snapshot: SimpleNamespace(hard_input_tokens=12000),
    )
    sessions = async_sessionmaker(
        isolated_worker_engine, expire_on_commit=False, autoflush=False
    )
    started = datetime.now(UTC)
    envelope = new_ai_run_envelope(
        operation_id=str(uuid.uuid4()),
        run_id=str(root_id),
        root_capability_id=progression.WORLD_PROGRESSION_CAPABILITY,
        novel_id=str(novel_id),
        request_limit=20,
        budget_mode="bounded",
        token_limit=20000,
        started_at=started,
        deadline_at=started + timedelta(hours=1),
    )
    request = {
        "novel_id": str(novel_id),
        "scene_id": str(scene_id),
        "participants": [{"kind": "character", "id": str(actor)}],
        "targets": [],
        "mode": "free",
        "step_length": "auto",
        "run_policy": "one_step" if step_count == 1 else "n_steps",
        "steps": None if step_count == 1 else step_count,
    }
    async with sessions.begin() as db:
        if seed_project:
            import modules.account.models  # noqa: F401
            from modules.project.models import Project

            db.add(Project(id=novel_id, title="世界推进离线 Worker 测试"))
            await db.flush()
        db.add(
            StoryWorldProgressionRoot(
                id=root_id,
                novel_id=novel_id,
                scene_id=scene_id,
                source_hash=source["source_hash"],
                request_json=request,
                source_snapshot_json=source,
                llm_execution_snapshot_json={"novel_id": str(novel_id)},
                run_envelope_json=envelope.snapshot().model_dump(mode="json"),
                context_confirmation_id="offline-confirmation",
                status="queued",
            )
        )
        await db.flush()
        db.add(
            StoryWorldProgressionBranch(
                id=branch_id,
                novel_id=novel_id,
                root_id=root_id,
                branch_kind="start",
                basis_choice="current",
                source_hash=source["source_hash"],
                request_json={},
                source_snapshot_json=source,
                status="queued",
            )
        )
        await db.flush()
        task_id = uuid.UUID(
            enqueue_task(
                db,
                progression.WORLD_PROGRESSION_TASK,
                novel_id=str(novel_id),
                meta=progression._task_meta(
                    request={
                        "novel_id": str(novel_id),
                        "context_confirmation_id": "offline-confirmation",
                    },
                    root_id=root_id,
                    branch_id=branch_id,
                    execution_snapshot={"novel_id": str(novel_id)},
                    envelope=envelope,
                ),
            )
        )
        root = await db.get(StoryWorldProgressionRoot, root_id)
        branch = await db.get(StoryWorldProgressionBranch, branch_id)
        root.current_task_id = branch.current_task_id = task_id

    await TaskWorker(db_manager=_Manager(isolated_worker_engine, sessions)).run_once(
        task_id=task_id, novel_id=novel_id
    )
    assert source_read_kwargs["confirmed_context"].compiled is confirmed_context.compiled
    async with sessions() as db:
        task = await db.get(AsyncTask, task_id)
        root = await db.get(StoryWorldProgressionRoot, root_id)
        persisted_steps = (
            await db.scalars(
                select(StoryWorldProgressionStep).where(
                    StoryWorldProgressionStep.root_id == root_id
                )
            )
        ).all()
        assert task.status == "done"
        assert len(persisted_steps) == expected_calls // 2
        assert root.run_envelope_json["requests_started"] == expected_calls
        assert provider.calls == expected_calls
