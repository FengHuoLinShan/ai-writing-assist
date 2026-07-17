"""LLM provider transport configuration tests."""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import pytest

from infrastructure.llm.providers import OpenAIProvider
from infrastructure.llm.schemas import LLMCallRequest, LLMMessage


def test_provider_initialization_log_omits_base_url_query_secret(caplog) -> None:
    query_secret = "fixture-query-secret"
    with (
        patch("infrastructure.llm.providers.httpx.AsyncClient", autospec=True),
        patch("infrastructure.llm.providers.AsyncOpenAI", autospec=True),
        caplog.at_level(logging.INFO, logger="infrastructure.llm.providers"),
    ):
        OpenAIProvider(
            api_key="test-key",
            base_url=f"https://gateway.example.test/v1?token={query_secret}",
            default_model="test-model",
        )

    messages = "\n".join(record.getMessage() for record in caplog.records)
    assert "base_url_host=gateway.example.test" in messages
    assert query_secret not in messages
    assert "token=" not in messages


def test_provider_disables_system_proxy_by_default(monkeypatch) -> None:
    """OpenAI SDK should not implicitly use macOS/system proxies."""
    from core.config import get_settings

    monkeypatch.delenv("LLM_PROXY_URL", raising=False)
    get_settings.cache_clear()
    with (
        patch(
            "infrastructure.llm.providers.httpx.AsyncClient", autospec=True
        ) as http_client_cls,
        patch("infrastructure.llm.providers.AsyncOpenAI", autospec=True) as openai_cls,
    ):
        http_client = MagicMock()
        http_client_cls.return_value = http_client

        OpenAIProvider(
            api_key="test-key",
            base_url="https://opencode.ai/zen/go/v1",
            default_model="deepseek-v4-flash",
        )

    http_client_cls.assert_called_once()
    kwargs = http_client_cls.call_args.kwargs
    assert kwargs["trust_env"] is False
    assert "proxy" not in kwargs
    assert openai_cls.call_args.kwargs["http_client"] is http_client
    get_settings.cache_clear()


def test_provider_does_not_fall_back_to_llm_env_profile(monkeypatch) -> None:
    """Business LLM API key/base/model must come from project profile, not env."""
    monkeypatch.setenv("LLM_API_KEY", "sk-env-should-not-be-used")
    monkeypatch.setenv("LLM_BASE_URL", "https://env.example/v1")
    monkeypatch.setenv("LLM_MODEL", "env-model")
    with (
        patch("infrastructure.llm.providers.httpx.AsyncClient", autospec=True),
        patch("infrastructure.llm.providers.AsyncOpenAI", autospec=True) as openai_cls,
    ):
        provider = OpenAIProvider()

    assert provider._api_key == ""
    assert provider._base_url == "https://api.deepseek.com"
    assert provider._default_model == "deepseek-v4-flash"
    assert openai_cls.call_args.kwargs["api_key"] == ""


def test_provider_uses_explicit_proxy_when_configured() -> None:
    """Explicit proxy configuration should be the only proxy path."""
    with (
        patch(
            "infrastructure.llm.providers.httpx.AsyncClient", autospec=True
        ) as http_client_cls,
        patch("infrastructure.llm.providers.AsyncOpenAI", autospec=True),
    ):
        OpenAIProvider(
            api_key="test-key",
            base_url="https://opencode.ai/zen/go/v1",
            default_model="deepseek-v4-flash",
            trust_env=True,
            proxy_url="http://127.0.0.1:1082",
        )

    kwargs = http_client_cls.call_args.kwargs
    assert kwargs["trust_env"] is True
    assert kwargs["proxy"] == "http://127.0.0.1:1082"


def test_provider_rejects_reserved_extra_fields() -> None:
    """Provider extra 不能覆盖模型、消息、流式、认证或传输字段。"""
    with (
        patch("infrastructure.llm.providers.httpx.AsyncClient", autospec=True),
        patch("infrastructure.llm.providers.AsyncOpenAI", autospec=True),
    ):
        provider = OpenAIProvider(
            api_key="test-key",
            base_url="https://opencode.ai/zen/go/v1",
            default_model="deepseek-v4-flash",
        )

    request = LLMCallRequest(
        model="deepseek-v4-flash",
        messages=[LLMMessage(role="user", content="hi")],
        extra={"headers": {"Authorization": "Bearer sk-secret"}},
    )

    with pytest.raises(ValueError, match="reserved LLM extra fields"):
        provider._build_kwargs(request, "deepseek-v4-flash")


def test_provider_allows_non_reserved_extra_fields() -> None:
    with (
        patch("infrastructure.llm.providers.httpx.AsyncClient", autospec=True),
        patch("infrastructure.llm.providers.AsyncOpenAI", autospec=True),
    ):
        provider = OpenAIProvider(
            api_key="test-key",
            base_url="https://opencode.ai/zen/go/v1",
            default_model="deepseek-v4-flash",
        )

    kwargs = provider._build_kwargs(
        LLMCallRequest(
            model="deepseek-v4-flash",
            messages=[LLMMessage(role="user", content="hi")],
            extra={"reasoning_effort": "low"},
        ),
        "deepseek-v4-flash",
    )

    assert kwargs["reasoning_effort"] == "low"


def test_provider_adds_json_keyword_for_json_object_mode() -> None:
    with (
        patch("infrastructure.llm.providers.httpx.AsyncClient", autospec=True),
        patch("infrastructure.llm.providers.AsyncOpenAI", autospec=True),
    ):
        provider = OpenAIProvider(
            api_key="test-key",
            base_url="https://api.deepseek.com/v1",
            default_model="deepseek-v4-flash",
        )

    request = LLMCallRequest(
        model="deepseek-v4-flash",
        messages=[
            LLMMessage(role="system", content="Only return the requested schema."),
            LLMMessage(role="user", content="Generate the proposal."),
        ],
        response_format={"type": "json_object"},
    )

    kwargs = provider._build_kwargs(request, "deepseek-v4-flash")

    assert "JSON" in kwargs["messages"][0]["content"]
    assert request.messages[0].content == "Only return the requested schema."


def test_provider_does_not_duplicate_existing_json_object_instruction() -> None:
    with (
        patch("infrastructure.llm.providers.httpx.AsyncClient", autospec=True),
        patch("infrastructure.llm.providers.AsyncOpenAI", autospec=True),
    ):
        provider = OpenAIProvider(
            api_key="test-key",
            base_url="https://api.deepseek.com/v1",
            default_model="deepseek-v4-flash",
        )

    kwargs = provider._build_kwargs(
        LLMCallRequest(
            model="deepseek-v4-flash",
            messages=[LLMMessage(role="user", content="Return a JSON object.")],
            response_format={"type": "json_object"},
        ),
        "deepseek-v4-flash",
    )

    assert kwargs["messages"] == [
        {"role": "user", "content": "Return a JSON object."}
    ]


def test_provider_sends_thinking_through_extra_body() -> None:
    with (
        patch("infrastructure.llm.providers.httpx.AsyncClient", autospec=True),
        patch("infrastructure.llm.providers.AsyncOpenAI", autospec=True),
    ):
        provider = OpenAIProvider(
            api_key="test-key",
            base_url="https://opencode.ai/zen/go/v1",
            default_model="deepseek-v4-flash",
        )

    kwargs = provider._build_kwargs(
        LLMCallRequest(
            model="deepseek-v4-flash",
            messages=[LLMMessage(role="user", content="hi")],
            extra={
                "thinking": {"type": "enabled"},
                "reasoning_effort": "max",
            },
        ),
        "deepseek-v4-flash",
    )

    assert "thinking" not in kwargs
    assert kwargs["extra_body"] == {"thinking": {"type": "enabled"}}
    assert kwargs["reasoning_effort"] == "max"
