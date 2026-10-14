"""One bounded native-Codex account queue shared by local API/worker processes."""

from __future__ import annotations

import asyncio
import os
import stat
from contextlib import asynccontextmanager
from pathlib import Path

from infrastructure.llm.codex_identity import codex_login_identity
from infrastructure.llm.errors import LLMError


def _admission_directory() -> Path:
    directory = Path("/tmp") / f"novelcraft-codex-admission-{os.getuid()}"
    directory.mkdir(mode=0o700, exist_ok=True)
    info = directory.lstat()
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid != os.getuid()
        or info.st_mode & 0o077
    ):
        raise ValueError(
            "Codex admission directory must be private and owned by this user"
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
        raise ValueError("Codex admission file must be private and owned by this user")
    return fd


def _try_admit(directory: Path, identity: str, limit: int) -> int | None:
    import fcntl

    guard = _open_lock(directory / f"{identity}.limit")
    locked = []
    try:
        try:
            fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return None
        saved = os.read(guard, 17)
        if saved != str(limit).encode():
            # A capacity change is allowed only while every account slot is idle.
            for i in range(8):
                fd = _open_lock(directory / f"{identity}.{i}")
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError as exc:
                    os.close(fd)
                    raise LLMError(
                        "Codex worker 并发配置不一致；请等待在途结束后统一配置",
                        provider="codex",
                        error_kind="codex_admission_configuration",
                    ) from exc
                locked.append(fd)
            os.lseek(guard, 0, os.SEEK_SET)
            os.ftruncate(guard, 0)
            os.write(guard, str(limit).encode())
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
async def codex_account_admission(limit: int):
    """OS releases slots on process death; cancellation never leaks an admission."""
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 8:
        raise ValueError("Codex admission limit must be an integer from 1 to 8")
    identity = codex_login_identity()
    directory = _admission_directory()
    from infrastructure.llm.limits import (
        _ai_run_remaining_seconds,
        _raise_ai_run_deadline,
    )

    while True:
        remaining = _ai_run_remaining_seconds()
        if remaining is not None and remaining <= 0:
            _raise_ai_run_deadline()
        fd = _try_admit(directory, identity, limit)
        if fd is not None:
            break
        await asyncio.sleep(min(0.025, remaining) if remaining is not None else 0.025)
    try:
        yield
    finally:
        os.close(fd)
