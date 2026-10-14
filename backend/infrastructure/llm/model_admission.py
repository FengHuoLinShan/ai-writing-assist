"""Model pools shared by local API/worker processes; no aggregate quota."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import stat
from contextlib import asynccontextmanager
from pathlib import Path


def _admission_directory() -> Path:
    directory = (
        Path(os.environ["LLM_MODEL_ADMISSION_DIRECTORY"])
        if os.environ.get("LLM_MODEL_ADMISSION_DIRECTORY")
        else Path("/tmp") / f"novelcraft-model-admission-{os.getuid()}"
    )
    directory.mkdir(mode=0o700, exist_ok=True)
    info = directory.lstat()
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid != os.getuid()
        or info.st_mode & 0o077
    ):
        raise ValueError(
            "Model admission directory must be private and owned by this user"
        )
    return directory


def _open_lock(path: Path) -> int:
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    info = os.fstat(fd)
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.getuid()
        or info.st_mode & 0o077
    ):
        os.close(fd)
        raise ValueError("Model admission file must be private and owned by this user")
    return fd


def _try_admit(directory: Path, identity: str, limit: int, rpm: int = 0) -> int | None:
    import fcntl

    guard = _open_lock(directory / f"{identity}.limit")
    locked = []
    try:
        try:
            fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
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
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
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
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
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
    )

    while True:
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
