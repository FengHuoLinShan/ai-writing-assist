#!/usr/bin/env python3
"""Serialize mutating production deployment operations with a host-local lock."""

from __future__ import annotations

import errno
import fcntl
import os
import stat
import sys
from pathlib import Path

_LOCK_ENV = "AI_WRITING_ASSIST_PRODUCTION_OPERATION_LOCK_FD"
_LOCK_FILE_MODE = 0o600
_STATE_DIR_MODE = 0o700
_LOCK_HELD_MESSAGE = "Another production operation is already running."
_LOCK_UNSAFE_MESSAGE = "Production operation lock is unsafe."


def _fail(message: str) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(1)


def _open_private_state_dir(state_dir: Path) -> int:
    fd = -1
    try:
        state_dir.mkdir(mode=_STATE_DIR_MODE, exist_ok=True)
        flags = os.O_RDONLY
        if hasattr(os, "O_DIRECTORY"):
            flags |= os.O_DIRECTORY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(state_dir, flags)
        descriptor_stat = os.fstat(fd)
        if (
            not stat.S_ISDIR(descriptor_stat.st_mode)
            or descriptor_stat.st_uid != os.getuid()
        ):
            raise OSError("invalid state directory")
        os.fchmod(fd, _STATE_DIR_MODE)
        path_stat = os.lstat(state_dir)
    except OSError:
        if fd >= 0:
            os.close(fd)
        _fail(_LOCK_UNSAFE_MESSAGE)
    if (
        stat.S_ISLNK(path_stat.st_mode)
        or not stat.S_ISDIR(descriptor_stat.st_mode)
        or descriptor_stat.st_uid != os.getuid()
        or stat.S_IMODE(descriptor_stat.st_mode) != _STATE_DIR_MODE
        or (descriptor_stat.st_dev, descriptor_stat.st_ino)
        != (path_stat.st_dev, path_stat.st_ino)
    ):
        os.close(fd)
        _fail(_LOCK_UNSAFE_MESSAGE)
    return fd


def _open_and_validate_lock(lock_path: Path) -> int:
    state_fd = _open_private_state_dir(lock_path.parent)
    flags = os.O_RDWR | os.O_CREAT
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(lock_path.name, flags, _LOCK_FILE_MODE, dir_fd=state_fd)
    except OSError:
        _fail(_LOCK_UNSAFE_MESSAGE)
    try:
        descriptor_stat = os.fstat(fd)
        path_stat = os.stat(lock_path.name, dir_fd=state_fd, follow_symlinks=False)
        if (
            stat.S_ISLNK(path_stat.st_mode)
            or not stat.S_ISREG(descriptor_stat.st_mode)
            or descriptor_stat.st_uid != os.getuid()
            or stat.S_IMODE(descriptor_stat.st_mode) != _LOCK_FILE_MODE
            or (descriptor_stat.st_dev, descriptor_stat.st_ino)
            != (path_stat.st_dev, path_stat.st_ino)
        ):
            raise OSError("invalid lock file")
        return fd
    except OSError:
        os.close(fd)
        _fail(_LOCK_UNSAFE_MESSAGE)
    finally:
        os.close(state_fd)


def _acquire_nonblocking(fd: int) -> None:
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        if exc.errno in (errno.EACCES, errno.EAGAIN):
            _fail(_LOCK_HELD_MESSAGE)
        _fail(_LOCK_UNSAFE_MESSAGE)


def _acquire(lock_path: Path, command: list[str]) -> None:
    if not command:
        _fail(_LOCK_UNSAFE_MESSAGE)
    fd = _open_and_validate_lock(lock_path)
    _acquire_nonblocking(fd)
    os.set_inheritable(fd, True)
    environment = os.environ.copy()
    environment[_LOCK_ENV] = str(fd)
    try:
        os.execvpe(command[0], command, environment)
    except OSError:
        _fail(_LOCK_UNSAFE_MESSAGE)


def _verify(lock_path: Path, fd_text: str) -> None:
    try:
        fd = int(fd_text)
    except ValueError:
        _fail(_LOCK_UNSAFE_MESSAGE)
    if fd < 0:
        _fail(_LOCK_UNSAFE_MESSAGE)
    state_fd = _open_private_state_dir(lock_path.parent)
    try:
        descriptor_stat = os.fstat(fd)
        path_stat = os.stat(lock_path.name, dir_fd=state_fd, follow_symlinks=False)
        if (
            stat.S_ISLNK(path_stat.st_mode)
            or not stat.S_ISREG(descriptor_stat.st_mode)
            or descriptor_stat.st_uid != os.getuid()
            or stat.S_IMODE(descriptor_stat.st_mode) != _LOCK_FILE_MODE
            or (descriptor_stat.st_dev, descriptor_stat.st_ino)
            != (path_stat.st_dev, path_stat.st_ino)
        ):
            raise OSError("invalid inherited lock")
    except OSError:
        _fail(_LOCK_UNSAFE_MESSAGE)
    finally:
        os.close(state_fd)
    _acquire_nonblocking(fd)


def main(argv: list[str]) -> None:
    if len(argv) < 3:
        _fail(_LOCK_UNSAFE_MESSAGE)
    operation, lock_file, *arguments = argv[1:]
    lock_path = Path(lock_file)
    if operation == "acquire":
        _acquire(lock_path, arguments)
    if operation == "verify" and len(arguments) == 1:
        _verify(lock_path, arguments[0])
        return
    _fail(_LOCK_UNSAFE_MESSAGE)


if __name__ == "__main__":
    main(sys.argv)
