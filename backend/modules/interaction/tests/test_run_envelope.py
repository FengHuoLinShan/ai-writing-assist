"""W3-C：Interaction 业务通道的运行信封回归。

真实 TaskWorker → 生产 handler → 真实 LLMClient（provider 传输层替身）的
代表链、agent 路径的 root capability 归属与单账本语义、预算耗尽的失败关闭。
"""

from __future__ import annotations

import json
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker

from infrastructure.llm.limits import reset_llm_limiter_for_tests
from infrastructure.llm.schemas import (
    AI_RUN_ENVELOPE_KEY,
    LLMCallResponse,
    LLMMessage,
    LLMStreamChunk,
    LLMToolCall,
    LLMUsage,
    read_ai_run_envelope,
)
from infrastructure.llm.workflow_budget import (
    AIRunEnvelope,
    new_ai_run_envelope,
)
from infrastructure.tasks.api import _public_task_meta
from infrastructure.tasks.enqueuer import enqueue_task
from infrastructure.tasks.models import AsyncTask
from infrastructure.tasks.registry import get_registry
from infrastructure.tasks.worker import TaskWorker
from modules.interaction import agent_runtime as interaction_agent_runtime
from modules.interaction import tasks as interaction_tasks
from modules.interaction.generation import (
    PreparedStoryGeneration,
    PreparedSummaryGeneration,
)
from modules.interaction.runtime_policy import AGENT_STORY_TASK


def test_interaction_tasks_declare_run_envelope_contracts() -> None:
    """单 task run 声明信封；跨 task 的 story attempt 在领域接线前保持旧预算。"""
    import modules.interaction.proactive  # noqa: F401  注册副作用
    import modules.interaction.tasks  # noqa: F401  注册副作用

    registry = get_registry()
    task = object()
    expected = {
        "interaction_summary_refresh": (
            "interaction.summary_refresh",
            8,
            None,
        ),
        "interaction_continuity_review": (
            "interaction.continuity_review",
            9,
            None,
        ),
    }
    for task_type, (root, limit, deadline) in expected.items():
        assert registry.get_root_capability(task_type) == root, task_type
        assert registry.resolve_run_request_limit(task_type, task) == limit, task_type
        assert registry.resolve_run_deadline_seconds(task_type, task) == deadline, (
            task_type
        )
    for task_type in ("interaction_story_generate", "interaction_agent_story_generate"):
        assert registry.get_root_capability(task_type) is None
        assert registry.resolve_run_request_limit(task_type, task) is None


_SUMMARY_PAYLOAD = {
    "segment_summary": "主角在夜市察觉到了跟踪者。",
    "overview": {
        "world_and_start": "夜市开局",
        "current_situation": "主角摆脱跟踪",
        "must_remember": "跟踪者戴青铜面具",
    },
}

_SETTINGS = {"llm": {"provider_id": "deepseek", "model": "deepseek-v4-flash"}}


class _NullLimiter:
    def run(self, call, *, limiter_scope=None):
        return call()

    @asynccontextmanager
    async def scope(self, *, limiter_scope=None):
        yield


class _JsonProvider:
    """structured 链路的 provider 替身：按序返回 JSON 正文。"""

    name = "fake"

    def __init__(self, payload: str) -> None:
        self._payload = payload
        self.calls = 0

    async def generate(self, request) -> LLMCallResponse:
        self.calls += 1
        return LLMCallResponse(
            content=self._payload,
            finish_reason="stop",
            model="deepseek-flash",
            provider="fake",
        )


class _OutputToolProvider:
    """Agent 链路的 provider 替身：调用请求里的输出工具返回结构化结果。"""

    name = "fake"

    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload
        self.calls = 0

    async def generate(self, request) -> LLMCallResponse:
        self.calls += 1
        output_tool = next(
            tool
            for tool in request.tools
            if tool.name not in {"lookup_history", "lookup_source"}
        )
        return LLMCallResponse(
            tool_calls=[
                LLMToolCall(
                    id=f"out-{self.calls}",
                    name=output_tool.name,
                    arguments=json.dumps(self._payload, ensure_ascii=False),
                )
            ],
            usage=LLMUsage(prompt_tokens=10, completion_tokens=4, total_tokens=14),
        )


class _StoryAgentProvider:
    """故事阶段 provider：一次准备 agent 请求 + 一次正文流。"""

    name = "fake"

    def __init__(self) -> None:
        self.generate_calls = 0
        self.stream_calls = 0

    async def generate(self, request) -> LLMCallResponse:
        self.generate_calls += 1
        output_tool = next(
            tool
            for tool in request.tools
            if tool.name not in {"lookup_history", "lookup_source"}
        )
        return LLMCallResponse(
            tool_calls=[
                LLMToolCall(
                    id="plan-1",
                    name=output_tool.name,
                    arguments=json.dumps(
                        {
                            "scene_intent": "主角在夜市摆脱跟踪者",
                            "continuity_notes": [],
                            "evidence_ids": [],
                        },
                        ensure_ascii=False,
                    ),
                )
            ],
            usage=LLMUsage(prompt_tokens=10, completion_tokens=4, total_tokens=14),
        )

    async def generate_stream(self, *, request):
        del request
        self.stream_calls += 1

        async def _chunks():
            yield LLMStreamChunk(content="夜色渐深。")
            yield LLMStreamChunk(
                content="结尾。",
                finish_reason="stop",
                usage=LLMUsage(prompt_tokens=6, completion_tokens=2, total_tokens=8),
            )

        return _chunks()


def _chain_client(monkeypatch: pytest.MonkeyPatch, provider: Any):
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


async def _enqueue(
    sessions: Any,
    task_type: str,
    *,
    meta: dict[str, Any],
    novel_id: str | None = None,
) -> uuid.UUID:
    async with sessions.begin() as db:
        task_id = uuid.UUID(enqueue_task(db, task_type, meta=meta, novel_id=novel_id))
    return task_id


async def _cleanup(sessions: Any, task_ids: list[uuid.UUID]) -> None:
    ids = [item for item in task_ids if item is not None]
    if not ids:
        return
    async with sessions.begin() as db:
        await db.execute(delete(AsyncTask).where(AsyncTask.id.in_(ids)))


def _summary_prepared(novel_id: str) -> PreparedSummaryGeneration:
    return PreparedSummaryGeneration(
        novel_id=novel_id,
        journey_id=str(uuid.uuid4()),
        path_hash="a" * 64,
        node_ids=[],
        segment_node_ids=[],
        started_overview_epoch=0,
        messages=[LLMMessage(role="system", content="回顾前情")],
        executable_settings=dict(_SETTINGS),
    )


def _stub_summary_workflow(monkeypatch: pytest.MonkeyPatch, prepared: Any) -> None:
    async def stub_prepare(db, *, task):
        del db, task
        return prepared

    async def stub_finalize(*_args, **_kwargs):
        return {"status": "completed"}

    async def stub_mark_summary_failed(*_args, **_kwargs):
        return None

    async def stub_mark_summary_task_failed(*_args, **_kwargs):
        return None

    monkeypatch.setattr(
        interaction_tasks._workflow, "prepare_summary_task", stub_prepare
    )
    monkeypatch.setattr(
        interaction_tasks._workflow, "finalize_summary_task", stub_finalize
    )
    monkeypatch.setattr(
        interaction_tasks._workflow, "mark_summary_failed", stub_mark_summary_failed
    )
    monkeypatch.setattr(
        interaction_tasks._workflow,
        "mark_summary_task_failed",
        stub_mark_summary_task_failed,
    )


@pytest.mark.asyncio
async def test_summary_refresh_chain_builds_envelope_and_keeps_wire_clean(
    test_engine,
    monkeypatch,
) -> None:
    """真实 worker → interaction_summary_refresh → LLMClient 单入口建立信封。"""
    sessions = async_sessionmaker(test_engine, expire_on_commit=False, autoflush=False)
    novel_id = str(uuid.uuid4())
    provider = _JsonProvider(json.dumps(_SUMMARY_PAYLOAD, ensure_ascii=False))

    _stub_summary_workflow(monkeypatch, prepared=_summary_prepared(novel_id))
    monkeypatch.setattr(
        interaction_tasks,
        "create_project_snapshot_llm_client",
        lambda *args, **kwargs: _chain_client(monkeypatch, provider),
    )

    task_id = await _enqueue(
        sessions,
        "interaction_summary_refresh",
        meta={"novel_id": novel_id},
        novel_id=novel_id,
    )
    try:
        returned = await TaskWorker(
            db_manager=_TaskManager(test_engine, sessions),
            heartbeat_interval=60.0,
        ).run_once()

        assert returned is not None and returned.status == "done"
        assert provider.calls == 1
        async with sessions() as db:
            stored = await db.get(AsyncTask, task_id)
            assert stored is not None
            assert (stored.result or {}).get("status") == "completed"
            envelope = read_ai_run_envelope(stored.meta.get(AI_RUN_ENVELOPE_KEY))
            assert envelope is not None
            # 信封 run 身份是 task.id（W0-C 冻结：与领域 generation attempt 并存，
            # attempt.usage/agent_checkpoint_json 仍是领域权威，两者互不覆写）。
            assert envelope.run_id == str(task_id)
            assert envelope.operation_id == str(task_id)
            assert envelope.root_capability_id == "interaction.summary_refresh"
            assert envelope.request_limit == 8
            assert envelope.deadline_at is None
            assert envelope.requests_started == 1
            assert envelope.requests_settled == 1
            assert envelope.status.value == "succeeded"
            assert [step.step_name for step in envelope.steps] == [
                "interaction.summary.generate"
            ]
            assert (
                envelope.steps[0].step_capability_id == "interaction.summary_refresh"
            )
            # 公开 wire 干净：下划线私有键被状态 API 投影剥离。
            public_meta = _public_task_meta(stored.meta)
            assert AI_RUN_ENVELOPE_KEY not in public_meta
            assert not [key for key in public_meta if str(key).startswith("_")]
    finally:
        await _cleanup(sessions, [task_id])


@pytest.mark.asyncio
async def test_agent_story_declares_run_root_and_single_ledger(
    monkeypatch,
) -> None:
    """agent 路径：run_project_agent 收到 root capability，双账本不双扣。"""
    from infrastructure.llm.agent_runtime import AGENT_STEP_NAME
    from infrastructure.llm.workflow_budget import ai_run_scope

    novel_id = str(uuid.uuid4())
    prepared_summary = _summary_prepared(novel_id)
    prepared_story = PreparedStoryGeneration(
        novel_id=novel_id,
        journey_id=prepared_summary.journey_id,
        attempt_id=str(uuid.uuid4()),
        request_kind="message",
        messages=[LLMMessage(role="user", content="继续")],
        executable_settings=dict(_SETTINGS),
        existing_visible_text="",
    )

    summary_provider = _OutputToolProvider(_SUMMARY_PAYLOAD)
    story_provider = _StoryAgentProvider()

    async def fake_load(self):
        self.state = {}
        self.budget = interaction_agent_runtime.AgentRunBudget(mode="rp")
        self.references = {}

    budgets: list[interaction_agent_runtime.AgentRunBudget] = []

    async def fake_checkpoint(self, values=None):
        del values
        budgets.append(self.budget)

    monkeypatch.setattr(
        interaction_agent_runtime.InteractionAgentRun, "load", fake_load
    )
    monkeypatch.setattr(
        interaction_agent_runtime.InteractionAgentRun, "checkpoint", fake_checkpoint
    )
    # 快照 v1 无已验证原生联网：不注册 web 工具，保持链路确定性。
    monkeypatch.setattr(
        interaction_agent_runtime, "verified_native_search", lambda *_args: None
    )

    async def stub_finalize_summary(*_args, **_kwargs):
        return {"status": "completed"}

    async def stub_checkpoint_story(*_args, **_kwargs):
        return 0

    async def stub_finalize_story(*_args, **_kwargs):
        return {"status": "completed"}

    async def stub_govern(*_args, **_kwargs):
        return {"status": "passed", "text": "受审正文", "review": {}}

    async def stub_release(*_args, **_kwargs):
        return None

    async def stub_fail(*_args, **_kwargs):
        raise AssertionError("fail_story_task should not be called")

    prepare_calls = {"count": 0}

    async def stub_prepare_story(db, *, task):
        del db, task
        prepare_calls["count"] += 1
        if prepare_calls["count"] == 1:
            return prepared_summary
        return prepared_story

    monkeypatch.setattr(
        interaction_tasks._workflow, "prepare_story_task", stub_prepare_story
    )
    monkeypatch.setattr(
        interaction_tasks._workflow, "finalize_summary_task", stub_finalize_summary
    )
    monkeypatch.setattr(
        interaction_tasks._workflow, "checkpoint_story_task", stub_checkpoint_story
    )
    monkeypatch.setattr(
        interaction_tasks._workflow, "finalize_story_task", stub_finalize_story
    )
    monkeypatch.setattr(interaction_tasks._workflow, "govern_held_story", stub_govern)
    monkeypatch.setattr(interaction_tasks._workflow, "release_story_task", stub_release)
    monkeypatch.setattr(interaction_tasks._workflow, "fail_story_task", stub_fail)

    clients = iter(
        [
            _chain_client(monkeypatch, summary_provider),
            _chain_client(monkeypatch, story_provider),
        ]
    )
    monkeypatch.setattr(
        interaction_tasks,
        "create_project_snapshot_llm_client",
        lambda *args, **kwargs: next(clients),
    )

    captured: list[str | None] = []
    real_run = interaction_agent_runtime.run_project_agent

    async def spying_run(client, request, **kwargs):
        captured.append(kwargs.get("capability_id"))
        return await real_run(client, request, **kwargs)

    monkeypatch.setattr(interaction_tasks, "run_project_agent", spying_run)
    monkeypatch.setattr(interaction_agent_runtime, "run_project_agent", spying_run)

    task = SimpleNamespace(
        id=uuid.uuid4(),
        meta={
            "novel_id": novel_id,
            "journey_id": prepared_summary.journey_id,
            "attempt_id": prepared_story.attempt_id,
            "llm_execution_snapshot": {
                "agent_runtime": {"version": "1", "mode": "rp", "allow_web": True},
            },
        },
        progress=0.0,
        task_type=AGENT_STORY_TASK,
    )
    task.update_progress = lambda progress: setattr(task, "progress", progress)

    envelope = AIRunEnvelope(
        new_ai_run_envelope(
            operation_id=str(task.id),
            run_id=str(task.id),
            root_capability_id="interaction.story_generate",
            novel_id=novel_id,
            request_limit=29,
            deadline_at=datetime.now(UTC) + timedelta(seconds=1800),
        ).snapshot()
    )

    with ai_run_scope(envelope):
        result = await interaction_tasks.handle_interaction_story_generate(None, task)

    assert result == {"status": "completed"}
    # 两处 run_project_agent（紧急回顾 + 准备）都显式声明 run 的 root capability。
    assert captured == ["interaction.story_generate", "interaction.story_generate"]
    # 3 次真实 provider 请求：回顾 agent 1 + 准备 agent 1 + 正文流 1。
    assert summary_provider.calls == 1
    assert story_provider.generate_calls == 1
    assert story_provider.stream_calls == 1
    snapshot = envelope.snapshot()
    assert snapshot.requests_started == 3
    assert snapshot.requests_settled == 3
    assert {step.step_name for step in snapshot.steps} == {
        AGENT_STEP_NAME,
        "interaction.story.stream",
    }
    assert all(
        step.step_capability_id == "interaction.story_generate"
        for step in snapshot.steps
    )
    # 同一批 provider 请求在两个账本上各恰好计一次（future_requests 只参与
    # 额度校验，不计入 requests）：信封 3 == AgentRunBudget.requests 3。
    assert budgets, "agent checkpoints were never persisted"
    assert budgets[-1].requests == 3
    assert snapshot.requests_started == budgets[-1].requests


@pytest.mark.asyncio
async def test_exhausted_budget_rejects_provider_io_and_fails_closed(
    test_engine,
    monkeypatch,
) -> None:
    """恢复已耗尽的 run：首个请求在 provider I/O 前被拒，失败关闭不重排。"""
    sessions = async_sessionmaker(test_engine, expire_on_commit=False, autoflush=False)
    novel_id = str(uuid.uuid4())
    provider = _JsonProvider(json.dumps(_SUMMARY_PAYLOAD, ensure_ascii=False))
    _stub_summary_workflow(monkeypatch, prepared=_summary_prepared(novel_id))
    monkeypatch.setattr(
        interaction_tasks,
        "create_project_snapshot_llm_client",
        lambda *args, **kwargs: _chain_client(monkeypatch, provider),
    )

    task_id = await _enqueue(
        sessions,
        "interaction_summary_refresh",
        meta={"novel_id": novel_id},
        novel_id=novel_id,
    )
    # 预置一个已把 request_limit 用尽的持久化信封（上次 attempt 的收尾真相，
    # step 回执按账本校验规则覆盖已发出的请求）。
    from infrastructure.llm.schemas import AIStepCallKind, AIStepReceiptV1

    exhausted = new_ai_run_envelope(
        operation_id=str(task_id),
        run_id=str(task_id),
        root_capability_id="interaction.summary_refresh",
        novel_id=novel_id,
        request_limit=1,
    ).snapshot()
    exhausted = exhausted.model_copy(
        update={
            "requests_started": 1,
            "requests_settled": 1,
            "usage": LLMUsage(prompt_tokens=5, completion_tokens=5, total_tokens=10),
            "steps": [
                AIStepReceiptV1(
                    step_name="interaction.summary.generate",
                    step_capability_id="interaction.summary_refresh",
                    call_kind=AIStepCallKind.structured,
                    requests_started=1,
                    requests_settled=1,
                    usage=LLMUsage(
                        prompt_tokens=5, completion_tokens=5, total_tokens=10
                    ),
                )
            ],
        }
    )
    async with sessions.begin() as db:
        stored = await db.get(AsyncTask, task_id)
        stored.meta = {
            **dict(stored.meta or {}),
            AI_RUN_ENVELOPE_KEY: exhausted.model_dump(mode="json"),
        }
    try:
        returned = await TaskWorker(
            db_manager=_TaskManager(test_engine, sessions),
            heartbeat_interval=60.0,
        ).run_once()

        # 预算拒绝失败关闭：provider 0 调用，任务终态失败且不重排（max_attempts=2）。
        assert provider.calls == 0
        assert returned is not None and returned.status == "failed"
        assert returned.attempt == 1
        assert "AIRunBudgetExceededError" in (returned.error_message or "")
        async with sessions() as db:
            stored = await db.get(AsyncTask, task_id)
            envelope = read_ai_run_envelope(stored.meta.get(AI_RUN_ENVELOPE_KEY))
            assert envelope is not None
            assert envelope.status.value == "failed"
            assert envelope.requests_started == 1
    finally:
        await _cleanup(sessions, [task_id])
