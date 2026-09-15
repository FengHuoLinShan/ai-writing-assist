"""W3-A：Writing 域任务运行信封声明的回归。

覆盖三条线：
1. 生产注册的五个 writing task type 都显式声明 canonical root capability、
   冻结请求额度（L0）与有来源的 deadline；
2. 一条真实链：TaskWorker.run_once → writing_semantic_review handler →
   真实 LLMClient（provider 替身），断言任务 done、信封只写 meta 私有键、
   请求计数与该链预期一致、公开投影不含 `_ai_run_envelope`；
3. 信封自身的失败关闭：额度耗尽时 provider 零多余调用、任务 failed 不重排；
   声明 root 的任务在裸 client 调用路径上零 I/O 失败。
"""

from __future__ import annotations

import json
import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any
from unittest import mock

import pytest
from pydantic import BaseModel
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker

from infrastructure.llm.limits import reset_llm_limiter_for_tests
from infrastructure.llm.schemas import (
    LLMCallRequest,
    LLMCallResponse,
    LLMMessage,
    read_ai_run_envelope,
)
from infrastructure.tasks.api import _public_task_meta
from infrastructure.tasks.enqueuer import enqueue_task
from infrastructure.tasks.models import AsyncTask
from infrastructure.tasks.registry import TaskRegistry
from infrastructure.tasks.worker import TaskWorker


class _ChainProvider:
    """provider 传输层替身：按请求顺序返回 JSON 正文并计数。"""

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


async def _enqueue(
    sessions: Any,
    task_type: str,
    *,
    meta: dict[str, Any],
    novel_id: str | None,
) -> uuid.UUID:
    async with sessions.begin() as db:
        return uuid.UUID(
            enqueue_task(db, task_type, meta=meta, novel_id=novel_id)
        )


async def _cleanup(
    sessions: Any,
    task_ids: list[uuid.UUID | None],
    *,
    task_types: list[str] = (),
) -> None:
    ids = [item for item in task_ids if item is not None]
    async with sessions.begin() as db:
        if ids:
            await db.execute(delete(AsyncTask).where(AsyncTask.id.in_(ids)))
        if task_types:
            await db.execute(
                delete(AsyncTask).where(AsyncTask.task_type.in_(task_types))
            )


def _review_target(draft_id: str, content_hash: str) -> dict[str, Any]:
    return {
        "draft_id": draft_id,
        "chapter_index": 3,
        "title": "第三章",
        "content": "冻结正文",
        "content_hash": content_hash,
        "status": "candidate",
        "role": "target",
        "source_task_id": "generation-task",
        "scene_id": None,
        "scene_execution_bundle": None,
        "scene_execution_bundle_hash": None,
        "upstream_manifest": [],
        "review_context": {
            "status": "checked",
            "review_mode": "narrative_only",
            "context_fingerprint": "context-fingerprint",
            "confirmed_context": "已确认资料",
            "generation_profile": "default",
            "viewpoint_character_id": None,
            "pov_view": None,
            "deterministic_pov_validation": {
                "status": "passed",
                "findings": [],
                "warnings": [],
            },
            "knowledge_boundary_checked": True,
        },
    }


def _review_chunk_payload(draft_id: str) -> str:
    return json.dumps(
        {
            "findings": [],
            "not_checked": [],
            "coverage": [
                {
                    "draft_id": draft_id,
                    "scene_contract": "checked",
                    "timeline_location": "checked",
                    "identity_relation": "checked",
                    "ability_world_rule": "checked",
                    "knowledge_boundary": "checked",
                }
            ],
        },
        ensure_ascii=False,
    )


# ---------------------------------------------------------------------------
# 1. 声明冻结：root capability / L0 / deadline
# ---------------------------------------------------------------------------


def _production_registry_with_writing() -> TaskRegistry:
    import modules.writing.tasks  # noqa: F401  生产 handler 注册

    return TaskRegistry()


@pytest.mark.parametrize(
    ("task_type", "capability", "limit"),
    [
        ("writing_generate", "writing.generate", None),
        ("writing_semantic_review", "writing.semantic_review", 144),
        ("writing_targeted_revision", "writing.targeted_revision", 4),
        ("writing_conflict_ai_review", "writing.conflict_check.ai_review", 6),
        (
            "writing_conflict_item_ai_suggestion",
            "writing.conflict_check.ai_suggestion",
            6,
        ),
    ],
)
def test_writing_tasks_declare_canonical_root_and_frozen_limit(
    task_type: str, capability: str, limit: int | None
) -> None:
    registry = _production_registry_with_writing()
    assert registry.get_root_capability(task_type) == capability
    resolved = registry.resolve_run_request_limit(task_type, SimpleNamespace(meta={}))
    if limit is None:
        # writing_generate 按 K 动态计算，单独覆盖。
        assert resolved == 6 * 256 + 8
    else:
        assert resolved == limit


def test_writing_generate_resolver_reads_frozen_receipt() -> None:
    registry = _production_registry_with_writing()
    receipt_included = [{"source_key": f"src:{index}"} for index in range(129)]
    task_with_receipt = SimpleNamespace(
        meta={"knowledge_scope_receipt": {"included": receipt_included}}
    )
    # ⌈129/64⌉=3 → A = 6×3 + 8。
    assert registry.resolve_run_request_limit("writing_generate", task_with_receipt) == 26
    # 读不到 receipt 时回退保守上界，不再使用过渡计量额度。
    assert registry.resolve_run_request_limit(
        "writing_generate", SimpleNamespace(meta={})
    ) == 6 * 256 + 8


@pytest.mark.parametrize(
    ("task_type", "deadline"),
    [
        # generation/director/audit 与 targeted revision 只有单 step timeout；
        # 整条串行链及 auto-requeue 没有既有 run 总时限。
        ("writing_generate", None),
        # 主 Agent 裁决：逐 chunk 串行的总时长随章节数增长，静态 run deadline
        # 会发明比现状更紧的时间边界；每片的 step 1800s 仍是真实边界。
        ("writing_semantic_review", None),
        ("writing_targeted_revision", None),
        # 冲突链没有 step/阶段超时来源，不硬编码 run deadline（报告已标注）。
        ("writing_conflict_ai_review", None),
        ("writing_conflict_item_ai_suggestion", None),
    ],
)
def test_writing_tasks_declare_deadline_with_code_source(
    task_type: str, deadline: float | None
) -> None:
    registry = _production_registry_with_writing()
    resolved = registry.resolve_run_deadline_seconds(
        task_type, SimpleNamespace(meta={})
    )
    assert resolved == deadline


# ---------------------------------------------------------------------------
# 2. 真实链：worker → handler → 真实 LLMClient（provider 替身）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_writing_semantic_review_chain_builds_envelope_through_worker(
    test_engine,
    monkeypatch,
) -> None:
    """真实 worker → writing_semantic_review handler → LLMClient 单入口。"""
    import modules.project.facade as project_facade
    import modules.writing.tasks  # noqa: F401  生产 handler 注册
    from modules.writing.models import WritingDraft

    sessions = async_sessionmaker(test_engine, expire_on_commit=False, autoflush=False)
    novel_id = str(uuid.uuid4())
    content_hash = "a" * 64

    draft = WritingDraft(
        novel_id=uuid.UUID(novel_id),
        chapter_index=3,
        title="第三章",
        content="冻结正文",
        content_hash=content_hash,
        status="candidate",
        provenance_json={},
    )
    async with sessions.begin() as db:
        db.add(draft)
        await db.flush()
        persisted_draft_id = uuid.UUID(str(draft.id))

    provider = _ChainProvider([_review_chunk_payload(str(persisted_draft_id))])
    created_clients: list[Any] = []

    @asynccontextmanager
    async def fake_snapshot_client(db, novel_id_arg, snapshot, **_kwargs):
        del db, novel_id_arg, snapshot
        client = _chain_client(monkeypatch, provider)
        created_clients.append(client)
        yield client

    monkeypatch.setattr(project_facade, "require_active_project", _async_noop)
    monkeypatch.setattr(
        project_facade,
        "open_project_snapshot_llm_client",
        fake_snapshot_client,
    )

    import modules.writing.semantic_review as semantic_review_module

    target = _review_target(str(persisted_draft_id), content_hash)
    monkeypatch.setattr(
        semantic_review_module.WritingSemanticWorkflowService,
        "_freeze_review_set",
        _freeze_stub(target),
    )

    task_id = await _enqueue(
        sessions,
        "writing_semantic_review",
        meta={
            "novel_id": novel_id,
            "draft_ids": [str(persisted_draft_id)],
            "scope": "selection",
            "llm_execution_snapshot": {
                "profile": {"model": "deepseek-flash"},
                "llm": {"model": "deepseek-flash"},
            },
        },
        novel_id=novel_id,
    )
    try:
        returned = await _run_once(test_engine, sessions)

        assert returned is not None and returned.status == "done"
        assert provider.calls == 1
        async with sessions() as db:
            stored = await db.get(AsyncTask, task_id)
            assert stored is not None
            result = stored.result or {}
            assert result.get("verdict") == "pass"
            envelope = read_ai_run_envelope(
                (stored.meta or {}).get("_ai_run_envelope")
            )
            assert envelope is not None
            assert envelope.root_capability_id == "writing.semantic_review"
            assert envelope.requests_started == 1
            assert envelope.requests_settled == 1
            assert envelope.requests_unknown == 0
            assert envelope.request_limit == 144
            # 主 Agent 裁决：该任务不设 run 级 deadline（逐 chunk 串行总时长
            # 随章节数增长，不发明更紧边界）。
            assert envelope.deadline_at is None
            assert envelope.task is not None
            assert str(envelope.task.task_id) == str(task_id)
            # 信封是 meta 私有键：公开投影剥离，result 不写信封。
            assert "_ai_run_envelope" not in _public_task_meta(stored.meta)
            assert "_ai_run_envelope" not in (stored.result or {})
    finally:
        async with sessions.begin() as db:
            await db.execute(
                delete(WritingDraft).where(WritingDraft.id == persisted_draft_id)
            )
        await _cleanup(sessions, [task_id])


async def _async_noop(_db, *_args, **_kwargs) -> None:
    return None


def _freeze_stub(target: dict[str, Any]):
    return mock.AsyncMock(side_effect=[([target], []), ([target], [])])


# ---------------------------------------------------------------------------
# 3. 信封自身的失败关闭：预算耗尽与裸调用零 I/O
# ---------------------------------------------------------------------------


class _ProbeOutput(BaseModel):
    value: int = 1


def _register_probe(
    registry: TaskRegistry,
    task_type: str,
    handler,
    *,
    run_request_limit: int | None,
) -> None:
    registry.register(
        task_type,
        handler,
        recovery_policy="restart_origin",
        max_attempts=1,
        retry_transient_llm_errors=True,
        root_capability_id="writing.w3a_probe",
        run_request_limit=run_request_limit,
        run_deadline_seconds=1800.0,
    )


@pytest.mark.asyncio
async def test_budget_exhaustion_fails_closed_with_zero_extra_provider_calls(
    test_engine,
    monkeypatch,
) -> None:
    """额度耗尽：第二个请求在 provider I/O 前被拒，任务 failed 且不重排。"""
    registry = TaskRegistry()
    task_type = "w3a_writing_budget_probe"
    provider = _ChainProvider([_probe_payload(), _probe_payload()])

    async def handler(db, task):
        del db, task
        from infrastructure.llm.agent_step_harness import run_managed_structured

        client = _chain_client(monkeypatch, provider)
        request = _probe_request()
        await run_managed_structured(
            client, request, _ProbeOutput, step_name="probe.first", max_fix_attempts=0
        )
        await run_managed_structured(
            client, request, _ProbeOutput, step_name="probe.second", max_fix_attempts=0
        )
        return {"ok": True}

    _register_probe(registry, task_type, handler, run_request_limit=1)
    sessions = async_sessionmaker(test_engine, expire_on_commit=False, autoflush=False)
    novel_id = str(uuid.uuid4())
    task_id = await _enqueue(
        sessions, task_type, meta={"novel_id": novel_id}, novel_id=novel_id
    )
    try:
        returned = await _run_once(test_engine, sessions)

        assert returned is not None
        assert returned.status == "failed"
        assert int(returned.attempt or 0) == 1
        # 第 1 个请求真实发出；第 2 个在 I/O 前被预算拒绝。
        assert provider.calls == 1
        async with sessions() as db:
            stored = await db.get(AsyncTask, task_id)
            assert stored is not None
            envelope = read_ai_run_envelope(
                (stored.meta or {}).get("_ai_run_envelope")
            )
            assert envelope is not None
            assert envelope.requests_started == 1
            assert envelope.requests_settled == 1
            assert envelope.request_limit == 1
    finally:
        registry.unregister(task_type)
        await _cleanup(sessions, [task_id])


@pytest.mark.asyncio
async def test_bare_client_call_under_envelope_fails_closed_with_zero_io(
    test_engine,
    monkeypatch,
) -> None:
    """声明 root 的任务在无受管 step 的裸调用路径上必须零 I/O 失败关闭。"""
    registry = TaskRegistry()
    task_type = "w3a_writing_bare_call_probe"
    provider = _ChainProvider([_probe_payload()])

    async def handler(db, task):
        del db, task
        client = _chain_client(monkeypatch, provider)
        await client.generate(_probe_request())
        return {"ok": True}
    _register_probe(registry, task_type, handler, run_request_limit=8)
    sessions = async_sessionmaker(test_engine, expire_on_commit=False, autoflush=False)
    novel_id = str(uuid.uuid4())
    task_id = await _enqueue(
        sessions, task_type, meta={"novel_id": novel_id}, novel_id=novel_id
    )
    try:
        returned = await _run_once(test_engine, sessions)

        assert returned is not None
        assert returned.status == "failed"
        assert provider.calls == 0
        async with sessions() as db:
            stored = await db.get(AsyncTask, task_id)
            assert stored is not None
            envelope = read_ai_run_envelope(
                (stored.meta or {}).get("_ai_run_envelope")
            )
            assert envelope is not None
            assert envelope.requests_started == 0
            assert envelope.requests_settled == 0
            assert envelope.requests_unknown == 0
    finally:
        registry.unregister(task_type)
        await _cleanup(sessions, [task_id])


def _probe_payload() -> str:
    return json.dumps({"value": 1})


def _probe_request() -> LLMCallRequest:
    return LLMCallRequest(
        model="deepseek-flash",
        messages=[LLMMessage(role="user", content="probe")],
    )
