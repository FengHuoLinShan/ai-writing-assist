"""LLM client structured-output behavior tests."""

from __future__ import annotations

import json
from types import MethodType

import pytest
from pydantic import BaseModel, Field

from infrastructure.llm.client import LLMClient
from infrastructure.llm.errors import LLMInvalidResponseError
from infrastructure.llm.profiles import resolve_llm_profile
from infrastructure.llm.schemas import (
    LLMCallRequest,
    LLMCallResponse,
    LLMMessage,
    LLMUsage,
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
