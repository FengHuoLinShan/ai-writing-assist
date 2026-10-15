import asyncio
import importlib.util
import io
import json
from contextlib import nullcontext
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from evals.codex_executor import (
    AskWorldCalibrationScope,
    CodexExecutionError,
    CodexStructuredExecutor,
)


class Answer(BaseModel):
    ready: bool


@pytest.mark.asyncio
@pytest.mark.parametrize("problem", [None, "stale", "provider", "effort", "unverified"])
async def test_calibration_revalidates_owner_runtime_before_native_call(
    monkeypatch, problem
):
    snapshot = {
        "profile": {
            "provider_id": "codex",
            "model": "gpt-6-luna",
            "connection_verified": True,
        }
    }
    current = deepcopy(snapshot)
    effort = "max"
    if problem == "stale":
        current["changed"] = True
    elif problem == "provider":
        current["profile"]["provider_id"] = "deepseek"
    elif problem == "effort":
        effort = "high"
    elif problem == "unverified":
        current["profile"]["connection_verified"] = False
    events = []

    async def build(db, novel_id):
        assert novel_id == "isolated"
        events.append("owner_runtime")
        return current

    async def restore(db, novel_id, actual):
        assert actual == current
        return {"llm": {"extra": {"reasoning_effort": effort}}}

    async def rollback():
        events.append("rollback")

    async def invoke(*args, **kwargs):
        events.append("native")
        return '{"ready":true}'

    monkeypatch.setattr(
        "modules.project.facade.build_project_llm_execution_snapshot", build
    )
    monkeypatch.setattr(
        "modules.project.facade.restore_project_llm_execution_settings", restore
    )
    executor = CodexStructuredExecutor(
        command="python3",
        attempts=1,
        calibration=AskWorldCalibrationScope(
            SimpleNamespace(rollback=rollback), "isolated", snapshot
        ),
    )
    monkeypatch.setattr(executor, "_invoke", invoke)
    with pytest.raises(CodexExecutionError) if problem else nullcontext():
        answer = await executor.generate_structured(
            "synthetic", Answer, step_name="eval.ask_world.teacher_calibration"
        )
        assert answer.ready
    assert events == (
        ["owner_runtime"] if problem else ["owner_runtime", "rollback", "native"]
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "effort,step", [("xhigh", "reviewer"), ("high", "eval.ask_world.teacher_calibration")]
)
async def test_calibration_does_not_open_other_roles_or_retry(effort, step):
    scope = AskWorldCalibrationScope(None, "isolated", {})
    with pytest.raises(ValueError, match="never automatically retries"):
        CodexStructuredExecutor(calibration=scope)
    executor = CodexStructuredExecutor(
        calibration=scope, attempts=1, reasoning_effort=effort
    )
    with pytest.raises(CodexExecutionError, match="only permits"):
        await executor.generate_structured("synthetic", Answer, step_name=step)


def test_native_capture_preserves_bytes_and_nonzero_exit(tmp_path, monkeypatch):
    path = Path(__file__).resolve().parents[3] / (
        ".agent/tasks/2026/T-20261015-g6b-recalibration/native-capture.py"
    )
    spec = importlib.util.spec_from_file_location("g6b_capture_test", path)
    capture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(capture)
    native = tmp_path / "native"
    native.write_text(
        "#!/usr/bin/python3\nimport sys\n"
        "data=sys.stdin.buffer.read()\n"
        "sys.stdout.buffer.write(b'output:'+data)\n"
        "sys.stderr.buffer.write(b'diagnostic')\nsys.exit(3)\n"
    )
    native.chmod(0o700)
    capture.REAL_CLI = str(native)
    capture.ARTIFACTS = tmp_path / "private"
    stdout, stderr = io.BytesIO(), io.BytesIO()
    monkeypatch.setattr(
        capture.sys, "stdin", SimpleNamespace(buffer=io.BytesIO(b"input\x00"))
    )
    monkeypatch.setattr(capture.sys, "stdout", SimpleNamespace(buffer=stdout))
    monkeypatch.setattr(capture.sys, "stderr", SimpleNamespace(buffer=stderr))
    monkeypatch.setattr(
        capture.sys,
        "argv",
        [str(path), "exec", "-m", "gpt-6-luna", "-c", 'model_reasoning_effort="max"'],
    )
    assert capture.main() == 3
    (call,) = capture.ARTIFACTS.iterdir()
    assert (call / "request.bin").read_bytes() == b"input\x00"
    assert (call / "stdout.bin").read_bytes() == stdout.getvalue() == b"output:input\x00"
    assert (call / "stderr.bin").read_bytes() == stderr.getvalue() == b"diagnostic"
    status = json.loads((call / "status.json").read_text())
    assert status["status"] == "native_exit" and status["exit_code"] == 3
    assert call.stat().st_mode & 0o777 == 0o700


@pytest.mark.asyncio
async def test_teacher_cancellation_stops_and_reaps_native_process(monkeypatch):
    events = []

    async def communicate(request):
        raise asyncio.CancelledError

    async def wait():
        events.append("reaped")

    process = SimpleNamespace(pid=12345, communicate=communicate, wait=wait)

    async def spawn(*args, **kwargs):
        assert "OPENAI_API_KEY" not in kwargs["env"]
        return process

    monkeypatch.setattr("evals.codex_executor.asyncio.create_subprocess_exec", spawn)
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-test-key")
    monkeypatch.setattr(
        "evals.codex_executor.os.killpg", lambda *args: events.append("stopped")
    )
    executor = CodexStructuredExecutor()
    with pytest.raises(asyncio.CancelledError):
        await executor._invoke("codex", "synthetic", {}, step_name="test")
    assert events == ["stopped", "reaped"]
