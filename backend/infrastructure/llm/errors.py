"""
LLM 自定义异常定义

按调用阶段区分异常类型，便于 retry 逻辑判断是否可重试。
"""

from __future__ import annotations


class LLMError(Exception):
    """LLM 调用基类异常"""

    def __init__(
        self,
        message: str,
        *,
        provider: str = "",
        model: str = "",
        error_kind: str = "",
    ) -> None:
        self.provider = provider
        self.model = model
        self.error_kind = error_kind
        super().__init__(message)


class LLMTimeoutError(LLMError):
    """LLM 调用超时 — 可重试"""

    def __init__(
        self,
        message: str = "LLM call timed out",
        *,
        provider: str = "",
        model: str = "",
        timeout: int = 0,
    ) -> None:
        self.timeout = timeout
        super().__init__(message, provider=provider, model=model)


class LLMConnectionError(LLMError):
    """LLM 网络连接失败 — 可重试，并携带可诊断错误类型"""

    def __init__(
        self,
        message: str = "LLM connection failed",
        *,
        provider: str = "",
        model: str = "",
        error_kind: str = "connection_error",
    ) -> None:
        super().__init__(
            message,
            provider=provider,
            model=model,
            error_kind=error_kind,
        )


class LLMRateLimitError(LLMError):
    """LLM 调用频率限制 — 可重试（带退避）"""

    def __init__(
        self,
        message: str = "LLM rate limit exceeded",
        *,
        provider: str = "",
        model: str = "",
        retry_after: float = 0.0,
    ) -> None:
        self.retry_after = retry_after
        super().__init__(message, provider=provider, model=model)


class LLMInvalidResponseError(LLMError):
    """LLM 返回了非法响应（格式错误、校验失败等）— 通常不可重试"""

    def __init__(
        self,
        message: str = "Invalid LLM response",
        *,
        provider: str = "",
        model: str = "",
        raw_response: str = "",
    ) -> None:
        self.raw_response = raw_response
        super().__init__(message, provider=provider, model=model)


class LLMAuthError(LLMError):
    """LLM 认证/授权失败 — 不可重试"""

    def __init__(
        self,
        message: str = "LLM authentication failed",
        *,
        provider: str = "",
        model: str = "",
    ) -> None:
        super().__init__(message, provider=provider, model=model)


class LLMContentFilterError(LLMError):
    """LLM 内容过滤/审查触发 — 不可重试"""

    def __init__(
        self,
        message: str = "LLM content filter triggered",
        *,
        provider: str = "",
        model: str = "",
        filter_reason: str = "",
    ) -> None:
        self.filter_reason = filter_reason
        super().__init__(message, provider=provider, model=model)
