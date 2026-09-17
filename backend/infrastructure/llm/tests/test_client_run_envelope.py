"""文本 provider 单入口的运行信封计量：transport/structured/format/stream/research。"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from pydantic import BaseModel, Field

from infrastructure.llm.client import LLMClient
from infrastructure.llm.errors import (
    LLMConnectionError,
    LLMInvalidResponseError,
    LLMTimeoutError,
)
from infrastructure.llm.limits import reset_llm_limiter_for_tests
from infrastructure.llm.native_search import (
    NativeSearchUnavailableError,
    WebResearchResult,
)
from infrastructure.llm.retry import llm_transport_retry_scope
from infrastructure.llm.schemas import (
    AIChargeState,
    AIRequestOutcome,
    AIRunEnvelopeV1,
    AIStepCallKind,
    AIStepPurpose,
    LLMCallRequest,
    LLMCallResponse,
    LLMMessage,
    LLMStreamChunk,
    LLMUsage,
)
from infrastructure.llm.workflow_budget import (
    AIManagedStepContext,
    AIRunBudgetExceededError,
    AIRunDeadlineExceededError,
    AIRunEnvelope,
    ai_run_scope,
    current_ai_run_envelope,
    managed_step_scope,
)

_STARTED_AT = datetime(2026, 9, 15, 10, 0, tzinfo=UTC)
_SUCCESS_USAGE = LLMUsage(prompt_tokens=2, completion_tokens=3, total_tokens=5)


class _Payload(BaseModel):
    value: str = Field(..., min_length=1)


def _raw_envelope(**overrides) -> AIRunEnvelopeV1:
    options = {
        "operation_id": "op-1",
        "run_id": "run-1",
        "root_capability_id": "writing.generate",
        "novel_id": "novel-1",
        "started_at": _STARTED_AT,
        "request_limit": 10,
    }
    options.update(overrides)
    return AIRunEnvelopeV1(**options)


def _step(**overrides) -> AIManagedStepContext:
    options = {
        "step_name": "writing.generate.primary",
        "call_kind": AIStepCallKind.generate,
        "capability_id": "writing.generate",
        "profile_source": "project",
        "profile_summary": {"model": "fake-model", "provider_id": "fake"},
    }
    options.update(overrides)
    return AIManagedStepContext(**options)


def _retry_settings(*, max_attempts: int = 3) -> SimpleNamespace:
    return SimpleNamespace(
        llm_retry_max_attempts=max_attempts,
        llm_retry_base_delay=0.0,
        llm_retry_max_delay=0.0,
    )


def _client(provider, *, max_attempts: int = 3) -> LLMClient:
    client = LLMClient()
    client._provider = provider  # type: ignore[assignment]
    client._settings = _retry_settings(max_attempts=max_attempts)
    return client


def _request(*, content: str = "return json") -> LLMCallRequest:
    return LLMCallRequest(
        model="fake",
        messages=[LLMMessage(role="user", content=content)],
        max_tokens=20000,
    )


@pytest.fixture(autouse=True)
def _reset_process_limiter() -> None:
    reset_llm_limiter_for_tests()
    yield
    reset_llm_limiter_for_tests()


@pytest.fixture
def retry_waits(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """捕获退避等待，测试不真实 sleep。"""
    waits: list[float] = []

    async def capture_sleep(delay: float) -> None:
        waits.append(delay)

    monkeypatch.setattr("infrastructure.llm.retry.asyncio.sleep", capture_sleep)
    monkeypatch.setattr(
        "infrastructure.llm.retry.random.uniform",
        lambda _minimum, _maximum: 1.0,
    )
    return waits


class _TextProvider:
    """失败指定次数后成功的文本 provider 替身。"""

    name = "fake"

    def __init__(
        self,
        *,
        failures: int = 0,
        contents: list[str] | None = None,
    ) -> None:
        self._failures = failures
        self._contents = list(contents or ["ok"])
        self.requests: list[LLMCallRequest] = []

    async def generate(self, request: LLMCallRequest) -> LLMCallResponse:
        self.requests.append(request.model_copy(deep=True))
        if len(self.requests) <= self._failures:
            raise LLMTimeoutError("provider timed out", provider="fake", model="fake")
        content = self._contents[
            min(len(self.requests) - 1, len(self._contents) - 1)
        ]
        return LLMCallResponse(
            content=content,
            finish_reason="stop",
            usage=_SUCCESS_USAGE,
            model="fake",
            provider="fake",
        )


class _StreamProvider:
    """记录建流次数的 stream provider 替身。"""

    name = "fake"

    def __init__(
        self,
        chunks: list[LLMStreamChunk],
        *,
        error: Exception | None = None,
        open_failures: int = 0,
    ) -> None:
        self._chunks = chunks
        self._error = error
        self._open_failures = open_failures
        self.opens = 0

    async def generate_stream(
        self,
        request: LLMCallRequest,
    ) -> AsyncIterator[LLMStreamChunk]:
        self.opens += 1
        if self.opens <= self._open_failures:
            raise LLMTimeoutError("open timed out", provider="fake", model="fake")

        async def stream() -> AsyncIterator[LLMStreamChunk]:
            for chunk in self._chunks:
                yield chunk
            if self._error is not None:
                raise self._error

        return stream()


class _ResearchProvider:
    """按 attempt 次数调用 before_request 的 research 替身。"""

    name = "fake"

    def __init__(
        self,
        *,
        attempts: int,
        usage: LLMUsage | None,
        error: Exception | None = None,
    ) -> None:
        self._attempts = attempts
        self._usage = usage
        self._error = error
        self.questions: list[str] = []

    async def research(self, *, provider_id, model, question, before_request):
        self.questions.append(question)
        for _ in range(self._attempts):
            await before_request()
        if self._error is not None:
            raise self._error
        return WebResearchResult(
            answer="ok",
            sources=[],
            usage=self._usage,
            requests=self._attempts,
        )


def _research_client(provider) -> LLMClient:
    client = _client(provider)
    client._default_model = "deepseek-flash"
    client._profile_summary = {"provider_id": "deepseek", "model": "deepseek-flash"}
    return client


@pytest.fixture
def native_search_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "infrastructure.llm.native_search.verified_native_search",
        lambda _provider_id, _model: "test-protocol",
    )


@pytest.mark.asyncio
async def test_transport_retries_reserve_and_settle_every_attempt(
    retry_waits: list[float],
) -> None:
    provider = _TextProvider(failures=2)
    client = _client(provider, max_attempts=3)
    ledger = AIRunEnvelope(_raw_envelope(request_limit=6))

    with ai_run_scope(ledger), managed_step_scope(_step()):
        response = await client.generate(_request())

    snapshot = ledger.snapshot()
    assert response.content == "ok"
    assert len(provider.requests) == 3
    assert snapshot.requests_started == 3
    assert snapshot.requests_settled == 1
    assert snapshot.requests_unknown == 2
    assert snapshot.usage.total_tokens == _SUCCESS_USAGE.total_tokens
    assert snapshot.charge_state is AIChargeState.possible
    # 自动 transport retry 只累计同一 run，不扩大额度、不增加授权 revision。
    assert snapshot.request_limit == 6
    assert snapshot.authorization_revision == 0
    step = snapshot.steps[0]
    assert step.requests_started == 3
    assert step.transport_retries == 2
    assert step.usage.total_tokens == _SUCCESS_USAGE.total_tokens
    assert retry_waits == [1.0, 1.0]


@pytest.mark.asyncio
async def test_structured_with_transport_retries_disabled_is_still_metred() -> None:
    provider = _TextProvider(contents=['{"value": "direct"}'])
    client = _client(provider, max_attempts=3)
    ledger = AIRunEnvelope(_raw_envelope())

    with (
        ai_run_scope(ledger),
        managed_step_scope(_step(call_kind=AIStepCallKind.structured)),
        llm_transport_retry_scope(enabled=False),
    ):
        result = await client.generate_structured(
            _request(), _Payload, transport_retries=True
        )

    snapshot = ledger.snapshot()
    assert result.value == "direct"
    assert len(provider.requests) == 1
    assert snapshot.requests_started == 1
    assert snapshot.requests_settled == 1
    assert snapshot.requests_unknown == 0
    assert snapshot.charge_state is AIChargeState.recorded
    step = snapshot.steps[0]
    assert step.call_kind is AIStepCallKind.structured
    assert step.profile_hash
    assert step.profile_source == "project"


@pytest.mark.asyncio
async def test_schema_repair_request_is_counted_as_structured_retry() -> None:
    provider = _TextProvider(contents=['{"value": ""}', '{"value": "fixed"}'])
    client = _client(provider)
    ledger = AIRunEnvelope(_raw_envelope())

    with ai_run_scope(ledger), managed_step_scope(_step()):
        result = await client.generate_structured(
            _request(), _Payload, max_fix_attempts=1
        )

    snapshot = ledger.snapshot()
    assert result.value == "fixed"
    assert len(provider.requests) == 2
    assert snapshot.requests_started == 2
    assert snapshot.requests_settled == 2
    receipts = {
        (step.purpose, step.call_kind): step for step in snapshot.steps
    }
    primary = receipts[(AIStepPurpose.primary, AIStepCallKind.generate)]
    repair = receipts[(AIStepPurpose.schema_repair, AIStepCallKind.generate)]
    assert primary.requests_started == 1
    assert primary.structured_retries == 0
    assert repair.requests_started == 1
    assert repair.structured_retries == 1


@pytest.mark.asyncio
async def test_format_repair_request_is_counted_as_format_retry() -> None:
    provider = _TextProvider(contents=['{"value": ""}', '{"value": "fixed"}'])
    client = _client(provider)
    ledger = AIRunEnvelope(_raw_envelope())

    with ai_run_scope(ledger), managed_step_scope(_step()):
        result = await client.generate_structured(
            _request(),
            _Payload,
            max_fix_attempts=0,
            format_repair_attempts=1,
        )

    snapshot = ledger.snapshot()
    assert result.value == "fixed"
    assert len(provider.requests) == 2
    assert snapshot.requests_started == 2
    assert snapshot.requests_settled == 2
    purposes = {step.purpose for step in snapshot.steps}
    assert purposes == {AIStepPurpose.primary, AIStepPurpose.format_repair}
    repair = next(
        step
        for step in snapshot.steps
        if step.purpose is AIStepPurpose.format_repair
    )
    assert repair.requests_started == 1
    assert repair.format_retries == 1
    assert repair.call_kind is AIStepCallKind.generate


@pytest.mark.asyncio
async def test_stream_settles_recorded_after_final_usage() -> None:
    provider = _StreamProvider(
        [
            LLMStreamChunk(content="first"),
            LLMStreamChunk(
                content="",
                finish_reason="stop",
                usage=LLMUsage(prompt_tokens=4, completion_tokens=6, total_tokens=10),
            ),
        ]
    )
    client = _client(provider)
    ledger = AIRunEnvelope(_raw_envelope())

    with ai_run_scope(ledger), managed_step_scope(_step()):
        chunks = [
            chunk.content async for chunk in client.generate_stream(_request())
        ]

    snapshot = ledger.snapshot()
    assert chunks == ["first", ""]
    assert provider.opens == 1
    assert snapshot.requests_started == 1
    assert snapshot.requests_settled == 1
    assert snapshot.requests_unknown == 0
    assert snapshot.usage.total_tokens == 10
    assert snapshot.charge_state is AIChargeState.recorded
    step = snapshot.steps[0]
    assert step.call_kind is AIStepCallKind.stream
    assert step.finish_reason == "stop"


@pytest.mark.asyncio
async def test_cancelled_stream_records_unknown_without_replay() -> None:
    provider = _StreamProvider(
        [
            LLMStreamChunk(content="first"),
            LLMStreamChunk(
                content="second",
                usage=LLMUsage(prompt_tokens=4, completion_tokens=6, total_tokens=10),
            ),
        ]
    )
    client = _client(provider)
    ledger = AIRunEnvelope(_raw_envelope())

    with ai_run_scope(ledger), managed_step_scope(_step()):
        stream = client.generate_stream(_request())
        first = await stream.__anext__()
        assert first.content == "first"
        await stream.aclose()

    snapshot = ledger.snapshot()
    assert provider.opens == 1
    assert snapshot.requests_started == 1
    assert snapshot.requests_settled == 0
    assert snapshot.requests_unknown == 1
    assert snapshot.usage.total_tokens == 0
    assert snapshot.usage_complete is False
    assert snapshot.charge_state is AIChargeState.possible


@pytest.mark.asyncio
async def test_stream_error_after_first_chunk_records_unknown_without_replay() -> None:
    provider = _StreamProvider(
        [LLMStreamChunk(content="first")],
        error=LLMConnectionError("stream broken", provider="fake"),
    )
    client = _client(provider)
    ledger = AIRunEnvelope(_raw_envelope())

    with ai_run_scope(ledger), managed_step_scope(_step()):
        with pytest.raises(LLMConnectionError):
            async for _chunk in client.generate_stream(_request()):
                pass

    snapshot = ledger.snapshot()
    assert provider.opens == 1
    assert snapshot.requests_started == 1
    assert snapshot.requests_unknown == 1
    assert snapshot.requests_settled == 0
    assert snapshot.charge_state is AIChargeState.possible
    assert snapshot.steps[0].error_kind == "connection_error"


@pytest.mark.asyncio
async def test_stream_open_retry_is_metred_per_attempt(
    retry_waits: list[float],
) -> None:
    provider = _StreamProvider(
        [
            LLMStreamChunk(content="only"),
            LLMStreamChunk(
                content="",
                finish_reason="stop",
                usage=LLMUsage(prompt_tokens=4, completion_tokens=6, total_tokens=10),
            ),
        ],
        open_failures=1,
    )
    client = _client(provider)
    ledger = AIRunEnvelope(_raw_envelope())

    with ai_run_scope(ledger), managed_step_scope(_step()):
        chunks = [chunk.content async for chunk in client.generate_stream(_request())]

    snapshot = ledger.snapshot()
    assert chunks == ["only", ""]
    assert provider.opens == 2
    assert snapshot.requests_started == 2
    assert snapshot.requests_settled == 1
    assert snapshot.requests_unknown == 1
    assert snapshot.usage.total_tokens == 10
    assert snapshot.steps[0].transport_retries == 1
    assert retry_waits == [1.0]


@pytest.mark.asyncio
async def test_research_single_attempt_is_metred_as_research(
    native_search_enabled: None,
) -> None:
    provider = _ResearchProvider(attempts=1, usage=_SUCCESS_USAGE)
    client = _research_client(provider)
    ledger = AIRunEnvelope(_raw_envelope())
    legacy_reserves = 0

    async def before_request() -> None:
        nonlocal legacy_reserves
        legacy_reserves += 1

    with ai_run_scope(ledger), managed_step_scope(_step()):
        result = await client.research("水的沸点", before_request=before_request)

    snapshot = ledger.snapshot()
    assert legacy_reserves == 1
    assert result.answer == "ok"
    assert snapshot.requests_started == 1
    assert snapshot.requests_settled == 1
    assert snapshot.usage.total_tokens == _SUCCESS_USAGE.total_tokens
    step = snapshot.steps[0]
    assert step.call_kind is AIStepCallKind.research
    assert step.charge_state is AIChargeState.recorded


@pytest.mark.asyncio
async def test_research_multi_attempt_loop_counts_every_request(
    native_search_enabled: None,
) -> None:
    aggregate = LLMUsage(prompt_tokens=9, completion_tokens=11, total_tokens=20)
    provider = _ResearchProvider(attempts=3, usage=aggregate)
    client = _research_client(provider)
    ledger = AIRunEnvelope(_raw_envelope())
    legacy_reserves = 0

    async def before_request() -> None:
        nonlocal legacy_reserves
        legacy_reserves += 1

    with ai_run_scope(ledger), managed_step_scope(_step()):
        await client.research("水的沸点", before_request=before_request)

    snapshot = ledger.snapshot()
    assert legacy_reserves == 3
    assert snapshot.requests_started == 3
    assert snapshot.requests_settled == 1
    assert snapshot.requests_unknown == 2
    assert snapshot.usage.total_tokens == aggregate.total_tokens
    assert snapshot.usage_complete is False
    assert snapshot.charge_state is AIChargeState.possible
    assert snapshot.steps[0].call_kind is AIStepCallKind.research


@pytest.mark.asyncio
async def test_research_failure_settles_started_requests(
    native_search_enabled: None,
) -> None:
    provider = _ResearchProvider(
        attempts=1,
        usage=None,
        error=NativeSearchUnavailableError("供应商没有返回实际联网执行记录。"),
    )
    client = _research_client(provider)
    ledger = AIRunEnvelope(_raw_envelope())

    async def before_request() -> None:
        return None

    with ai_run_scope(ledger), managed_step_scope(_step()):
        with pytest.raises(NativeSearchUnavailableError):
            await client.research("水的沸点", before_request=before_request)

    snapshot = ledger.snapshot()
    assert snapshot.requests_started == 1
    assert snapshot.requests_unknown == 1
    assert snapshot.requests_settled == 0
    assert snapshot.charge_state is AIChargeState.possible


@pytest.mark.asyncio
async def test_research_failure_with_measured_usage_is_recorded(
    native_search_enabled: None,
) -> None:
    provider = _ResearchProvider(
        attempts=1,
        usage=None,
        error=NativeSearchUnavailableError(
            "没有可验证引用。",
            usage=_SUCCESS_USAGE,
            requests=1,
        ),
    )
    client = _research_client(provider)
    ledger = AIRunEnvelope(_raw_envelope())

    async def before_request() -> None:
        return None

    with ai_run_scope(ledger), managed_step_scope(_step()):
        with pytest.raises(NativeSearchUnavailableError):
            await client.research("水的沸点", before_request=before_request)

    snapshot = ledger.snapshot()
    assert snapshot.requests_started == 1
    assert snapshot.requests_settled == 1
    assert snapshot.requests_unknown == 0
    assert snapshot.usage.total_tokens == _SUCCESS_USAGE.total_tokens
    assert snapshot.recent_attempts[0].outcome is AIRequestOutcome.failed


@pytest.mark.asyncio
async def test_research_envelope_refusal_does_not_mutate_legacy_budget(
    native_search_enabled: None,
) -> None:
    provider = _ResearchProvider(attempts=1, usage=_SUCCESS_USAGE)
    client = _research_client(provider)
    ledger = AIRunEnvelope(_raw_envelope(request_limit=0))
    legacy_reserves = 0

    async def before_request() -> None:
        nonlocal legacy_reserves
        legacy_reserves += 1

    with ai_run_scope(ledger), managed_step_scope(_step()):
        with pytest.raises(AIRunBudgetExceededError):
            await client.research("水的沸点", before_request=before_request)

    assert legacy_reserves == 0
    assert ledger.snapshot().requests_started == 0


@pytest.mark.asyncio
async def test_research_legacy_refusal_discards_envelope_reservation(
    native_search_enabled: None,
) -> None:
    provider = _ResearchProvider(attempts=1, usage=_SUCCESS_USAGE)
    client = _research_client(provider)
    ledger = AIRunEnvelope(_raw_envelope())

    async def before_request() -> None:
        raise RuntimeError("legacy budget rejected")

    with ai_run_scope(ledger), managed_step_scope(_step()):
        with pytest.raises(RuntimeError, match="legacy budget rejected"):
            await client.research("水的沸点", before_request=before_request)

    snapshot = ledger.snapshot()
    assert snapshot.requests_started == 0
    assert snapshot.recent_attempts == []
    assert snapshot.steps == []


@pytest.mark.asyncio
async def test_expired_deadline_stops_transport_retry_without_sleeping(
    retry_waits: list[float],
) -> None:
    now = [_STARTED_AT]
    ledger = AIRunEnvelope(
        _raw_envelope(deadline_at=_STARTED_AT + timedelta(seconds=30)),
        clock=lambda: now[0],
    )

    class AdvancingProvider(_TextProvider):
        async def generate(self, request: LLMCallRequest) -> LLMCallResponse:
            now[0] = _STARTED_AT + timedelta(seconds=31)
            return await super().generate(request)

    provider = AdvancingProvider(failures=1)
    client = _client(provider, max_attempts=3)

    with ai_run_scope(ledger), managed_step_scope(_step()):
        with pytest.raises(LLMTimeoutError):
            await client.generate(_request())

    snapshot = ledger.snapshot()
    assert len(provider.requests) == 1
    assert retry_waits == []
    assert snapshot.requests_started == 1
    assert snapshot.requests_unknown == 1
    assert snapshot.steps[0].transport_retries == 0


@pytest.mark.asyncio
async def test_expired_deadline_rejects_before_any_counting() -> None:
    now = [_STARTED_AT + timedelta(seconds=31)]
    ledger = AIRunEnvelope(
        _raw_envelope(deadline_at=_STARTED_AT + timedelta(seconds=30)),
        clock=lambda: now[0],
    )
    provider = _TextProvider()
    client = _client(provider, max_attempts=3)

    with ai_run_scope(ledger), managed_step_scope(_step()):
        with pytest.raises(AIRunDeadlineExceededError):
            await client.generate(_request())

    snapshot = ledger.snapshot()
    assert provider.requests == []
    assert snapshot.requests_started == 0
    assert snapshot.steps == []
    assert snapshot.charge_state is AIChargeState.none


@pytest.mark.asyncio
async def test_exhausted_request_limit_rejects_before_provider_io() -> None:
    ledger = AIRunEnvelope(_raw_envelope(request_limit=0))
    provider = _TextProvider()
    client = _client(provider, max_attempts=3)

    with ai_run_scope(ledger), managed_step_scope(_step()):
        with pytest.raises(AIRunBudgetExceededError):
            await client.generate(_request())

    snapshot = ledger.snapshot()
    assert provider.requests == []
    assert snapshot.requests_started == 0
    assert snapshot.request_limit == 0


@pytest.mark.asyncio
async def test_project_scoped_client_without_envelope_keeps_previous_behavior(
    retry_waits: list[float],
) -> None:
    provider = _TextProvider(failures=2, contents=['{"value": "direct"}'])
    client = _client(provider, max_attempts=3)
    client.bind_runtime_scope(novel_id="novel-1", profile_source="project")

    assert current_ai_run_envelope() is None
    response = await client.generate(_request())
    structured = await client.generate_structured(_request(), _Payload)

    assert response.content == '{"value": "direct"}'
    assert structured.value == "direct"
    assert len(provider.requests) == 4
    assert retry_waits == [1.0, 1.0]


@pytest.mark.asyncio
async def test_structured_backoff_crossing_deadline_stops_without_next_request(
    retry_waits: list[float],
) -> None:
    """structured 退避跨过 deadline：不 sleep、不发下一次请求、保留原始错误类型。"""
    ledger = AIRunEnvelope(
        _raw_envelope(deadline_at=_STARTED_AT + timedelta(seconds=30)),
        clock=lambda: _STARTED_AT + timedelta(seconds=28),
    )
    provider = _TextProvider(contents=["not json at all"])
    client = _client(provider, max_attempts=3)
    client._settings = SimpleNamespace(
        llm_retry_max_attempts=3,
        llm_retry_base_delay=30.0,
        llm_retry_max_delay=30.0,
    )

    with ai_run_scope(ledger), managed_step_scope(_step()):
        with pytest.raises(LLMInvalidResponseError):
            await client.generate_structured(
                _request(),
                _Payload,
                max_fix_attempts=2,
                transport_retries=False,
            )

    snapshot = ledger.snapshot()
    # 一次真实 provider 请求，退避被 deadline 切断后不再发起修复请求。
    assert len(provider.requests) == 1
    assert retry_waits == []
    assert snapshot.requests_started == 1
    assert snapshot.requests_settled == 1
    assert snapshot.steps[0].structured_retries == 0


@pytest.mark.asyncio
async def test_format_repair_backoff_crossing_deadline_stops_without_next_request(
    retry_waits: list[float],
) -> None:
    """format repair 退避跨过 deadline：按既有失败契约收尾，不再发请求。"""
    ledger = AIRunEnvelope(
        _raw_envelope(deadline_at=_STARTED_AT + timedelta(seconds=30)),
        clock=lambda: _STARTED_AT + timedelta(seconds=28),
    )
    provider = _TextProvider(contents=["still not json", "bad again"])
    client = _client(provider, max_attempts=3)
    client._settings = SimpleNamespace(
        llm_retry_max_attempts=3,
        llm_retry_base_delay=30.0,
        llm_retry_max_delay=30.0,
    )

    with ai_run_scope(ledger), managed_step_scope(_step()):
        with pytest.raises(LLMInvalidResponseError):
            await client.generate_structured(
                _request(),
                _Payload,
                max_fix_attempts=0,
                format_repair_attempts=2,
                transport_retries=False,
            )

    snapshot = ledger.snapshot()
    assert len(provider.requests) == 2
    assert retry_waits == []
    assert snapshot.requests_started == 2
    assert snapshot.requests_settled == 2
    assert sum(step.format_retries for step in snapshot.steps) == 1


@pytest.mark.asyncio
async def test_envelope_refusal_keeps_compatible_budget_untouched() -> None:
    """信封在 provider I/O 前拒绝：兼容预算不得先增长。"""
    from infrastructure.llm.agent_runtime import AgentRunBudget
    from infrastructure.llm.workflow_budget import workflow_budget

    calls = 0

    class _CountingProvider(_TextProvider):
        async def generate(self, request: LLMCallRequest) -> LLMCallResponse:
            nonlocal calls
            calls += 1
            return await super().generate(request)

    provider = _CountingProvider()
    client = _client(provider)
    ledger = AIRunEnvelope(_raw_envelope(request_limit=0))
    budget = AgentRunBudget(mode="author")

    with (
        ai_run_scope(ledger),
        managed_step_scope(_step()),
        workflow_budget(budget, lambda _snapshot: asyncio.sleep(0)),
    ):
        with pytest.raises(AIRunBudgetExceededError):
            await client.generate(_request())

    assert calls == 0
    assert ledger.snapshot().requests_started == 0
    # 信封拒绝发生在兼容预算预留之前：不产生"已请求"的部分计数。
    assert budget.requests == 0
    assert budget.pending_usage == 0


@pytest.mark.asyncio
async def test_compatible_budget_refusal_discards_envelope_reservation() -> None:
    """兼容预算在信封之后拒绝：信封预留被撤销，两个账本都不计数。"""
    from infrastructure.llm.agent_runtime import AgentBudgetError, AgentRunBudget
    from infrastructure.llm.workflow_budget import workflow_budget

    calls = 0

    class _CountingProvider(_TextProvider):
        async def generate(self, request: LLMCallRequest) -> LLMCallResponse:
            nonlocal calls
            calls += 1
            return await super().generate(request)

    provider = _CountingProvider()
    client = _client(provider)
    ledger = AIRunEnvelope(_raw_envelope(request_limit=10))
    budget = AgentRunBudget(mode="author", requests=12)

    with (
        ai_run_scope(ledger),
        managed_step_scope(_step()),
        workflow_budget(budget, lambda _snapshot: asyncio.sleep(0)),
    ):
        with pytest.raises(AgentBudgetError):
            await client.generate(_request())

    assert calls == 0
    assert ledger.snapshot().requests_started == 0
    assert ledger.snapshot().recent_attempts == []
    assert budget.requests == 12
    assert budget.pending_usage == 0


@pytest.mark.asyncio
async def test_successful_request_counts_once_on_both_ledgers() -> None:
    """成功请求在信封与兼容预算上各恰好计一次。"""
    from infrastructure.llm.agent_runtime import AgentRunBudget
    from infrastructure.llm.workflow_budget import workflow_budget

    provider = _TextProvider()
    client = _client(provider)
    ledger = AIRunEnvelope(_raw_envelope(request_limit=10))
    budget = AgentRunBudget(mode="author")

    with (
        ai_run_scope(ledger),
        managed_step_scope(_step()),
        workflow_budget(budget, lambda _snapshot: asyncio.sleep(0)),
    ):
        await client.generate(_request())

    snapshot = ledger.snapshot()
    assert provider.requests
    assert snapshot.requests_started == 1
    assert snapshot.requests_settled == 1
    assert snapshot.requests_unknown == 0
    assert budget.requests == 1
    assert budget.pending_usage == 0
    assert budget.usage_unknown is False


@pytest.mark.asyncio
async def test_token_limit_refuses_new_requests_after_settled_usage() -> None:
    """P1-3：累计 token 上限按已结算用量闸断新请求；显式续算可提高。"""
    from infrastructure.llm.schemas import AIRunAuthorizationReason

    provider = _TextProvider()
    client = _client(provider, max_attempts=1)
    ledger = AIRunEnvelope(_raw_envelope(request_limit=6, token_limit=5))

    with ai_run_scope(ledger), managed_step_scope(_step()):
        await client.generate(_request())
        with pytest.raises(AIRunBudgetExceededError, match="token limit"):
            await client.generate(_request())

    snapshot = ledger.snapshot()
    assert snapshot.requests_started == 1
    assert snapshot.usage.total_tokens == _SUCCESS_USAGE.total_tokens

    await ledger.authorize_additional_requests(
        3,
        reason=AIRunAuthorizationReason.author_resume,
        additional_tokens=100,
    )
    snapshot = ledger.snapshot()
    assert snapshot.token_limit == 105
    assert snapshot.authorizations[-1].additional_tokens == 100


@pytest.mark.asyncio
async def test_provider_call_is_clipped_by_remaining_run_deadline() -> None:
    """P1-3：deadline 前一刻发出的在途请求不得运行完整 provider timeout。"""

    class SlowProvider(_TextProvider):
        async def generate(self, request: LLMCallRequest) -> LLMCallResponse:
            await asyncio.sleep(2.0)
            return await super().generate(request)

    provider = SlowProvider()
    provider._timeout = 120
    client = _client(provider, max_attempts=1)
    deadline = datetime.now(UTC) + timedelta(seconds=0.2)
    ledger = AIRunEnvelope(_raw_envelope(request_limit=6, deadline_at=deadline))

    started = asyncio.get_running_loop().time()
    with (
        ai_run_scope(ledger),
        managed_step_scope(_step()),
        pytest.raises(asyncio.TimeoutError),
    ):
        await client.generate(_request(), transport_retries=False)
    elapsed = asyncio.get_running_loop().time() - started

    assert elapsed < 1.5
    snapshot = ledger.snapshot()
    assert snapshot.requests_started == 1
    assert snapshot.requests_unknown == 1


@pytest.mark.asyncio
async def test_remote_embedding_is_metred_by_the_run_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """P1-5：远程 embedding 与文本请求共用同一信封（用量未知按 possible 落账）。"""

    class EmbeddingProvider(_TextProvider):
        _timeout = 30

        async def generate_embedding(self, text, model=None):  # noqa: ANN001
            self.requests.append(text)  # type: ignore[arg-type]
            return [[0.1, 0.2] for _ in (text if isinstance(text, list) else [text])]

    provider = EmbeddingProvider()
    client = _client(provider, max_attempts=1)
    monkeypatch.setattr(
        "infrastructure.llm.client.get_settings",
        lambda: SimpleNamespace(embedding_provider="openai"),
    )
    ledger = AIRunEnvelope(_raw_envelope(request_limit=6))

    with ai_run_scope(ledger):
        vectors = await client.generate_embedding(["一段文本", "另一段文本"])

    assert vectors == [[0.1, 0.2], [0.1, 0.2]]
    snapshot = ledger.snapshot()
    assert snapshot.requests_started == 1
    assert snapshot.requests_settled == 0
    assert snapshot.requests_unknown == 1
    assert snapshot.charge_state is AIChargeState.possible
    assert snapshot.steps[0].step_capability_id == "infrastructure.embedding"
