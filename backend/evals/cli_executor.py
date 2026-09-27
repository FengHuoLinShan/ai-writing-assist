"""Optional five-CLI executor for local, synthetic evaluation tasks."""

from __future__ import annotations

import hashlib
import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

from infrastructure.llm.cli_agent import CLIKind, CLISpec, run_cli_agent

T = TypeVar("T", bound=BaseModel)


@dataclass(frozen=True)
class CLIExecutionMeta:
    model: str
    executor_hash: str
    reasoning_effort: None = None


class CLIStructuredExecutor:
    """Run one isolated local CLI task and validate its final JSON."""

    cost_status = "unavailable_local_cli"

    def __init__(
        self,
        kind: CLIKind,
        *,
        model: str | None = None,
        timeout_seconds: float = 300,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.kind = kind
        self.model = model or f"{kind}:local-default"
        self._model_override = model
        self.timeout_seconds = timeout_seconds

    @property
    def meta(self) -> CLIExecutionMeta:
        profile = {
            "kind": self.kind,
            "model": self.model,
            "transport": "local_cli",
            "workspace": "ephemeral",
            "tool_attempts": 2,
        }
        return CLIExecutionMeta(
            model=self.model,
            executor_hash=hashlib.sha256(
                json.dumps(profile, sort_keys=True).encode()
            ).hexdigest(),
        )

    async def generate_structured(
        self,
        prompt: str,
        response_model: type[T],
        *,
        step_name: str,
    ) -> T:
        with tempfile.TemporaryDirectory(prefix=f"novelcraft-eval-{self.kind}-") as root:
            spec = CLISpec(
                kind=self.kind,
                prompt=(
                    f"Evaluation step: {step_name}\n"
                    "Return only JSON conforming to this schema:\n"
                    f"{json.dumps(response_model.model_json_schema())}\n\n{prompt}"
                ),
                workspace=Path(root),
                timeout_seconds=self.timeout_seconds,
                max_tool_attempts=2,
                model=self._model_override,
            )
            result = await run_cli_agent(spec)
        return response_model.model_validate_json(result.answer)
