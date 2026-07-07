"""LLM client structured-output behavior tests."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from types import MethodType, SimpleNamespace

import pytest
from pydantic import BaseModel, Field

from infrastructure.llm.client import LLMClient
from infrastructure.llm.errors import LLMInvalidResponseError, LLMTimeoutError
from infrastructure.llm.limits import (
    LLMCircuitBreakerOpenError,
    get_llm_limiter,
    reset_llm_limiter_for_tests,
)
from infrastructure.llm.profiles import resolve_llm_profile
from infrastructure.llm.schemas import (
    LLMCallRequest,
    LLMCallResponse,
    LLMMessage,
    LLMStreamChunk,
    LLMUsage,
)


def _retry_settings(
    *,
    base_delay: float,
    max_delay: float,
) -> SimpleNamespace:
    return SimpleNamespace(
        llm_retry_max_attempts=1,
        llm_retry_base_delay=base_delay,
        llm_retry_max_delay=max_delay,
    )


class _StructuredPayload(BaseModel):
    value: str = Field(..., min_length=1)


class _StructuredItemsPayload(BaseModel):
    items: list[_StructuredPayload]


class _StructuredScenesPayload(BaseModel):
    scenes: list[_StructuredPayload]
    notes: list[str] = []


class _FakeEnvSettings:
    llm_api_key = "sk-env"
    llm_base_url = "https://env.example/v1"
    llm_model = "env-model"
    llm_timeout = 70
    llm_max_tokens = 1234


def _limit_settings(
    *,
    max_concurrent_requests: int = 8,
    rate_limit_per_minute: int = 0,
    failure_threshold: int = 5,
    reset_seconds: float = 60.0,
) -> SimpleNamespace:
    return SimpleNamespace(
        llm_max_concurrent_requests=max_concurrent_requests,
        llm_rate_limit_per_minute=rate_limit_per_minute,
        llm_circuit_breaker_failure_threshold=failure_threshold,
        llm_circuit_breaker_reset_seconds=reset_seconds,
    )


@pytest.fixture(autouse=True)
def _reset_process_limiter() -> None:
    reset_llm_limiter_for_tests()
    yield
    reset_llm_limiter_for_tests()


def test_resolve_llm_profile_uses_deepseek_code_defaults_without_env(monkeypatch) -> None:
    for name in (
        "LLM_API_KEY",
        "LLM_BASE_URL",
        "LLM_MODEL",
        "LLM_TIMEOUT",
        "LLM_MAX_TOKENS",
    ):
        monkeypatch.delenv(name, raising=False)

    profile = resolve_llm_profile(env_settings=_FakeEnvSettings())

    assert profile.provider_id == "deepseek"
    assert profile.base_url == "https://api.deepseek.com"
    assert profile.model == "deepseek-v4-flash"
    assert profile.timeout == 180
    assert profile.max_tokens == 4096
    assert profile.sources["model"] == "default"
    assert profile.sources["timeout"] == "default"


def test_resolve_llm_profile_ignores_legacy_env_when_configured(monkeypatch) -> None:
    monkeypatch.setenv("LLM_API_KEY", "set")
    monkeypatch.setenv("LLM_BASE_URL", "set")
    monkeypatch.setenv("LLM_MODEL", "set")
    monkeypatch.setenv("LLM_TIMEOUT", "set")
    monkeypatch.setenv("LLM_MAX_TOKENS", "set")

    profile = resolve_llm_profile(env_settings=_FakeEnvSettings())

    assert profile.api_key == ""
    assert profile.base_url == "https://api.deepseek.com"
    assert profile.model == "deepseek-v4-flash"
    assert profile.timeout == 180
    assert profile.max_tokens == 4096
    assert profile.sources["api_key"] == "default"
    assert profile.sources["base_url"] == "default"


def test_resolve_llm_profile_test_override_sits_between_project_and_default(
    monkeypatch,
) -> None:
    monkeypatch.setenv("LLM_MODEL", "set")
    monkeypatch.setenv("LLM_TIMEOUT", "set")

    profile = resolve_llm_profile(
        {
            "llm": {
                "provider_id": "openai-compatible",
                "base_url": "https://project.example/v1",
                "model": "project-model",
                "timeout": 180,
            }
        },
        env_settings=_FakeEnvSettings(),
        test_overrides={"LLM_MODEL": "override-model", "LLM_TIMEOUT": 90},
    )

    assert profile.model == "project-model"
    assert profile.timeout == 180
    assert profile.base_url == "https://project.example/v1"
    assert profile.sources["model"] == "project"
    assert profile.sources["timeout"] == "project"

    profile_without_project = resolve_llm_profile(
        {},
        env_settings=_FakeEnvSettings(),
        test_overrides={"LLM_MODEL": "override-model", "LLM_TIMEOUT": 90},
    )
    assert profile_without_project.model == "override-model"
    assert profile_without_project.timeout == 90
    assert profile_without_project.sources["model"] == "test_override"


def test_resolve_llm_profile_invalid_overrides_fall_back(monkeypatch) -> None:
    monkeypatch.setenv("LLM_TIMEOUT", "set")
    monkeypatch.setenv("LLM_MAX_TOKENS", "set")

    class BadEnvSettings:
        llm_api_key = ""
        llm_base_url = ""
        llm_model = ""
        llm_timeout = "bad"
        llm_max_tokens = 0

    profile = resolve_llm_profile(
        env_settings=BadEnvSettings(),
        test_overrides={"LLM_TIMEOUT": "bad", "LLM_MAX_TOKENS": 0},
    )

    assert profile.timeout == 180
    assert profile.max_tokens == 4096
    assert profile.sources["timeout"] == "default"
    assert profile.sources["max_tokens"] == "default"


def test_resolve_llm_profile_sanitized_summary_redacts_api_key() -> None:
    profile = resolve_llm_profile(
        {
            "llm": {
                "provider_id": "openai-compatible",
                "label": "Open CodeGo",
                "api_key": "sk-secret",
                "base_url": "https://opencode.ai/zen/go/v1",
                "model": "deepseek-v4-flash",
                "timeout": 180,
                "max_tokens": 8192,
            }
        },
        env_settings=_FakeEnvSettings(),
    )

    summary = profile.sanitized_summary()

    assert summary["provider_id"] == "openai-compatible"
    assert summary["base_url_host"] == "opencode.ai"
    assert summary["api_key_configured"] is True
    assert "sk-secret" not in json.dumps(summary)


def test_from_project_settings_uses_project_profile_defaults() -> None:
    client = LLMClient.from_project_settings(
        {
            "llm": {
                "api_key": "sk-test",
                "base_url": "https://api.deepseek.com/v1",
                "model": "deepseek-chat",
                "timeout": 180,
            }
        }
    )

    assert client.model_name == "deepseek-chat"
    assert getattr(client._provider, "_timeout") == 180


@pytest.mark.asyncio
async def test_generate_embedding_bge_error_does_not_call_remote_provider(
    monkeypatch,
) -> None:
    client = LLMClient()
    client._settings = _retry_settings(base_delay=0.0, max_delay=0.0)
    remote_calls = 0

    class RemoteProvider:
        name = "remote"

        async def generate_embedding(
            self,
            text: str | list[str],
            model: str | None = None,
        ) -> list[float]:
            nonlocal remote_calls
            remote_calls += 1
            return [0.1, 0.2]

    class FailingBgeClient:
        async def generate_embedding(
            self,
            text: str | list[str],
            *,
            is_query: bool = False,
        ) -> list[float] | list[list[float]]:
            raise RuntimeError("bge down")

    async def fake_get_instance() -> FailingBgeClient:
        return FailingBgeClient()

    monkeypatch.setattr(
        "infrastructure.llm.client.get_settings",
        lambda: SimpleNamespace(embedding_provider="bge_onnx"),
    )
    monkeypatch.setattr(
        "infrastructure.embedding.client.BgeEmbeddingClient.get_instance",
        staticmethod(fake_get_instance),
    )
    client._provider = RemoteProvider()  # type: ignore[assignment]

    with pytest.raises(RuntimeError, match="bge down"):
        await client.generate_embedding("测试文本")

    assert remote_calls == 0


@pytest.mark.asyncio
async def test_generate_uses_process_concurrency_limiter(monkeypatch) -> None:
    monkeypatch.setattr(
        "infrastructure.llm.limits.get_settings",
        lambda: _limit_settings(max_concurrent_requests=1),
    )
    client = LLMClient()
    active = 0
    max_active = 0
    release_first = asyncio.Event()
    first_started = asyncio.Event()

    class FakeProvider:
        name = "fake"

        async def generate(self, request: LLMCallRequest) -> LLMCallResponse:
            nonlocal active, max_active
            active += 1
            max_active = max(max_active, active)
            if not first_started.is_set():
                first_started.set()
                await release_first.wait()
            active -= 1
            return LLMCallResponse(content="ok", model="fake", provider="fake")

    client._provider = FakeProvider()  # type: ignore[assignment]

    first = asyncio.create_task(client.generate(LLMCallRequest(model="fake")))
    await first_started.wait()
    second = asyncio.create_task(client.generate(LLMCallRequest(model="fake")))
    await asyncio.sleep(0)

    assert max_active == 1
    release_first.set()
    await asyncio.gather(first, second)
    assert max_active == 1


@pytest.mark.asyncio
async def test_limiter_breaker_counts_only_after_retry_exhaustion(monkeypatch) -> None:
    monkeypatch.setattr(
        "infrastructure.llm.limits.get_settings",
        lambda: _limit_settings(failure_threshold=1, reset_seconds=30.0),
    )
    client = LLMClient()
    client._settings = SimpleNamespace(
        llm_retry_max_attempts=2,
        llm_retry_base_delay=0.0,
        llm_retry_max_delay=0.0,
    )
    calls = 0

    class FakeProvider:
        name = "fake"

        async def generate(self, request: LLMCallRequest) -> LLMCallResponse:
            nonlocal calls
            calls += 1
            raise LLMTimeoutError("timeout without prompt or secret", provider="fake")

    client._provider = FakeProvider()  # type: ignore[assignment]

    with pytest.raises(LLMTimeoutError):
        await client.generate(
            LLMCallRequest(
                model="fake",
                messages=[LLMMessage(role="user", content="raw prompt")],
            )
        )

    assert calls == 2

    with pytest.raises(LLMCircuitBreakerOpenError) as exc_info:
        await client.generate(
            LLMCallRequest(
                model="fake",
                messages=[LLMMessage(role="user", content="raw prompt")],
            )
        )

    assert calls == 2
    assert "raw prompt" not in str(exc_info.value)
    assert "Authorization" not in str(exc_info.value)


@pytest.mark.asyncio
async def test_generate_stream_holds_limiter_until_stream_consumed(monkeypatch) -> None:
    monkeypatch.setattr(
        "infrastructure.llm.limits.get_settings",
        lambda: _limit_settings(max_concurrent_requests=1),
    )
    client = LLMClient()
    active_streams = 0
    max_active_streams = 0
    first_chunk_ready = asyncio.Event()
    release_first_stream = asyncio.Event()

    class FakeProvider:
        name = "fake"

        async def generate_stream(
            self,
            request: LLMCallRequest,
        ) -> AsyncIterator[LLMStreamChunk]:
            async def stream() -> AsyncIterator[LLMStreamChunk]:
                nonlocal active_streams, max_active_streams
                active_streams += 1
                max_active_streams = max(max_active_streams, active_streams)
                first_chunk_ready.set()
                yield LLMStreamChunk(content="first")
                await release_first_stream.wait()
                active_streams -= 1

            return stream()

    client._provider = FakeProvider()  # type: ignore[assignment]

    async def consume() -> list[str]:
        return [
            chunk.content
            async for chunk in client.generate_stream(LLMCallRequest(model="fake"))
        ]

    first = asyncio.create_task(consume())
    await first_chunk_ready.wait()
    second = asyncio.create_task(consume())
    await asyncio.sleep(0)

    assert max_active_streams == 1
    release_first_stream.set()
    await asyncio.gather(first, second)
    assert max_active_streams == 1


@pytest.mark.asyncio
async def test_generate_structured_retries_truncated_json_with_larger_budget() -> None:
    client = LLMClient()
    requests: list[LLMCallRequest] = []

    async def fake_generate(self: LLMClient, request: LLMCallRequest) -> LLMCallResponse:
        requests.append(request.model_copy(deep=True))
        if len(requests) == 1:
            return LLMCallResponse(
                content='{"value": "unfinished',
                finish_reason="length",
                usage=LLMUsage(completion_tokens=20000, total_tokens=20000),
                model="fake",
                provider="fake",
            )
        return LLMCallResponse(
            content='{"value": "complete"}',
            finish_reason="stop",
            usage=LLMUsage(completion_tokens=8, total_tokens=8),
            model="fake",
            provider="fake",
        )

    client.generate = MethodType(fake_generate, client)  # type: ignore[method-assign]

    result = await client.generate_structured(
        LLMCallRequest(
            model="fake",
            messages=[LLMMessage(role="user", content="return json")],
            max_tokens=20000,
        ),
        _StructuredPayload,
    )

    assert result.value == "complete"
    assert len(requests) == 2
    assert requests[1].max_tokens == 40000
    assert requests[1].messages[-1].role == "user"
    assert "上一轮输出被截断" in requests[1].messages[-1].content
    assert "从头重新输出完整 JSON" in requests[1].messages[-1].content


@pytest.mark.asyncio
async def test_generate_structured_validation_retry_keeps_existing_fix_path() -> None:
    client = LLMClient()
    requests: list[LLMCallRequest] = []

    async def fake_generate(self: LLMClient, request: LLMCallRequest) -> LLMCallResponse:
        requests.append(request.model_copy(deep=True))
        if len(requests) == 1:
            return LLMCallResponse(
                content='{"value": ""}',
                finish_reason="stop",
                usage=LLMUsage(completion_tokens=5, total_tokens=5),
                model="fake",
                provider="fake",
            )
        return LLMCallResponse(
            content='{"value": "valid"}',
            finish_reason="stop",
            usage=LLMUsage(completion_tokens=5, total_tokens=5),
            model="fake",
            provider="fake",
        )

    client.generate = MethodType(fake_generate, client)  # type: ignore[method-assign]

    result = await client.generate_structured(
        LLMCallRequest(
            model="fake",
            messages=[LLMMessage(role="user", content="return json")],
            max_tokens=20000,
        ),
        _StructuredPayload,
    )

    assert result.value == "valid"
    assert len(requests) == 2
    assert requests[1].max_tokens == 20000
    assert "Your previous response failed validation" in requests[1].messages[-1].content


@pytest.mark.asyncio
async def test_generate_structured_validation_retry_uses_backoff(monkeypatch) -> None:
    client = LLMClient()
    client._settings = _retry_settings(base_delay=0.25, max_delay=1.0)
    delays: list[float] = []

    async def fake_sleep(delay: float) -> None:
        delays.append(delay)

    async def fake_generate(self: LLMClient, request: LLMCallRequest) -> LLMCallResponse:
        return LLMCallResponse(
            content='{"value": ""}',
            finish_reason="stop",
            usage=LLMUsage(completion_tokens=5, total_tokens=5),
            model="fake",
            provider="fake",
        )

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    client.generate = MethodType(fake_generate, client)  # type: ignore[method-assign]

    with pytest.raises(LLMInvalidResponseError):
        await client.generate_structured(
            LLMCallRequest(model="fake", messages=[]),
            _StructuredPayload,
            max_fix_attempts=2,
        )

    assert delays == [0.25, 0.5]


@pytest.mark.asyncio
async def test_generate_structured_final_error_keeps_last_validation_detail() -> None:
    client = LLMClient()

    async def fake_generate(self: LLMClient, request: LLMCallRequest) -> LLMCallResponse:
        return LLMCallResponse(
            content='{"value": ""}',
            finish_reason="stop",
            usage=LLMUsage(completion_tokens=5, total_tokens=5),
            model="fake",
            provider="fake",
        )

    client.generate = MethodType(fake_generate, client)  # type: ignore[method-assign]

    with pytest.raises(LLMInvalidResponseError) as exc_info:
        await client.generate_structured(
            LLMCallRequest(
                model="fake",
                messages=[LLMMessage(role="user", content="return json")],
                max_tokens=20000,
            ),
            _StructuredPayload,
            max_fix_attempts=0,
        )

    assert "String should have at least 1 character" in str(exc_info.value)
    assert exc_info.value.raw_response == '{"value": ""}'


@pytest.mark.asyncio
async def test_generate_structured_can_bypass_transport_retries() -> None:
    client = LLMClient()
    requests: list[LLMCallRequest] = []

    class FakeProvider:
        name = "fake"

        async def generate(self, request: LLMCallRequest) -> LLMCallResponse:
            requests.append(request.model_copy(deep=True))
            return LLMCallResponse(
                content='{"value": "direct"}',
                finish_reason="stop",
                usage=LLMUsage(completion_tokens=5, total_tokens=5),
                model="fake",
                provider="fake",
            )

    async def forbidden_generate(
        self: LLMClient,
        request: LLMCallRequest,
    ) -> LLMCallResponse:
        raise AssertionError("client.generate should be bypassed")

    client._provider = FakeProvider()  # type: ignore[assignment]
    client.generate = MethodType(forbidden_generate, client)  # type: ignore[method-assign]

    result = await client.generate_structured(
        LLMCallRequest(
            model="fake",
            messages=[LLMMessage(role="user", content="return json")],
            max_tokens=20000,
        ),
        _StructuredPayload,
        transport_retries=False,
    )

    assert result.value == "direct"
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_generate_structured_direct_provider_path_uses_limiter(monkeypatch) -> None:
    monkeypatch.setattr(
        "infrastructure.llm.limits.get_settings",
        lambda: _limit_settings(failure_threshold=1, reset_seconds=30.0),
    )
    client = LLMClient()
    calls = 0

    class FakeProvider:
        name = "fake"

        async def generate(self, request: LLMCallRequest) -> LLMCallResponse:
            nonlocal calls
            calls += 1
            return LLMCallResponse(
                content='{"value": "direct"}',
                finish_reason="stop",
                usage=LLMUsage(completion_tokens=5, total_tokens=5),
                model="fake",
                provider="fake",
            )

    client._provider = FakeProvider()  # type: ignore[assignment]
    limiter = get_llm_limiter()
    await limiter.run(lambda: _async_noop())
    await limiter.record_failure()

    with pytest.raises(LLMCircuitBreakerOpenError):
        await client.generate_structured(
            LLMCallRequest(
                model="fake",
                messages=[LLMMessage(role="user", content="raw prompt")],
            ),
            _StructuredPayload,
            transport_retries=False,
        )

    assert calls == 0


async def _async_noop() -> None:
    return None


@pytest.mark.asyncio
async def test_generate_structured_accepts_markdown_json() -> None:
    client = LLMClient()
    diagnostics: list[dict] = []

    async def fake_generate(self: LLMClient, request: LLMCallRequest) -> LLMCallResponse:
        return LLMCallResponse(
            content='```json\n{"value": "from fence"}\n```',
            finish_reason="stop",
            usage=LLMUsage(completion_tokens=9, total_tokens=9),
            model="fake",
            provider="fake",
        )

    client.generate = MethodType(fake_generate, client)  # type: ignore[method-assign]

    result = await client.generate_structured(
        LLMCallRequest(model="fake", messages=[]),
        _StructuredPayload,
        max_fix_attempts=0,
        diagnostics=diagnostics,
    )

    assert result.value == "from fence"
    assert diagnostics == [
        {
            "kind": "structured_parse",
            "strategy": "markdown_code_block",
            "attempt": 1,
        }
    ]


@pytest.mark.asyncio
async def test_generate_structured_extracts_json_from_explanatory_text() -> None:
    client = LLMClient()

    async def fake_generate(self: LLMClient, request: LLMCallRequest) -> LLMCallResponse:
        return LLMCallResponse(
            content='好的，结果如下：{"value": "inside prose"}\n请查收。',
            finish_reason="stop",
            usage=LLMUsage(completion_tokens=12, total_tokens=12),
            model="fake",
            provider="fake",
        )

    client.generate = MethodType(fake_generate, client)  # type: ignore[method-assign]

    result = await client.generate_structured(
        LLMCallRequest(model="fake", messages=[]),
        _StructuredPayload,
        max_fix_attempts=0,
    )

    assert result.value == "inside prose"


@pytest.mark.asyncio
async def test_generate_structured_wraps_bare_list_for_single_list_schema() -> None:
    client = LLMClient()

    async def fake_generate(self: LLMClient, request: LLMCallRequest) -> LLMCallResponse:
        return LLMCallResponse(
            content='[{"value": "one"}]',
            finish_reason="stop",
            usage=LLMUsage(completion_tokens=8, total_tokens=8),
            model="fake",
            provider="fake",
        )

    client.generate = MethodType(fake_generate, client)  # type: ignore[method-assign]

    result = await client.generate_structured(
        LLMCallRequest(model="fake", messages=[]),
        _StructuredItemsPayload,
        max_fix_attempts=0,
    )

    assert [item.value for item in result.items] == ["one"]


@pytest.mark.asyncio
async def test_generate_structured_wraps_bare_list_for_primary_scenes_field() -> None:
    client = LLMClient()

    async def fake_generate(self: LLMClient, request: LLMCallRequest) -> LLMCallResponse:
        return LLMCallResponse(
            content='[{"value": "scene one"}]',
            finish_reason="stop",
            usage=LLMUsage(completion_tokens=8, total_tokens=8),
            model="fake",
            provider="fake",
        )

    client.generate = MethodType(fake_generate, client)  # type: ignore[method-assign]

    result = await client.generate_structured(
        LLMCallRequest(model="fake", messages=[]),
        _StructuredScenesPayload,
        max_fix_attempts=0,
    )

    assert [item.value for item in result.scenes] == ["scene one"]
    assert result.notes == []


@pytest.mark.asyncio
async def test_generate_structured_recovers_lightly_unclosed_json() -> None:
    client = LLMClient()
    diagnostics: list[dict] = []

    async def fake_generate(self: LLMClient, request: LLMCallRequest) -> LLMCallResponse:
        return LLMCallResponse(
            content='{"items": [{"value": "one"}',
            finish_reason="stop",
            usage=LLMUsage(completion_tokens=10, total_tokens=10),
            model="fake",
            provider="fake",
        )

    client.generate = MethodType(fake_generate, client)  # type: ignore[method-assign]

    result = await client.generate_structured(
        LLMCallRequest(model="fake", messages=[]),
        _StructuredItemsPayload,
        max_fix_attempts=0,
        diagnostics=diagnostics,
    )

    assert [item.value for item in result.items] == ["one"]
    assert diagnostics[0]["strategy"] == "balanced_truncated_json"


@pytest.mark.asyncio
async def test_generate_structured_partial_list_keeps_valid_items() -> None:
    client = LLMClient()
    diagnostics: list[dict] = []

    async def fake_generate(self: LLMClient, request: LLMCallRequest) -> LLMCallResponse:
        return LLMCallResponse(
            content='{"items": [{"value": "valid"}, {"value": ""}]}',
            finish_reason="stop",
            usage=LLMUsage(completion_tokens=12, total_tokens=12),
            model="fake",
            provider="fake",
        )

    client.generate = MethodType(fake_generate, client)  # type: ignore[method-assign]

    result = await client.generate_structured(
        LLMCallRequest(model="fake", messages=[]),
        _StructuredItemsPayload,
        max_fix_attempts=0,
        partial_list_fields={"items"},
        diagnostics=diagnostics,
    )

    assert [item.value for item in result.items] == ["valid"]
    assert diagnostics[0]["kind"] == "partial_list_validation"
    assert diagnostics[0]["field"] == "items"
    assert diagnostics[0]["kept"] == 1
    assert diagnostics[0]["skipped"] == 1


@pytest.mark.asyncio
async def test_generate_structured_default_strict_mode_keeps_list_item_errors() -> None:
    client = LLMClient()

    async def fake_generate(self: LLMClient, request: LLMCallRequest) -> LLMCallResponse:
        return LLMCallResponse(
            content='{"items": [{"value": "valid"}, {"value": ""}]}',
            finish_reason="stop",
            usage=LLMUsage(completion_tokens=12, total_tokens=12),
            model="fake",
            provider="fake",
        )

    client.generate = MethodType(fake_generate, client)  # type: ignore[method-assign]

    with pytest.raises(LLMInvalidResponseError):
        await client.generate_structured(
            LLMCallRequest(model="fake", messages=[]),
            _StructuredItemsPayload,
            max_fix_attempts=0,
        )


@pytest.mark.asyncio
async def test_generate_structured_format_repair_after_validation_failure() -> None:
    client = LLMClient()
    requests: list[LLMCallRequest] = []
    diagnostics: list[dict] = []

    async def fake_generate(self: LLMClient, request: LLMCallRequest) -> LLMCallResponse:
        requests.append(request.model_copy(deep=True))
        if len(requests) == 1:
            return LLMCallResponse(
                content='{"value": ""}',
                finish_reason="stop",
                usage=LLMUsage(completion_tokens=5, total_tokens=5),
                model="fake",
                provider="fake",
            )
        return LLMCallResponse(
            content='{"value": "repaired"}',
            finish_reason="stop",
            usage=LLMUsage(completion_tokens=5, total_tokens=5),
            model="fake",
            provider="fake",
        )

    client.generate = MethodType(fake_generate, client)  # type: ignore[method-assign]

    result = await client.generate_structured(
        LLMCallRequest(model="fake", messages=[]),
        _StructuredPayload,
        max_fix_attempts=0,
        format_repair_attempts=1,
        diagnostics=diagnostics,
    )

    assert result.value == "repaired"
    assert len(requests) == 2
    assert "JSON 格式转换器" in requests[1].messages[0].content
    assert diagnostics[-1]["kind"] == "format_repair"
    assert diagnostics[-1]["status"] == "succeeded"


@pytest.mark.asyncio
async def test_generate_structured_format_repair_failure_keeps_detail() -> None:
    client = LLMClient()
    diagnostics: list[dict] = []

    async def fake_generate(self: LLMClient, request: LLMCallRequest) -> LLMCallResponse:
        return LLMCallResponse(
            content='{"value": ""}',
            finish_reason="stop",
            usage=LLMUsage(completion_tokens=5, total_tokens=5),
            model="fake",
            provider="fake",
        )

    client.generate = MethodType(fake_generate, client)  # type: ignore[method-assign]

    with pytest.raises(LLMInvalidResponseError) as exc_info:
        await client.generate_structured(
            LLMCallRequest(model="fake", messages=[]),
            _StructuredPayload,
            max_fix_attempts=0,
            format_repair_attempts=1,
            diagnostics=diagnostics,
        )

    assert "Format repair failed" in str(exc_info.value)
    assert diagnostics[-1]["kind"] == "format_repair"
    assert diagnostics[-1]["status"] == "failed"


@pytest.mark.asyncio
async def test_generate_structured_format_repair_retry_uses_backoff(monkeypatch) -> None:
    client = LLMClient()
    client._settings = _retry_settings(base_delay=0.25, max_delay=0.4)
    diagnostics: list[dict] = []
    delays: list[float] = []

    async def fake_sleep(delay: float) -> None:
        delays.append(delay)

    async def fake_generate(self: LLMClient, request: LLMCallRequest) -> LLMCallResponse:
        return LLMCallResponse(
            content='{"value": ""}',
            finish_reason="stop",
            usage=LLMUsage(completion_tokens=5, total_tokens=5),
            model="fake",
            provider="fake",
        )

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    client.generate = MethodType(fake_generate, client)  # type: ignore[method-assign]

    with pytest.raises(LLMInvalidResponseError):
        await client.generate_structured(
            LLMCallRequest(model="fake", messages=[]),
            _StructuredPayload,
            max_fix_attempts=0,
            format_repair_attempts=3,
            diagnostics=diagnostics,
        )

    assert delays == [0.25, 0.4]
    assert [d["attempt"] for d in diagnostics if d["kind"] == "format_repair"] == [
        1,
        2,
        3,
    ]


@pytest.mark.asyncio
async def test_generate_structured_truncated_json_does_not_format_repair() -> None:
    client = LLMClient()
    requests: list[LLMCallRequest] = []

    async def fake_generate(self: LLMClient, request: LLMCallRequest) -> LLMCallResponse:
        requests.append(request.model_copy(deep=True))
        return LLMCallResponse(
            content='{"value": "unfinished',
            finish_reason="length",
            usage=LLMUsage(completion_tokens=20000, total_tokens=20000),
            model="fake",
            provider="fake",
        )

    client.generate = MethodType(fake_generate, client)  # type: ignore[method-assign]

    with pytest.raises(LLMInvalidResponseError):
        await client.generate_structured(
            LLMCallRequest(
                model="fake",
                messages=[],
                max_tokens=20000,
            ),
            _StructuredPayload,
            max_fix_attempts=0,
            format_repair_attempts=1,
        )

    assert len(requests) == 1
