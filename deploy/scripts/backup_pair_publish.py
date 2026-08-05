#!/usr/bin/env python3
"""Atomically publish a private backup pair without replacing another writer's file."""

from __future__ import annotations

import os
import re
import signal
import stat
import sys
from pathlib import Path

_BACKUP_NAME = re.compile(r"^[0-9]{8}T[0-9]{6}Z\.dump$")
_STAGING_NAME = re.compile(r"^\.(?:backup|rehydrate)-[A-Za-z0-9._-]+$")
_BLOCKED_SIGNALS = tuple(
    candidate
    for candidate in (signal.SIGHUP, signal.SIGINT, signal.SIGTERM)
    if candidate is not None
)


def _fail(message: str) -> None:
    print(f"Backup pair publication refused: {message}.", file=sys.stderr)
    raise SystemExit(1)


def _same_inode(first: os.stat_result, second: os.stat_result) -> bool:
    return (first.st_dev, first.st_ino) == (second.st_dev, second.st_ino)


def _stat_regular(directory_fd: int, name: str) -> os.stat_result:
    try:
        candidate = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    except OSError:
        _fail("staging file cannot be inspected")
    if not stat.S_ISREG(candidate.st_mode) or stat.S_ISLNK(candidate.st_mode):
        _fail("staging file is not a regular non-symlink file")
    if candidate.st_size == 0:
        _fail("staging file is empty")
    return candidate


def _unlink_if_same_inode(
    directory_fd: int, name: str, expected: os.stat_result
) -> None:
    try:
        candidate = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        return
    except OSError:
        return
    if not stat.S_ISREG(candidate.st_mode) or not _same_inode(candidate, expected):
        return
    try:
        os.unlink(name, dir_fd=directory_fd)
    except OSError:
        return


def _fsync_file(directory_fd: int, name: str) -> None:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(name, flags, dir_fd=directory_fd)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except OSError:
        _fail("published file cannot be synced")


def _block_signals() -> set[signal.Signals] | None:
    if not hasattr(signal, "pthread_sigmask"):
        return None
    try:
        return signal.pthread_sigmask(signal.SIG_BLOCK, _BLOCKED_SIGNALS)
    except (OSError, RuntimeError, ValueError):
        _fail("cannot protect backup pair publication")
    raise AssertionError


def _restore_signals(previous: set[signal.Signals] | None) -> None:
    if previous is None:
        return
    try:
        for blocked in _BLOCKED_SIGNALS:
            signal.signal(blocked, signal.SIG_IGN)
        signal.pthread_sigmask(signal.SIG_SETMASK, previous)
    except (OSError, RuntimeError, ValueError):
        _fail("cannot complete backup pair publication")


def publish(
    directory: str, staging_dump: str, staging_sidecar: str, dump_name: str
) -> None:
    backup_dir = Path(directory)
    dump_path = Path(staging_dump)
    sidecar_path = Path(staging_sidecar)
    if _BACKUP_NAME.fullmatch(dump_name) is None:
        _fail("backup basename is invalid")
    if (
        dump_path.parent != backup_dir
        or sidecar_path.parent != backup_dir
        or _STAGING_NAME.fullmatch(dump_path.name) is None
        or _STAGING_NAME.fullmatch(sidecar_path.name) is None
    ):
        _fail("staging path is outside the private backup directory")
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        directory_stat = backup_dir.lstat()
        directory_fd = os.open(backup_dir, flags)
        opened_stat = os.fstat(directory_fd)
    except OSError:
        _fail("private backup directory cannot be opened")
    try:
        if (
            stat.S_ISLNK(directory_stat.st_mode)
            or not stat.S_ISDIR(opened_stat.st_mode)
            or opened_stat.st_uid != os.getuid()
            or stat.S_IMODE(opened_stat.st_mode) != 0o700
            or not _same_inode(directory_stat, opened_stat)
        ):
            _fail("private backup directory is unsafe")
        dump_stage_stat = _stat_regular(directory_fd, dump_path.name)
        sidecar_stage_stat = _stat_regular(directory_fd, sidecar_path.name)
        sidecar_name = f"{dump_name}.sha256"
        sidecar_linked = False
        dump_linked = False
        previous_mask = _block_signals()
        try:
            try:
                os.link(
                    sidecar_path.name,
                    sidecar_name,
                    src_dir_fd=directory_fd,
                    dst_dir_fd=directory_fd,
                    follow_symlinks=False,
                )
                sidecar_linked = True
            except FileExistsError:
                _fail("backup checksum already exists")
            try:
                os.link(
                    dump_path.name,
                    dump_name,
                    src_dir_fd=directory_fd,
                    dst_dir_fd=directory_fd,
                    follow_symlinks=False,
                )
                dump_linked = True
            except FileExistsError:
                _fail("backup dump already exists")
            _fsync_file(directory_fd, sidecar_name)
            _fsync_file(directory_fd, dump_name)
            os.fsync(directory_fd)
            os.unlink(sidecar_path.name, dir_fd=directory_fd)
            os.unlink(dump_path.name, dir_fd=directory_fd)
            os.fsync(directory_fd)
        except BaseException:
            if dump_linked:
                _unlink_if_same_inode(directory_fd, dump_name, dump_stage_stat)
            if sidecar_linked:
                _unlink_if_same_inode(directory_fd, sidecar_name, sidecar_stage_stat)
            try:
                os.fsync(directory_fd)
            except OSError:
                pass
            raise
        finally:
            _restore_signals(previous_mask)
    finally:
        os.close(directory_fd)


def main(arguments: list[str]) -> None:
    if len(arguments) != 6 or arguments[1] != "publish":
        _fail(
            "usage is publish <backup-dir> <staging-dump> <staging-sidecar> <dump-name>"
        )
    publish(*arguments[2:])


if __name__ == "__main__":
    main(sys.argv)
