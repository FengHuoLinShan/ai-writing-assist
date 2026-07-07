"""
LLM Provider 管理

提供 OpenAI-compatible API 的 Provider 实现。
通过 get_provider() 工厂函数获取 Provider 实例。
"""

from __future__ import annotations

import logging
import ssl
import time
from collections.abc import AsyncIterator
from typing import Any

import httpx
from openai import (
    APIConnectionError,
    APIError,
    APITimeoutError,
    AsyncOpenAI,
    AuthenticationError,
    BadRequestError,
    ContentFilterFinishReasonError,
    RateLimitError,
)

from core.config import get_settings
from infrastructure.llm.errors import (
    LLMAuthError,
    LLMConnectionError,
    LLMContentFilterError,
    LLMError,
    LLMInvalidResponseError,
    LLMRateLimitError,
    LLMTimeoutError,
)
from infrastructure.llm.profiles import default_llm_profile
from infrastructure.llm.redaction import redact_diagnostic
from infrastructure.llm.schemas import (
    LLMCallRequest,
    LLMCallResponse,
    LLMStreamChunk,
    LLMUsage,
)

logger = logging.getLogger(__name__)

_RESERVED_EXTRA_FIELDS = {
    "model",
    "messages",
    "stream",
    "api_key",
    "base_url",
    "headers",
    "authorization",
    "timeout",
}

_EXTRA_BODY_FIELDS = {
    "thinking",
}


class OpenAIProvider:
    """OpenAI-compatible API Provider

    支持 OpenAI、Azure OpenAI、以及任何 OpenAI-compatible 的 API
    （如 Ollama、vLLM、DeepSeek 等）。
    """

    def __init__(
        self,
        api_key: str = "",
        base_url: str = "",
        default_model: str = "",
        timeout: int = 60,
        trust_env: bool | None = None,
        proxy_url: str | None = None,
    ) -> None:
        settings = get_settings()
        defaults = default_llm_profile()
        self._api_key = api_key or ""
        self._base_url = base_url or str(defaults["base_url"])
        self._default_model = default_model or str(defaults["model"])
        self._timeout = timeout or settings.llm_timeout
        self._trust_env = settings.llm_trust_env if trust_env is None else trust_env
        self._proxy_url = settings.llm_proxy_url if proxy_url is None else proxy_url

        self._http_client = self._build_http_client()

        self._client = AsyncOpenAI(
            api_key=self._api_key,
            base_url=self._base_url,
            timeout=self._timeout,
            http_client=self._http_client,
        )

        # 独立的 embedding 客户端：当配置了 EMBEDDING_BASE_URL 时使用独立端点
        _emb_base_url = settings.embedding_base_url
        _emb_api_key = settings.embedding_api_key or self._api_key
        if _emb_base_url:
            self._embedding_http_client = self._build_http_client()
            self._embedding_client = AsyncOpenAI(
                api_key=_emb_api_key,
                base_url=_emb_base_url,
                timeout=self._timeout,
                http_client=self._embedding_http_client,
            )
        else:
            self._embedding_http_client = None
            self._embedding_client = self._client

        logger.info(
            "OpenAIProvider initialized — base_url=%s, default_model=%s",
            self._base_url,
            self._default_model,
        )

    @property
    def name(self) -> str:
        return "openai"

    async def close(self) -> None:
        """关闭 HTTP 连接，释放 AsyncOpenAI 客户端资源

        （Bug C2: 防止 HTTP 连接泄漏）
        """
        if hasattr(self, "_client"):
            await self._client.close()
        if (
            hasattr(self, "_embedding_client")
            and self._embedding_client is not self._client
        ):
            await self._embedding_client.close()
            logger.debug("OpenAIProvider embedding HTTP connection closed")

    def _build_http_client(self) -> httpx.AsyncClient:
        kwargs: dict[str, Any] = {
            "timeout": self._timeout,
            "trust_env": self._trust_env,
        }
        if self._proxy_url:
            kwargs["proxy"] = self._proxy_url
        return httpx.AsyncClient(**kwargs)

    async def generate(self, request: LLMCallRequest) -> LLMCallResponse:
        """调用 LLM 并返回完整响应"""
        start_time = time.monotonic()
        model = request.model or self._default_model

        kwargs = self._build_kwargs(request, model)
        logger.debug("LLM call — model=%s, messages=%s", model, len(request.messages))

        try:
            response = await self._client.chat.completions.create(
                **kwargs,
            )  # type: ignore[arg-type]
        except APITimeoutError as e:
            raise LLMTimeoutError(
                f"OpenAI API timeout after {self._timeout}s",
                provider=self.name,
                model=model,
                timeout=self._timeout,
            ) from e
        except RateLimitError as e:
            retry_after = (
                float(e.response.headers.get("retry-after", "5")) if e.response else 5.0
            )
            raise LLMRateLimitError(
                f"OpenAI rate limit: {redact_diagnostic(e)}",
                provider=self.name,
                model=model,
                retry_after=retry_after,
            ) from e
        except AuthenticationError as e:
            raise LLMAuthError(
                f"OpenAI auth failed: {redact_diagnostic(e)}",
                provider=self.name,
                model=model,
            ) from e
        except BadRequestError as e:
            raise LLMInvalidResponseError(
                f"OpenAI bad request: {redact_diagnostic(e)}",
                provider=self.name,
                model=model,
            ) from e
        except ContentFilterFinishReasonError as e:
            raise LLMContentFilterError(
                "Content filter triggered",
                provider=self.name,
                model=model,
                filter_reason=str(e),
            ) from e
        except APIConnectionError as e:
            kind = _classify_connection_error(e)
            raise LLMConnectionError(
                f"OpenAI connection failed ({kind}): {redact_diagnostic(e)}",
                provider=self.name,
                model=model,
                error_kind=kind,
            ) from e
        except APIError as e:
            raise LLMError(
                f"OpenAI API error: {redact_diagnostic(e)}",
                provider=self.name,
                model=model,
            ) from e

        elapsed_ms = (time.monotonic() - start_time) * 1000

        choice = response.choices[0] if response.choices else None
        content = choice.message.content or "" if choice else ""
        finish_reason = choice.finish_reason or "" if choice else ""

        usage = LLMUsage()
        if response.usage:
            usage.prompt_tokens = response.usage.prompt_tokens or 0
            usage.completion_tokens = response.usage.completion_tokens or 0
            usage.total_tokens = response.usage.total_tokens or 0

        return LLMCallResponse(
            content=content,
            finish_reason=finish_reason,
            usage=usage,
            model=response.model or model,
            provider=self.name,
            latency_ms=round(elapsed_ms, 1),
            raw=response.model_dump() if hasattr(response, "model_dump") else {},
        )

    async def generate_stream(
        self,
        request: LLMCallRequest,
    ) -> AsyncIterator[LLMStreamChunk]:
        """流式调用 LLM，逐个 chunk 返回"""
        model = request.model or self._default_model
        kwargs = self._build_kwargs(request, model)
        kwargs["stream"] = True

        logger.debug("LLM stream call — model=%s", model)

        try:
            stream = await self._client.chat.completions.create(
                **kwargs,
            )  # type: ignore[arg-type]
        except APITimeoutError as e:
            raise LLMTimeoutError(
                f"OpenAI API timeout after {self._timeout}s",
                provider=self.name,
                model=model,
                timeout=self._timeout,
            ) from e
        except RateLimitError as e:
            retry_after = (
                float(e.response.headers.get("retry-after", "5")) if e.response else 5.0
            )
            raise LLMRateLimitError(
                f"OpenAI rate limit: {redact_diagnostic(e)}",
                provider=self.name,
                model=model,
                retry_after=retry_after,
            ) from e
        except AuthenticationError as e:
            raise LLMAuthError(
                f"OpenAI auth failed: {redact_diagnostic(e)}",
                provider=self.name,
                model=model,
            ) from e
        except APIConnectionError as e:
            kind = _classify_connection_error(e)
            raise LLMConnectionError(
                f"OpenAI connection failed ({kind}): {redact_diagnostic(e)}",
                provider=self.name,
                model=model,
                error_kind=kind,
            ) from e
        except APIError as e:
            raise LLMError(
                f"OpenAI API error: {redact_diagnostic(e)}",
                provider=self.name,
                model=model,
            ) from e

        async for chunk in stream:
            delta = chunk.choices[0].delta if chunk.choices else None
            content = delta.content or "" if delta else ""
            finish = chunk.choices[0].finish_reason if chunk.choices else None

            usage = None
            if chunk.usage:
                usage = LLMUsage(
                    prompt_tokens=chunk.usage.prompt_tokens or 0,
                    completion_tokens=chunk.usage.completion_tokens or 0,
                    total_tokens=chunk.usage.total_tokens or 0,
                )

            yield LLMStreamChunk(
                content=content,
                finish_reason=finish,
                usage=usage,
            )

    async def generate_embedding(
        self,
        text: str | list[str],
        model: str | None = None,
    ) -> list[float] | list[list[float]]:
        """生成文本的 embedding 向量

        Args:
            text: 单文本或文本列表（批量）
            model: embedding 模型名称，默认使用配置中的 embedding_model

        Returns:
            单文本 → list[float]（一维向量）
            文本列表 → list[list[float]]（批量向量）

        Raises:
            ValueError: 输入为空
        """
        if isinstance(text, str):
            if not text.strip():
                raise ValueError("Input text is empty")
        elif isinstance(text, list):
            if not text:
                raise ValueError("Input text list is empty")
            if any(not t.strip() for t in text):
                raise ValueError("Input text list contains empty string")

        model_name = model or get_settings().embedding_model

        response = await self._embedding_client.embeddings.create(
            model=model_name,
            input=text,
        )

        embeddings = [item.embedding for item in response.data]

        if isinstance(text, str):
            return embeddings[0]
        return embeddings

    def _build_kwargs(self, request: LLMCallRequest, model: str) -> dict[str, Any]:
        """构建 OpenAI SDK 调用参数"""
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": [m.model_dump() for m in request.messages],
        }
        if request.temperature is not None:
            kwargs["temperature"] = request.temperature
        if request.max_tokens is not None:
            kwargs["max_tokens"] = request.max_tokens
        if request.response_format is not None:
            kwargs["response_format"] = request.response_format
        if request.stop is not None:
            kwargs["stop"] = request.stop
        if request.top_p is not None:
            kwargs["top_p"] = request.top_p
        if request.frequency_penalty is not None:
            kwargs["frequency_penalty"] = request.frequency_penalty
        if request.presence_penalty is not None:
            kwargs["presence_penalty"] = request.presence_penalty
        if request.seed is not None:
            kwargs["seed"] = request.seed
        reserved_extra = _RESERVED_EXTRA_FIELDS.intersection(
            key.lower() for key in request.extra
        )
        if reserved_extra:
            fields = ", ".join(sorted(reserved_extra))
            raise ValueError(f"reserved LLM extra fields are not allowed: {fields}")

        extra_body = dict(request.extra.get("extra_body") or {})
        for key, value in request.extra.items():
            if key in _EXTRA_BODY_FIELDS:
                extra_body[key] = value
                continue
            if key == "extra_body":
                continue
            kwargs[key] = value
        if extra_body:
            kwargs["extra_body"] = extra_body
        return kwargs


# ============================================================
# Provider 工厂
# ============================================================


def get_provider(name: str = "openai", **kwargs: Any) -> OpenAIProvider:
    """获取 Provider 实例

    Args:
        name: Provider 名称（目前仅支持 "openai"）
        **kwargs: 传递给 Provider 构造函数的参数

    Returns:
        OpenAIProvider 实例

    Raises:
        ValueError: 未知的 provider 名称
    """
    if name != "openai":
        raise ValueError(f"Unknown provider: {name}. Available: ['openai']")
    return OpenAIProvider(**kwargs)


def _classify_connection_error(error: BaseException) -> str:
    """Classify OpenAI/httpx connection errors without logging secrets."""
    chain: list[BaseException] = []
    current: BaseException | None = error
    while current is not None and len(chain) < 8:
        chain.append(current)
        current = current.__cause__

    names = " ".join(type(item).__name__ for item in chain).lower()
    text = " ".join(str(item) for item in chain).lower()
    combined = f"{names} {text}"

    if "proxy" in combined or "connect tunnel" in combined or "503" in combined:
        return "proxy_error"
    if "ssl" in combined or "tls" in combined or "eof" in combined:
        return "tls_error"
    if "name or service" in combined or "nodename" in combined:
        return "dns_error"
    if any(isinstance(item, ssl.SSLError) for item in chain):
        return "tls_error"
    return "connection_error"
