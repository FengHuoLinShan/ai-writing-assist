"""
LLM 调用重试逻辑

提供 retry_with_backoff 装饰器，支持指数退避重试。
区分可重试错误（超时、频率限制）和不可重试错误（认证失败、格式错误）。
"""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Callable
from functools import wraps
from typing import Any, ParamSpec, TypeVar

from infrastructure.llm.errors import (
    LLMAuthError,
    LLMContentFilterError,
    LLMError,
    LLMInvalidResponseError,
    LLMRateLimitError,
    LLMTimeoutError,
)
from infrastructure.llm.redaction import redact_diagnostic
from shared.constants import LLM_RETRY_BASE_DELAY, LLM_RETRY_MAX_ATTEMPTS

logger = logging.getLogger(__name__)

P = ParamSpec("P")
T = TypeVar("T")


def _is_retryable(error: Exception) -> bool:
    """判断错误是否可重试

    可重试：
    - LLMTimeoutError: 超时，可能是临时网络问题
    - LLMRateLimitError: 频率限制，退避后可重试

    不可重试：
    - LLMAuthError: 认证失败，重试也没用
    - LLMContentFilterError: 内容审查，应调整输入
    - LLMInvalidResponseError: 响应格式错误，模型本身的问题
    """
    if isinstance(error, (LLMTimeoutError, LLMRateLimitError)):
        return True
    if isinstance(error, (LLMAuthError, LLMContentFilterError, LLMInvalidResponseError)):
        return False
    # LLMError 可重试（通用 API 错误）
    if isinstance(error, LLMError):
        return True
    return False


def _get_retry_after(error: Exception) -> float:
    """从可重试错误中提取推荐的等待时间"""
    if isinstance(error, LLMRateLimitError) and error.retry_after > 0:
        return float(error.retry_after)
    return LLM_RETRY_BASE_DELAY


async def retry_with_backoff(
    fn: Callable[..., Any],
    *,
    max_attempts: int = LLM_RETRY_MAX_ATTEMPTS,
    base_delay: float = LLM_RETRY_BASE_DELAY,
    max_delay: float = 60.0,
    **kwargs: Any,
) -> Any:
    """使用指数退避重试执行异步函数

    Args:
        fn: 要执行的异步函数
        max_attempts: 最大重试次数（默认 3）
        base_delay: 基础等待时间（默认 1.0 秒）
        max_delay: 最大等待时间（默认 60 秒）
        **kwargs: 传递给 fn 的参数

    Returns:
        fn 的返回值

    Raises:
        LLMError: 所有重试均失败时抛出最后一次的异常
    """
    last_error: Exception | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            return await fn(**kwargs)
        except Exception as e:
            last_error = e
            diagnostic = redact_diagnostic(e, limit=500)

            if not _is_retryable(e):
                logger.warning(
                    "Non-retryable error at attempt %d/%d: %s",
                    attempt,
                    max_attempts,
                    diagnostic,
                )
                raise

            if attempt == max_attempts:
                logger.error(
                    "All %d retry attempts exhausted: %s",
                    max_attempts,
                    diagnostic,
                )
                raise

            # 计算退避时间：base_delay * 2^(attempt-1) + jitter
            delay = min(base_delay * (2 ** (attempt - 1)), max_delay)
            retry_after = _get_retry_after(e)
            if retry_after > delay:
                delay = retry_after
            # 添加 ±25% 的 jitter 防止 thundering herd
            jitter = random.uniform(0.75, 1.25)
            actual_delay = delay * jitter

            logger.info(
                "Retry attempt %d/%d after %.2fs (base: %.2f, jitter: %.2f) — %s",
                attempt,
                max_attempts,
                actual_delay,
                delay,
                jitter,
                diagnostic,
            )
            await asyncio.sleep(actual_delay)

    # 理论上不会到这里，但为类型安全保留
    if last_error:
        raise last_error
    raise LLMError("Retry failed for unknown reason")


def retryable(
    max_attempts: int = LLM_RETRY_MAX_ATTEMPTS,
    base_delay: float = LLM_RETRY_BASE_DELAY,
    max_delay: float = 60.0,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """重试装饰器

    用法:
        @retryable(max_attempts=3, base_delay=1.0)
        async def my_llm_call(...):
            ...
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            return await retry_with_backoff(
                lambda: func(*args, **kwargs),
                max_attempts=max_attempts,
                base_delay=base_delay,
                max_delay=max_delay,
            )

        return wrapper

    return decorator
