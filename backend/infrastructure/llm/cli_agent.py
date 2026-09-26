"""Bounded subprocess adapter for locally installed coding-agent CLIs.

Only the final answer and observable tool counts cross this boundary. Native
tools run with the local user's permissions; the caller must obtain consent.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import signal
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

CLIKind = Literal["codex", "claude", "kimi", "dsh", "pi"]
CLI_KINDS: tuple[CLIKind, ...] = ("codex", "claude", "kimi", "dsh", "pi")
_MAX_LINE = 1024 * 1024
_MAX_OUTPUT = 8 * 1024 * 1024


class CLIAgentError(RuntimeError):
    """A local CLI failed without a valid final answer."""


@dataclass(frozen=True)
class CLIEvent:
    kind: Literal["text", "tool", "usage"]
    text: str = ""
    tool_name: str = ""
    usage: dict[str, int] | None = None


@dataclass(frozen=True)
class CLIResult:
    answer: str
    tool_attempts: int
    usage: dict[str, int] | None


@dataclass(frozen=True)
class CLISpec:
    kind: CLIKind
    prompt: str
    workspace: Path
    timeout_seconds: float = 1800
    max_tool_attempts: int = 32
    command: str | None = None
    model: str | None = None
    env: dict[str, str] | None = None


def _command(spec: CLISpec) -> tuple[list[str], bytes | None]:
    executable = shutil.which(spec.command or spec.kind)
    if executable is None:
        raise CLIAgentError(f"{spec.kind} CLI 未安装或不在 PATH 中")
    if spec.kind == "codex":
        return (
            [
                executable,
                *(["-m", spec.model] if spec.model else []),
                "-a",
                "never",
                "exec",
                "--json",
                "--ephemeral",
                "--sandbox",
                "danger-full-access",
                "--skip-git-repo-check",
                "-C",
                str(spec.workspace),
                "-",
            ],
            spec.prompt.encode(),
        )
    if spec.kind == "claude":
        return (
            [
                executable,
                "-p",
                "--output-format",
                "stream-json",
                "--include-partial-messages",
                "--verbose",
                "--no-session-persistence",
                "--permission-mode",
                "bypassPermissions",
            ],
            spec.prompt.encode(),
        )
    if spec.kind in {"kimi", "dsh"}:
        task = spec.workspace / ".novelcraft-task.md"
        task.write_text(spec.prompt, encoding="utf-8")
        task.chmod(0o600)
        instruction = "Read .novelcraft-task.md in this directory and complete its task."
        if spec.kind == "kimi":
            return (
                [
                    executable,
                    "-p",
                    instruction,
                    "--output-format",
                    "stream-json",
                ],
                None,
            )
        return ([executable, "--profile", "headless", instruction], None)
    task = spec.workspace / ".novelcraft-task.md"
    task.write_text(spec.prompt, encoding="utf-8")
    task.chmod(0o600)
    return (
        [
            executable,
            *(["--model", spec.model] if spec.model else []),
            "--mode",
            "json",
            "--no-session",
            "-p",
            "Read .novelcraft-task.md in this directory and complete its task.",
        ],
        None,
    )


def _text_blocks(message: Any) -> str:
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            str(block.get("text"))
            for block in content
            if isinstance(block, dict)
            and block.get("type") == "text"
            and isinstance(block.get("text"), str)
        )
    return ""


def _usage(event: dict) -> dict[str, int] | None:
    source = event.get("usage")
    if not isinstance(source, dict):
        return None
    result = {
        key: value
        for key, value in source.items()
        if key in {"input_tokens", "output_tokens", "prompt_tokens", "completion_tokens"}
        and isinstance(value, int)
        and not isinstance(value, bool)
        and value >= 0
    }
    return result or None


class _Decoder:
    def __init__(self, kind: CLIKind):
        self.kind = kind
        self.answer = ""
        self.tool_attempts = 0
        self.usage: dict[str, int] | None = None
        self._streamed = ""

    def feed(self, event: dict) -> list[CLIEvent]:
        kind = self.kind
        name = str(event.get("type") or "")
        result: list[CLIEvent] = []
        if kind == "codex":
            item = event.get("item") or {}
            if (
                name == "item.started"
                and isinstance(item, dict)
                and item.get("type")
                in {
                    "command_execution",
                    "mcp_tool_call",
                    "file_change",
                }
            ):
                result.append(CLIEvent("tool", tool_name=str(item.get("type"))))
            elif (
                name == "item.completed"
                and isinstance(item, dict)
                and item.get("type") == "agent_message"
            ):
                self.answer = str(item.get("text") or "")
                result.append(CLIEvent("text", text=self.answer))
            elif name == "turn.completed":
                usage = _usage(event)
                if usage:
                    result.append(CLIEvent("usage", usage=usage))
            elif name in {"turn.failed", "error"}:
                raise CLIAgentError("Codex 执行失败；请在本机检查 CLI 模型与登录状态")
        elif kind == "claude":
            if name == "stream_event":
                delta = (event.get("event") or {}).get("delta") or {}
                if delta.get("type") == "text_delta" and isinstance(
                    delta.get("text"), str
                ):
                    self._streamed += delta["text"]
                    result.append(CLIEvent("text", text=delta["text"]))
            elif name == "assistant":
                message = event.get("message") or {}
                if isinstance(message, dict):
                    result.extend(
                        CLIEvent("tool", tool_name=str(block.get("name") or ""))
                        for block in message.get("content") or []
                        if isinstance(block, dict) and block.get("type") == "tool_use"
                    )
                    self.answer = _text_blocks(message) or self.answer
                    usage = _usage(message)
                    if usage:
                        result.append(CLIEvent("usage", usage=usage))
            elif name == "result":
                if event.get("is_error"):
                    raise CLIAgentError("Claude 执行失败；请在本机检查 CLI 配置")
                self.answer = str(event.get("result") or self.answer)
                usage = _usage(event)
                if usage:
                    result.append(CLIEvent("usage", usage=usage))
                if not self._streamed and self.answer:
                    result.append(CLIEvent("text", text=self.answer))
        elif kind == "kimi":
            message = event.get("message") or event
            if isinstance(message, dict) and message.get("role") == "assistant":
                tool_calls = message.get("tool_calls") or []
                result.extend(
                    CLIEvent(
                        "tool",
                        tool_name=str(
                            (call.get("function") or {}).get("name")
                            or call.get("name")
                            or ""
                        ),
                    )
                    for call in tool_calls
                    if isinstance(call, dict)
                )
                text = _text_blocks(message)
                if text:
                    self.answer = text
                    result.append(CLIEvent("text", text=text))
            if name == "error":
                raise CLIAgentError("Kimi 执行失败；请在本机检查 CLI 配置")
        elif kind == "pi":
            if name == "tool_execution_start":
                result.append(
                    CLIEvent("tool", tool_name=str(event.get("toolName") or ""))
                )
            elif name == "message_update":
                update = event.get("assistantMessageEvent") or {}
                if update.get("type") == "text_delta" and isinstance(
                    update.get("delta"), str
                ):
                    self._streamed += update["delta"]
                    result.append(CLIEvent("text", text=update["delta"]))
            elif name == "message_end":
                message = event.get("message") or {}
                if isinstance(message, dict) and message.get("role") == "assistant":
                    if message.get("stopReason") == "error":
                        raise CLIAgentError(
                            "Pi 模型请求失败；请在本机检查 CLI 模型与登录状态"
                        )
                    self.answer = _text_blocks(message) or self.answer
                    usage = _usage(message)
                    if usage:
                        result.append(CLIEvent("usage", usage=usage))
            elif name == "agent_end" and not self._streamed and self.answer:
                result.append(CLIEvent("text", text=self.answer))
        for item in result:
            if item.kind == "tool":
                self.tool_attempts += 1
            elif item.kind == "usage":
                self.usage = item.usage
        return result


async def _stop(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except (AttributeError, OSError, ProcessLookupError):
        process.terminate()
    try:
        await asyncio.wait_for(process.wait(), timeout=2)
    except TimeoutError:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (AttributeError, OSError, ProcessLookupError):
            process.kill()
        await process.wait()


async def run_cli_agent(
    spec: CLISpec,
    *,
    on_event: Callable[[CLIEvent], Awaitable[None]] | None = None,
) -> CLIResult:
    """Execute one CLI run; never replay a run with uncertain local side effects."""
    if spec.kind not in CLI_KINDS:
        raise ValueError("unknown CLI kind")
    if not spec.workspace.is_absolute() or not spec.workspace.is_dir():
        raise ValueError("workspace must be an existing absolute directory")
    if not spec.prompt.strip() or spec.timeout_seconds <= 0 or spec.max_tool_attempts < 0:
        raise ValueError("invalid CLI run limits or prompt")
    argv, stdin = _command(spec)
    process = await asyncio.create_subprocess_exec(
        *argv,
        cwd=spec.workspace,
        stdin=asyncio.subprocess.PIPE
        if stdin is not None
        else asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env={**os.environ, **spec.env} if spec.env else None,
        start_new_session=True,
    )
    decoder = _Decoder(spec.kind)
    output_bytes = 0

    async def read_stderr() -> None:
        while await process.stderr.read(4096):
            pass

    async def read_stdout() -> None:
        nonlocal output_bytes
        while line := await process.stdout.readline():
            output_bytes += len(line)
            if len(line) > _MAX_LINE or output_bytes > _MAX_OUTPUT:
                raise CLIAgentError("CLI 输出超过上限")
            if spec.kind == "dsh":
                decoder.answer += line.decode("utf-8", errors="replace")
                if on_event:
                    await on_event(
                        CLIEvent("text", text=line.decode("utf-8", errors="replace"))
                    )
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                raise CLIAgentError("CLI 事件不是有效 JSON") from exc
            if not isinstance(event, dict):
                raise CLIAgentError("CLI 事件格式错误")
            for normalized in decoder.feed(event):
                if decoder.tool_attempts > spec.max_tool_attempts:
                    raise CLIAgentError("CLI 工具调用超过上限")
                if on_event:
                    await on_event(normalized)

    try:
        async with asyncio.timeout(spec.timeout_seconds):
            async with asyncio.TaskGroup() as group:
                group.create_task(read_stdout())
                group.create_task(read_stderr())
                if stdin is not None:
                    process.stdin.write(stdin)
                    await process.stdin.drain()
                    process.stdin.close()
            code = await process.wait()
    except BaseException as exc:
        await _stop(process)
        if isinstance(exc, TimeoutError):
            raise CLIAgentError("CLI 执行超时") from exc
        if isinstance(exc, ExceptionGroup) and len(exc.exceptions) == 1:
            raise exc.exceptions[0] from exc
        raise
    if code != 0:
        raise CLIAgentError(f"{spec.kind} CLI 退出码 {code}；请在本机检查配置与日志")
    answer = decoder.answer.strip()
    if not answer:
        raise CLIAgentError(f"{spec.kind} CLI 没有返回答案")
    return CLIResult(answer, decoder.tool_attempts, decoder.usage)
