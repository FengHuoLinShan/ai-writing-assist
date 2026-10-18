"""Model pools shared by local API/worker processes; no aggregate quota."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path

from infrastructure.os_security import open_private_file, private_directory, try_lock


def _admission_directory() -> Path:
    directory = (
        Path(os.environ["LLM_MODEL_ADMISSION_DIRECTORY"])
        if os.environ.get("LLM_MODEL_ADMISSION_DIRECTORY")
        else (
            Path.home() / "AppData/Local/NovelCraft/model-admission"
            if os.name == "nt"
            else Path("/tmp") / f"novelcraft-model-admission-{os.getuid()}"
        )
    )
    return private_directory(directory)


def _open_lock(path: Path) -> int:
    return open_private_file(path, write=True)


def _try_admit(directory: Path, identity: str, limit: int, rpm: int = 0) -> int | None:
    guard = _open_lock(directory / f"{identity}.limit")
    locked = []
    try:
        if not try_lock(guard):
            return None
        saved = os.read(guard, 256)
        config = json.dumps({"concurrency": limit, "rpm": rpm}).encode()
        if saved != config:
            # A capacity change is allowed only while every account slot is idle.
            previous = (
                json.loads(saved)["concurrency"]
                if saved.startswith(b"{")
                else int(saved or limit)
            )
            for i in range(max(previous, limit)):
                fd = _open_lock(directory / f"{identity}.{i}")
                if not try_lock(fd):
                    os.close(fd)
                    return None
                locked.append(fd)
            os.lseek(guard, 0, os.SEEK_SET)
            os.ftruncate(guard, 0)
            os.write(guard, config)
            for fd in locked:
                os.close(fd)
            locked.clear()
        for i in range(limit):
            fd = _open_lock(directory / f"{identity}.{i}")
            if not try_lock(fd):
                os.close(fd)
            else:
                return fd
        return None
    finally:
        for fd in locked:
            os.close(fd)
        os.close(guard)


@asynccontextmanager
async def model_admission(pool_key: tuple[str, ...], limit: int, *, rpm: int = 0):
    """OS releases slots on process death; cancellation never leaks an admission."""
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise ValueError("Model admission limit must be a positive integer")
    identity = hashlib.sha256(json.dumps(pool_key).encode()).hexdigest()
    directory = _admission_directory()
    from infrastructure.llm.limits import (
        _ai_run_remaining_seconds,
        _raise_ai_run_deadline,
        require_request_admission,
    )

    while True:
        require_request_admission()
        remaining = _ai_run_remaining_seconds()
        if remaining is not None and remaining <= 0:
            _raise_ai_run_deadline()
        fd = _try_admit(directory, identity, limit, rpm)
        if fd is not None:
            break
        await asyncio.sleep(min(0.025, remaining) if remaining is not None else 0.025)
    try:
        yield
    finally:
        os.close(fd)
