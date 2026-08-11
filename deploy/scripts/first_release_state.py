#!/usr/bin/env python3
"""Persist the recoverable database state of an unfinished first release."""

from __future__ import annotations

import json
import os
import secrets
import stat
import sys
from pathlib import Path
from typing import Any

_STATE_NAME = "first-release-prepared.json"
_STATE_DIR_MODE = 0o700
_STATE_FILE_MODE = 0o600
_MAX_STATE_BYTES = 1024
_REQUIRED_KEYS = {"schema_version", "prepared_commit"}


def _fail() -> None:
    print("First-release recovery state is unsafe.", file=sys.stderr)
    raise SystemExit(1)


def _is_commit(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 40
        and all(character in "0123456789abcdef" for character in value)
    )


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _open_state_dir(state_dir: Path) -> int:
    try:
        path_stat = state_dir.lstat()
        flags = os.O_RDONLY
        if hasattr(os, "O_DIRECTORY"):
            flags |= os.O_DIRECTORY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(state_dir, flags)
        descriptor_stat = os.fstat(descriptor)
    except OSError:
        _fail()
    if (
        stat.S_ISLNK(path_stat.st_mode)
        or not stat.S_ISDIR(descriptor_stat.st_mode)
        or descriptor_stat.st_uid != os.getuid()
        or stat.S_IMODE(descriptor_stat.st_mode) != _STATE_DIR_MODE
        or (descriptor_stat.st_dev, descriptor_stat.st_ino)
        != (path_stat.st_dev, path_stat.st_ino)
    ):
        os.close(descriptor)
        _fail()
    return descriptor


def _state_stat(directory_fd: int) -> os.stat_result | None:
    try:
        return os.stat(_STATE_NAME, dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        return None
    except OSError:
        _fail()


def _read(directory_fd: int) -> dict[str, Any]:
    path_stat = _state_stat(directory_fd)
    if path_stat is None:
        _fail()
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(_STATE_NAME, flags, dir_fd=directory_fd)
        descriptor_stat = os.fstat(descriptor)
        if (
            stat.S_ISLNK(path_stat.st_mode)
            or not stat.S_ISREG(descriptor_stat.st_mode)
            or descriptor_stat.st_uid != os.getuid()
            or stat.S_IMODE(descriptor_stat.st_mode) != _STATE_FILE_MODE
            or descriptor_stat.st_nlink != 1
            or (descriptor_stat.st_dev, descriptor_stat.st_ino)
            != (path_stat.st_dev, path_stat.st_ino)
            or descriptor_stat.st_size > _MAX_STATE_BYTES
        ):
            _fail()
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(descriptor, _MAX_STATE_BYTES + 1)
            if not chunk:
                break
            total += len(chunk)
            if total > _MAX_STATE_BYTES:
                _fail()
            chunks.append(chunk)
    except OSError:
        _fail()
    finally:
        if "descriptor" in locals():
            os.close(descriptor)
    raw = b"".join(chunks)
    try:
        decoded = raw.decode("utf-8")
        payload = json.loads(decoded, object_pairs_hook=_reject_duplicate_keys)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        _fail()
    if (
        "\n" in decoded
        or "\r" in decoded
        or not isinstance(payload, dict)
        or set(payload) != _REQUIRED_KEYS
        or payload["schema_version"] != 1
        or type(payload["schema_version"]) is not int
        or not _is_commit(payload["prepared_commit"])
    ):
        _fail()
    return payload


def _write(state_dir: Path, prepared_commit: str) -> None:
    if not _is_commit(prepared_commit):
        _fail()
    directory_fd = _open_state_dir(state_dir)
    temporary_name = f".{_STATE_NAME}.tmp.{secrets.token_hex(16)}"
    descriptor = -1
    try:
        existing = _state_stat(directory_fd)
        if existing is not None:
            if _read(directory_fd)["prepared_commit"] == prepared_commit:
                return
            _fail()
        encoded = json.dumps(
            {"schema_version": 1, "prepared_commit": prepared_commit},
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(
            temporary_name,
            flags,
            _STATE_FILE_MODE,
            dir_fd=directory_fd,
        )
        os.fchmod(descriptor, _STATE_FILE_MODE)
        written = 0
        while written < len(encoded):
            count = os.write(descriptor, encoded[written:])
            if count <= 0:
                raise OSError("short first-release state write")
            written += count
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        if _state_stat(directory_fd) is not None:
            _fail()
        os.replace(
            temporary_name,
            _STATE_NAME,
            src_dir_fd=directory_fd,
            dst_dir_fd=directory_fd,
        )
        temporary_name = ""
        os.fsync(directory_fd)
    except OSError:
        _fail()
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary_name:
            try:
                os.unlink(temporary_name, dir_fd=directory_fd)
            except FileNotFoundError:
                pass
            except OSError:
                pass
        os.close(directory_fd)


def _read_commit(state_dir: Path) -> str:
    directory_fd = _open_state_dir(state_dir)
    try:
        return str(_read(directory_fd)["prepared_commit"])
    finally:
        os.close(directory_fd)


def _clear(state_dir: Path) -> None:
    directory_fd = _open_state_dir(state_dir)
    try:
        if _state_stat(directory_fd) is None:
            return
        _read(directory_fd)
        os.unlink(_STATE_NAME, dir_fd=directory_fd)
        os.fsync(directory_fd)
    except OSError:
        _fail()
    finally:
        os.close(directory_fd)


def main(argv: list[str]) -> None:
    if len(argv) < 2:
        _fail()
    command, *arguments = argv[1:]
    if command == "write" and len(arguments) == 2:
        _write(Path(arguments[0]), arguments[1])
        return
    if command == "read" and len(arguments) == 1:
        print(_read_commit(Path(arguments[0])))
        return
    if command == "clear" and len(arguments) == 1:
        _clear(Path(arguments[0]))
        return
    _fail()


if __name__ == "__main__":
    main(sys.argv)
