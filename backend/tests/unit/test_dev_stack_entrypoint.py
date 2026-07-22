from __future__ import annotations

import importlib.util
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]


def _load_dev_stack() -> ModuleType:
    module_path = REPO_ROOT / "scripts" / "dev_stack.py"
    spec = importlib.util.spec_from_file_location("dev_stack_under_test", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_repo_dev_process_requires_matching_command_and_repo_cwd(monkeypatch) -> None:
    dev_stack = _load_dev_stack()
    monkeypatch.setattr(
        dev_stack,
        "_process_command",
        lambda _pid: "python scripts/dev_server.py --port 8000",
    )
    monkeypatch.setattr(dev_stack, "_process_cwd", lambda _pid: dev_stack.BACKEND)

    assert dev_stack._is_repo_dev_process(123) is True

    monkeypatch.setattr(dev_stack, "_process_cwd", lambda _pid: Path("/tmp/other"))
    assert dev_stack._is_repo_dev_process(123) is False

    monkeypatch.setattr(dev_stack, "_process_cwd", lambda _pid: dev_stack.BACKEND)
    monkeypatch.setattr(dev_stack, "_process_command", lambda _pid: "python other.py")
    assert dev_stack._is_repo_dev_process(123) is False


def test_stop_apps_skips_unverified_stale_pid(monkeypatch, tmp_path) -> None:
    dev_stack = _load_dev_stack()
    pidfile = tmp_path / "stack.json"
    pidfile.write_text(
        json.dumps(
            {
                "root": str(dev_stack.ROOT),
                "processes": {"backend": 4242},
            }
        )
    )
    terminated: list[int] = []
    monkeypatch.setattr(dev_stack, "PIDFILE", pidfile)
    monkeypatch.setattr(dev_stack, "_is_alive", lambda _pid: True)
    monkeypatch.setattr(dev_stack, "_is_repo_dev_process", lambda _pid: False)
    monkeypatch.setattr(dev_stack, "_terminate_pid", terminated.append)

    dev_stack.stop_apps(fallback=False)

    assert terminated == []


def test_legacy_start_script_delegates_from_any_cwd_with_spaced_paths(
    tmp_path: Path,
) -> None:
    fake_root = tmp_path / "repo with spaces"
    fake_root.mkdir()
    start_script = fake_root / "start.sh"
    start_script.write_bytes((REPO_ROOT / "start.sh").read_bytes())
    start_script.chmod(0o755)
    fake_python = tmp_path / "python override with spaces"
    fake_python.write_text(
        "#!/bin/sh\nprintf 'ARG=%s\\n' \"$@\"\nexit 23\n",
        encoding="utf-8",
    )
    fake_python.chmod(0o755)

    result = subprocess.run(
        ["bash", str(start_script)],
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHON": str(fake_python)},
        cwd=tmp_path,
    )

    assert result.returncode == 23
    assert result.stdout.splitlines() == [
        f"ARG={fake_root / 'scripts' / 'dev_stack.py'}",
        "ARG=start",
    ]
    assert "compatibility entrypoint" in result.stderr


@pytest.mark.skipif(sys.platform == "win32", reason="start.sh requires POSIX signals")
def test_legacy_start_script_exec_propagates_signal_to_python_override(
    tmp_path: Path,
) -> None:
    fake_python = tmp_path / "fake-python"
    fake_python.write_text(
        "#!/bin/sh\n"
        "trap 'exit 42' TERM\n"
        "printf 'PID=%s\\n' \"$$\"\n"
        "while :; do sleep 0.1; done\n",
        encoding="utf-8",
    )
    fake_python.chmod(0o755)

    process = subprocess.Popen(
        ["bash", str(REPO_ROOT / "start.sh")],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env={**os.environ, "PYTHON": str(fake_python)},
        cwd=tmp_path,
    )
    try:
        assert process.stdout is not None
        assert process.stdout.readline().strip() == f"PID={process.pid}"
        process.send_signal(signal.SIGTERM)
        assert process.wait(timeout=3) == 42
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=3)


class _ProcessStub:
    def __init__(self, pid: int, returncode: int | None = None) -> None:
        self.pid = pid
        self.returncode = returncode

    def poll(self) -> int | None:
        return self.returncode


class _InterruptingProcessStub(_ProcessStub):
    def __init__(self, pid: int, interrupt: object) -> None:
        super().__init__(pid)
        assert callable(interrupt)
        self._interrupt = interrupt

    def poll(self) -> int | None:
        interrupt, self._interrupt = self._interrupt, None
        if interrupt is not None:
            interrupt()
        return self.returncode


def test_cancellable_run_terminates_a_command_that_is_still_executing(
    tmp_path: Path,
) -> None:
    dev_stack = _load_dev_stack()
    pid_file = tmp_path / "child.pid"
    started_at = time.monotonic()

    with pytest.raises(dev_stack._RunCancelledError):
        dev_stack._run(
            [
                sys.executable,
                "-c",
                (
                    "import os, pathlib, sys, time; "
                    "pathlib.Path(sys.argv[1]).write_text(str(os.getpid())); "
                    "time.sleep(10)"
                ),
                str(pid_file),
            ],
            cancelled=pid_file.exists,
        )

    assert time.monotonic() - started_at < 2
    child_pid = int(pid_file.read_text())
    with pytest.raises(ProcessLookupError):
        os.kill(child_pid, 0)


def test_parent_cancellation_wins_when_foreground_command_exits_nonzero(
    tmp_path: Path,
) -> None:
    dev_stack = _load_dev_stack()
    cancellation_marker = tmp_path / "cancelled"

    with pytest.raises(dev_stack._RunCancelledError):
        dev_stack._run(
            [
                sys.executable,
                "-c",
                (
                    "import pathlib, sys; "
                    "pathlib.Path(sys.argv[1]).touch(); "
                    "raise SystemExit(9)"
                ),
                str(cancellation_marker),
            ],
            cancelled=cancellation_marker.exists,
        )


@pytest.mark.parametrize(
    ("signum", "expected_code"),
    [(signal.SIGINT, 130), (signal.SIGTERM, 143)],
)
def test_signal_during_database_health_wait_cancels_before_app_spawn(
    monkeypatch: pytest.MonkeyPatch,
    signum: int,
    expected_code: int,
) -> None:
    dev_stack = _load_dev_stack()
    handlers: dict[int, object] = {}
    commands: list[list[str]] = []

    def run(cmd: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        commands.append(cmd)
        stdout = "starting\n" if "-f" in cmd else ""
        return subprocess.CompletedProcess(cmd, 0, stdout, "")

    def interrupt_wait(_seconds: float) -> None:
        handler = handlers[signum]
        assert callable(handler)
        handler(signum, None)

    monkeypatch.setattr(dev_stack, "stop_apps", lambda **_kwargs: None)
    monkeypatch.setattr(dev_stack, "_run", run)
    monkeypatch.setattr(dev_stack.time, "sleep", interrupt_wait)
    monkeypatch.setattr(
        dev_stack.signal,
        "signal",
        lambda registered_signum, handler: handlers.__setitem__(
            registered_signum, handler
        ),
    )
    monkeypatch.setattr(
        dev_stack,
        "_spawn",
        lambda *_args, **_kwargs: pytest.fail("cancelled DB wait must not spawn apps"),
    )

    assert dev_stack.start_stack() == expected_code
    assert any("-f" in cmd for cmd in commands)


def test_managed_stack_spawns_backend_worker_and_frontend_without_real_services(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dev_stack = _load_dev_stack()
    spawned: list[tuple[str, list[str], Path]] = []

    monkeypatch.setattr(dev_stack, "stop_apps", lambda **_kwargs: None)
    monkeypatch.setattr(dev_stack, "start_db", lambda **_kwargs: True)
    monkeypatch.setattr(dev_stack, "_write_pidfile", lambda _processes: None)
    monkeypatch.setattr(dev_stack.signal, "signal", lambda *_args: None)
    monkeypatch.setattr(dev_stack.atexit, "register", lambda *_args: None)
    monkeypatch.setattr(dev_stack.time, "sleep", lambda _seconds: None)

    def spawn(
        name: str,
        cmd: list[str],
        *,
        cwd: Path,
        env: dict[str, str] | None = None,
    ) -> _ProcessStub:
        del env
        spawned.append((name, cmd, cwd))
        return _ProcessStub(100 + len(spawned), 0 if name == "backend" else None)

    monkeypatch.setattr(dev_stack, "_spawn", spawn)

    assert dev_stack.start_stack() == 0
    assert [name for name, _cmd, _cwd in spawned] == [
        "backend",
        "worker",
        "frontend",
    ]
    assert spawned[1] == (
        "worker",
        [sys.executable, "run_worker.py", "--reload"],
        dev_stack.BACKEND,
    )


def test_managed_stack_ctrl_c_cleans_up_and_returns_standard_signal_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dev_stack = _load_dev_stack()
    processes: list[_ProcessStub] = []
    handlers: dict[int, object] = {}
    cleanup_calls = 0

    def stop_apps(*, fallback: bool, remove_pidfile: bool = True) -> None:
        nonlocal cleanup_calls
        del remove_pidfile
        if fallback:
            return
        cleanup_calls += 1
        for process in processes:
            process.returncode = -signal.SIGTERM

    def spawn(
        _name: str,
        _cmd: list[str],
        *,
        cwd: Path,
        env: dict[str, str] | None = None,
    ) -> _ProcessStub:
        del cwd, env
        process = _ProcessStub(300 + len(processes))
        processes.append(process)
        return process

    def register_handler(signum: int, handler: object) -> None:
        handlers[signum] = handler

    sleep_calls = 0

    def interrupt_once(_seconds: float) -> None:
        nonlocal sleep_calls
        sleep_calls += 1
        if sleep_calls == 1:
            handler = handlers[signal.SIGINT]
            assert callable(handler)
            handler(signal.SIGINT, None)

    monkeypatch.setattr(dev_stack, "stop_apps", stop_apps)
    monkeypatch.setattr(dev_stack, "start_db", lambda **_kwargs: True)
    monkeypatch.setattr(dev_stack, "_spawn", spawn)
    monkeypatch.setattr(dev_stack, "_write_pidfile", lambda _processes: None)
    monkeypatch.setattr(dev_stack.signal, "signal", register_handler)
    monkeypatch.setattr(dev_stack.atexit, "register", lambda *_args: None)
    monkeypatch.setattr(dev_stack.time, "sleep", interrupt_once)

    assert dev_stack.start_stack() == 130
    assert cleanup_calls == 1


def test_parent_signal_during_child_poll_takes_priority_over_child_exit_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dev_stack = _load_dev_stack()
    processes: list[_ProcessStub] = []
    handlers: dict[int, object] = {}

    def stop_apps(*, fallback: bool, remove_pidfile: bool = True) -> None:
        del remove_pidfile
        if fallback:
            return
        for process in processes:
            process.returncode = -signal.SIGTERM

    def interrupt() -> None:
        handler = handlers[signal.SIGINT]
        assert callable(handler)
        handler(signal.SIGINT, None)

    def spawn(
        _name: str,
        _cmd: list[str],
        *,
        cwd: Path,
        env: dict[str, str] | None = None,
    ) -> _ProcessStub:
        del cwd, env
        if not processes:
            process = _InterruptingProcessStub(350, interrupt)
        else:
            process = _ProcessStub(350 + len(processes))
        processes.append(process)
        return process

    monkeypatch.setattr(dev_stack, "stop_apps", stop_apps)
    monkeypatch.setattr(dev_stack, "start_db", lambda **_kwargs: True)
    monkeypatch.setattr(dev_stack, "_spawn", spawn)
    monkeypatch.setattr(dev_stack, "_write_pidfile", lambda _processes: None)
    monkeypatch.setattr(
        dev_stack.signal,
        "signal",
        lambda signum, handler: handlers.__setitem__(signum, handler),
    )
    monkeypatch.setattr(dev_stack.atexit, "register", lambda *_args: None)

    assert dev_stack.start_stack() == 130


def test_sigterm_during_partial_startup_rolls_back_known_processes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    dev_stack = _load_dev_stack()
    handlers: dict[int, object] = {}
    spawned: list[str] = []
    terminated: list[int] = []
    stable_cleanup_calls = 0

    def stop_apps(*, fallback: bool, remove_pidfile: bool = True) -> None:
        nonlocal stable_cleanup_calls
        del remove_pidfile
        if not fallback:
            stable_cleanup_calls += 1

    def spawn(
        name: str,
        _cmd: list[str],
        *,
        cwd: Path,
        env: dict[str, str] | None = None,
    ) -> _ProcessStub:
        del cwd, env
        spawned.append(name)
        process = _ProcessStub(375 + len(spawned))
        if name == "worker":
            handler = handlers[signal.SIGTERM]
            assert callable(handler)
            handler(signal.SIGTERM, None)
        return process

    monkeypatch.setattr(dev_stack, "stop_apps", stop_apps)
    monkeypatch.setattr(dev_stack, "start_db", lambda **_kwargs: True)
    monkeypatch.setattr(dev_stack, "_spawn", spawn)
    monkeypatch.setattr(dev_stack, "_terminate_pid", terminated.append)
    monkeypatch.setattr(dev_stack, "PIDFILE", tmp_path / "dev-stack.pid")
    monkeypatch.setattr(
        dev_stack.signal,
        "signal",
        lambda signum, handler: handlers.__setitem__(signum, handler),
    )
    monkeypatch.setattr(
        dev_stack,
        "_write_pidfile",
        lambda _processes: pytest.fail("interrupted startup must not write pidfile"),
    )

    assert dev_stack.start_stack() == 143
    assert spawned == ["backend", "worker"]
    assert terminated == [377, 376]
    assert stable_cleanup_calls == 0


def test_managed_stack_normalizes_child_signal_exit_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dev_stack = _load_dev_stack()

    monkeypatch.setattr(dev_stack, "stop_apps", lambda **_kwargs: None)
    monkeypatch.setattr(dev_stack, "start_db", lambda **_kwargs: True)
    monkeypatch.setattr(dev_stack, "_write_pidfile", lambda _processes: None)
    monkeypatch.setattr(dev_stack.signal, "signal", lambda *_args: None)
    monkeypatch.setattr(dev_stack.atexit, "register", lambda *_args: None)
    monkeypatch.setattr(
        dev_stack,
        "_spawn",
        lambda *_args, **_kwargs: _ProcessStub(400, -signal.SIGTERM),
    )

    assert dev_stack.start_stack() == 143


@pytest.mark.parametrize("failure_stage", ["worker", "frontend", "pidfile"])
def test_managed_stack_rolls_back_every_partially_started_process(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    failure_stage: str,
) -> None:
    dev_stack = _load_dev_stack()
    started: list[_ProcessStub] = []
    terminated: list[int] = []

    monkeypatch.setattr(dev_stack, "stop_apps", lambda **_kwargs: None)
    monkeypatch.setattr(dev_stack, "start_db", lambda **_kwargs: True)
    monkeypatch.setattr(dev_stack, "PIDFILE", tmp_path / "dev-stack.pid")
    monkeypatch.setattr(dev_stack, "_terminate_pid", terminated.append)

    def spawn(
        name: str,
        _cmd: list[str],
        *,
        cwd: Path,
        env: dict[str, str] | None = None,
    ) -> _ProcessStub:
        del cwd, env
        if name == failure_stage:
            raise OSError(f"cannot start {name}")
        process = _ProcessStub(200 + len(started))
        started.append(process)
        return process

    def write_pidfile(_processes: dict[str, _ProcessStub]) -> None:
        if failure_stage == "pidfile":
            raise OSError("cannot write pidfile")

    monkeypatch.setattr(dev_stack, "_spawn", spawn)
    monkeypatch.setattr(dev_stack, "_write_pidfile", write_pidfile)

    with pytest.raises(OSError):
        dev_stack.start_stack()

    assert terminated == [process.pid for process in reversed(started)]
