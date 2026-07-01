"""
LLM 客户端封装

LLMClient 是 Infrastructure 层的核心入口，封装：
- Provider 选择与调用
- 普通 JSON 调用与流式输出
- 自动重试（指数退避）
- Token 和调用耗时记录
- 结构化输出修复（重试 + 校验）
"""

from __future__ import annotations

import json
import logging
import typing
from collections.abc import AsyncIterator
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from core.config import get_settings
from infrastructure.llm.errors import LLMInvalidResponseError
from infrastructure.llm.profiles import LLM_API_KEY_FIELD, get_llm_profile
from infrastructure.llm.providers import get_provider
from infrastructure.llm.retry import retry_with_backoff
from infrastructure.llm.schemas import (
    LLMCallRequest,
    LLMCallResponse,
    LLMMessage,
    LLMStreamChunk,
)

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)
_TRUNCATION_RETRY_MAX_TOKENS = 40000
_TOKEN_LIMIT_PROXIMITY = 0.95


def _looks_truncated_response(
    *,
    finish_reason: str,
    completion_tokens: int,
    max_tokens: int | None,
) -> bool:
    if finish_reason == "length":
        return True
    if max_tokens is None or max_tokens <= 0:
        return False
    return completion_tokens >= int(max_tokens * _TOKEN_LIMIT_PROXIMITY)


def _expanded_token_budget(max_tokens: int | None) -> int:
    if max_tokens is None or max_tokens <= 0:
        return _TRUNCATION_RETRY_MAX_TOKENS
    return min(max_tokens * 2, _TRUNCATION_RETRY_MAX_TOKENS)


class LLMClient:
    """LLM 客户端

    封装 LLM 调用的完整流程，是 Infrastructure 层提供给业务模块的主要接口。

    用法:
        client = LLMClient()
        # 普通调用
        resp = await client.generate(request)
        # 结构化 JSON 输出
        result = await client.generate_structured(request, MySchema)
        # 流式调用
        async for chunk in client.generate_stream(request):
            ...
    """

    def __init__(self, provider_name: str = "openai", **provider_kwargs: Any) -> None:
        self._provider = get_provider(provider_name, **provider_kwargs)
        self._settings = get_settings()
        self._default_model = (
            provider_kwargs.get("default_model") or self._settings.llm_model
        )

    @classmethod
    def from_project_settings(
        cls,
        project_settings: dict[str, Any] | None,
        **provider_kwargs: Any,
    ) -> LLMClient:
        """Build an OpenAI-compatible client from ``project.settings["llm"]``.

        Project-level settings override the global env defaults only when set.
        Missing values still fall back to ``core.config.Settings`` inside the
        provider, so legacy env-based deployments keep working.
        """
        profile = get_llm_profile(project_settings)
        merged_kwargs = dict(provider_kwargs)
        if profile.get(LLM_API_KEY_FIELD):
            merged_kwargs["api_key"] = profile[LLM_API_KEY_FIELD]
        if profile.get("base_url"):
            merged_kwargs["base_url"] = profile["base_url"]
        if profile.get("model"):
            merged_kwargs["default_model"] = profile["model"]
        return cls(provider_name="openai", **merged_kwargs)

    async def close(self) -> None:
        """关闭 LLMClient 并释放 provider HTTP 连接

        （Bug C2: 防止 HTTP 连接泄漏）
        """
        if hasattr(self, "_provider") and hasattr(self._provider, "close"):
            await self._provider.close()

    async def switch_provider(self, provider_name: str, **provider_kwargs: Any) -> None:
        """切换 provider，旧 provider 会被关闭

        （Bug C2: 切换时释放旧连接）
        """
        if hasattr(self, "_provider") and hasattr(self._provider, "close"):
            await self._provider.close()
        self._provider = get_provider(provider_name, **provider_kwargs)
        self._default_model = (
            provider_kwargs.get("default_model") or self._settings.llm_model
        )

    @property
    def provider(self) -> str:
        """当前使用的 provider 名称"""
        return self._provider.name

    @property
    def model_name(self) -> str:
        """当前默认的 LLM 模型名称"""
        return self._default_model

    async def generate(self, request: LLMCallRequest) -> LLMCallResponse:
        """执行 LLM 调用（带自动重试）

        Args:
            request: 调用请求参数

        Returns:
            LLM 调用响应

        Raises:
            LLMError: 所有重试均失败
        """
        return await retry_with_backoff(
            self._provider.generate,
            max_attempts=self._settings.llm_retry_max_attempts,
            base_delay=self._settings.llm_retry_base_delay,
            max_delay=self._settings.llm_retry_max_delay,
            request=request,
        )

    async def generate_stream(
        self,
        request: LLMCallRequest,
    ) -> AsyncIterator[LLMStreamChunk]:
        """流式调用 LLM（带自动重试）

        Args:
            request: 调用请求参数

        Yields:
            LLMStreamChunk: 流式输出片段
        """
        # 流式调用也包装重试，但只在开始前重试
        # 一旦流开始后断掉，由上层处理
        stream = await retry_with_backoff(
            self._provider.generate_stream,
            max_attempts=self._settings.llm_retry_max_attempts,
            base_delay=self._settings.llm_retry_base_delay,
            max_delay=self._settings.llm_retry_max_delay,
            request=request,
        )
        async for chunk in stream:
            yield chunk

    async def generate_structured(
        self,
        request: LLMCallRequest,
        schema: type[T],
        *,
        max_fix_attempts: int = 2,
        fix_prompt: str | None = None,
        transport_retries: bool = True,
    ) -> T:
        """调用 LLM 并校验返回结构化 JSON 数据

        流程：
        1. 设置 response_format = {"type": "json_object"}（如果支持）
        2. 调用 LLM
        3. 解析 JSON
        4. 用 Pydantic schema 校验
        5. 如果校验失败，用 fix_prompt 重试

        Args:
            request: 调用请求参数（model, messages 等）
            schema: Pydantic BaseModel 子类，用于校验输出
            max_fix_attempts: 结构化输出修复的最大重试次数
            fix_prompt: 修复提示模板（用于告诉模型输出格式不对）

        Returns:
            校验通过的结构化数据

        Raises:
            LLMInvalidResponseError: 输出格式持续错误
        """
        # 设置 JSON 输出格式
        req = request.model_copy(deep=True)
        if req.response_format is None:
            req.response_format = {"type": "json_object"}
        if req.temperature is None:
            req.temperature = 0.3  # 结构化输出用较低温度

        last_error: Exception | None = None

        for attempt in range(max_fix_attempts + 1):
            try:
                if transport_retries:
                    response = await self.generate(req)
                else:
                    response = await self._provider.generate(req)
                data = json.loads(response.content)
                # Auto-wrap bare list if schema expects a single list field
                # (LLMs often return [...] instead of {"entities": [...]})
                if isinstance(data, list):
                    fields = list(schema.model_fields.keys())
                    if len(fields) == 1:
                        field_annotation = schema.model_fields[fields[0]].annotation
                        if (
                            field_annotation is not None
                            and typing.get_origin(field_annotation) is list
                        ):
                            data = {fields[0]: data}
                return schema.model_validate(data)
            except json.JSONDecodeError as e:
                raw_content = response.content if locals().get("response") else ""
                finish_reason = getattr(response, "finish_reason", "")
                completion_tokens = getattr(response.usage, "completion_tokens", 0)
                max_tokens = req.max_tokens
                error_kind = (
                    "truncated_json"
                    if _looks_truncated_response(
                        finish_reason=finish_reason,
                        completion_tokens=completion_tokens,
                        max_tokens=max_tokens,
                    )
                    else "invalid_json"
                )
                last_error = LLMInvalidResponseError(
                    (
                        f"Invalid JSON response (attempt {attempt + 1}, "
                        f"kind={error_kind}): {e}"
                    ),
                    provider=self._provider.name,
                    raw_response=raw_content,
                )
                logger.warning(
                    (
                        "JSON decode failed, attempt %d/%d: %s "
                        "finish_reason=%s completion_tokens=%s max_tokens=%s "
                        "error_kind=%s"
                    ),
                    attempt + 1,
                    max_fix_attempts + 1,
                    e,
                    finish_reason,
                    completion_tokens,
                    max_tokens,
                    error_kind,
                )
            except ValidationError as e:
                error_kind = "schema_validation"
                last_error = LLMInvalidResponseError(
                    f"Schema validation failed (attempt {attempt + 1}): {e}",
                    provider=self._provider.name,
                )
                logger.warning(
                    "Schema validation failed, attempt %d/%d: %s error_kind=%s",
                    attempt + 1,
                    max_fix_attempts + 1,
                    e,
                    error_kind,
                )

            if attempt < max_fix_attempts:
                if error_kind == "truncated_json":
                    original_budget = req.max_tokens
                    req.max_tokens = _expanded_token_budget(req.max_tokens)
                    fix_msg = (
                        "上一轮输出被截断，JSON 未完整闭合。请从头重新输出完整 JSON，"
                        "不要继续上一段，不要输出 Markdown 或解释。"
                        f"输出必须匹配这个 schema: {schema.model_json_schema()}"
                    )
                    logger.warning(
                        "Retrying truncated structured output with larger budget: "
                        "from=%s to=%s",
                        original_budget,
                        req.max_tokens,
                    )
                else:
                    # 修复模式：追加错误信息，让模型修正输出
                    fix_msg = fix_prompt or (
                        f"Your previous response failed validation. Error: "
                        f"{last_error}\n"
                        f"Please output valid JSON matching this schema: "
                        f"{schema.model_json_schema()}"
                    )
                    req.messages.append(
                        LLMMessage(role="assistant", content=response.content)
                    )
                req.messages.append(LLMMessage(role="user", content=fix_msg))

        raw_response = ""
        if locals().get("response") is not None:
            raw_response = getattr(response, "content", "")
        detail = f": {last_error}" if last_error is not None else ""
        raise LLMInvalidResponseError(
            f"All {max_fix_attempts + 1} structured output attempts failed{detail}",
            provider=self._provider.name,
            raw_response=raw_response,
        )

    async def generate_simple(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        """简化的 LLM 调用（字符串入参，字符串出参）

        适合快速调用场景。

        Args:
            system_prompt: 系统提示词
            user_prompt: 用户提示词
            model: 模型名称（默认使用配置中的 default_model）
            temperature: 温度
            max_tokens: 最大 token 数

        Returns:
            生成的文本内容
        """
        request = LLMCallRequest(
            model=model or self._settings.llm_model,
            messages=[
                LLMMessage(role="system", content=system_prompt),
                LLMMessage(role="user", content=user_prompt),
            ],
            temperature=temperature,
            max_tokens=max_tokens or self._settings.llm_max_tokens,
        )
        response = await self.generate(request)
        return response.content

    async def generate_embedding(
        self,
        text: str | list[str],
        model: str | None = None,
        *,
        is_query: bool = False,
    ) -> list[float] | list[list[float]]:
        """生成文本 embedding。

        根据 EMBEDDING_PROVIDER 配置自动路由：
        - bge_onnx → 本地 BGE ONNX/sentence-transformers worker
        - openai → OpenAI API (保留为 fallback)

        Args:
            text: 单文本或文本列表
            model: embedding 模型名称，默认使用配置中的 embedding_model
            is_query: 是否为查询文本（BGE 模式会自动拼接指令前缀）
        """
        settings = get_settings()
        provider = settings.embedding_provider

        if provider == "bge_onnx":
            from infrastructure.embedding.client import BgeEmbeddingClient

            client = await BgeEmbeddingClient.get_instance()
            try:
                return await client.generate_embedding(text, is_query=is_query)
            except Exception:
                logger.warning("BGE embedding failed, falling back to OpenAI")
                raise

        # OpenAI / 其他远程 API
        return await retry_with_backoff(
            self._provider.generate_embedding,
            max_attempts=self._settings.llm_retry_max_attempts,
            base_delay=self._settings.llm_retry_base_delay,
            max_delay=self._settings.llm_retry_max_delay,
            text=text,
            model=model,
        )

    async def get_usage_stats(self) -> dict[str, Any]:
        """获取当前 provider 状态信息

        Returns:
            包含 provider 名称和配置信息的字典
        """
        return {
            "provider": self._provider.name,
            "default_model": self._settings.llm_model,
            "base_url": self._settings.llm_base_url,
        }
