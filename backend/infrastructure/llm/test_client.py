"""LLM client structured-output behavior tests."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from types import MethodType, SimpleNamespace

import pytest
from pydantic import BaseModel, Field

from infrastructure.llm.client import LLMClient
from infrastructure.llm.errors import (
    LLMAuthError,
    LLMContentFilterError,
    LLMInvalidResponseError,
    LLMRateLimitError,
    LLMTimeoutError,
)
from infrastructure.llm.limits import (
    LLMCircuitBreakerOpenError,
    LLMLimiterScope,
    LLMProcessLimiter,
    get_llm_limiter,
    reset_llm_limiter_for_tests,
)
from infrastructure.llm.profiles import resolve_llm_profile
from infrastructure.llm.providers import OpenAIProvider
from infrastructure.llm.schemas import (
    LLMCallRequest,
    LLMCallResponse,
    LLMMessage,
    LLMStreamChunk,
    LLMUsage,
)
from infrastructure.llm.secret_store import encrypt_secret


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


class _StructuredMappingPayload(BaseModel):
    values: dict[str, int]


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
    assert profile.max_tokens == 12_000
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
    assert profile.max_tokens == 12_000
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
    assert profile.max_tokens == 12_000
    assert profile.sources["timeout"] == "default"
    assert profile.sources["max_tokens"] == "default"


@pytest.mark.parametrize(
    ("field", "invalid", "expected"),
    [
        ("temperature", "nan", 0.3),
        ("temperature", "inf", 0.3),
        ("temperature", 2.1, 0.3),
        ("top_p", "-inf", None),
        ("top_p", 1.1, None),
        ("timeout", True, 180),
        ("timeout", 3601, 180),
        ("max_tokens", 200_001, 12_000),
    ],
)
def test_resolve_llm_profile_rejects_invalid_numeric_values(
    field: str,
    invalid: object,
    expected: object,
) -> None:
    profile = resolve_llm_profile(
        {"llm": {field: invalid}},
    )

    assert getattr(profile, field) == expected
    assert profile.sources[field] == "default"


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


def test_resolve_llm_profile_decrypts_encrypted_project_api_key() -> None:
    encrypted = encrypt_secret("sk-encrypted")

    profile = resolve_llm_profile(
        {
            "llm": {
                "provider_id": "openai-compatible",
                "api_key": encrypted,
                "base_url": "https://opencode.ai/zen/go/v1",
                "model": "deepseek-v4-flash",
            }
        },
        env_settings=_FakeEnvSettings(),
    )

    assert profile.api_key == "sk-encrypted"
    assert profile.sources["api_key"] == "project"


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
async def test_switch_provider_refreshes_limiter_endpoint_and_safe_summary(
    monkeypatch,
) -> None:
    client = LLMClient(base_url="https://old.example/v1")

    class OldProvider:
        async def close(self) -> None:
            return None

    class NewProvider:
        name = "openai"
        _api_key = "private-key-value"
        _base_url = "https://new.example/v2/?token=private-query"
        _embedding_base_url = "https://embedding.example/v1/?token=private-embedding"
        _timeout = 45

    client._provider = OldProvider()  # type: ignore[assignment]
    monkeypatch.setattr(
        "infrastructure.llm.client.get_provider",
        lambda *_args, **_kwargs: NewProvider(),
    )

    await client.switch_provider(
        "openai",
        api_key="private-key-value",
        base_url="https://new.example/v2/?token=private-query",
        default_model="new-model",
        timeout=45,
    )

    scope = client._limiter_scope("chat")
    embedding_scope = client._limiter_scope("embedding")
    assert scope.endpoint == "https://new.example/v2"
    assert embedding_scope.endpoint == "https://embedding.example/v1"
    assert client.profile_summary["provider_id"] == "openai"
    assert client.profile_summary["label"] == "OpenAI"
    assert client.profile_summary["model"] == "new-model"
    assert client.profile_summary["base_url_host"] == "new.example"
    assert "private" not in repr(scope)
    assert "private" not in repr(embedding_scope)
    assert "private" not in str(client.profile_summary)


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
async def test_remote_embedding_uses_embedding_limiter_scope(monkeypatch) -> None:
    client = LLMClient(base_url="https://chat.example/v1")
    client._limiter_embedding_base_url = "https://embedding.example/v1"
    client._settings = _retry_settings(base_delay=0.0, max_delay=0.0)
    captured_scopes: list[LLMLimiterScope] = []

    class RemoteProvider:
        name = "remote"

        async def generate_embedding(
            self,
            text: str | list[str],
            model: str | None = None,
        ) -> list[float]:
            assert text == "测试文本"
            return [0.1, 0.2]

    class CapturingLimiter:
        async def run(self, fn, *, limiter_scope=None):
            captured_scopes.append(limiter_scope)
            return await fn()

    client._provider = RemoteProvider()  # type: ignore[assignment]
    monkeypatch.setattr(
        "infrastructure.llm.client.get_settings",
        lambda: SimpleNamespace(embedding_provider="openai"),
    )
    monkeypatch.setattr(
        "infrastructure.llm.client.get_llm_limiter",
        lambda: CapturingLimiter(),
    )

    result = await client.generate_embedding("测试文本")

    assert result == [0.1, 0.2]
    assert len(captured_scopes) == 1
    assert captured_scopes[0].operation_kind == "embedding"
    assert captured_scopes[0].owner == "system"
    assert captured_scopes[0].endpoint == "https://embedding.example/v1"


@pytest.mark.asyncio
async def test_project_remote_embedding_routes_once_with_project_scope(
    monkeypatch,
) -> None:
    settings = SimpleNamespace(
        embedding_provider="openai",
        llm_retry_max_attempts=1,
        llm_retry_base_delay=0.0,
        llm_retry_max_delay=0.0,
    )
    providers = []
    captured_scopes: list[LLMLimiterScope] = []

    class RemoteProvider:
        name = "openai"
        _api_key = ""
        _base_url = "https://chat.example/v1"
        _embedding_base_url = "https://embedding.example/v1"
        _timeout = 30

        def __init__(self) -> None:
            self.embedding_calls = 0

        async def generate_embedding(self, text, model=None):
            self.embedding_calls += 1
            assert text == "project text"
            return [0.1, 0.2]

        async def close(self) -> None:
            return None

    class CapturingLimiter:
        async def run(self, fn, *, limiter_scope=None):
            captured_scopes.append(limiter_scope)
            return await fn()

    def make_provider(*_args, **_kwargs):
        provider = RemoteProvider()
        providers.append(provider)
        return provider

    monkeypatch.setattr("infrastructure.llm.client.get_settings", lambda: settings)
    monkeypatch.setattr("infrastructure.llm.client.get_provider", make_provider)
    monkeypatch.setattr(
        "infrastructure.llm.client.get_llm_limiter",
        lambda: CapturingLimiter(),
    )
    client = LLMClient(base_url="https://project-chat.example/v1")
    client.bind_runtime_scope(novel_id="project-a", profile_source="project")

    result = await client.generate_embedding("project text")

    assert result == [0.1, 0.2]
    assert len(providers) == 2
    assert providers[0].embedding_calls == 0
    assert providers[1].embedding_calls == 1
    assert captured_scopes == [
        LLMLimiterScope.for_call(
            novel_id="project-a",
            operation_kind="embedding",
            base_url="https://embedding.example/v1",
            provider_id="openai",
        )
    ]


@pytest.mark.asyncio
async def test_usage_stats_omit_complete_endpoint_and_credentials() -> None:
    client = LLMClient.__new__(LLMClient)
    client._provider = SimpleNamespace(
        name="openai",
        _base_url=(
            "https://user:private-password@example.test/v1"
            "?api_key=private-query#private-fragment"
        ),
    )
    client._default_model = "test-model"
    client._profile_summary = {"base_url_host": "example.test"}

    stats = await client.get_usage_stats()

    assert stats == {
        "provider": "openai",
        "default_model": "test-model",
        "base_url_host": "example.test",
    }
    assert "private" not in str(stats)


@pytest.mark.asyncio
async def test_project_chat_profile_cannot_override_remote_embedding_client(
    monkeypatch,
) -> None:
    project_client = LLMClient.__new__(LLMClient)
    project_client._runtime_scope = {
        "novel_id": "project-a",
        "profile_source": "project",
    }
    project_client._settings = _retry_settings(base_delay=0.0, max_delay=0.0)
    project_provider_calls = 0

    class ProjectChatProvider:
        async def generate_embedding(self, *_args, **_kwargs):
            nonlocal project_provider_calls
            project_provider_calls += 1
            return [9.9]

    project_client._provider = ProjectChatProvider()

    class IndependentEmbeddingClient:
        def __init__(self) -> None:
            self._runtime_scope = {"profile_source": "system"}
            self._uses_system_embedding_profile = False
            self.closed = False

        def bind_runtime_scope(self, *, novel_id, profile_source):
            self._runtime_scope = {
                "novel_id": novel_id,
                "profile_source": profile_source,
            }

        async def generate_embedding(self, text, model=None, *, is_query=False):
            assert text == "独立 embedding"
            assert model == "embedding-model"
            assert is_query is True
            assert self._runtime_scope == {
                "novel_id": "project-a",
                "profile_source": "system",
            }
            assert self._uses_system_embedding_profile is True
            return [0.1, 0.2]

        async def close(self) -> None:
            self.closed = True

    independent = IndependentEmbeddingClient()
    monkeypatch.setattr(
        "infrastructure.llm.client.get_settings",
        lambda: SimpleNamespace(embedding_provider="openai"),
    )
    monkeypatch.setattr(
        "infrastructure.llm.client.LLMClient",
        lambda: independent,
    )

    result = await LLMClient.generate_embedding(
        project_client,
        "独立 embedding",
        model="embedding-model",
        is_query=True,
    )

    assert result == [0.1, 0.2]
    assert project_provider_calls == 0
    assert independent._runtime_scope["novel_id"] == "project-a"
    assert independent.closed is True


@pytest.mark.asyncio
async def test_generate_uses_process_concurrency_limiter(monkeypatch) -> None:
    monkeypatch.setattr(
        "infrastructure.llm.limits.get_settings",
        lambda: _limit_settings(max_concurrent_requests=1),
    )
    first_client = LLMClient()
    second_client = LLMClient()
    first_client.bind_runtime_scope(novel_id="novel-a", profile_source="project")
    second_client.bind_runtime_scope(novel_id="novel-b", profile_source="project")
    active = 0
    max_active = 0
    release_first = asyncio.Event()
    first_started = asyncio.Event()

    class FakeProvider:
        name = "fake"

        async def generate(self, request: LLMCallRequest) -> LLMCallResponse:
            nonlocal active, max_active
            assert request.max_tokens == 12_000
            active += 1
            max_active = max(max_active, active)
            if not first_started.is_set():
                first_started.set()
                await release_first.wait()
            active -= 1
            return LLMCallResponse(content="ok", model="fake", provider="fake")

    provider = FakeProvider()
    first_client._provider = provider  # type: ignore[assignment]
    second_client._provider = provider  # type: ignore[assignment]

    first = asyncio.create_task(first_client.generate(LLMCallRequest(model="fake")))
    await first_started.wait()
    second = asyncio.create_task(second_client.generate(LLMCallRequest(model="fake")))
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
async def test_limiter_breaker_ignores_project_auth_failure(monkeypatch) -> None:
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
            assert request.model == "fake"
            calls += 1
            if calls == 1:
                raise LLMAuthError("project key rejected", provider="fake")
            return LLMCallResponse(content="ok", model="fake", provider="fake")

    client._provider = FakeProvider()  # type: ignore[assignment]

    with pytest.raises(LLMAuthError):
        await client.generate(LLMCallRequest(model="fake"))

    response = await client.generate(LLMCallRequest(model="fake"))
    assert response.content == "ok"
    assert calls == 2


@pytest.mark.asyncio
async def test_limiter_breaker_isolates_projects_on_same_endpoint(monkeypatch) -> None:
    monkeypatch.setattr(
        "infrastructure.llm.limits.get_settings",
        lambda: _limit_settings(failure_threshold=1, reset_seconds=30.0),
    )
    first = LLMClient(base_url="https://shared.example/v1")
    second = LLMClient(base_url="https://shared.example/v1/")
    first.bind_runtime_scope(novel_id="novel-a", profile_source="project")
    second.bind_runtime_scope(novel_id="novel-b", profile_source="project")
    first._settings = _retry_settings(base_delay=0.0, max_delay=0.0)
    second_calls = 0

    class FailingProvider:
        name = "fake"

        async def generate(self, request: LLMCallRequest) -> LLMCallResponse:
            raise LLMRateLimitError("project A exhausted its quota", provider="fake")

    class HealthyProvider:
        name = "fake"

        async def generate(self, request: LLMCallRequest) -> LLMCallResponse:
            nonlocal second_calls
            second_calls += 1
            return LLMCallResponse(content="ok", model="fake", provider="fake")

    first._provider = FailingProvider()  # type: ignore[assignment]
    second._provider = HealthyProvider()  # type: ignore[assignment]

    with pytest.raises(LLMRateLimitError):
        await first.generate(LLMCallRequest(model="fake"))
    with pytest.raises(LLMCircuitBreakerOpenError):
        await first.generate(LLMCallRequest(model="fake"))

    response = await second.generate(LLMCallRequest(model="fake"))
    assert response.content == "ok"
    assert second_calls == 1
    with pytest.raises(LLMCircuitBreakerOpenError):
        await first.generate(LLMCallRequest(model="fake"))


@pytest.mark.asyncio
async def test_limiter_breaker_isolates_endpoints_within_project(monkeypatch) -> None:
    monkeypatch.setattr(
        "infrastructure.llm.limits.get_settings",
        lambda: _limit_settings(failure_threshold=1, reset_seconds=30.0),
    )
    limiter = LLMProcessLimiter()
    failed_scope = LLMLimiterScope.for_call(
        novel_id="novel-a",
        operation_kind="chat",
        base_url="https://down.example/v1",
        provider_id="custom",
    )
    healthy_scope = LLMLimiterScope.for_call(
        novel_id="novel-a",
        operation_kind="chat",
        base_url="https://healthy.example/v1",
        provider_id="custom",
    )
    await limiter.run(_async_noop, limiter_scope=failed_scope)
    await limiter.record_failure(failed_scope)

    with pytest.raises(LLMCircuitBreakerOpenError):
        await limiter.run(_async_noop, limiter_scope=failed_scope)
    await limiter.run(_async_noop, limiter_scope=healthy_scope)


def test_limiter_scope_normalizes_endpoint_without_secrets() -> None:
    first = LLMLimiterScope.for_call(
        novel_id="novel-a",
        operation_kind="CHAT",
        base_url=(
            "HTTPS://user:private-value@Example.COM:443/v1/"
            "?api_key=private-query#private-fragment"
        ),
        provider_id="custom",
    )
    second = LLMLimiterScope.for_call(
        novel_id="novel-a",
        operation_kind="chat",
        base_url="https://example.com/v1",
        provider_id="other-model",
    )

    assert first == second
    assert first.endpoint == "https://example.com/v1"
    assert "private" not in repr(first)
    assert "api_key" not in repr(first)


@pytest.mark.asyncio
async def test_limiter_separates_system_chat_and_embedding(monkeypatch) -> None:
    monkeypatch.setattr(
        "infrastructure.llm.limits.get_settings",
        lambda: _limit_settings(failure_threshold=1, reset_seconds=30.0),
    )
    limiter = LLMProcessLimiter()
    chat_scope = LLMLimiterScope.for_call(
        novel_id=None,
        operation_kind="chat",
        base_url="https://shared.example/v1",
        provider_id="custom",
    )
    embedding_scope = LLMLimiterScope.for_call(
        novel_id=None,
        operation_kind="embedding",
        base_url="https://shared.example/v1",
        provider_id="custom",
    )
    await limiter.run(_async_noop, limiter_scope=chat_scope)
    await limiter.record_failure(chat_scope)

    with pytest.raises(LLMCircuitBreakerOpenError):
        await limiter.run(_async_noop, limiter_scope=chat_scope)
    await limiter.run(_async_noop, limiter_scope=embedding_scope)


@pytest.mark.asyncio
async def test_limiter_allows_one_half_open_probe(monkeypatch) -> None:
    now = 100.0
    monkeypatch.setattr("infrastructure.llm.limits.monotonic", lambda: now)
    monkeypatch.setattr(
        "infrastructure.llm.limits.get_settings",
        lambda: _limit_settings(failure_threshold=1, reset_seconds=10.0),
    )
    limiter = LLMProcessLimiter()
    scope = LLMLimiterScope.for_call(
        novel_id="novel-a",
        operation_kind="chat",
        base_url="https://provider.example/v1",
        provider_id="custom",
    )
    await limiter.run(_async_noop, limiter_scope=scope)
    await limiter.record_failure(scope)
    now = 111.0
    probe_started = asyncio.Event()
    release_probe = asyncio.Event()

    async def probe() -> None:
        probe_started.set()
        await release_probe.wait()

    first_probe = asyncio.create_task(limiter.run(probe, limiter_scope=scope))
    await probe_started.wait()
    with pytest.raises(LLMCircuitBreakerOpenError) as exc_info:
        await limiter.run(_async_noop, limiter_scope=scope)
    assert exc_info.value.retry_after == 1.0

    release_probe.set()
    await first_probe
    await limiter.run(_async_noop, limiter_scope=scope)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "provider_error",
    [
        LLMAuthError("project key rejected", provider="fake"),
        LLMContentFilterError("content filtered", provider="fake"),
        LLMInvalidResponseError("schema rejected", provider="fake"),
    ],
)
async def test_non_availability_half_open_response_closes_bucket(
    monkeypatch,
    provider_error,
) -> None:
    now = 100.0
    monkeypatch.setattr("infrastructure.llm.limits.monotonic", lambda: now)
    monkeypatch.setattr(
        "infrastructure.llm.limits.get_settings",
        lambda: _limit_settings(failure_threshold=1, reset_seconds=10.0),
    )
    limiter = LLMProcessLimiter()
    scope = LLMLimiterScope.for_call(
        novel_id="novel-a",
        operation_kind="chat",
        base_url="https://provider.example/v1",
        provider_id="custom",
    )
    await limiter.run(_async_noop, limiter_scope=scope)
    await limiter.record_failure(scope)
    now = 111.0

    async def deterministic_failure() -> None:
        raise provider_error

    with pytest.raises(type(provider_error)):
        await limiter.run(deterministic_failure, limiter_scope=scope)
    await limiter.run(_async_noop, limiter_scope=scope)


@pytest.mark.asyncio
async def test_limiter_half_open_failure_reopens_and_cancellation_releases(
    monkeypatch,
) -> None:
    now = 100.0
    monkeypatch.setattr("infrastructure.llm.limits.monotonic", lambda: now)
    monkeypatch.setattr(
        "infrastructure.llm.limits.get_settings",
        lambda: _limit_settings(failure_threshold=1, reset_seconds=10.0),
    )
    limiter = LLMProcessLimiter()
    scope = LLMLimiterScope.for_call(
        novel_id="novel-a",
        operation_kind="chat",
        base_url="https://provider.example/v1",
        provider_id="custom",
    )
    await limiter.run(_async_noop, limiter_scope=scope)
    await limiter.record_failure(scope)
    now = 111.0

    async def failing_probe() -> None:
        raise LLMTimeoutError("probe timeout", provider="fake")

    with pytest.raises(LLMTimeoutError):
        await limiter.run(failing_probe, limiter_scope=scope)
    with pytest.raises(LLMCircuitBreakerOpenError):
        await limiter.run(_async_noop, limiter_scope=scope)

    now = 122.0
    probe_started = asyncio.Event()

    async def cancelled_probe() -> None:
        probe_started.set()
        await asyncio.Event().wait()

    task = asyncio.create_task(limiter.run(cancelled_probe, limiter_scope=scope))
    await probe_started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    await limiter.run(_async_noop, limiter_scope=scope)


@pytest.mark.asyncio
async def test_open_breaker_does_not_consume_global_admission_capacity(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "infrastructure.llm.limits.get_settings",
        lambda: _limit_settings(
            max_concurrent_requests=1,
            rate_limit_per_minute=60,
            failure_threshold=1,
            reset_seconds=30.0,
        ),
    )
    limiter = LLMProcessLimiter()
    scope = LLMLimiterScope.for_call(
        novel_id="novel-a",
        operation_kind="chat",
        base_url="https://provider.example/v1",
        provider_id="custom",
    )
    await limiter.run(_async_noop, limiter_scope=scope)
    await limiter.record_failure(scope)
    limiter._tokens = 1.0
    semaphore = limiter._semaphore
    assert semaphore is not None

    with pytest.raises(LLMCircuitBreakerOpenError):
        await limiter.run(_async_noop, limiter_scope=scope)

    assert limiter._tokens == 1.0
    assert semaphore._value == 1


@pytest.mark.asyncio
async def test_breaker_registry_is_bounded_and_keeps_active_probe(monkeypatch) -> None:
    now = 100.0
    monkeypatch.setattr("infrastructure.llm.limits.monotonic", lambda: now)
    monkeypatch.setattr(
        "infrastructure.llm.limits.get_settings",
        lambda: _limit_settings(failure_threshold=1, reset_seconds=10.0),
    )
    limiter = LLMProcessLimiter()
    protected_scope = LLMLimiterScope.for_call(
        novel_id="protected",
        operation_kind="chat",
        base_url="https://protected.example/v1",
        provider_id="custom",
    )
    await limiter.run(_async_noop, limiter_scope=protected_scope)
    await limiter.record_failure(protected_scope)
    now = 111.0
    probe_started = asyncio.Event()
    release_probe = asyncio.Event()

    async def probe() -> None:
        probe_started.set()
        await release_probe.wait()

    active_probe = asyncio.create_task(limiter.run(probe, limiter_scope=protected_scope))
    await probe_started.wait()
    for index in range(300):
        scope = LLMLimiterScope.for_call(
            novel_id=f"novel-{index}",
            operation_kind="chat",
            base_url=f"https://provider-{index}.example/v1",
            provider_id="custom",
        )
        await limiter.record_failure(scope)

    assert len(limiter._breakers) == 256
    assert protected_scope in limiter._breakers
    release_probe.set()
    await active_probe


@pytest.mark.asyncio
async def test_breaker_registry_fails_open_when_all_buckets_are_active_probes(
    monkeypatch,
    caplog,
) -> None:
    monkeypatch.setattr(
        "infrastructure.llm.limits.get_settings",
        lambda: _limit_settings(failure_threshold=1, reset_seconds=10.0),
    )
    limiter = LLMProcessLimiter()
    await limiter.run(_async_noop)
    for index in range(256):
        scope = LLMLimiterScope.for_call(
            novel_id=f"novel-{index}",
            operation_kind="chat",
            base_url=f"https://provider-{index}.example/v1",
            provider_id="custom",
        )
        await limiter.record_failure(scope)
    for state in limiter._breakers.values():
        state.half_open_probe = True

    secret = "private-endpoint-value"
    overflow_scope = LLMLimiterScope.for_call(
        novel_id="overflow-project",
        operation_kind="chat",
        base_url=f"https://user:{secret}@overflow.example/v1?api_key={secret}",
        provider_id="custom",
    )
    await limiter.record_failure(overflow_scope)

    assert len(limiter._breakers) == 256
    assert overflow_scope not in limiter._breakers
    messages = "\n".join(record.getMessage() for record in caplog.records)
    assert "saturated with active probes" in messages
    assert secret not in messages


@pytest.mark.asyncio
async def test_different_scopes_share_global_rpm_bucket(monkeypatch) -> None:
    now = 100.0
    monkeypatch.setattr("infrastructure.llm.limits.monotonic", lambda: now)
    monkeypatch.setattr(
        "infrastructure.llm.limits.get_settings",
        lambda: _limit_settings(rate_limit_per_minute=2),
    )
    limiter = LLMProcessLimiter()
    first_scope = LLMLimiterScope.for_call(
        novel_id="novel-a",
        operation_kind="chat",
        base_url="https://first.example/v1",
        provider_id="custom",
    )
    second_scope = LLMLimiterScope.for_call(
        novel_id="novel-b",
        operation_kind="chat",
        base_url="https://second.example/v1",
        provider_id="custom",
    )

    await limiter.run(_async_noop, limiter_scope=first_scope)
    assert limiter._tokens == 1.0
    await limiter.run(_async_noop, limiter_scope=second_scope)
    assert limiter._tokens == 0.0


@pytest.mark.asyncio
async def test_breaker_state_is_process_local(monkeypatch) -> None:
    monkeypatch.setattr(
        "infrastructure.llm.limits.get_settings",
        lambda: _limit_settings(failure_threshold=1, reset_seconds=30.0),
    )
    first_process = LLMProcessLimiter()
    second_process = LLMProcessLimiter()
    scope = LLMLimiterScope.for_call(
        novel_id="novel-a",
        operation_kind="chat",
        base_url="https://provider.example/v1",
        provider_id="custom",
    )
    await first_process.run(_async_noop, limiter_scope=scope)
    await second_process.run(_async_noop, limiter_scope=scope)
    await first_process.record_failure(scope)

    with pytest.raises(LLMCircuitBreakerOpenError):
        await first_process.run(_async_noop, limiter_scope=scope)
    await second_process.run(_async_noop, limiter_scope=scope)


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
            assert request.max_tokens == 12_000

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
async def test_client_accepts_real_provider_stream_coroutine_shape(monkeypatch) -> None:
    monkeypatch.setattr(
        "infrastructure.llm.limits.get_settings",
        lambda: _limit_settings(max_concurrent_requests=1),
    )

    class SDKStream:
        def __init__(self) -> None:
            self._sent = False

        def __aiter__(self):
            return self

        async def __anext__(self):
            if self._sent:
                raise StopAsyncIteration
            self._sent = True
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        delta=SimpleNamespace(content="real-provider-chunk"),
                        finish_reason=None,
                    )
                ],
                usage=None,
            )

    class Completions:
        async def create(self, **_kwargs):
            return SDKStream()

    provider = OpenAIProvider.__new__(OpenAIProvider)
    provider._client = SimpleNamespace(chat=SimpleNamespace(completions=Completions()))
    provider._default_model = "test-model"
    provider._timeout = 15

    client = LLMClient.__new__(LLMClient)
    client._provider = provider
    client._settings = _retry_settings(base_delay=0.0, max_delay=0.0)
    client._default_max_tokens = 12_000
    client._runtime_scope = {"profile_source": "system"}
    client._limiter_provider_id = "openai"
    client._limiter_base_url = "https://chat.example/v1"

    chunks = [
        chunk
        async for chunk in client.generate_stream(
            LLMCallRequest(model="test-model"),
        )
    ]

    assert [chunk.content for chunk in chunks] == ["real-provider-chunk"]


@pytest.mark.asyncio
async def test_generate_structured_retries_truncated_json_with_larger_budget() -> None:
    client = LLMClient()
    requests: list[LLMCallRequest] = []
    diagnostics: list[dict] = []

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
        diagnostics=diagnostics,
    )

    assert result.value == "complete"
    assert len(requests) == 2
    assert requests[1].max_tokens == 40000
    assert requests[1].messages[-1].role == "user"
    assert "上一轮输出被截断" in requests[1].messages[-1].content
    assert "从头重新输出完整 JSON" in requests[1].messages[-1].content
    usage = [item for item in diagnostics if item["kind"] == "structured_usage"]
    assert usage == [
        {
            "kind": "structured_usage",
            "status": "failed",
            "error_kind": "truncated_json",
            "attempt": 1,
            "finish_reason": "length",
            "completion_tokens": 20000,
            "max_tokens": 20000,
        },
        {
            "kind": "structured_usage",
            "status": "succeeded",
            "attempt": 2,
            "finish_reason": "stop",
            "completion_tokens": 8,
            "max_tokens": 40000,
        },
    ]


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
async def test_generate_structured_final_error_keeps_safe_validation_detail() -> None:
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

    assert "string_too_short" in str(exc_info.value)
    assert exc_info.value.raw_response == '{"value": ""}'


@pytest.mark.asyncio
async def test_generate_structured_does_not_log_invalid_field_content(
    caplog: pytest.LogCaptureFixture,
) -> None:
    client = LLMClient()
    private_content = "PRIVATE_NOVEL_TEXT_MUST_NOT_REACH_LOGS"

    async def fake_generate(self: LLMClient, request: LLMCallRequest) -> LLMCallResponse:
        return LLMCallResponse(
            content=json.dumps({"value": [private_content]}),
            finish_reason="stop",
            usage=LLMUsage(completion_tokens=5, total_tokens=5),
            model="fake",
            provider="fake",
        )

    client.generate = MethodType(fake_generate, client)  # type: ignore[method-assign]

    with (
        caplog.at_level("WARNING", logger="infrastructure.llm.client"),
        pytest.raises(LLMInvalidResponseError) as exc_info,
    ):
        await client.generate_structured(
            LLMCallRequest(model="fake", messages=[]),
            _StructuredPayload,
            max_fix_attempts=0,
        )

    assert private_content not in caplog.text
    assert private_content not in str(exc_info.value)
    assert "string_type" in str(exc_info.value)


@pytest.mark.asyncio
async def test_generate_structured_masks_dynamic_mapping_keys_in_errors(
    caplog: pytest.LogCaptureFixture,
) -> None:
    client = LLMClient()
    private_key = "PRIVATE_NOVEL_KEY_MUST_NOT_REACH_DIAGNOSTICS"
    diagnostics: list[dict] = []

    async def fake_generate(self: LLMClient, request: LLMCallRequest) -> LLMCallResponse:
        return LLMCallResponse(
            content=json.dumps({"values": {private_key: "not-an-integer"}}),
            finish_reason="stop",
            usage=LLMUsage(completion_tokens=5, total_tokens=5),
            model="fake",
            provider="fake",
        )

    client.generate = MethodType(fake_generate, client)  # type: ignore[method-assign]

    with (
        caplog.at_level("WARNING", logger="infrastructure.llm.client"),
        pytest.raises(LLMInvalidResponseError) as exc_info,
    ):
        await client.generate_structured(
            LLMCallRequest(model="fake", messages=[]),
            _StructuredMappingPayload,
            max_fix_attempts=0,
            diagnostics=diagnostics,
        )

    assert private_key not in caplog.text
    assert private_key not in str(exc_info.value)
    assert private_key not in str(diagnostics)
    assert "int_parsing" in str(exc_info.value)


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
    limiter_scope = client._limiter_scope("chat")
    await limiter.run(lambda: _async_noop(), limiter_scope=limiter_scope)
    await limiter.record_failure(limiter_scope)

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
        },
        {
            "kind": "structured_usage",
            "status": "succeeded",
            "attempt": 1,
            "finish_reason": "stop",
            "completion_tokens": 9,
            "max_tokens": 12_000,
        },
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
