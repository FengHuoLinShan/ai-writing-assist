"""LLM provider transport configuration tests."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from infrastructure.llm.providers import OpenAIProvider


def test_provider_disables_system_proxy_by_default() -> None:
    """OpenAI SDK should not implicitly use macOS/system proxies."""
    with (
        patch("infrastructure.llm.providers.httpx.AsyncClient") as http_client_cls,
        patch("infrastructure.llm.providers.AsyncOpenAI") as openai_cls,
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


def test_provider_uses_explicit_proxy_when_configured() -> None:
    """Explicit proxy configuration should be the only proxy path."""
    with (
        patch("infrastructure.llm.providers.httpx.AsyncClient") as http_client_cls,
        patch("infrastructure.llm.providers.AsyncOpenAI"),
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
