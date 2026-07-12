"""Schema-guarded local Codex CLI execution for evaluation-only workflows."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import signal
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

from evals.schemas import (
    ALLOWED_HIGH_QUALITY_LLM_MODELS,
    HIGH_QUALITY_LLM_MODEL,
)

StructuredResultT = TypeVar("StructuredResultT", bound=BaseModel)


class CodexExecutionError(RuntimeError):
    """Raised when the pinned local Codex execution cannot produce valid output."""


@dataclass(frozen=True)
class CodexExecutionMeta:
    model: str
    executor_hash: str
    reasoning_effort: str | None = None


class CodexStructuredExecutor:
    """Run one isolated structured request through the locally logged-in Codex CLI.

    The executor deliberately ignores user config, plugins, project instructions, and
    workspace files. Authentication still comes from the local Codex login. Source text
    is supplied only through stdin and the final response must match a JSON Schema.
    """

    def __init__(
        self,
        *,
        model: str | None = None,
        reasoning_effort: str | None = None,
        allowed_models: frozenset[str] = ALLOWED_HIGH_QUALITY_LLM_MODELS,
        command: str = "codex",
        timeout_seconds: float = 300.0,
        attempts: int = 2,
    ) -> None:
        model = model or os.environ.get("EVAL_CODEX_MODEL", HIGH_QUALITY_LLM_MODEL)
        if model not in allowed_models:
            allowed = ", ".join(sorted(allowed_models))
            raise ValueError(f"eval model must be one of: {allowed}")
        if reasoning_effort is None and model == "gpt-5.6-luna":
            reasoning_effort = "medium"
        if reasoning_effort not in {None, "low", "medium", "high", "xhigh"}:
            raise ValueError("unsupported eval reasoning effort")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if attempts < 1:
            raise ValueError("attempts must be positive")
        self.model = model
        self.reasoning_effort = reasoning_effort
        self.command = command
        self.timeout_seconds = timeout_seconds
        self.attempts = attempts

    @property
    def meta(self) -> CodexExecutionMeta:
        execution_profile = {
            "command": Path(self.command).name,
            "model": self.model,
            "reasoning_effort": self.reasoning_effort,
            "transport": "local_codex_cli",
            "ephemeral": True,
            "ignore_user_config": True,
            "ignore_rules": True,
            "disabled_features": [
                "image_generation",
                "plugin_sharing",
                "plugins",
                "shell_tool",
                "tool_suggest",
            ],
            "sandbox": "read-only",
            "structured_output": True,
        }
        executor_hash = hashlib.sha256(
            json.dumps(execution_profile, sort_keys=True).encode("utf-8")
        ).hexdigest()
        return CodexExecutionMeta(
            model=self.model,
            executor_hash=executor_hash,
            reasoning_effort=self.reasoning_effort,
        )

    async def generate_structured(
        self,
        prompt: str,
        response_model: type[StructuredResultT],
        *,
        step_name: str,
    ) -> StructuredResultT:
        executable = shutil.which(self.command)
        if executable is None:
            raise CodexExecutionError(f"Codex CLI is unavailable: {self.command}")

        failures: list[str] = []
        for attempt in range(1, self.attempts + 1):
            try:
                payload = await self._invoke(
                    executable,
                    prompt,
                    _strict_json_schema(response_model.model_json_schema()),
                    step_name=step_name,
                )
                return response_model.model_validate_json(payload)
            except (CodexExecutionError, ValueError) as exc:
                failures.append(f"attempt {attempt}: {exc}")
        raise CodexExecutionError("; ".join(failures))

    async def _invoke(
        self,
        executable: str,
        prompt: str,
        schema: dict[str, object],
        *,
        step_name: str,
    ) -> str:
        with tempfile.TemporaryDirectory(prefix="ai-writing-eval-codex-") as temp_dir:
            temp_path = Path(temp_dir)
            schema_path = temp_path / "response.schema.json"
            output_path = temp_path / "response.json"
            schema_path.write_text(
                json.dumps(schema, ensure_ascii=False),
                encoding="utf-8",
            )
            args = (
                executable,
                "-a",
                "never",
                "--disable",
                "plugins",
                "--disable",
                "plugin_sharing",
                "--disable",
                "image_generation",
                "--disable",
                "shell_tool",
                "--disable",
                "tool_suggest",
                "exec",
                "--ephemeral",
                "--ignore-user-config",
                "--ignore-rules",
                "--sandbox",
                "read-only",
                "--skip-git-repo-check",
                "--color",
                "never",
                "-C",
                temp_dir,
                "-m",
                self.model,
                *(
                    ("-c", f'model_reasoning_effort="{self.reasoning_effort}"')
                    if self.reasoning_effort
                    else ()
                ),
                "--output-schema",
                str(schema_path),
                "--output-last-message",
                str(output_path),
                "-",
            )
            process = await asyncio.create_subprocess_exec(
                *args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=True,
            )
            request = (
                "Evaluation step: "
                f"{step_name}\n"
                "Return only the final JSON matching the supplied schema.\n\n"
                f"{prompt}"
            ).encode()
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(request),
                    timeout=self.timeout_seconds,
                )
            except TimeoutError as exc:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except (AttributeError, OSError, ProcessLookupError):
                    process.kill()
                await process.wait()
                raise CodexExecutionError(
                    f"Codex timed out after {self.timeout_seconds:g}s"
                ) from exc

            diagnostics = (stdout + stderr).decode("utf-8", errors="replace")
            if process.returncode != 0:
                raise CodexExecutionError(
                    f"Codex exited {process.returncode}: {diagnostics[-1000:]}"
                )
            if f"model: {self.model}" not in diagnostics:
                raise CodexExecutionError("Codex did not confirm the pinned model")
            if not output_path.exists():
                raise CodexExecutionError("Codex did not write the structured response")
            return output_path.read_text(encoding="utf-8")


def _strict_json_schema(schema: dict[str, object]) -> dict[str, object]:
    """Normalize Pydantic JSON Schema for Codex strict structured outputs."""

    normalized = json.loads(json.dumps(schema))

    def visit(node: object) -> None:
        if isinstance(node, dict):
            node.pop("default", None)
            properties = node.get("properties")
            if isinstance(properties, dict):
                node["required"] = list(properties)
                node["additionalProperties"] = False
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)

    visit(normalized)
    return normalized
