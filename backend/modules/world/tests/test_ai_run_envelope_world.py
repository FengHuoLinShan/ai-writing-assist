"""W3-B：World/Map 业务通道的运行信封回归。

覆盖：真实 TaskWorker → world_map_schematic_generate handler → LLMClient 单入口
的私有信封与公开 wire、各 task type 的额度 resolver、图片通道的 reserve/settle
hook 与无信封行为不变、预算拒绝在真实 worker 下零 provider 调用失败关闭。
"""

from __future__ import annotations

import base64
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
    AIStepCallKind,
    LLMCallRequest,
    LLMCallResponse,
    LLMMessage,
    LLMUsage,
    read_ai_run_envelope,
)
from infrastructure.llm.workflow_budget import (
    AIManagedStepContext,
    AIRunBudgetExceededError,
    AIRunEnvelope,
    ai_run_scope,
    current_ai_run_envelope,
    managed_step_scope,
    new_ai_run_envelope,
)
from infrastructure.tasks.api import _public_task_meta
from infrastructure.tasks.enqueuer import enqueue_task
from infrastructure.tasks.models import AsyncTask
from infrastructure.tasks.registry import get_registry
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


# ---------------------------------------------------------------------------
# 真实链：TaskWorker → world_map_schematic_generate → LLMClient 单入口
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_world_map_schematic_chain_records_private_envelope(
    test_engine,
    monkeypatch,
) -> None:
    """声明 root 的任务在真实 worker 链上建立私有信封，公开 wire 保持干净。"""
    import modules.world.map_structure_workflow as map_workflow

    sessions = async_sessionmaker(test_engine, expire_on_commit=False, autoflush=False)
    novel_id = str(uuid.uuid4())
    node_id = str(uuid.uuid4())
    confirmation_id = str(uuid.uuid4())
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
        async def node(self, _db, _novel_id, _node_id, *, lock=False):
            del lock
            return SimpleNamespace(
                structure_task_id=task_holder.get("id"),
                novel_id=uuid.UUID(novel_id),
                id=uuid.UUID(node_id),
            )

        async def source(self, _db, _novel_id, ref):
            return ref

    task_holder: dict[str, uuid.UUID] = {}

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
        del novel_id, settings
        return _chain_client(monkeypatch, provider)

    monkeypatch.setattr(map_workflow, "MapStructureService", lambda: _StubService())
    monkeypatch.setattr(map_workflow, "prepare_confirmed_ai_action", stub_prepare)
    monkeypatch.setattr(map_workflow, "structure_inputs", stub_structure_inputs)
    monkeypatch.setattr(
        map_workflow,
        "restore_project_llm_execution_settings",
        stub_restore_settings,
    )
    monkeypatch.setattr(
        map_workflow,
        "create_project_snapshot_llm_client",
        fake_snapshot_client,
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
    task_id = await _enqueue(
        sessions, "world_map_schematic_generate", meta=meta, novel_id=novel_id
    )
    task_holder["id"] = task_id
    try:
        returned = await _run_once(test_engine, sessions)

        assert returned is not None and returned.status == "done"
        assert provider.calls == 1
        result = returned.result or {}
        assert result["summary"]["outcome"] == "complete"

        async with sessions() as db:
            stored = await db.get(AsyncTask, task_id)
            assert stored is not None
            # 私有信封只写 meta 下划线键：root、冻结额度、请求数都落在私有侧。
            envelope = read_ai_run_envelope(
                (stored.meta or {}).get(AI_RUN_ENVELOPE_KEY)
            )
            assert envelope is not None
            assert envelope.root_capability_id == "world.map_structure.generate"
            assert envelope.request_limit == 60
            assert envelope.requests_started == 1
            assert envelope.requests_settled == 1
            assert envelope.requests_unknown == 0
            assert envelope.status.value == "succeeded"
            assert envelope.charge_state.value == "recorded"
            assert [step.step_name for step in envelope.steps] == [
                "world.map_structure.generate.relations"
            ]
            assert (
                envelope.steps[0].step_capability_id
                == "world.map_structure.generate"
            )
            assert envelope.task is not None
            assert envelope.task.task_id == str(task_id)
            # 公开 wire：meta/result 投影剥离下划线私有键。
            assert "_ai_run_envelope" not in _public_task_meta(stored.meta)
            assert "_ai_run_envelope" not in (stored.result or {})
        assert current_ai_run_envelope() is None
    finally:
        await _cleanup(sessions, [task_id])


# ---------------------------------------------------------------------------
# 额度 resolver：从冻结输入计算 A
# ---------------------------------------------------------------------------


def _registry_limit(task_type: str, task: Any) -> int | None:
    import modules.world.tasks  # noqa: F401  确保生产 handler 已注册

    return get_registry().resolve_run_request_limit(task_type, task)


def _registry_deadline(task_type: str, task: Any) -> float | None:
    import modules.world.tasks  # noqa: F401

    return get_registry().resolve_run_deadline_seconds(task_type, task)


def test_world_validation_limit_uses_frozen_packet_plan() -> None:
    """P = min(planned_packets, max_packets)，A = 6P；deadline 覆盖两次 attempt。"""
    task = SimpleNamespace(
        meta={
            "_validation_plan": {
                "planned_packets": 300,
                "max_packets": 24,
                "per_packet_timeout_seconds": 120,
            }
        }
    )
    assert _registry_limit("world_validation", task) == 6 * 24
    assert _registry_deadline("world_validation", task) == 24 * 120 * 2 + 60


def test_world_validation_limit_falls_back_to_schema_ceiling() -> None:
    """旧在途任务没有冻结计划时按 schema 上界 P≤256 兜底；冻结 0 packet 时 A=1。"""
    task = SimpleNamespace(meta={"novel_id": "x"})
    assert _registry_limit("world_validation", task) == 6 * 256
    assert _registry_deadline("world_validation", task) == 256 * 180 * 2 + 60
    disabled = SimpleNamespace(
        meta={
            "_validation_plan": {
                "planned_packets": 0,
                "max_packets": 24,
                "per_packet_timeout_seconds": 120,
            }
        }
    )
    assert _registry_limit("world_validation", disabled) == 1
    assert _registry_deadline("world_validation", disabled) == 60


def test_world_validation_limit_rejects_out_of_schema_private_plan() -> None:
    task = SimpleNamespace(
        meta={
            "_validation_plan": {
                "planned_packets": 999_999,
                "max_packets": 999_999,
                "per_packet_timeout_seconds": 999_999,
            }
        }
    )
    assert _registry_limit("world_validation", task) == 1536
    assert _registry_deadline("world_validation", task) == 256 * 180 * 2 + 60


def test_world_entity_fusion_limit_scales_with_frozen_suggestions() -> None:
    """A = 12M + 6；M 夹在 schema 上界 200 内。"""
    assert (
        _registry_limit(
            "world_entity_fusion_suggestions",
            SimpleNamespace(meta={"max_suggestions": 200}),
        )
        == 12 * 200 + 6
    )
    assert _registry_limit(
        "world_entity_fusion_suggestions", SimpleNamespace(meta={})
    ) == 12 * 50 + 6
    assert (
        _registry_limit(
            "world_entity_fusion_suggestions",
            SimpleNamespace(meta={"max_suggestions": 10_000}),
        )
        == 12 * 200 + 6
    )


def test_world_cocreation_uses_one_parent_with_mode_specific_bounded_limits() -> None:
    registry = get_registry()
    assert registry.get_root_capability("world_cocreation_turn") == (
        "world.generation.cocreation"
    )
    assert (
        _registry_limit(
            "world_cocreation_turn",
            SimpleNamespace(meta={"mode": "chat", "quality_mode": "fast"}),
        )
        == 10
    )
    assert (
        _registry_limit(
            "world_cocreation_turn",
            SimpleNamespace(meta={"mode": "chat", "quality_mode": "pro"}),
        )
        == 14
    )
    assert (
        _registry_limit(
            "world_cocreation_turn",
            SimpleNamespace(meta={"mode": "design", "quality_mode": "fast"}),
        )
        == 24
    )
    assert (
        _registry_limit(
            "world_cocreation_turn",
            SimpleNamespace(meta={"mode": "design", "quality_mode": "pro"}),
        )
        == 66
    )
    assert _registry_deadline("world_cocreation_turn", SimpleNamespace(meta={})) is None


def test_world_alias_relation_task_uses_frozen_scene_scope() -> None:
    registry = get_registry()
    task = SimpleNamespace(meta={"scene_ids": [str(uuid.uuid4()) for _ in range(3)]})
    assert (
        registry.get_root_capability("world_alias_relation_extraction")
        == "world.alias_relations.extract"
    )
    assert registry.resolve_run_request_limit(
        "world_alias_relation_extraction", task
    ) == 18


def test_static_limits_are_declared_for_remaining_world_tasks() -> None:
    task = SimpleNamespace(meta={})
    assert _registry_limit("world_generation_suggestion", task) == 96
    assert _registry_deadline("world_generation_suggestion", task) == 3660.0
    assert _registry_limit("world_bible_synopsis_refresh", task) == 36
    # main/audit 各有 step timeout，但整条串行链及 auto-requeue 无总时限。
    assert _registry_deadline("world_bible_synopsis_refresh", task) is None
    assert _registry_limit("world_map_schematic_generate", task) == 60
    atlas_run_id = str(uuid.uuid4())
    atlas_task = SimpleNamespace(
        meta={"run_id": atlas_run_id, "run_request_limit": 111}
    )
    assert (
        get_registry().get_root_capability("map_atlas_generate")
        == "world.map_atlas.generate"
    )
    assert _registry_limit("map_atlas_generate", atlas_task) == 111
    assert get_registry().resolve_run_id("map_atlas_generate", atlas_task) == atlas_run_id
    assert _registry_deadline("world_map_schematic_generate", task) is None


# ---------------------------------------------------------------------------
# 图片通道：OpenAIImageClient 的 reserve/settle hook
# ---------------------------------------------------------------------------


class _FakeImages:
    def __init__(self, responses: list[Any]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    async def _next(self, kwargs: dict[str, Any]) -> Any:
        self.calls.append(kwargs)
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    async def generate(self, **kwargs):
        return await self._next(kwargs)

    async def edit(self, **kwargs):
        return await self._next(kwargs)


class _FakeSdk:
    def __init__(self, images: _FakeImages) -> None:
        self.images = images


def _image_response(*, usage: Any = None, request_id: str | None = "req_test_1"):
    payload = base64.b64encode(b"png-bytes").decode("ascii")
    return SimpleNamespace(
        data=[SimpleNamespace(b64_json=payload)],
        usage=usage,
        _request_id=request_id,
    )


def _image_envelope(request_limit: int = 5) -> AIRunEnvelope:
    run_id = str(uuid.uuid4())
    return new_ai_run_envelope(
        operation_id=run_id,
        run_id=run_id,
        root_capability_id="world.map_image.generate",
        novel_id=str(uuid.uuid4()),
        request_limit=request_limit,
    )


def _image_client(responses: list[Any]) -> Any:
    from infrastructure.llm.image_client import OpenAIImageClient

    client = OpenAIImageClient(api_key="unit-test-image-key")
    client._client = _FakeSdk(_FakeImages(responses))  # type: ignore[attr-defined]
    return client


@pytest.mark.asyncio
async def test_image_generate_reserves_and_settles_known_usage() -> None:
    envelope = _image_envelope()
    client = _image_client([_image_response(usage=_image_usage())])
    with ai_run_scope(envelope):
        generated = await client.generate(prompt="p", size="1024x1024", quality="high")
    assert generated.data == b"png-bytes"
    snapshot = envelope.snapshot()
    assert snapshot.requests_started == 1
    assert snapshot.requests_settled == 1
    assert snapshot.requests_unknown == 0
    assert snapshot.usage.total_tokens == 30
    assert snapshot.charge_state.value == "recorded"
    step = snapshot.steps[0]
    assert step.step_name == "world.map_image.render"
    assert step.step_capability_id == "world.map_image.generate"
    assert step.call_kind is AIStepCallKind.image_generate
    assert "request:req_test_1" in step.finish_reason


@pytest.mark.asyncio
async def test_image_edit_settles_with_image_edit_call_kind() -> None:
    envelope = _image_envelope()
    client = _image_client([_image_response(usage=None, request_id="req_edit_1")])
    with ai_run_scope(envelope):
        generated = await client.edit(
            prompt="p",
            images=[("ref.png", b"bytes", "image/png")],
            mask=None,
            size="1024x1024",
            quality="medium",
        )
    assert generated.data == b"png-bytes"
    step = envelope.snapshot().steps[0]
    assert step.call_kind is AIStepCallKind.image_edit
    assert step.requests_settled == 0
    assert step.requests_unknown == 1
    assert envelope.snapshot().charge_state.value == "possible"


def _image_usage() -> Any:
    return SimpleNamespace(input_tokens=10, output_tokens=20, total_tokens=30)


@pytest.mark.asyncio
async def test_image_request_rejected_before_io_when_budget_exhausted() -> None:
    envelope = _image_envelope(request_limit=0)
    client = _image_client([_image_response()])
    with ai_run_scope(envelope):
        with pytest.raises(AIRunBudgetExceededError):
            await client.generate(prompt="p", size="1024x1024", quality="high")
    assert client._client.images.calls == []  # type: ignore[attr-defined]
    assert envelope.snapshot().requests_started == 0
    assert envelope.snapshot().steps == []


@pytest.mark.asyncio
async def test_image_client_without_envelope_keeps_legacy_behavior() -> None:
    client = _image_client([_image_response()])
    generated = await client.generate(prompt="p", size="1024x1024", quality="high")
    assert generated.data == b"png-bytes"
    assert generated.request_id == "req_test_1"
    assert client._client.images.calls  # type: ignore[attr-defined]
    assert current_ai_run_envelope() is None


# ---------------------------------------------------------------------------
# 预算拒绝失败关闭：真实 worker 下零 provider 调用、任务 failed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_budget_rejection_fails_task_closed_with_zero_provider_calls(
    test_engine,
    monkeypatch,
) -> None:
    """恢复已耗尽额度的 run 后，reserve 在 provider I/O 前失败关闭。"""
    registry = get_registry()
    probe_type = "world_envelope_budget_probe"
    provider = _ChainProvider(['{"reply":"x"}'])
    captured: dict[str, Any] = {}

    async def probe_handler(db, task):
        from infrastructure.llm.agent_step_harness import run_managed_generate

        captured["client"] = _chain_client(monkeypatch, provider)
        return await run_managed_generate(
            captured["client"],
            LLMCallRequest(
                messages=[LLMMessage(role="user", content="预算探测")],
                max_tokens=8,
            ),
            step_name="world.envelope.probe.step",
            capability_id="world.generation.suggestion",
        )

    registry.register(
        probe_type,
        probe_handler,
        recovery_policy="auto_requeue",
        max_attempts=2,
        retry_transient_llm_errors=True,
        root_capability_id="world.generation.suggestion",
        run_request_limit=1,
    )
    sessions = async_sessionmaker(test_engine, expire_on_commit=False, autoflush=False)
    novel_id = str(uuid.uuid4())
    task_id = await _enqueue(
        sessions, probe_type, meta={"novel_id": novel_id}, novel_id=novel_id
    )
    try:
        # 预置一条已把额度用尽的 v1 信封：恢复后第一次 reserve 即被拒。
        async with sessions.begin() as db:
            row = await db.get(AsyncTask, task_id)
            assert row is not None
            ledger = new_ai_run_envelope(
                operation_id=str(task_id),
                run_id=str(task_id),
                root_capability_id="world.generation.suggestion",
                novel_id=novel_id,
                request_limit=1,
            )
            context = AIManagedStepContext(
                step_name="world.envelope.probe.step",
                call_kind=AIStepCallKind.generate,
                capability_id="world.generation.suggestion",
            )
            with managed_step_scope(context), ai_run_scope(ledger):
                reservation = await ledger.reserve()
                await ledger.settle(
                    reservation,
                    usage=LLMUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
                )
            row.meta = {
                **(row.meta or {}),
                AI_RUN_ENVELOPE_KEY: ledger.snapshot().model_dump(mode="json"),
            }

        returned = await _run_once(test_engine, sessions)

        assert returned is not None and returned.status == "failed"
        assert provider.calls == 0
        async with sessions() as db:
            stored = await db.get(AsyncTask, task_id)
            assert stored is not None
            envelope = read_ai_run_envelope(
                (stored.meta or {}).get(AI_RUN_ENVELOPE_KEY)
            )
            assert envelope is not None
            assert envelope.status.value == "failed"
            assert envelope.requests_started == 1
    finally:
        registry.unregister(probe_type)
        await _cleanup(sessions, [task_id])


def test_world_design_failure_receipt_reports_stage_usage_and_message():
    """P1-8/RB-3：失败回执公开脱敏的阶段进度、attempt 与信封用量。"""
    from datetime import UTC, datetime

    from infrastructure.llm.schemas import (
        AI_RUN_ENVELOPE_KEY,
        AIRunEnvelopeV1,
        AIStepReceiptV1,
        read_ai_run_envelope,
    )
    from modules.world.tasks import _world_design_failure_receipt

    started = datetime.now(UTC)
    envelope = AIRunEnvelopeV1(
        operation_id="op-1",
        run_id="run-1",
        root_capability_id="world.generation.cocreation",
        novel_id="novel-1",
        started_at=started,
        request_limit=66,
        requests_started=9,
        requests_settled=7,
        requests_unknown=2,
        usage=LLMUsage(prompt_tokens=60, completion_tokens=30, total_tokens=90),
        steps=[
            AIStepReceiptV1(
                step_name="world.generation.design_iteration",
                step_capability_id="world.generation.cocreation",
                call_kind=AIStepCallKind.structured,
                requests_started=9,
                requests_settled=7,
                requests_unknown=2,
                usage=LLMUsage(prompt_tokens=60, completion_tokens=30, total_tokens=90),
            )
        ],
    )
    # 通过 schema 校验器要求 step 账目自洽：直接用无 step 的聚合（校验允许 0 step）。
    task = SimpleNamespace(
        attempt=1,
        result={
            "_world_design_review_state": {
                "schema_version": "world_design_review_state.v1",
                "task_brief": {"goal": "x"},
                "generated_output": {"changes": {}},
            }
        },
        meta={AI_RUN_ENVELOPE_KEY: envelope.model_dump(mode="json")},
    )
    assert read_ai_run_envelope(task.meta[AI_RUN_ENVELOPE_KEY]) is not None

    receipt = _world_design_failure_receipt(
        task, RuntimeError("本轮推演未通过知识审查（已返修仍失败）")
    )
    assert receipt["schema_version"] == "world_design_review_failure.v1"
    assert receipt["attempt"] == 1
    assert receipt["error_kind"] == "RuntimeError"
    assert "知识审查" in receipt["message"]
    assert receipt["review_progress"] == ["task_brief", "generated_output"]
    assert receipt["requests_started"] == 9
    assert receipt["requests_settled"] == 7
    assert receipt["requests_unknown"] == 2
