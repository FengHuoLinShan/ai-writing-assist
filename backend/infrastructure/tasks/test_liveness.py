from __future__ import annotations

import asyncio
import math
import stat
import subprocess
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

from infrastructure.tasks import liveness
from infrastructure.tasks.worker import TaskWorker


def _write_cmdline(path, *tokens: bytes) -> None:
    path.write_bytes(b"\0".join(tokens) + b"\0")


def test_control_loop_marker_writes_an_atomic_private_monotonic_value(tmp_path) -> None:
    marker_path = tmp_path / "control-loop"

    liveness.write_control_loop_liveness(
        marker_path=marker_path,
        monotonic=lambda: 123.5,
    )

    assert marker_path.read_bytes() == b"123.5\n"
    assert stat.S_IMODE(marker_path.stat().st_mode) == 0o600
    assert not list(tmp_path.glob(".control-loop.*"))


@pytest.mark.parametrize(
    "contents",
    (
        b"",
        b"not-a-number\n",
        b"nan\n",
        b"inf\n",
        b"1.0",
        b"1.0\nextra\n",
        b"1.0\x00\n",
    ),
)
def test_control_loop_health_rejects_missing_or_malformed_markers(
    tmp_path,
    contents: bytes,
) -> None:
    marker_path = tmp_path / "control-loop"
    cmdline_path = tmp_path / "cmdline"
    _write_cmdline(cmdline_path, b"python", b"/app/run_worker.py")
    if contents:
        marker_path.write_bytes(contents)

    assert not liveness.is_control_loop_liveness_healthy(
        marker_path=marker_path,
        cmdline_path=cmdline_path,
        monotonic=lambda: 10.0,
    )


def test_control_loop_health_rejects_oversized_or_symlinked_markers(tmp_path) -> None:
    marker_path = tmp_path / "control-loop"
    cmdline_path = tmp_path / "cmdline"
    _write_cmdline(cmdline_path, b"python", b"run_worker.py")

    marker_path.write_bytes(b"1" * (liveness._MAX_MARKER_BYTES + 1))
    assert not liveness.is_control_loop_liveness_healthy(
        marker_path=marker_path,
        cmdline_path=cmdline_path,
        monotonic=lambda: 1.0,
    )

    marker_target = tmp_path / "marker-target"
    marker_target.write_text("1\n", encoding="ascii")
    marker_path.unlink()
    marker_path.symlink_to(marker_target)
    assert not liveness.is_control_loop_liveness_healthy(
        marker_path=marker_path,
        cmdline_path=cmdline_path,
        monotonic=lambda: 1.0,
    )


def test_control_loop_health_requires_fresh_marker_and_worker_argv(tmp_path) -> None:
    marker_path = tmp_path / "control-loop"
    cmdline_path = tmp_path / "cmdline"
    marker_path.write_text("100\n", encoding="ascii")
    _write_cmdline(cmdline_path, b"python", b"/app/run_worker.py")

    assert liveness.is_control_loop_liveness_healthy(
        marker_path=marker_path,
        cmdline_path=cmdline_path,
        monotonic=lambda: 130.0,
    )
    assert not liveness.is_control_loop_liveness_healthy(
        marker_path=marker_path,
        cmdline_path=cmdline_path,
        monotonic=lambda: 130.1,
    )
    assert not liveness.is_control_loop_liveness_healthy(
        marker_path=marker_path,
        cmdline_path=cmdline_path,
        monotonic=lambda: 99.9,
    )

    _write_cmdline(cmdline_path, b"python", b"run_worker.py.bak")
    assert not liveness.is_control_loop_liveness_healthy(
        marker_path=marker_path,
        cmdline_path=cmdline_path,
        monotonic=lambda: 101.0,
    )


def test_control_loop_health_rejects_os_errors_and_nonfinite_values(tmp_path) -> None:
    marker_path = tmp_path / "control-loop"
    marker_path.write_text("1\n", encoding="ascii")
    cmdline_path = tmp_path / "cmdline"
    _write_cmdline(cmdline_path, b"python", b"run_worker.py")

    assert not liveness.is_control_loop_liveness_healthy(
        marker_path=marker_path,
        cmdline_path=tmp_path / "missing-cmdline",
        monotonic=lambda: 1.0,
    )
    assert not liveness.is_control_loop_liveness_healthy(
        marker_path=marker_path,
        cmdline_path=cmdline_path,
        freshness_seconds=math.inf,
        monotonic=lambda: 1.0,
    )


def test_liveness_cli_return_codes_are_zero_output(capsys) -> None:
    assert liveness.main(health_check=lambda: True) == 0
    assert liveness.main(health_check=lambda: False) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_standalone_liveness_cli_fails_without_dynamic_output() -> None:
    result = subprocess.run(
        [sys.executable, str(liveness.__file__)],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr == ""


@pytest.mark.asyncio
async def test_control_loop_observer_runs_only_in_forever_after_startup() -> None:
    calls: list[str] = []
    worker = TaskWorker(
        db_manager=MagicMock(),
        poll_interval=0.0,
        control_loop_observer=lambda: calls.append("observer"),
    )
    worker._maybe_recover_stale_tasks = AsyncMock(return_value=0)

    async def startup_reconcilers() -> None:
        calls.append("startup")

    worker._run_startup_reconcilers = AsyncMock(side_effect=startup_reconcilers)

    async def stop_after_first_control_loop():
        worker.stop()
        return None

    worker._claim_task_runner = AsyncMock(side_effect=stop_after_first_control_loop)

    await worker.run_forever()

    assert calls == ["startup", "observer"]
    worker._run_startup_reconcilers.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_control_loop_observer_runs_after_controlled_startup_failure() -> None:
    observer_calls: list[str] = []
    worker = TaskWorker(
        db_manager=MagicMock(),
        poll_interval=0.0,
        control_loop_observer=lambda: (observer_calls.append("observer"), worker.stop()),
    )
    worker._maybe_recover_stale_tasks = AsyncMock(side_effect=RuntimeError("startup"))
    worker._run_startup_reconcilers = AsyncMock(return_value=None)
    worker._claim_task_runner = AsyncMock(return_value=None)

    await worker.run_forever()

    assert observer_calls == ["observer"]
    worker._maybe_recover_stale_tasks.assert_awaited_once_with(force=True)
    worker._run_startup_reconcilers.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_once_does_not_call_control_loop_observer() -> None:
    observer_calls: list[str] = []
    session_context = AsyncMock()
    session_context.__aenter__ = AsyncMock(return_value=AsyncMock())
    session_context.__aexit__ = AsyncMock()
    db_manager = MagicMock()
    db_manager.session_factory = MagicMock(return_value=session_context)
    worker = TaskWorker(
        db_manager=db_manager,
        control_loop_observer=lambda: observer_calls.append("observer"),
    )
    worker._claim_task = AsyncMock(return_value=None)

    assert await worker.run_once() is None
    assert observer_calls == []


@pytest.mark.asyncio
async def test_control_loop_observer_failures_do_not_block_or_log_storms(caplog) -> None:
    calls = 0
    worker = TaskWorker(db_manager=MagicMock(), poll_interval=0.0)

    def observer() -> None:
        nonlocal calls
        calls += 1
        if calls == 3:
            return
        if calls == 4:
            worker.stop()
        raise RuntimeError("private observer detail")

    worker._control_loop_observer = observer
    worker._maybe_recover_stale_tasks = AsyncMock(return_value=0)
    worker._run_startup_reconcilers = AsyncMock(return_value=None)
    worker._claim_task_runner = AsyncMock(return_value=None)

    with caplog.at_level("INFO", logger="infrastructure.tasks.worker"):
        await asyncio.wait_for(worker.run_forever(), timeout=1.0)

    warnings = [
        message
        for message in caplog.messages
        if "control-loop observer failed" in message
    ]
    assert calls == 4
    assert worker._claim_task_runner.await_count == 3
    assert warnings == [
        "TaskWorker control-loop observer failed: RuntimeError",
        "TaskWorker control-loop observer failed: RuntimeError",
    ]
    assert "TaskWorker control-loop observer recovered" in caplog.messages
    assert "private observer detail" not in "\n".join(caplog.messages)
