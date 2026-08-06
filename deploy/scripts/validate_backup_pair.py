#!/usr/bin/env python3
"""Validate a private PostgreSQL dump pair without following links or writing it."""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import stat
import sys
from pathlib import Path

_BACKUP_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*\.dump$")
_SNAPSHOT_NAME = re.compile(r"^restore-input-[0-9a-f]{24}\.dump$")
_CHECKSUM_RECORD = re.compile(rb"^([0-9a-f]{64})(?:  [^\r\n]+)?\n?$")


def _fail(message: str) -> None:
    print(f"Backup pair validation failed: {message}.", file=sys.stderr)
    raise SystemExit(1)


def _open_regular(directory_fd: int, name: str, *, require_nonempty: bool) -> int:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(name, flags, dir_fd=directory_fd)
    except OSError:
        _fail("backup input cannot be opened safely")
    metadata = os.fstat(descriptor)
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or stat.S_IMODE(metadata.st_mode) != 0o600
        or metadata.st_nlink != 1
        or (require_nonempty and metadata.st_size <= 0)
    ):
        os.close(descriptor)
        _fail("backup input must be a current-user 0600 regular file")
    return descriptor


def _same_file(first: os.stat_result, second: os.stat_result) -> bool:
    return (
        first.st_dev,
        first.st_ino,
        first.st_size,
        first.st_mtime_ns,
        first.st_ctime_ns,
        first.st_nlink,
        stat.S_IMODE(first.st_mode),
        first.st_uid,
    ) == (
        second.st_dev,
        second.st_ino,
        second.st_size,
        second.st_mtime_ns,
        second.st_ctime_ns,
        second.st_nlink,
        stat.S_IMODE(second.st_mode),
        second.st_uid,
    )


def _same_directory(first: os.stat_result, second: os.stat_result) -> bool:
    return (
        first.st_dev,
        first.st_ino,
        stat.S_IMODE(first.st_mode),
        first.st_uid,
    ) == (
        second.st_dev,
        second.st_ino,
        stat.S_IMODE(second.st_mode),
        second.st_uid,
    )


def _write_all(descriptor: int, payload: bytes) -> None:
    offset = 0
    while offset < len(payload):
        written = os.write(descriptor, payload[offset:])
        if written <= 0:
            _fail("private snapshot could not be written")
        offset += written


def _create_snapshot(
    directory_fd: int,
    dump_fd: int,
    snapshot_path: Path,
    expected_digest: str,
) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    snapshot_fd = -1
    sidecar_fd = -1
    sidecar_name = f"{snapshot_path.name}.sha256"
    try:
        snapshot_fd = os.open(
            snapshot_path.name,
            flags,
            0o600,
            dir_fd=directory_fd,
        )
        os.lseek(dump_fd, 0, os.SEEK_SET)
        snapshot_digest = hashlib.sha256()
        while chunk := os.read(dump_fd, 1024 * 1024):
            _write_all(snapshot_fd, chunk)
            snapshot_digest.update(chunk)
        os.fsync(snapshot_fd)
        if not hmac.compare_digest(snapshot_digest.hexdigest(), expected_digest):
            _fail("private snapshot digest does not match the validated dump")

        sidecar_fd = os.open(sidecar_name, flags, 0o600, dir_fd=directory_fd)
        _write_all(
            sidecar_fd,
            f"{expected_digest}  {snapshot_path.name}\n".encode("ascii"),
        )
        os.fsync(sidecar_fd)
        os.fsync(directory_fd)
    except BaseException:
        for name in (sidecar_name, snapshot_path.name):
            try:
                os.unlink(name, dir_fd=directory_fd)
            except FileNotFoundError:
                pass
        raise
    finally:
        if sidecar_fd >= 0:
            os.close(sidecar_fd)
        if snapshot_fd >= 0:
            os.close(snapshot_fd)


def validate(
    backup_directory: Path,
    backup_input: Path,
    snapshot_output: Path | None = None,
) -> tuple[Path, str, int]:
    directory_path = Path(os.path.abspath(backup_directory))
    backup_path = Path(os.path.abspath(backup_input))
    if backup_path.parent != directory_path or _BACKUP_NAME.fullmatch(backup_path.name) is None:
        _fail("dump must be a direct .dump child of the private backup directory")
    snapshot_path: Path | None = None
    if snapshot_output is not None:
        snapshot_path = Path(os.path.abspath(snapshot_output))
        if (
            snapshot_path.parent != directory_path
            or _SNAPSHOT_NAME.fullmatch(snapshot_path.name) is None
            or snapshot_path == backup_path
        ):
            _fail("private snapshot path is outside the approved backup boundary")

    directory_flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        directory_flags |= os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        directory_flags |= os.O_NOFOLLOW
    try:
        directory_fd = os.open(directory_path, directory_flags)
    except OSError:
        _fail("private backup directory cannot be opened safely")
    try:
        directory_metadata = os.fstat(directory_fd)
        if (
            not stat.S_ISDIR(directory_metadata.st_mode)
            or directory_metadata.st_uid != os.getuid()
            or stat.S_IMODE(directory_metadata.st_mode) != 0o700
        ):
            _fail("private backup directory must be a current-user 0700 directory")

        dump_fd = _open_regular(directory_fd, backup_path.name, require_nonempty=True)
        try:
            sidecar_fd = _open_regular(
                directory_fd,
                f"{backup_path.name}.sha256",
                require_nonempty=True,
            )
            try:
                dump_before = os.fstat(dump_fd)
                sidecar_before = os.fstat(sidecar_fd)
                sidecar_contents = os.read(sidecar_fd, 4097)
                if len(sidecar_contents) > 4096:
                    _fail("checksum sidecar is too large")
                match = _CHECKSUM_RECORD.fullmatch(sidecar_contents)
                if match is None:
                    _fail("checksum sidecar must contain one lowercase SHA-256 record")
                expected_digest = match.group(1).decode("ascii")

                digest = hashlib.sha256()
                while chunk := os.read(dump_fd, 1024 * 1024):
                    digest.update(chunk)
                actual_digest = digest.hexdigest()
                if not hmac.compare_digest(expected_digest, actual_digest):
                    _fail("checksum does not match the selected dump")
                if snapshot_path is not None:
                    try:
                        _create_snapshot(
                            directory_fd,
                            dump_fd,
                            snapshot_path,
                            actual_digest,
                        )
                    except OSError:
                        _fail("private snapshot could not be created safely")
                if not _same_file(dump_before, os.fstat(dump_fd)) or not _same_file(
                    sidecar_before,
                    os.fstat(sidecar_fd),
                ):
                    _fail("backup pair changed during validation")
                path_metadata = os.stat(directory_path, follow_symlinks=False)
                if not _same_directory(directory_metadata, path_metadata):
                    _fail("private backup directory changed during validation")
                return snapshot_path or backup_path, actual_digest, dump_before.st_size
            finally:
                os.close(sidecar_fd)
        finally:
            os.close(dump_fd)
    finally:
        os.close(directory_fd)


def main(arguments: list[str]) -> int:
    if len(arguments) not in {3, 4}:
        print(
            "Usage: validate_backup_pair.py <backup-directory> <backup.dump> "
            "[private-snapshot.dump]",
            file=sys.stderr,
        )
        return 2
    snapshot_output = Path(arguments[3]) if len(arguments) == 4 else None
    backup_path, digest, size = validate(
        Path(arguments[1]),
        Path(arguments[2]),
        snapshot_output,
    )
    print(backup_path)
    print(digest)
    print(size)
    print(Path(os.path.abspath(arguments[2])))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
