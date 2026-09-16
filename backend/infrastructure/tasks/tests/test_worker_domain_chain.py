"""W2.1 代表链：真实 TaskWorker → 领域 handler → 真实 LLMClient 的端到端回归。

领域 DB 状态在 facade 边界打桩，provider 传输层用替身；LLMClient 单入口计量、
worker 信封边界与领域 handler 逻辑全部走真实实现。
"""

from __future__ import annotations

import json
import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker

from infrastructure.llm.limits import reset_llm_limiter_for_tests
from infrastructure.llm.schemas import (
    AI_RUN_ENVELOPE_KEY,
    AIRunStatus,
    LLMCallResponse,
    read_ai_run_envelope,
)
from infrastructure.llm.workflow_budget import current_ai_run_envelope
from infrastructure.tasks.api import _public_task_meta
from infrastructure.tasks.enqueuer import enqueue_task
from infrastructure.tasks.models import AsyncTask
from infrastructure.tasks.worker import TaskWorker


class _ChainProvider:
    """provider 传输层替身：按请求顺序返回 JSON 正文。"""

    name = "fake"

    def __init__(self, payloads: list[str]) -> None:
        self._payloads = list(payloads)
        self.calls = 0

    async def generate(self, request) -> LLMCallResponse:
        self.calls += 1
        index = min(self.calls - 1, len(self._payloads) - 1)
        return LLMCallResponse(
            content=self._payloads[index],
            finish_reason="stop",
            model="deepseek-flash",
            provider="fake",
        )


class _NullLimiter:
    def run(self, call, *, limiter_scope=None):
        return call()

    @asynccontextmanager
    async def scope(self, *, limiter_scope=None):
        yield


def _chain_client(monkeypatch: pytest.MonkeyPatch, provider: _ChainProvider):
    from infrastructure.llm.client import LLMClient

    reset_llm_limiter_for_tests()
    client = LLMClient()
    client._provider = provider  # type: ignore[attr-defined]
    monkeypatch.setattr(
        "infrastructure.llm.client.get_llm_limiter", lambda: _NullLimiter()
    )
    return client


class _TaskManager:
    def __init__(self, engine: Any, sessions: Any) -> None:
        self.engine = engine
        self.session_factory = sessions


async def _run_once(test_engine, sessions) -> AsyncTask | None:
    return await TaskWorker(
        db_manager=_TaskManager(test_engine, sessions),
        heartbeat_interval=60.0,
    ).run_once()


@pytest.mark.asyncio
async def test_interaction_summary_refresh_chain_runs_through_worker_and_client(
    test_engine,
    monkeypatch,
) -> None:
    """真实 worker → interaction.summary_refresh handler → LLMClient 单入口。"""
    import modules.interaction.tasks as interaction_tasks
    from infrastructure.llm.schemas import LLMMessage, read_ai_run_envelope
    from modules.interaction.generation import PreparedSummaryGeneration

    sessions = async_sessionmaker(test_engine, expire_on_commit=False, autoflush=False)
    novel_id = str(uuid.uuid4())
    provider = _ChainProvider(
        [
            json.dumps(
                {
                    "segment_summary": "主角在夜市察觉到了跟踪者。",
                    "overview": {
                        "world_and_start": "夜市开局",
                        "current_situation": "主角摆脱跟踪",
                        "must_remember": "跟踪者戴青铜面具",
                    },
                },
                ensure_ascii=False,
            )
        ]
    )

    async def stub_prepare(db, *, task):
        del db, task
        return PreparedSummaryGeneration(
            novel_id=novel_id,
            journey_id=str(uuid.uuid4()),
            path_hash="chain-path",
            node_ids=[],
            segment_node_ids=[],
            started_overview_epoch=0,
            messages=[
                LLMMessage(role="system", content="回顾前情"),
                LLMMessage(role="user", content="剧情片段"),
            ],
            executable_settings={
                "llm": {
                    "provider_id": "deepseek",
                    "model": "deepseek-flash",
                    "max_tokens": 2000,
                }
            },
        )

    async def stub_finalize(*_args, **_kwargs):
        return {"status": "completed"}

    captured: dict[str, Any] = {}

    def fake_snapshot_client(settings, *, novel_id, **_kwargs):
        captured["settings"] = settings
        captured["novel_id"] = novel_id
        return _chain_client(monkeypatch, provider)

    monkeypatch.setattr(
        interaction_tasks._workflow, "prepare_summary_task", stub_prepare
    )
    monkeypatch.setattr(
        interaction_tasks._workflow, "finalize_summary_task", stub_finalize
    )
    monkeypatch.setattr(
        interaction_tasks,
        "create_project_snapshot_llm_client",
        fake_snapshot_client,
    )

    task_id = await _enqueue(
        sessions, "interaction_summary_refresh", meta={"novel_id": novel_id},
        novel_id=novel_id,
    )
    try:
        returned = await _run_once(test_engine, sessions)

        assert returned is not None and returned.status == "done"
        assert provider.calls == 1
        assert captured["novel_id"] == novel_id
        async with sessions() as db:
            stored = await db.get(AsyncTask, task_id)
            assert stored is not None
            assert (stored.result or {}).get("status") == "completed"
            # W3-C 起该任务声明 root=interaction.summary_refresh（L0=8）：
            # 信封写入私有 meta，公开投影不暴露。
            envelope = read_ai_run_envelope(
                (stored.meta or {}).get("_ai_run_envelope")
            )
            assert envelope is not None
            assert envelope.root_capability_id == "interaction.summary_refresh"
            assert envelope.requests_started == 1
            assert envelope.requests_settled == 1
            assert envelope.status is AIRunStatus.succeeded
            assert "_ai_run_envelope" not in (stored.result or {})
            assert current_ai_run_envelope() is None
    finally:
        await _cleanup(sessions, [task_id])


@pytest.mark.asyncio
async def test_world_map_schematic_generate_chain_runs_through_worker_and_client(
    test_engine,
    monkeypatch,
) -> None:
    """真实 worker → world_map_schematic_generate handler → LLMClient 单入口。"""
    import modules.world.map_structure_workflow as map_workflow

    sessions = async_sessionmaker(test_engine, expire_on_commit=False, autoflush=False)
    novel_id = str(uuid.uuid4())
    node_id = str(uuid.uuid4())
    confirmation_id = str(uuid.uuid4())
    task_id = uuid.uuid4()

    source_hash = "a" * 64
    relation_payload = json.dumps(
        {
            "relations": [
                {
                    "subject": "loc-a",
                    "relation": "connects",
                    "target": "loc-b",
                    "path_kind": "road",
                    "evidence": [
                        {"source_key": "doc:1", "quote": "A城有官道直通B镇。"}
                    ],
                }
            ]
        },
        ensure_ascii=False,
    )
    provider = _ChainProvider([relation_payload])

    document = map_workflow.MapDocument(
        features=[
            map_workflow.MapFeature(id="loc-a", kind="location", label="A城"),
            map_workflow.MapFeature(id="loc-b", kind="location", label="B镇"),
        ]
    )
    source_ref = map_workflow.MapSource(
        kind="entity",
        id=uuid.uuid4(),
        source_hash=source_hash,
    )

    class _StubService:
        def __init__(self) -> None:
            self.node_calls = 0

        async def node(self, _db, _novel_id, _node_id, *, lock=False):
            del lock
            self.node_calls += 1
            return SimpleNamespace(
                structure_task_id=task_id,
                novel_id=uuid.UUID(novel_id),
                id=uuid.UUID(node_id),
            )

        async def source(self, _db, _novel_id, ref):
            return ref

    stub_service = _StubService()

    async def stub_prepare(db, *, novel_id, action, confirmation_id):
        del db, novel_id, action
        return SimpleNamespace(
            confirmation=SimpleNamespace(context_fingerprint="chain-fingerprint"),
            confirmation_id=confirmation_id,
        )

    async def stub_structure_inputs(_db, _novel_id, _node_id, _meta, _prepared):
        return (
            None,
            document,
            {"doc:1": {"text": "A城有官道直通B镇。", "ref": source_ref}},
            [
                {"key": "loc-a", "name": "A城", "kind": "location"},
                {"key": "loc-b", "name": "B镇", "kind": "location"},
            ],
            {"loc-a": ["doc:1"], "loc-b": ["doc:1"]},
        )

    async def stub_restore_settings(_db, _novel_id, _snapshot):
        return {"llm": {"provider_id": "deepseek", "model": "deepseek-flash"}}

    async def stub_require_active_project(_db, _novel_id):
        return None

    async def stub_require_active_project_exclusive(_db, _novel_id):
        return None

    async def stub_require_fresh_confirmation(_db, *, novel_id, action, confirmation_id):
        del novel_id, action, confirmation_id
        return None

    async def stub_govern_group_output(_client, **_kwargs):
        return {"status": "passed", "review": {"verdict": "pass"}}

    def fake_snapshot_client(settings, *, novel_id, **_kwargs):
        del novel_id
        captured_settings.append(settings)
        return _chain_client(monkeypatch, provider)

    captured_settings: list[dict] = []

    monkeypatch.setattr(
        map_workflow, "MapStructureService", lambda: stub_service
    )
    monkeypatch.setattr(
        map_workflow, "prepare_confirmed_ai_action", stub_prepare
    )
    monkeypatch.setattr(
        map_workflow, "structure_inputs", stub_structure_inputs
    )
    monkeypatch.setattr(
        map_workflow, "restore_project_llm_execution_settings", stub_restore_settings
    )
    monkeypatch.setattr(
        map_workflow, "create_project_snapshot_llm_client", fake_snapshot_client
    )
    monkeypatch.setattr(
        map_workflow, "require_active_project", stub_require_active_project
    )
    monkeypatch.setattr(
        map_workflow,
        "require_active_project_exclusive",
        stub_require_active_project_exclusive,
    )
    monkeypatch.setattr(
        map_workflow, "require_fresh_confirmation", stub_require_fresh_confirmation
    )
    monkeypatch.setattr(map_workflow, "govern_group_output", stub_govern_group_output)

    meta = {
        "novel_id": novel_id,
        "node_id": node_id,
        "context_confirmation_id": confirmation_id,
        "llm_execution_snapshot": {"llm": {"model": "deepseek-flash"}},
    }
    try:
        enqueued = await _enqueue(
            sessions, "world_map_schematic_generate", meta=meta, novel_id=novel_id
        )
        # handler 校验 node.structure_task_id == task.id，回填真实 id。
        task_id = enqueued
        returned = await _run_once(test_engine, sessions)

        assert returned is not None and returned.status == "done"
        assert provider.calls == 1
        assert captured_settings
        result = returned.result or {}
        assert result["node_id"] == node_id
        # 成功收尾的 result 是 handler 返回值：关系被接受则 outcome 为 complete。
        assert result["summary"]["outcome"] == "complete"
        assert result["summary"]["accepted_relations"] == 1
        assert result["partial"] is False
        async with sessions() as db:
            stored = await db.get(AsyncTask, task_id)
            assert stored is not None
            # W3-B 起该任务声明 root=world.map_structure.generate（L0=60）：
            # 信封写入私有 meta，公开投影仍剥离。
            envelope = read_ai_run_envelope(
                (stored.meta or {}).get(AI_RUN_ENVELOPE_KEY)
            )
            assert envelope is not None
            assert envelope.root_capability_id == "world.map_structure.generate"
            assert envelope.request_limit == 60
            assert envelope.requests_started == 1
            assert envelope.status is AIRunStatus.succeeded
            assert AI_RUN_ENVELOPE_KEY not in (stored.result or {})
            assert AI_RUN_ENVELOPE_KEY not in _public_task_meta(stored.meta)
    finally:
        await _cleanup(sessions, [task_id])


async def _enqueue(
    sessions: Any,
    task_type: str,
    *,
    meta: dict[str, Any],
    novel_id=None,
) -> uuid.UUID:
    async with sessions.begin() as db:
        task_id = uuid.UUID(
            enqueue_task(db, task_type, meta=meta, novel_id=novel_id)
        )
    return task_id


async def _cleanup(sessions: Any, task_ids: list[uuid.UUID]) -> None:
    ids = [item for item in task_ids if item is not None]
    if not ids:
        return
    async with sessions.begin() as db:
        await db.execute(delete(AsyncTask).where(AsyncTask.id.in_(ids)))
