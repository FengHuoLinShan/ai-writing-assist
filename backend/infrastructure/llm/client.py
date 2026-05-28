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
from collections.abc import AsyncIterator
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from core.config import get_settings
from infrastructure.llm.errors import LLMInvalidResponseError
from infrastructure.llm.providers import get_provider
from infrastructure.llm.retry import retry_with_backoff
from infrastructure.llm.schemas import (
    LLMCallRequest,
    LLMCallResponse,
    LLMMessage,
    LLMStreamChunk,
)
from shared.constants import LLM_RETRY_BASE_DELAY, LLM_RETRY_MAX_ATTEMPTS

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


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

    @property
    def provider(self) -> str:
        """当前使用的 provider 名称"""
        return self._provider.name

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
            max_attempts=LLM_RETRY_MAX_ATTEMPTS,
            base_delay=LLM_RETRY_BASE_DELAY,
            request=request,
        )

    async def generate_stream(
        self, request: LLMCallRequest,
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
            max_attempts=LLM_RETRY_MAX_ATTEMPTS,
            base_delay=LLM_RETRY_BASE_DELAY,
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
                response = await self.generate(req)
                data = json.loads(response.content)
                return schema.model_validate(data)
            except json.JSONDecodeError as e:
                raw_content = response.content if locals().get("response") else ""
                last_error = LLMInvalidResponseError(
                    f"Invalid JSON response (attempt {attempt+1}): {e}",
                    provider=self._provider.name,
                    raw_response=raw_content,
                )
                logger.warning(
                    "JSON decode failed, attempt %d/%d: %s",
                    attempt + 1,
                    max_fix_attempts + 1,
                    e,
                )
            except ValidationError as e:
                last_error = LLMInvalidResponseError(
                    f"Schema validation failed (attempt {attempt+1}): {e}",
                    provider=self._provider.name,
                )
                logger.warning(
                    "Schema validation failed, attempt %d/%d: %s",
                    attempt + 1,
                    max_fix_attempts + 1,
                    e,
                )

            if attempt < max_fix_attempts:
                # 修复模式：追加错误信息，让模型修正输出
                fix_msg = fix_prompt or (
                    f"Your previous response failed validation. Error: {last_error}\n"
                    f"Please output valid JSON matching this schema: {schema.model_json_schema()}"
                )
                req.messages.append(LLMMessage(role="assistant", content=response.content))
                req.messages.append(LLMMessage(role="user", content=fix_msg))

        raise LLMInvalidResponseError(
            f"All {max_fix_attempts + 1} structured output attempts failed",
            provider=self._provider.name,
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
    ) -> list[float] | list[list[float]]:
        """生成文本 embedding（带自动重试）。

        Args:
            text: 单文本或文本列表
            model: embedding 模型名称，默认使用配置中的 embedding_model
        """
        return await retry_with_backoff(
            self._provider.generate_embedding,
            max_attempts=LLM_RETRY_MAX_ATTEMPTS,
            base_delay=LLM_RETRY_BASE_DELAY,
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
