"""Single-turn Codex text steps; native host tools are never exposed."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import time
from pathlib import Path
from uuid import uuid4

from core.config import get_settings
from infrastructure.llm.cli_agent import (
    CODEX_TEXT_ADAPTER_VERSION,
    CLIAgentError,
    CLISpec,
    run_cli_agent,
)
from infrastructure.llm.codex_identity import codex_login_identity
from infrastructure.llm.errors import LLMError, LLMInvalidResponseError
from infrastructure.llm.schemas import (
    LLMCallResponse,
    LLMMessage,
    LLMStreamChunk,
    LLMToolCall,
    LLMToolDelta,
    LLMUsage,
)

CODEX_MODEL = "gpt-6-luna"
CODEX_EFFORT = "max"
CODEX_BASE_URL = "codex://local"


def codex_text_enabled() -> bool:
    settings = get_settings()
    return settings.auth_mode == "local" and settings.app_env in {
        "development",
        "test",
        "local",
    }


def codex_connection_fingerprint() -> str:
    if not codex_text_enabled():
        raise ValueError("Codex 文本连接仅用于本机单用户模式")
    command = shutil.which(os.environ.get("CODEX_CLI_COMMAND", "codex"))
    if not command:
        raise ValueError("本机尚未安装 Codex CLI，请安装并登录后验证连接")
    identity = [
        "chatgpt-login-v2",
        codex_login_identity(),
        str(Path(command).resolve()),
        str(Path(command).resolve().stat().st_mtime_ns),
        str(os.getuid()),
        str(Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))).resolve()),
    ]
    return hashlib.sha256(json.dumps(identity).encode()).hexdigest()


def native_schema(schema: dict) -> dict | None:
    """Keep open maps intact in an envelope instead of silently closing them."""
    result = json.loads(json.dumps(schema))

    def visit(node):
        if isinstance(node, dict):
            node.pop("default", None)
            if not node or node.get("additionalProperties") not in (None, False):
                return False
            if node.get("type") == "object":
                if not isinstance(node.get("properties"), dict):
                    return False
                node["additionalProperties"] = False
                node["required"] = list(node["properties"])
            return all(visit(v) for v in node.values() if isinstance(v, (dict, list)))
        if isinstance(node, list):
            return all(visit(v) for v in node)
        return True

    return result if visit(result) else None


class CodexProvider:
    name = "codex"

    def __init__(
        self,
        *,
        default_model=CODEX_MODEL,
        timeout=900,
        base_url=CODEX_BASE_URL,
        api_key="",
        connection_fingerprint=None,
    ):
        current = codex_connection_fingerprint()
        if default_model != CODEX_MODEL or api_key or base_url != CODEX_BASE_URL:
            raise ValueError("Codex 使用本机登录态与 Luna/max，不接受 API Key 或远程地址")
        if connection_fingerprint is not None and connection_fingerprint != current:
            raise ValueError("Codex 本机连接已变化，请重新验证")
        self.command = shutil.which(os.environ.get("CODEX_CLI_COMMAND", "codex"))
        self.request_timeout = timeout
        self._base_url = base_url
        self._api_key = ""
        self._connection_fingerprint = current

    def validate_connection(self) -> None:
        if codex_connection_fingerprint() != self._connection_fingerprint:
            raise ValueError("Codex 本机登录身份或 CLI 已变化，请重新验证")

    async def generate(self, request, *, complete_stream=False):
        self.validate_connection()
        if (
            request.model != CODEX_MODEL
            or request.extra.get("reasoning_effort", CODEX_EFFORT) != CODEX_EFFORT
            or request.extra.get("codex_text_adapter_version", CODEX_TEXT_ADAPTER_VERSION)
            != CODEX_TEXT_ADAPTER_VERSION
        ):
            raise LLMError(
                "Codex 文本步骤固定使用 Luna/max",
                provider=self.name,
                error_kind="codex_configuration",
            )
        started = time.monotonic()
        format_schema = (request.response_format or {}).get("json_schema", {})
        if not isinstance(format_schema, dict):
            raise ValueError("json_schema must be an object")
        schema = format_schema.get("schema")
        if schema is not None and not isinstance(schema, dict):
            raise ValueError("schema must be an object")
        constrained = native_schema(schema) if schema and not request.tools else None
        props = {"content": {"type": "string"}}
        definitions = {}
        if constrained is not None:
            definitions = constrained.pop("$defs", {})
            props = {"data": constrained}
        if request.tools:
            props["tool_calls"] = {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "enum": [t.name for t in request.tools],
                        },
                        "arguments": {"type": "string"},
                    },
                    "required": ["name", "arguments"],
                    "additionalProperties": False,
                },
            }
            if request.tool_choice == "none":
                props["tool_calls"]["maxItems"] = 0
            if request.tool_choice == "required":
                props["tool_calls"]["minItems"] = 1
        output_schema = {
            "type": "object",
            "properties": props,
            "required": list(props),
            "additionalProperties": False,
            **({"$defs": definitions} if definitions else {}),
        }
        payload = {
            "messages": [m.model_dump() for m in request.messages],
            "response_format": request.response_format,
            "tools": [t.model_dump() for t in request.tools],
            "tool_choice": request.tool_choice,
            "target_output_tokens": request.max_tokens,
        }
        with tempfile.TemporaryDirectory(prefix="novelcraft-codex-text-") as directory:
            try:
                result = await run_cli_agent(
                    CLISpec(
                        kind="codex",
                        command=self.command,
                        prompt=json.dumps(payload, ensure_ascii=False),
                        workspace=Path(directory),
                        model=CODEX_MODEL,
                        timeout_seconds=self.request_timeout,
                        max_tool_attempts=0,
                        text_only=True,
                        output_schema=output_schema,
                    )
                )
            except CLIAgentError as exc:
                # Unknown completion is never a retryable connection/timeout error.
                raise LLMError(
                    str(exc),
                    provider=self.name,
                    model=CODEX_MODEL,
                    error_kind="codex_result_unknown",
                    diagnostic=exc.diagnostic,
                ) from exc
        native_usage = result.usage or {}
        usage = LLMUsage(
            prompt_tokens=native_usage.get("input_tokens", 0),
            completion_tokens=native_usage.get("output_tokens", 0),
            total_tokens=native_usage.get("input_tokens", 0)
            + native_usage.get("output_tokens", 0),
        )
        try:
            output = json.loads(result.answer)
            content = (
                json.dumps(output["data"], ensure_ascii=False)
                if constrained is not None
                else output["content"]
            )
            if not isinstance(content, str):
                raise ValueError("content must be text")
            if (
                request.response_format
                and constrained is None
                and not output.get("tool_calls")
            ):
                if not isinstance(json.loads(content), dict):
                    raise ValueError("content must contain an object")
            calls = []
            for proposed in output.get("tool_calls", []):
                if proposed["name"] not in {t.name for t in request.tools}:
                    raise ValueError("unknown product tool")
                if not isinstance(json.loads(proposed["arguments"]), dict):
                    raise ValueError("tool arguments must be an object")
                calls.append(
                    LLMToolCall(
                        id="codex-" + uuid4().hex,
                        name=proposed["name"],
                        arguments=proposed["arguments"],
                    )
                )
            if request.tool_choice == "none" and calls:
                raise ValueError("tool use disabled")
            if request.tool_choice == "required" and not calls:
                raise ValueError("tool call required")
        except (ValueError, KeyError, TypeError, AssertionError) as exc:
            raise LLMInvalidResponseError(
                "Codex 完整响应不符合步骤契约",
                provider=self.name,
                model=CODEX_MODEL,
                raw_response=result.answer,
                usage=usage,
            ) from exc
        return LLMCallResponse(
            content=content,
            tool_calls=calls,
            finish_reason="tool_calls" if calls else "stop",
            model=CODEX_MODEL,
            provider=self.name,
            usage=usage,
            latency_ms=(time.monotonic() - started) * 1000,
            raw={
                "transport": "codex_cli",
                "adapter_version": CODEX_TEXT_ADAPTER_VERSION,
                "cli_diagnostic": getattr(result, "diagnostic", None),
                "reasoning_effort": CODEX_EFFORT,
                "schema_mode": "native" if constrained is not None else "envelope",
                "native_tool_attempts": result.tool_attempts,
                "output_token_limit_enforced": False,
                "delayed_stream": True,
            },
        )

    async def generate_stream(self, request):
        result = await self.generate(request)

        async def iterate():
            yield LLMStreamChunk(
                content=result.content,
                tool_deltas=[
                    LLMToolDelta(index=i, id=c.id, name=c.name, arguments=c.arguments)
                    for i, c in enumerate(result.tool_calls)
                ],
            )
            yield LLMStreamChunk(finish_reason=result.finish_reason, usage=result.usage)

        return iterate()

    async def close(self):
        pass


async def verify_codex_connection() -> str:
    fingerprint = codex_connection_fingerprint()
    provider = CodexProvider(timeout=60)
    from infrastructure.llm.limits import LLMLimiterScope, get_llm_limiter
    from infrastructure.llm.schemas import LLMCallRequest

    async def call():
        return await provider.generate(request)

    request = LLMCallRequest(
        model=CODEX_MODEL,
        messages=[
            LLMMessage(
                content=f'Verify {CODEX_TEXT_ADAPTER_VERSION}. Return {{"ready":true}}.'
            )
        ],
        response_format={
            "type": "json_schema",
            "json_schema": {
                "schema": {
                    "type": "object",
                    "properties": {"ready": {"type": "boolean", "const": True}},
                    "required": ["ready"],
                    "additionalProperties": False,
                }
            },
        },
    )
    response = await get_llm_limiter().run(
        call,
        limiter_scope=LLMLimiterScope.for_call(
            novel_id=None,
            operation_kind="verification",
            base_url=CODEX_BASE_URL,
            provider_id="codex",
        ),
    )
    if json.loads(response.content) != {"ready": True}:
        raise ValueError("Codex 登录或 Luna/max 验证失败")
    return fingerprint
