"""LLM provider transport configuration tests."""

from __future__ import annotations

import logging
import socket
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import httpx
import pytest
from openai import APIConnectionError, APITimeoutError, BadRequestError, RateLimitError

from core.config import Settings, get_settings
from infrastructure.llm.egress import (
    build_public_llm_request_guard,
    validate_user_llm_base_url,
)
from infrastructure.llm.errors import (
    LLMConnectionError,
    LLMQuotaError,
    LLMRateLimitError,
    LLMTimeoutError,
)
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


def test_provider_tracks_independent_embedding_endpoint_identity(monkeypatch) -> None:
    settings = Settings(
        auth_mode="local",
        embedding_base_url=(
            "https://embedding.example.test/v1?api_key=embedding-query-secret"
        ),
    )
    monkeypatch.setattr("infrastructure.llm.providers.get_settings", lambda: settings)
    with (
        patch("infrastructure.llm.providers.httpx.AsyncClient", autospec=True),
        patch("infrastructure.llm.providers.AsyncOpenAI", autospec=True),
    ):
        provider = OpenAIProvider(
            api_key="test-key",
            base_url="https://chat.example.test/v1",
            default_model="test-model",
        )

    assert provider._base_url == "https://chat.example.test/v1"
    assert provider._embedding_base_url == (
        "https://embedding.example.test/v1?api_key=embedding-query-secret"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("sdk_error", "expected_error"),
    [
        (
            APITimeoutError(httpx.Request("POST", "https://provider.example/v1")),
            LLMTimeoutError,
        ),
        (
            APIConnectionError(
                request=httpx.Request("POST", "https://provider.example/v1")
            ),
            LLMConnectionError,
        ),
        (
            RateLimitError(
                "rate limited",
                response=httpx.Response(
                    429,
                    request=httpx.Request(
                        "POST",
                        "https://provider.example/v1",
                    ),
                    headers={"retry-after": "2"},
                ),
                body=None,
            ),
            LLMRateLimitError,
        ),
    ],
)
async def test_provider_maps_mid_stream_availability_errors(
    sdk_error,
    expected_error,
) -> None:
    class FailingStream:
        def __aiter__(self):
            return self

        async def __anext__(self):
            raise sdk_error

    class Completions:
        async def create(self, **_kwargs):
            return FailingStream()

    provider = OpenAIProvider.__new__(OpenAIProvider)
    provider._client = SimpleNamespace(chat=SimpleNamespace(completions=Completions()))
    provider._default_model = "test-model"
    provider._timeout = 15

    stream = await provider.generate_stream(LLMCallRequest(model="test-model"))
    with pytest.raises(expected_error):
        async for _chunk in stream:
            pass


@pytest.mark.parametrize(
    "sdk_error",
    [
        BadRequestError(
            "balance unavailable",
            response=httpx.Response(
                400,
                request=httpx.Request("POST", "https://provider.example/v1"),
            ),
            body={"error": {"code": "insufficient_balance"}},
        ),
        RateLimitError(
            "quota unavailable",
            response=httpx.Response(
                429,
                request=httpx.Request("POST", "https://provider.example/v1"),
            ),
            body={"error": {"code": "insufficient_quota"}},
        ),
        BadRequestError(
            "payment required",
            response=httpx.Response(
                402,
                request=httpx.Request("POST", "https://provider.example/v1"),
            ),
            body=None,
        ),
    ],
)
def test_provider_maps_quota_shapes_to_stable_error(sdk_error) -> None:
    provider = OpenAIProvider.__new__(OpenAIProvider)
    provider._timeout = 15

    mapped = provider._map_provider_error(sdk_error, model="test-model")

    assert isinstance(mapped, LLMQuotaError)
    assert "insufficient" not in str(mapped).lower()


@pytest.mark.asyncio
async def test_provider_maps_remote_embedding_availability_error() -> None:
    request = httpx.Request("POST", "https://embedding.example/v1")

    class Embeddings:
        async def create(self, **_kwargs):
            raise APIConnectionError(request=request)

    provider = OpenAIProvider.__new__(OpenAIProvider)
    provider._embedding_client = SimpleNamespace(embeddings=Embeddings())
    provider._timeout = 15

    with pytest.raises(LLMConnectionError):
        await provider.generate_embedding("text", model="embedding-model")


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
    assert len(kwargs["event_hooks"]["request"]) == 1
    assert openai_cls.call_args.kwargs["http_client"] is http_client
    assert openai_cls.call_args.kwargs["max_retries"] == 0
    get_settings.cache_clear()


@pytest.mark.parametrize(
    "base_url",
    [
        "http://provider.example/v1",
        "https://127.0.0.1/v1",
        "https://[::1]/v1",
        "https://service.internal/v1",
        "https://user:password@provider.example/v1",
        "https://provider.example/v1#fragment",
    ],
)
def test_public_llm_base_url_rejects_unsafe_destinations(base_url: str) -> None:
    settings = Settings(auth_mode="public")
    with pytest.raises(ValueError):
        validate_user_llm_base_url(base_url, settings=settings)


def test_public_llm_base_url_allows_builtin_provider_hostname() -> None:
    settings = Settings(auth_mode="public")
    assert (
        validate_user_llm_base_url(
            "https://api.deepseek.com/v1",
            settings=settings,
        )
        == "https://api.deepseek.com/v1"
    )


def test_public_custom_llm_base_url_requires_explicit_proxy() -> None:
    with pytest.raises(ValueError, match="LLM_PROXY_URL"):
        validate_user_llm_base_url(
            "https://gateway.example.com/openai/v1",
            settings=Settings(auth_mode="public", llm_proxy_url=""),
        )
    assert (
        validate_user_llm_base_url(
            "https://gateway.example.com/openai/v1",
            settings=Settings(
                auth_mode="public",
                llm_proxy_url="http://egress-proxy.internal:8080",
            ),
        )
        == "https://gateway.example.com/openai/v1"
    )


def test_local_llm_base_url_preserves_loopback_http() -> None:
    settings = Settings(auth_mode="local")
    assert (
        validate_user_llm_base_url(
            "http://127.0.0.1:11434/v1",
            settings=settings,
        )
        == "http://127.0.0.1:11434/v1"
    )


@pytest.mark.asyncio
async def test_public_request_guard_rejects_private_dns_result(monkeypatch) -> None:
    monkeypatch.setenv("AUTH_MODE", "public")
    get_settings.cache_clear()
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.8", 443))
        ],
    )
    request = httpx.Request("POST", "https://api.deepseek.com/v1")
    with pytest.raises(httpx.ConnectError, match="public destination"):
        await build_public_llm_request_guard(resolve_dns=True)(request)
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_public_request_guard_allows_public_dns_result(monkeypatch) -> None:
    monkeypatch.setenv("AUTH_MODE", "public")
    get_settings.cache_clear()
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))
        ],
    )
    request = httpx.Request("POST", "https://api.deepseek.com/v1")
    await build_public_llm_request_guard(resolve_dns=True)(request)
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

    assert kwargs["messages"] == [{"role": "user", "content": "Return a JSON object."}]


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
