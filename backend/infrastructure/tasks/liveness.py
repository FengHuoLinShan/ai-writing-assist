#!/usr/bin/env python3
"""Bounded control-loop liveness signal for the production task worker."""

from __future__ import annotations

import math
import os
import re
import tempfile
import time
from collections.abc import Callable
from pathlib import Path

CONTROL_LOOP_MARKER_PATH = Path("/tmp/ai-writing-task-worker-control-loop")
DEFAULT_FRESHNESS_SECONDS = 30.0
_MAX_MARKER_BYTES = 128
_MARKER_VALUE_RE = re.compile(
    r"^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?\n$"
)


def write_control_loop_liveness(
    *,
    marker_path: Path = CONTROL_LOOP_MARKER_PATH,
    monotonic: Callable[[], float] = time.monotonic,
) -> None:
    """Atomically publish that the TaskWorker control loop just ran."""
    timestamp = monotonic()
    if not math.isfinite(timestamp):
        raise ValueError("control-loop monotonic timestamp must be finite")

    marker_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{marker_path.name}.",
        dir=marker_path.parent,
    )
    temporary_path = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        marker_file = os.fdopen(descriptor, "w", encoding="ascii")
        descriptor = -1
        with marker_file:
            marker_file.write(f"{timestamp:.17g}\n")
            marker_file.flush()
        os.replace(temporary_path, marker_path)
    finally:
        if descriptor != -1:
            os.close(descriptor)
        try:
            temporary_path.unlink()
        except OSError:
            pass


def _is_worker_pid_one(cmdline_path: Path) -> bool:
    try:
        argv_tokens = cmdline_path.read_bytes().split(b"\0")
    except OSError:
        return False
    return any(
        token == b"run_worker.py"
        or (token.startswith(b"/") and token.endswith(b"/run_worker.py"))
        for token in argv_tokens
    )


def is_control_loop_liveness_healthy(
    *,
    marker_path: Path = CONTROL_LOOP_MARKER_PATH,
    cmdline_path: Path = Path("/proc/1/cmdline"),
    freshness_seconds: float = DEFAULT_FRESHNESS_SECONDS,
    monotonic: Callable[[], float] = time.monotonic,
) -> bool:
    """Return whether PID 1 is the worker and its control loop is fresh."""
    if not math.isfinite(freshness_seconds) or freshness_seconds <= 0:
        return False
    if not _is_worker_pid_one(cmdline_path):
        return False
    try:
        if marker_path.is_symlink() or not marker_path.is_file():
            return False
        with marker_path.open("rb") as marker_file:
            raw_marker = marker_file.read(_MAX_MARKER_BYTES + 1)
        if len(raw_marker) > _MAX_MARKER_BYTES:
            return False
        marker_text = raw_marker.decode("ascii")
        if not _MARKER_VALUE_RE.fullmatch(marker_text):
            return False
        recorded_at = float(marker_text)
        current_time = monotonic()
    except (OSError, UnicodeDecodeError, ValueError):
        return False
    if not math.isfinite(recorded_at) or not math.isfinite(current_time):
        return False
    age = current_time - recorded_at
    return 0 <= age <= freshness_seconds


def main(
    *,
    health_check: Callable[[], bool] = is_control_loop_liveness_healthy,
) -> int:
    return 0 if health_check() else 1


if __name__ == "__main__":
    raise SystemExit(main())
