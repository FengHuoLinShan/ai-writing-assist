#!/usr/bin/env python3
"""Manage the local development stack.

This script is intentionally small and dependency-free. It replaces fragile
Makefile-only process matching with pidfile + process-group cleanup, while
still keeping command/port fallbacks for stale processes from older runs.
"""

from __future__ import annotations

import argparse
import atexit
import hashlib
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend-console"

STACK_ID = hashlib.sha1(str(ROOT).encode("utf-8")).hexdigest()[:12]
PIDFILE = Path("/tmp") / f"ai-writing-assist-dev-stack-{STACK_ID}.json"

BACKEND_PORT = int(os.environ.get("BACKEND_PORT", "8000"))
FRONTEND_PORT = int(os.environ.get("FRONTEND_PORT", "8080"))
DB_CONTAINER = os.environ.get("DEV_DB_CONTAINER", "ai-novel-db")

def _run(
    cmd: list[str],
    *,
    cwd: Path = ROOT,
    check: bool = True,
    capture: bool = False,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=str(cwd),
        check=check,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
        env=env,
    )


def _fallback_patterns() -> tuple[str, ...]:
    return (
        rf"python .*scripts/dev_server\.py.*--port {BACKEND_PORT}",
        r"python .*run_worker\.py.*--reload",
        r"python .*run_worker\.py$",
        rf"vite .*--port {FRONTEND_PORT}",
    )


def _read_pidfile() -> dict[str, Any]:
    if not PIDFILE.exists():
        return {}
    try:
        return json.loads(PIDFILE.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def _write_pidfile(processes: dict[str, subprocess.Popen[Any]]) -> None:
    data = {
        "root": str(ROOT),
        "created_at": time.time(),
        "processes": {name: proc.pid for name, proc in processes.items()},
        "ports": {"backend": BACKEND_PORT, "frontend": FRONTEND_PORT},
    }
    PIDFILE.write_text(json.dumps(data, indent=2, sort_keys=True))


def _is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _children_of(pid: int) -> list[int]:
    result = _run(["pgrep", "-P", str(pid)], check=False, capture=True)
    if result.returncode not in (0, 1):
        return []
    children: list[int] = []
    for line in (result.stdout or "").splitlines():
        try:
            children.append(int(line.strip()))
        except ValueError:
            pass
    return children


def _descendants(pid: int) -> list[int]:
    found: list[int] = []
    queue = _children_of(pid)
    while queue:
        child = queue.pop()
        found.append(child)
        queue.extend(_children_of(child))
    return found


def _terminate_pid(pid: int, *, timeout: float = 3.0) -> None:
    if pid <= 1 or not _is_alive(pid):
        return

    try:
        os.killpg(pid, signal.SIGTERM)
        targets = [pid]
    except ProcessLookupError:
        return
    except PermissionError:
        return
    except OSError:
        targets = [*_descendants(pid), pid]
        for target in targets:
            try:
                os.kill(target, signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                pass

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not any(_is_alive(target) for target in targets):
            return
        time.sleep(0.1)

    try:
        os.killpg(pid, signal.SIGKILL)
        return
    except (ProcessLookupError, PermissionError, OSError):
        pass

    for target in targets:
        try:
            os.kill(target, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass


def _pids_for_pattern(pattern: str) -> set[int]:
    result = _run(["pgrep", "-f", pattern], check=False, capture=True)
    if result.returncode not in (0, 1):
        return set()
    current = {os.getpid(), os.getppid()}
    pids: set[int] = set()
    for line in (result.stdout or "").splitlines():
        try:
            pid = int(line.strip())
        except ValueError:
            continue
        if pid not in current:
            pids.add(pid)
    return pids


def _pids_for_port(port: int) -> set[int]:
    result = _run(
        ["lsof", "-ti", f"TCP:{port}", "-sTCP:LISTEN"],
        check=False,
        capture=True,
    )
    if result.returncode not in (0, 1):
        return set()
    pids: set[int] = set()
    for line in (result.stdout or "").splitlines():
        try:
            pids.add(int(line.strip()))
        except ValueError:
            pass
    return pids


def stop_apps(*, fallback: bool = True, remove_pidfile: bool = True) -> None:
    data = _read_pidfile()
    processes = data.get("processes") if isinstance(data, dict) else {}
    if isinstance(processes, dict):
        for name, raw_pid in processes.items():
            try:
                pid = int(raw_pid)
            except (TypeError, ValueError):
                continue
            if _is_alive(pid):
                print(f"Stopping {name} pid={pid}")
                _terminate_pid(pid)

    if fallback:
        fallback_pids: set[int] = set()
        for pattern in _fallback_patterns():
            fallback_pids.update(_pids_for_pattern(pattern))
        fallback_pids.update(_pids_for_port(BACKEND_PORT))
        fallback_pids.update(_pids_for_port(FRONTEND_PORT))
        for pid in sorted(fallback_pids):
            if _is_alive(pid):
                print(f"Stopping stale dev process pid={pid}")
                _terminate_pid(pid)

    if remove_pidfile:
        try:
            PIDFILE.unlink()
        except FileNotFoundError:
            pass


def start_db() -> None:
    inspect = _run(["docker", "inspect", DB_CONTAINER], check=False, capture=True)
    if inspect.returncode == 0:
        print(f"=== Reusing existing {DB_CONTAINER} container ===")
        _run(["docker", "start", DB_CONTAINER], check=False, capture=True)
    else:
        _run(["docker", "compose", "up", "-d"], cwd=ROOT)

    while True:
        health = _run(
            ["docker", "inspect", "-f", "{{.State.Health.Status}}", DB_CONTAINER],
            check=False,
            capture=True,
        )
        status = (health.stdout or "").strip()
        if status == "healthy":
            return
        if health.returncode == 0 and status in {"", "<no value>"}:
            return
        print(f"Waiting for {DB_CONTAINER} healthcheck...")
        time.sleep(1)


def stop_db() -> None:
    inspect = _run(["docker", "inspect", DB_CONTAINER], check=False, capture=True)
    if inspect.returncode != 0:
        return
    print(f"Stopping {DB_CONTAINER}")
    _run(["docker", "stop", DB_CONTAINER], check=False, capture=True)


def _spawn(
    name: str,
    cmd: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
) -> subprocess.Popen[Any]:
    print(f"Starting {name}: {' '.join(cmd)}")
    return subprocess.Popen(
        cmd,
        cwd=str(cwd),
        env=env,
        start_new_session=True,
    )


def start_stack() -> int:
    stop_apps(fallback=True)
    start_db()

    frontend_env = os.environ.copy()
    frontend_env["FRONTEND_PORT"] = str(FRONTEND_PORT)

    processes = {
        "backend": _spawn(
            "backend",
            [
                sys.executable,
                "scripts/dev_server.py",
                "--host",
                "0.0.0.0",
                "--port",
                str(BACKEND_PORT),
            ],
            cwd=BACKEND,
        ),
        "worker": _spawn(
            "worker",
            [sys.executable, "run_worker.py", "--reload"],
            cwd=BACKEND,
        ),
        "frontend": _spawn(
            "frontend",
            ["npm", "run", "dev"],
            cwd=FRONTEND,
            env=frontend_env,
        ),
    }
    _write_pidfile(processes)

    stopping = False

    def shutdown(_signum: int | None = None, _frame: Any | None = None) -> None:
        nonlocal stopping
        if stopping:
            return
        stopping = True
        stop_apps(fallback=False)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)
    atexit.register(shutdown)

    print("")
    print("=== Services started ===")
    print(f"  Backend:  http://localhost:{BACKEND_PORT} (--reload)")
    print(f"  Frontend: http://localhost:{FRONTEND_PORT} (Vite hot reload)")
    print("  Worker:   running with --reload")
    print("  Press Ctrl+C to stop app services")

    try:
        while True:
            for name, proc in processes.items():
                code = proc.poll()
                if code is not None:
                    print(f"{name} exited with code {code}; stopping stack")
                    shutdown()
                    return code or 0
            time.sleep(0.5)
    finally:
        shutdown()


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage local dev services")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("start")
    subparsers.add_parser("stop")
    subparsers.add_parser("stop-apps")
    subparsers.add_parser("start-db")
    subparsers.add_parser("stop-db")
    args = parser.parse_args()

    if args.command == "start":
        return start_stack()
    if args.command == "stop":
        stop_apps(fallback=True)
        stop_db()
        return 0
    if args.command == "stop-apps":
        stop_apps(fallback=True)
        return 0
    if args.command == "start-db":
        start_db()
        return 0
    if args.command == "stop-db":
        stop_db()
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
