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

import asyncio
import json
import logging
import re
import typing
from collections.abc import AsyncIterator
from copy import deepcopy
from typing import Any, TypeVar

from pydantic import BaseModel, TypeAdapter, ValidationError

from core.config import get_settings
from infrastructure.llm.errors import LLMInvalidResponseError
from infrastructure.llm.limits import get_llm_limiter
from infrastructure.llm.profiles import (
    ResolvedLLMProfile,
    default_llm_profile,
    resolve_llm_profile,
)
from infrastructure.llm.providers import get_provider
from infrastructure.llm.redaction import redact_diagnostic
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
_FORMAT_REPAIR_RAW_RESPONSE_LIMIT = 12000
_FORMAT_REPAIR_ERROR_LIMIT = 4000


class _StructuredParseError(ValueError):
    """Raised when tolerant structured-output extraction cannot find JSON."""


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


def _structured_retry_delay(
    *,
    attempt: int,
    base_delay: float,
    max_delay: float,
) -> float:
    if base_delay <= 0 or max_delay <= 0:
        return 0.0
    return min(base_delay * (2**attempt), max_delay)


def _schema_list_field(schema: type[BaseModel], field_name: str) -> str | None:
    if field_name not in schema.model_fields:
        return None
    field_annotation = schema.model_fields[field_name].annotation
    if field_annotation is not None and typing.get_origin(field_annotation) is list:
        return field_name
    return None


def _schema_bare_list_field(schema: type[BaseModel]) -> str | None:
    fields = list(schema.model_fields.keys())
    if len(fields) == 1:
        return _schema_list_field(schema, fields[0])
    for candidate in ("scenes", "items", "entities", "aliases", "relations"):
        field_name = _schema_list_field(schema, candidate)
        if field_name is not None:
            return field_name
    return None


def _wrap_bare_list_for_schema(data: Any, schema: type[BaseModel]) -> Any:
    if not isinstance(data, list):
        return data
    field_name = _schema_bare_list_field(schema)
    if field_name is None:
        return data
    return {field_name: data}


def _load_json_candidate(candidate: str) -> Any:
    return json.loads(candidate.strip("\ufeff \t\r\n"))


def _balanced_json_candidate(candidate: str) -> str | None:
    """Close missing object/array brackets when a response is only lightly clipped."""

    text = candidate.strip()
    if not text:
        return None
    opens = {"{": "}", "[": "]"}
    stack: list[str] = []
    in_string = False
    escape = False
    for char in text:
        if escape:
            escape = False
            continue
        if char == "\\":
            escape = True
            continue
        if char == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if char in opens:
            stack.append(opens[char])
            continue
        if char in ("}", "]"):
            if stack and stack[-1] == char:
                stack.pop()
            else:
                return None
    if in_string or not stack:
        return None
    return text + "".join(reversed(stack))


def _parse_structured_json(
    content: str,
    schema: type[BaseModel],
    *,
    allow_truncated_recovery: bool,
) -> tuple[Any, str]:
    """Parse common LLM JSON wrappers without changing business content."""

    text = content.strip()
    if not text:
        raise _StructuredParseError("structured response is empty")

    candidates: list[tuple[str, str]] = [("direct", text)]

    code_block = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if code_block:
        candidates.append(("markdown_code_block", code_block.group(1)))

    first_brace = text.find("{")
    last_brace = text.rfind("}")
    if first_brace >= 0 and last_brace > first_brace:
        candidates.append(("object_slice", text[first_brace : last_brace + 1]))

    first_bracket = text.find("[")
    last_bracket = text.rfind("]")
    if first_bracket >= 0 and last_bracket > first_bracket:
        candidates.append(("array_slice", text[first_bracket : last_bracket + 1]))

    last_error: Exception | None = None
    for strategy, candidate in candidates:
        try:
            return _wrap_bare_list_for_schema(
                _load_json_candidate(candidate),
                schema,
            ), strategy
        except json.JSONDecodeError as exc:
            last_error = exc

    if allow_truncated_recovery:
        for start in (first_brace, first_bracket):
            if start < 0:
                continue
            balanced = _balanced_json_candidate(text[start:])
            if balanced is None:
                continue
            try:
                return _wrap_bare_list_for_schema(
                    _load_json_candidate(balanced),
                    schema,
                ), "balanced_truncated_json"
            except json.JSONDecodeError as exc:
                last_error = exc

    detail = f": {last_error}" if last_error is not None else ""
    raise _StructuredParseError(f"structured response is not valid JSON{detail}")


def _validation_error_summary(exc: ValidationError) -> list[dict[str, Any]]:
    summary: list[dict[str, Any]] = []
    for error in exc.errors():
        location: list[int | str] = []
        for part in error.get("loc", []):
            if isinstance(part, int):
                location.append(part)
            else:
                # Pydantic locations can contain dynamic mapping keys. Even a
                # syntactically ordinary identifier may be private model output,
                # so string segments are never copied into logs or exceptions.
                location.append("[field]")
        raw_type = error.get("type")
        error_type = (
            raw_type
            if isinstance(raw_type, str)
            and re.fullmatch(r"[a-z][a-z0-9_]{0,79}", raw_type)
            else "validation_error"
        )
        summary.append(
            {
                "loc": location,
                "type": error_type,
            }
        )
    return summary


def _structured_error_detail(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        return json.dumps(
            {
                "error_count": exc.error_count(),
                "errors": _validation_error_summary(exc)[:10],
            },
            ensure_ascii=True,
            separators=(",", ":"),
        )
    return redact_diagnostic(exc, limit=500)


def _append_structured_diagnostic(
    diagnostics: list[dict[str, Any]] | None,
    entry: dict[str, Any],
) -> None:
    if diagnostics is not None:
        diagnostics.append(entry)


def _list_item_adapter(schema: type[BaseModel], field_name: str) -> TypeAdapter | None:
    field = schema.model_fields.get(field_name)
    if field is None:
        return None
    annotation = field.annotation
    if typing.get_origin(annotation) is not list:
        return None
    args = typing.get_args(annotation)
    if not args:
        return None
    return TypeAdapter(args[0])


def _apply_partial_list_validation(
    data: Any,
    schema: type[BaseModel],
    *,
    partial_list_fields: set[str] | None,
    diagnostics: list[dict[str, Any]] | None,
    attempt: int,
) -> Any:
    if not partial_list_fields or not isinstance(data, dict):
        return data

    normalized = dict(data)
    for field_name in partial_list_fields:
        value = normalized.get(field_name)
        if not isinstance(value, list) or not value:
            continue
        adapter = _list_item_adapter(schema, field_name)
        if adapter is None:
            continue

        valid_items: list[Any] = []
        errors: list[dict[str, Any]] = []
        for index, item in enumerate(value):
            try:
                valid_items.append(adapter.validate_python(item))
            except ValidationError as exc:
                errors.append(
                    {
                        "index": index,
                        "errors": _validation_error_summary(exc)[:3],
                    }
                )

        if not errors:
            continue

        _append_structured_diagnostic(
            diagnostics,
            {
                "kind": "partial_list_validation",
                "field": field_name,
                "attempt": attempt,
                "kept": len(valid_items),
                "skipped": len(errors),
                "errors": errors[:5],
            },
        )
        if valid_items:
            normalized[field_name] = valid_items

    return normalized


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
        defaults = default_llm_profile()
        self._default_model = str(
            provider_kwargs.pop("default_model", None) or defaults["model"]
        )
        self._default_max_tokens = int(
            provider_kwargs.pop("default_max_tokens", None) or defaults["max_tokens"]
        )
        provider_kwargs["default_model"] = self._default_model
        self._provider = get_provider(provider_name, **provider_kwargs)
        self._settings = get_settings()
        runtime_profile = resolve_llm_profile(
            test_overrides={
                "provider_id": provider_name,
                "api_key": getattr(self._provider, "_api_key", ""),
                "base_url": getattr(self._provider, "_base_url", ""),
                "model": self._default_model,
                "timeout": getattr(self._provider, "_timeout", None),
                "max_tokens": self._default_max_tokens,
            }
        )
        self._profile_summary = runtime_profile.sanitized_summary()
        self._runtime_scope: dict[str, Any] = {"profile_source": "system"}

    @classmethod
    def from_project_settings(
        cls,
        project_settings: dict[str, Any] | None,
        **provider_kwargs: Any,
    ) -> LLMClient:
        """Build an OpenAI-compatible client from ``project.settings["llm"]``.

        Project-level settings override code defaults only when set. Business
        LLM provider fields intentionally do not fall back to ``LLM_*`` env
        vars; API keys are project-level.
        """
        profile = resolve_llm_profile(project_settings)
        return cls.from_resolved_profile(profile, **provider_kwargs)

    @classmethod
    def from_resolved_profile(
        cls,
        profile: ResolvedLLMProfile,
        **provider_kwargs: Any,
    ) -> LLMClient:
        """Build a client from an already resolved profile with provenance."""
        merged_kwargs = {
            **profile.provider_kwargs(),
            "default_max_tokens": profile.max_tokens,
            **provider_kwargs,
        }
        client = cls(provider_name="openai", **merged_kwargs)
        client._profile_summary = profile.sanitized_summary()
        return client

    def bind_runtime_scope(
        self,
        *,
        novel_id: str,
        profile_source: str,
    ) -> None:
        """Attach secret-free workflow scope used by managed-step observability."""
        self._runtime_scope = {
            "novel_id": str(novel_id),
            "profile_source": str(profile_source),
        }

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
        defaults = default_llm_profile()
        self._default_model = str(
            provider_kwargs.pop("default_model", None) or defaults["model"]
        )
        self._default_max_tokens = int(
            provider_kwargs.pop("default_max_tokens", None) or defaults["max_tokens"]
        )
        provider_kwargs["default_model"] = self._default_model
        self._provider = get_provider(provider_name, **provider_kwargs)

    @property
    def provider(self) -> str:
        """当前使用的 provider 名称"""
        return self._provider.name

    @property
    def model_name(self) -> str:
        """当前默认的 LLM 模型名称"""
        return self._default_model

    @property
    def profile_summary(self) -> dict[str, Any]:
        """Return a defensive, secret-free summary of the active profile."""
        return deepcopy(self._profile_summary)

    @property
    def runtime_scope(self) -> dict[str, Any]:
        """Return a defensive copy of secret-free managed-step scope."""
        return deepcopy(self._runtime_scope)

    def resolve_request_defaults(self, request: LLMCallRequest) -> LLMCallRequest:
        """Return a request copy with client-owned defaults materialized."""
        resolved = request.model_copy(deep=True)
        if resolved.max_tokens is None:
            resolved.max_tokens = self._default_max_tokens
        return resolved

    async def generate(self, request: LLMCallRequest) -> LLMCallResponse:
        """执行 LLM 调用（带自动重试）

        Args:
            request: 调用请求参数

        Returns:
            LLM 调用响应

        Raises:
            LLMError: 所有重试均失败
        """
        resolved_request = self.resolve_request_defaults(request)
        limiter = get_llm_limiter()
        return await limiter.run(
            lambda: retry_with_backoff(
                self._provider.generate,
                max_attempts=self._settings.llm_retry_max_attempts,
                base_delay=self._settings.llm_retry_base_delay,
                max_delay=self._settings.llm_retry_max_delay,
                request=resolved_request,
            )
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
        resolved_request = self.resolve_request_defaults(request)
        limiter = get_llm_limiter()
        async with limiter.scope():
            stream = await retry_with_backoff(
                self._provider.generate_stream,
                max_attempts=self._settings.llm_retry_max_attempts,
                base_delay=self._settings.llm_retry_base_delay,
                max_delay=self._settings.llm_retry_max_delay,
                request=resolved_request,
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
        partial_list_fields: set[str] | None = None,
        diagnostics: list[dict[str, Any]] | None = None,
        format_repair_attempts: int = 0,
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
            partial_list_fields: 允许逐项保留有效对象的顶层列表字段
            diagnostics: 可选诊断收集列表（不包含原始响应）
            format_repair_attempts: 常规修复失败后，格式转换兜底次数

        Returns:
            校验通过的结构化数据

        Raises:
            LLMInvalidResponseError: 输出格式持续错误
        """
        # 设置 JSON 输出格式
        req = self.resolve_request_defaults(request)
        if req.response_format is None:
            req.response_format = {"type": "json_object"}
        if req.temperature is None:
            req.temperature = 0.3  # 结构化输出用较低温度

        last_error: Exception | None = None
        last_error_kind: str | None = None
        response: LLMCallResponse | None = None

        for attempt in range(max_fix_attempts + 1):
            try:
                if transport_retries:
                    response = await self.generate(req)
                else:
                    response = await get_llm_limiter().run(
                        lambda: self._provider.generate(req)
                    )
                finish_reason = getattr(response, "finish_reason", "")
                completion_tokens = getattr(response.usage, "completion_tokens", 0)
                max_tokens = req.max_tokens
                truncated_like = _looks_truncated_response(
                    finish_reason=finish_reason,
                    completion_tokens=completion_tokens,
                    max_tokens=max_tokens,
                )
                data, parse_strategy = _parse_structured_json(
                    response.content,
                    schema,
                    allow_truncated_recovery=not truncated_like,
                )
                if parse_strategy != "direct":
                    _append_structured_diagnostic(
                        diagnostics,
                        {
                            "kind": "structured_parse",
                            "strategy": parse_strategy,
                            "attempt": attempt + 1,
                        },
                    )
                data = _apply_partial_list_validation(
                    data,
                    schema,
                    partial_list_fields=partial_list_fields,
                    diagnostics=diagnostics,
                    attempt=attempt + 1,
                )
                validated = schema.model_validate(data)
                _append_structured_diagnostic(
                    diagnostics,
                    {
                        "kind": "structured_usage",
                        "status": "succeeded",
                        "attempt": attempt + 1,
                        "finish_reason": finish_reason,
                        "completion_tokens": completion_tokens,
                        "max_tokens": max_tokens,
                    },
                )
                return validated
            except _StructuredParseError as e:
                raw_content = response.content if response is not None else ""
                redacted_raw_content = redact_diagnostic(raw_content)
                finish_reason = getattr(response, "finish_reason", "")
                completion_tokens = (
                    getattr(response.usage, "completion_tokens", 0)
                    if response is not None
                    else 0
                )
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
                last_error_kind = error_kind
                last_error = LLMInvalidResponseError(
                    (
                        f"Invalid JSON response (attempt {attempt + 1}, "
                        f"kind={error_kind}): {e}"
                    ),
                    provider=self._provider.name,
                    raw_response=redacted_raw_content,
                )
                logger.warning(
                    (
                        "JSON decode failed, attempt %d/%d: %s "
                        "finish_reason=%s completion_tokens=%s max_tokens=%s "
                        "error_kind=%s"
                    ),
                    attempt + 1,
                    max_fix_attempts + 1,
                    redact_diagnostic(e),
                    finish_reason,
                    completion_tokens,
                    max_tokens,
                    error_kind,
                )
                _append_structured_diagnostic(
                    diagnostics,
                    {
                        "kind": "structured_usage",
                        "status": "failed",
                        "error_kind": error_kind,
                        "attempt": attempt + 1,
                        "finish_reason": finish_reason,
                        "completion_tokens": completion_tokens,
                        "max_tokens": max_tokens,
                    },
                )
            except ValidationError as e:
                error_kind = "schema_validation"
                last_error_kind = error_kind
                validation_detail = _structured_error_detail(e)
                last_error = LLMInvalidResponseError(
                    "Schema validation failed "
                    f"(attempt {attempt + 1}): {validation_detail}",
                    provider=self._provider.name,
                )
                logger.warning(
                    "Schema validation failed, attempt %d/%d: %s error_kind=%s",
                    attempt + 1,
                    max_fix_attempts + 1,
                    validation_detail,
                    error_kind,
                )
                _append_structured_diagnostic(
                    diagnostics,
                    {
                        "kind": "structured_usage",
                        "status": "failed",
                        "error_kind": error_kind,
                        "attempt": attempt + 1,
                        "finish_reason": getattr(response, "finish_reason", ""),
                        "completion_tokens": (
                            getattr(response.usage, "completion_tokens", 0)
                            if response is not None
                            else 0
                        ),
                        "max_tokens": req.max_tokens,
                    },
                )

            if attempt < max_fix_attempts:
                delay = _structured_retry_delay(
                    attempt=attempt,
                    base_delay=self._settings.llm_retry_base_delay,
                    max_delay=self._settings.llm_retry_max_delay,
                )
                if delay > 0:
                    await asyncio.sleep(delay)
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
        if response is not None:
            raw_response = redact_diagnostic(getattr(response, "content", ""))
        if (
            format_repair_attempts > 0
            and last_error_kind != "truncated_json"
            and response is not None
        ):
            try:
                return await self._repair_structured_format(
                    req,
                    schema,
                    raw_content=response.content,
                    error_detail=str(last_error or ""),
                    attempts=format_repair_attempts,
                    transport_retries=transport_retries,
                    partial_list_fields=partial_list_fields,
                    diagnostics=diagnostics,
                )
            except LLMInvalidResponseError as exc:
                last_error = exc
                raw_response = exc.raw_response or raw_response

        detail = f": {last_error}" if last_error is not None else ""
        raise LLMInvalidResponseError(
            f"All {max_fix_attempts + 1} structured output attempts failed{detail}",
            provider=self._provider.name,
            raw_response=raw_response,
        )

    async def _repair_structured_format(
        self,
        request: LLMCallRequest,
        schema: type[T],
        *,
        raw_content: str,
        error_detail: str,
        attempts: int,
        transport_retries: bool,
        partial_list_fields: set[str] | None,
        diagnostics: list[dict[str, Any]] | None,
    ) -> T:
        last_error: Exception | None = None
        last_raw_response = ""
        for attempt in range(1, attempts + 1):
            repair_req = request.model_copy(deep=True)
            repair_req.temperature = 0
            repair_req.response_format = {"type": "json_object"}
            repair_req.messages = [
                LLMMessage(
                    role="system",
                    content=(
                        "你是 JSON 格式转换器。只把输入转换成目标 JSON schema，"
                        "不得新增事实、删除事实、补剧情、解释或输出 Markdown。"
                        "字段缺失且原文没有信息时使用 schema 默认值或空值。"
                    ),
                ),
                LLMMessage(
                    role="user",
                    content=(
                        "目标 schema:\n"
                        f"{json.dumps(schema.model_json_schema(), ensure_ascii=False)}"
                        "\n\n验证错误摘要:\n"
                        f"{error_detail[:_FORMAT_REPAIR_ERROR_LIMIT]}"
                        "\n\n待转换原始输出:\n"
                        f"{raw_content[:_FORMAT_REPAIR_RAW_RESPONSE_LIMIT]}"
                    ),
                ),
            ]
            try:
                if transport_retries:
                    response = await self.generate(repair_req)
                else:
                    response = await get_llm_limiter().run(
                        lambda: self._provider.generate(repair_req)
                    )
                last_raw_response = redact_diagnostic(response.content)
                truncated_like = _looks_truncated_response(
                    finish_reason=getattr(response, "finish_reason", ""),
                    completion_tokens=getattr(response.usage, "completion_tokens", 0),
                    max_tokens=repair_req.max_tokens,
                )
                data, parse_strategy = _parse_structured_json(
                    response.content,
                    schema,
                    allow_truncated_recovery=not truncated_like,
                )
                data = _apply_partial_list_validation(
                    data,
                    schema,
                    partial_list_fields=partial_list_fields,
                    diagnostics=diagnostics,
                    attempt=attempt,
                )
                result = schema.model_validate(data)
                _append_structured_diagnostic(
                    diagnostics,
                    {
                        "kind": "format_repair",
                        "status": "succeeded",
                        "attempt": attempt,
                        "parse_strategy": parse_strategy,
                    },
                )
                return result
            except (_StructuredParseError, ValidationError) as exc:
                last_error = exc
                error_detail = _structured_error_detail(exc)
                _append_structured_diagnostic(
                    diagnostics,
                    {
                        "kind": "format_repair",
                        "status": "failed",
                        "attempt": attempt,
                        "error": error_detail,
                    },
                )
                if attempt < attempts:
                    delay = _structured_retry_delay(
                        attempt=attempt - 1,
                        base_delay=self._settings.llm_retry_base_delay,
                        max_delay=self._settings.llm_retry_max_delay,
                    )
                    if delay > 0:
                        await asyncio.sleep(delay)

        raise LLMInvalidResponseError(
            "Format repair failed after "
            f"{attempts} attempts: "
            f"{_structured_error_detail(last_error) if last_error else 'unknown'}",
            provider=self._provider.name,
            raw_response=last_raw_response,
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
            model=model or self._default_model,
            messages=[
                LLMMessage(role="system", content=system_prompt),
                LLMMessage(role="user", content=user_prompt),
            ],
            temperature=temperature,
            max_tokens=max_tokens or self._default_max_tokens,
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
        - openai / 其他远程 provider → provider.generate_embedding

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
                logger.warning("BGE embedding failed")
                raise

        # A novel-scoped client owns chat/structured-generation credentials only.
        # Remote embeddings must still resolve exclusively through EMBEDDING_*;
        # never let a project chat profile become an implicit embedding profile.
        if self._runtime_scope.get("novel_id"):
            embedding_client = LLMClient()
            try:
                return await embedding_client.generate_embedding(
                    text,
                    model=model,
                    is_query=is_query,
                )
            finally:
                await embedding_client.close()

        # OpenAI / 其他远程 provider
        return await get_llm_limiter().run(
            lambda: retry_with_backoff(
                self._provider.generate_embedding,
                max_attempts=self._settings.llm_retry_max_attempts,
                base_delay=self._settings.llm_retry_base_delay,
                max_delay=self._settings.llm_retry_max_delay,
                text=text,
                model=model,
            )
        )

    async def get_usage_stats(self) -> dict[str, Any]:
        """获取当前 provider 状态信息

        Returns:
            包含 provider 名称和配置信息的字典
        """
        return {
            "provider": self._provider.name,
            "default_model": self._default_model,
            "base_url": getattr(self._provider, "_base_url", ""),
        }
