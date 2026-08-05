#!/usr/bin/env python3
"""Read and atomically replace the authoritative private deployment state."""

from __future__ import annotations

import json
import os
import secrets
import signal
import stat
import sys
from pathlib import Path
from typing import Any

_STATE_NAME = "deployment-state.json"
_STATE_DIR_MODE = 0o700
_STATE_FILE_MODE = 0o600
_MAX_STATE_BYTES = 4096
_OPERATIONS = {"release", "restore"}
_REQUIRED_KEYS = {
    "schema_version",
    "operation_id",
    "operation",
    "current_commit",
    "previous_commit",
    "backup_path",
}
_BLOCKED_SIGNALS = tuple(
    candidate
    for candidate in (signal.SIGHUP, signal.SIGINT, signal.SIGTERM)
    if candidate is not None
)


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _fail() -> None:
    print("Deployment state is unsafe.", file=sys.stderr)
    raise SystemExit(1)


def _is_lower_hex(value: object, length: int) -> bool:
    return isinstance(value, str) and len(value) == length and all(
        character in "0123456789abcdef" for character in value
    )


def _open_state_dir(state_dir: Path, *, create: bool) -> int:
    if create:
        try:
            state_dir.mkdir(mode=_STATE_DIR_MODE, exist_ok=True)
        except OSError:
            _fail()
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


def _state_file_stat(directory_fd: int) -> os.stat_result | None:
    try:
        return os.stat(_STATE_NAME, dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        return None
    except OSError:
        _fail()


def _read_state_bytes(
    directory_fd: int, repo_root: Path
) -> tuple[dict[str, Any], bytes]:
    path_stat = _state_file_stat(directory_fd)
    if path_stat is None:
        _fail()
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(_STATE_NAME, flags, dir_fd=directory_fd)
        descriptor_stat = os.fstat(descriptor)
    except OSError:
        _fail()
    try:
        if (
            stat.S_ISLNK(path_stat.st_mode)
            or not stat.S_ISREG(descriptor_stat.st_mode)
            or descriptor_stat.st_uid != os.getuid()
            or stat.S_IMODE(descriptor_stat.st_mode) != _STATE_FILE_MODE
            or (descriptor_stat.st_dev, descriptor_stat.st_ino)
            != (path_stat.st_dev, path_stat.st_ino)
            or descriptor_stat.st_size > _MAX_STATE_BYTES
        ):
            _fail()
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, _MAX_STATE_BYTES + 1)
            if not chunk:
                break
            chunks.append(chunk)
            if sum(len(part) for part in chunks) > _MAX_STATE_BYTES:
                _fail()
    except OSError:
        _fail()
    finally:
        os.close(descriptor)
    try:
        decoded = b"".join(chunks).decode("utf-8")
        payload = json.loads(decoded, object_pairs_hook=_reject_duplicate_keys)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        _fail()
    if "\n" in decoded or "\r" in decoded:
        _fail()
    if not isinstance(payload, dict) or set(payload) != _REQUIRED_KEYS:
        _fail()
    _validate_payload(payload, repo_root, require_existing_backup=False)
    return payload, b"".join(chunks)


def _read_state(directory_fd: int, repo_root: Path) -> dict[str, Any]:
    return _read_state_bytes(directory_fd, repo_root)[0]


def _validate_backup_path(
    value: object,
    repo_root: Path,
    *,
    require_existing_file: bool,
) -> None:
    if not isinstance(value, str) or "\n" in value or "\r" in value:
        _fail()
    supplied = Path(value)
    if not supplied.is_absolute() or supplied.suffix != ".dump":
        _fail()
    try:
        resolved_root = repo_root.resolve(strict=True)
    except (OSError, RuntimeError):
        _fail()
    expected_directory = resolved_root / "deploy" / "backups"
    normalized_backup = Path(os.path.normpath(str(supplied)))
    if (
        str(supplied) != str(normalized_backup)
        or normalized_backup.parent != expected_directory
    ):
        _fail()
    if require_existing_file:
        try:
            directory_stat = expected_directory.lstat()
            backup_stat = normalized_backup.lstat()
        except OSError:
            _fail()
        if (
            stat.S_ISLNK(directory_stat.st_mode)
            or not stat.S_ISDIR(directory_stat.st_mode)
            or directory_stat.st_uid != os.getuid()
            or stat.S_IMODE(directory_stat.st_mode) != _STATE_DIR_MODE
            or stat.S_ISLNK(backup_stat.st_mode)
            or not stat.S_ISREG(backup_stat.st_mode)
        ):
            _fail()


def _validate_payload(
    payload: dict[str, Any],
    repo_root: Path,
    *,
    require_existing_backup: bool,
) -> None:
    if payload["schema_version"] != 1 or type(payload["schema_version"]) is not int:
        _fail()
    if not _is_lower_hex(payload["operation_id"], 32):
        _fail()
    if (
        not isinstance(payload["operation"], str)
        or payload["operation"] not in _OPERATIONS
    ):
        _fail()
    if not _is_lower_hex(payload["current_commit"], 40):
        _fail()
    if not _is_lower_hex(payload["previous_commit"], 40):
        _fail()
    _validate_backup_path(
        payload["backup_path"],
        repo_root,
        require_existing_file=require_existing_backup,
    )


def _payload(
    operation_id: str,
    operation: str,
    current_commit: str,
    previous_commit: str,
    backup_path: str,
    repo_root: Path,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": 1,
        "operation_id": operation_id,
        "operation": operation,
        "current_commit": current_commit,
        "previous_commit": previous_commit,
        "backup_path": backup_path,
    }
    _validate_payload(payload, repo_root, require_existing_backup=True)
    return payload


def _block_write_signals() -> set[signal.Signals] | None:
    if not hasattr(signal, "pthread_sigmask"):
        return None
    try:
        return signal.pthread_sigmask(signal.SIG_BLOCK, _BLOCKED_SIGNALS)
    except (OSError, RuntimeError, ValueError):
        _fail()


def _restore_write_signals(previous_mask: set[signal.Signals] | None) -> None:
    if previous_mask is None:
        return
    try:
        signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)
    except (OSError, RuntimeError, ValueError):
        _fail()


def _ignore_blocked_signals() -> None:
    """Keep child-only cancellation from changing a completed transaction's result.

    The deployment shell receives group signals itself and performs its nonce-aware
    cleanup.  This short-lived helper must not instead die while unblocking a
    pending signal after it has made a manifest visible.
    """
    try:
        for caught_signal in _BLOCKED_SIGNALS:
            signal.signal(caught_signal, signal.SIG_IGN)
    except (OSError, RuntimeError, ValueError):
        _fail()


def _write_temporary_state(
    directory_fd: int,
    contents: bytes,
) -> str:
    temporary_name = f".{_STATE_NAME}.tmp.{secrets.token_hex(16)}"
    descriptor = -1
    try:
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
        while written < len(contents):
            write_count = os.write(descriptor, contents[written:])
            if write_count <= 0:
                raise OSError("short deployment state write")
            written += write_count
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        return temporary_name
    except OSError:
        try:
            os.unlink(temporary_name, dir_fd=directory_fd)
        except FileNotFoundError:
            pass
        except OSError:
            pass
        raise
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _unlink_temporary_state(directory_fd: int, temporary_name: str | None) -> None:
    if temporary_name is None:
        return
    try:
        os.unlink(temporary_name, dir_fd=directory_fd)
    except FileNotFoundError:
        pass
    except OSError:
        _fail()


def _state_bytes_equal(
    directory_fd: int,
    repo_root: Path,
    expected: bytes | None,
) -> bool:
    try:
        if expected is None:
            return _state_file_stat(directory_fd) is None
        _payload, actual = _read_state_bytes(directory_fd, repo_root)
    except SystemExit:
        return False
    return actual == expected


def _restore_previous_state(
    directory_fd: int,
    repo_root: Path,
    previous_bytes: bytes | None,
    new_bytes: bytes,
) -> bool:
    """Restore the exact prior state after a post-replace fsync failure.

    Return false without raising when the recovery cannot be proven.  The caller
    then preserves the target checkout if the new manifest remains authoritative.
    """
    if not _state_bytes_equal(directory_fd, repo_root, new_bytes):
        return False
    temporary_name: str | None = None
    restored = False
    cleanup_failed = False
    try:
        if previous_bytes is None:
            os.unlink(_STATE_NAME, dir_fd=directory_fd)
        else:
            temporary_name = _write_temporary_state(directory_fd, previous_bytes)
            os.replace(
                temporary_name,
                _STATE_NAME,
                src_dir_fd=directory_fd,
                dst_dir_fd=directory_fd,
            )
            temporary_name = None
        os.fsync(directory_fd)
    except OSError:
        restored = False
    else:
        restored = True
    finally:
        if temporary_name is not None:
            try:
                os.unlink(temporary_name, dir_fd=directory_fd)
            except FileNotFoundError:
                pass
            except OSError:
                cleanup_failed = True
    return (
        restored
        and not cleanup_failed
        and _state_bytes_equal(directory_fd, repo_root, previous_bytes)
    )


def _write_state(directory_fd: int, payload: dict[str, Any], repo_root: Path) -> None:
    existing = _state_file_stat(directory_fd)
    previous_bytes = (
        _read_state_bytes(directory_fd, repo_root)[1] if existing is not None else None
    )
    encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    temporary_name: str | None = None
    replaced = False
    previous_mask = _block_write_signals()
    try:
        _ignore_blocked_signals()
        try:
            temporary_name = _write_temporary_state(directory_fd, encoded)
            if not _state_bytes_equal(directory_fd, repo_root, previous_bytes):
                _fail()
            os.replace(
                temporary_name,
                _STATE_NAME,
                src_dir_fd=directory_fd,
                dst_dir_fd=directory_fd,
            )
            temporary_name = None
            replaced = True
            os.fsync(directory_fd)
        except OSError:
            if not replaced:
                _fail()
            if _restore_previous_state(
                directory_fd,
                repo_root,
                previous_bytes,
                encoded,
            ):
                _fail()
            if _state_bytes_equal(directory_fd, repo_root, encoded):
                print(
                    "Deployment state directory fsync failed after manifest "
                    "visibility; retaining the target deployment.",
                    file=sys.stderr,
                )
                return
            # The recovery may have made the prior state visible before its fsync
            # failed.  Returning failure is now coherent with shell rollback.
            if _state_bytes_equal(directory_fd, repo_root, previous_bytes):
                _fail()
            print(
                "Deployment state recovery is indeterminate; retaining the "
                "target deployment.",
                file=sys.stderr,
            )
            return
        finally:
            _unlink_temporary_state(directory_fd, temporary_name)
    finally:
        _restore_write_signals(previous_mask)


def _write(
    state_dir: Path,
    repo_root: Path,
    operation_id: str,
    operation: str,
    current_commit: str,
    previous_commit: str,
    backup_path: str,
) -> None:
    payload = _payload(
        operation_id,
        operation,
        current_commit,
        previous_commit,
        backup_path,
        repo_root,
    )
    directory_fd = _open_state_dir(state_dir, create=True)
    try:
        _write_state(directory_fd, payload, repo_root)
    finally:
        os.close(directory_fd)


def _read_current_commit(state_dir: Path, repo_root: Path) -> str:
    directory_fd = _open_state_dir(state_dir, create=False)
    try:
        return str(_read_state(directory_fd, repo_root)["current_commit"])
    finally:
        os.close(directory_fd)


def _matches(
    state_dir: Path,
    repo_root: Path,
    current_commit: str,
    operation_id: str,
) -> bool:
    directory_fd = _open_state_dir(state_dir, create=False)
    try:
        if _state_file_stat(directory_fd) is None:
            return False
        payload = _read_state(directory_fd, repo_root)
    finally:
        os.close(directory_fd)
    return (
        payload["current_commit"] == current_commit
        and payload["operation_id"] == operation_id
    )


def main(argv: list[str]) -> None:
    if len(argv) < 2:
        _fail()
    command, *arguments = argv[1:]
    if command == "generate-operation-id" and not arguments:
        print(secrets.token_hex(16))
        return
    if command == "write" and len(arguments) == 7:
        _write(
            Path(arguments[0]),
            Path(arguments[1]),
            arguments[2],
            arguments[3],
            arguments[4],
            arguments[5],
            arguments[6],
        )
        return
    if command == "read-current-commit" and len(arguments) == 2:
        print(_read_current_commit(Path(arguments[0]), Path(arguments[1])))
        return
    if command == "matches" and len(arguments) == 4:
        raise SystemExit(
            0
            if _matches(
                Path(arguments[0]),
                Path(arguments[1]),
                arguments[2],
                arguments[3],
            )
            else 1
        )
    _fail()


if __name__ == "__main__":
    main(sys.argv)
