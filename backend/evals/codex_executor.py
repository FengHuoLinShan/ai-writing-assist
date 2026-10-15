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
from typing import NoReturn, TypeVar

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from evals.schemas import (
    ALLOWED_EVAL_TEACHER_MODELS,
    EVAL_TEACHER_MODEL,
    EVAL_TEACHER_REASONING_EFFORT,
    HIGH_QUALITY_LLM_FALLBACK_MODEL,
)

StructuredResultT = TypeVar("StructuredResultT", bound=BaseModel)


class CodexExecutionError(RuntimeError):
    """Raised when the pinned local Codex execution cannot produce valid output."""


@dataclass(frozen=True)
class AskWorldCalibrationScope:
    """G6b opt-in: revalidate the actual owner runtime before every teacher call."""

    db: AsyncSession
    novel_id: str
    snapshot: dict

    async def verify(self) -> None:
        from modules.project.facade import (
            build_project_llm_execution_snapshot,
            restore_project_llm_execution_settings,
        )

        current = await build_project_llm_execution_snapshot(self.db, self.novel_id)
        restored = await restore_project_llm_execution_settings(
            self.db, self.novel_id, current
        )
        profile = current["profile"]
        if (
            current != self.snapshot
            or profile.get("provider_id") != "codex"
            or profile.get("model") != "gpt-6-luna"
            or not profile.get("connection_verified")
            or restored["llm"]["extra"].get("reasoning_effort") != "max"
        ):
            raise CodexExecutionError(
                "G6b requires the unchanged verified Luna/max snapshot"
            )
        # Do not hold a database read transaction across the teacher's model IO.
        await self.db.rollback()


def require_live_eval_calibration() -> NoReturn:
    """Reject new standalone model execution before any irreversible side effects."""
    raise CodexExecutionError(
        "Standalone evaluation is paused until G6b re-calibration: teacher/judge "
        "roles are now pinned to gpt-6.1-sol/xhigh and the system under test runs "
        "through the verified owner/Project runtime on Luna/max. New standalone "
        "model calls stay rejected in this phase. Frozen metadata remain available; "
        "cache-only replay applies to the current contract only (legacy scene-gold "
        "fallback cache keys no longer match)."
    )


@dataclass(frozen=True)
class CodexExecutionMeta:
    model: str
    executor_hash: str
    reasoning_effort: str | None = None


class CodexStructuredExecutor:
    """Run one isolated structured request through the locally logged-in Codex CLI.

    Evaluation teacher/judge contract: teacher, judge, reviewer/adjudicator and
    scene-gold reference calls are pinned to gpt-6.1-sol/xhigh. The frozen legacy
    models (spark/5.6-luna/terra) are accepted only through an explicit
    ``allowed_models`` override so historical metadata and executor hashes can be
    reconstructed; they must not be used for new calls.

    The executor deliberately ignores user config, plugins, project instructions, and
    workspace files. Authentication still comes from the local Codex login. Source text
    is supplied only through stdin and the final response must match a JSON Schema.
    """

    def __init__(
        self,
        *,
        model: str | None = None,
        reasoning_effort: str | None = None,
        allowed_models: frozenset[str] = ALLOWED_EVAL_TEACHER_MODELS,
        command: str = "codex",
        timeout_seconds: float = 300.0,
        attempts: int = 2,
        calibration: AskWorldCalibrationScope | None = None,
    ) -> None:
        model = model or os.environ.get("EVAL_CODEX_MODEL", EVAL_TEACHER_MODEL)
        if model not in allowed_models:
            allowed = ", ".join(sorted(allowed_models))
            raise ValueError(f"eval model must be one of: {allowed}")
        if reasoning_effort is None and model == EVAL_TEACHER_MODEL:
            reasoning_effort = EVAL_TEACHER_REASONING_EFFORT
        if reasoning_effort is None and model == HIGH_QUALITY_LLM_FALLBACK_MODEL:
            # Frozen legacy metadata rule: historical luna runs recorded medium.
            reasoning_effort = "medium"
        if reasoning_effort not in {None, "low", "medium", "high", "xhigh", "max"}:
            raise ValueError("unsupported eval reasoning effort")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if attempts < 1:
            raise ValueError("attempts must be positive")
        if calibration is not None and attempts != 1:
            raise ValueError(
                "G6b calibration never automatically retries a model request"
            )
        self.model = model
        self.reasoning_effort = reasoning_effort
        self.command = command
        self.timeout_seconds = timeout_seconds
        self.attempts = attempts
        self.calibration = calibration

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
        if self.calibration is None:
            require_live_eval_calibration()
        if (
            self.model != EVAL_TEACHER_MODEL
            or self.reasoning_effort != EVAL_TEACHER_REASONING_EFFORT
            or step_name != "eval.ask_world.teacher_calibration"
        ):
            raise CodexExecutionError(
                "G6b only permits the pinned Ask World teacher step"
            )
        await self.calibration.verify()
        executable = shutil.which(self.command)
        if executable is None:
            raise CodexExecutionError("G6b Codex CLI is unavailable")
        payload = await self._invoke(
            executable,
            prompt,
            _strict_json_schema(response_model.model_json_schema()),
            step_name=step_name,
        )
        return response_model.model_validate_json(payload)

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
                "--disable",
                "multi_agent",
                "--disable",
                "apps",
                "--disable",
                "hooks",
                *[
                    arg
                    for feature in (
                        "view_image",
                        "browser_use",
                        "browser_use_external",
                        "computer_use",
                        "in_app_browser",
                        "code_mode_host",
                        "goals",
                        "skill_search",
                        "skill_mcp_dependency_install",
                        "shell_snapshot",
                        "unified_exec",
                        "remote_plugin",
                        "unbounded_connection_retries",
                    )
                    for arg in ("--disable", feature)
                ],
                "--enable",
                "skip_host_skill_discovery",
                "-c",
                "project_doc_max_bytes=0",
                "-c",
                'web_search="disabled"',
                "-c",
                "mcp_servers={}",
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
                env={
                    key: value
                    for key, value in os.environ.items()
                    if key
                    in {
                        "PATH",
                        "HOME",
                        "CODEX_HOME",
                        "TMPDIR",
                        "LANG",
                        "LC_ALL",
                        "HTTPS_PROXY",
                        "HTTP_PROXY",
                        "NO_PROXY",
                        "SSL_CERT_FILE",
                    }
                },
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
            except (TimeoutError, asyncio.CancelledError) as exc:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except (AttributeError, OSError, ProcessLookupError):
                    process.kill()
                await process.wait()
                if isinstance(exc, TimeoutError):
                    raise CodexExecutionError(
                        f"Codex timed out after {self.timeout_seconds:g}s"
                    ) from exc
                raise

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
