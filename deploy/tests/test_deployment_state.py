from __future__ import annotations

import importlib.util
import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

DEPLOY_ROOT = Path(__file__).parents[1]
HELPER = DEPLOY_ROOT / "scripts" / "deployment_state.py"


def _load_helper() -> ModuleType:
    spec = importlib.util.spec_from_file_location("deployment_state", HELPER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(
    *arguments: str,
    environment: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(HELPER), *arguments],
        capture_output=True,
        text=True,
        timeout=5,
        env=environment,
    )


def _paths(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    repo_root = tmp_path / "repo"
    backup_dir = repo_root / "deploy" / "backups"
    backup_dir.mkdir(parents=True, mode=0o700)
    backup_path = backup_dir / "backup.dump"
    backup_path.write_bytes(b"backup")
    state_dir = repo_root / "deploy" / ".state"
    state_dir.mkdir(mode=0o700)
    return repo_root, state_dir, backup_dir, backup_path


def _write(
    state_dir: Path,
    repo_root: Path,
    backup_path: Path,
    *,
    operation_id: str = "a" * 32,
    operation: str = "release",
    current_commit: str = "b" * 40,
    previous_commit: str = "c" * 40,
) -> subprocess.CompletedProcess[str]:
    return _run(
        "write",
        str(state_dir),
        str(repo_root),
        operation_id,
        operation,
        current_commit,
        previous_commit,
        str(backup_path),
    )


def _payload(backup_path: Path) -> dict[str, object]:
    return {
        "schema_version": 1,
        "operation_id": "a" * 32,
        "operation": "release",
        "current_commit": "b" * 40,
        "previous_commit": "c" * 40,
        "backup_path": str(backup_path),
    }


def test_generate_operation_id_is_cryptographic_shape() -> None:
    result = _run("generate-operation-id")

    assert result.returncode == 0, result.stderr
    assert re.fullmatch(r"[0-9a-f]{32}\n", result.stdout)


def test_write_read_and_match_are_atomic_private_and_retention_tolerant(
    tmp_path: Path,
) -> None:
    repo_root, state_dir, _backup_dir, backup_path = _paths(tmp_path)
    first = _write(state_dir, repo_root, backup_path)

    assert first.returncode == 0, first.stderr
    state_path = state_dir / "deployment-state.json"
    assert stat.S_IMODE(state_path.stat().st_mode) == 0o600
    assert json.loads(state_path.read_text()) == _payload(backup_path)
    assert not list(state_dir.glob(".deployment-state.json.tmp.*"))

    second = _write(
        state_dir,
        repo_root,
        backup_path,
        operation_id="d" * 32,
        operation="restore",
        current_commit="e" * 40,
    )
    read = _run("read-current-commit", str(state_dir), str(repo_root))
    exact_match = _run(
        "matches", str(state_dir), str(repo_root), "e" * 40, "d" * 32
    )
    different_nonce = _run(
        "matches", str(state_dir), str(repo_root), "e" * 40, "f" * 32
    )

    assert second.returncode == 0, second.stderr
    assert read.returncode == 0, read.stderr
    assert read.stdout == "e" * 40 + "\n"
    assert exact_match.returncode == 0, exact_match.stderr
    assert different_nonce.returncode == 1
    backup_path.unlink()
    retained_read = _run("read-current-commit", str(state_dir), str(repo_root))
    assert retained_read.returncode == 0, retained_read.stderr
    assert not list(state_dir.glob(".deployment-state.json.tmp.*"))


def test_read_rejects_malformed_schema_duplicate_keys_and_unsafe_state(
    tmp_path: Path,
) -> None:
    repo_root, state_dir, _backup_dir, backup_path = _paths(tmp_path)
    state_path = state_dir / "deployment-state.json"
    invalid_contents = (
        "{}",
        json.dumps(_payload(backup_path) | {"extra": "value"}),
        json.dumps(_payload(backup_path) | {"schema_version": True}),
        json.dumps(_payload(backup_path) | {"operation": {"bad": "type"}}),
        json.dumps(_payload(backup_path) | {"backup_path": str(tmp_path / "bad.dump")}),
        '{"schema_version":1,"schema_version":1}',
    )

    for contents in invalid_contents:
        state_path.write_text(contents)
        state_path.chmod(0o600)
        result = _run("read-current-commit", str(state_dir), str(repo_root))
        assert result.returncode == 1
        assert result.stdout == ""
        assert result.stderr == "Deployment state is unsafe.\n"

    state_path.unlink()
    outside = tmp_path / "outside-state"
    outside.write_text(json.dumps(_payload(backup_path)))
    state_path.symlink_to(outside)
    symlinked = _run("read-current-commit", str(state_dir), str(repo_root))
    assert symlinked.returncode == 1
    assert symlinked.stderr == "Deployment state is unsafe.\n"

    state_path.unlink()
    state_dir.chmod(0o755)
    unsafe_directory = _run("read-current-commit", str(state_dir), str(repo_root))
    assert unsafe_directory.returncode == 1
    assert unsafe_directory.stderr == "Deployment state is unsafe.\n"


def test_write_refuses_to_replace_malformed_existing_state_and_cleans_temp(
    tmp_path: Path,
) -> None:
    repo_root, state_dir, _backup_dir, backup_path = _paths(tmp_path)
    state_path = state_dir / "deployment-state.json"
    state_path.write_text("{}")
    state_path.chmod(0o600)

    result = _write(state_dir, repo_root, backup_path)

    assert result.returncode == 1
    assert result.stderr == "Deployment state is unsafe.\n"
    assert state_path.read_text() == "{}"
    assert not list(state_dir.glob(".deployment-state.json.tmp.*"))


def test_malformed_cli_fails_closed_without_a_traceback() -> None:
    result = _run("write")

    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr == "Deployment state is unsafe.\n"


def test_post_replace_directory_fsync_failure_restores_exact_existing_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_helper()
    repo_root, state_dir, _backup_dir, backup_path = _paths(tmp_path)
    first = _write(state_dir, repo_root, backup_path)
    assert first.returncode == 0, first.stderr
    state_path = state_dir / "deployment-state.json"
    previous_bytes = state_path.read_bytes()
    real_fsync = module.os.fsync
    directory_fsyncs = 0

    def fail_directory_fsync(descriptor: int) -> None:
        nonlocal directory_fsyncs
        if stat.S_ISDIR(os.fstat(descriptor).st_mode):
            directory_fsyncs += 1
            if directory_fsyncs == 1:
                raise OSError("directory fsync failure")
        real_fsync(descriptor)

    monkeypatch.setattr(module.os, "fsync", fail_directory_fsync)
    monkeypatch.setattr(module.signal, "signal", lambda *_args: None)

    with pytest.raises(SystemExit) as error:
        module._write(
            state_dir,
            repo_root,
            "d" * 32,
            "restore",
            "e" * 40,
            "c" * 40,
            str(backup_path),
        )

    assert error.value.code == 1
    assert state_path.read_bytes() == previous_bytes
    assert json.loads(state_path.read_text())["current_commit"] == "b" * 40
    assert not list(state_dir.glob(".deployment-state.json.tmp.*"))


def test_post_replace_directory_fsync_failure_removes_first_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_helper()
    repo_root, state_dir, _backup_dir, backup_path = _paths(tmp_path)
    legacy_release = state_dir / "current-release"
    legacy_commit = state_dir / "current-commit"
    legacy_release.write_text("b" * 12 + "\n")
    legacy_commit.write_text("b" * 40 + "\n")
    real_fsync = module.os.fsync
    directory_fsyncs = 0

    def fail_first_directory_fsync(descriptor: int) -> None:
        nonlocal directory_fsyncs
        if stat.S_ISDIR(os.fstat(descriptor).st_mode):
            directory_fsyncs += 1
            if directory_fsyncs == 1:
                raise OSError("directory fsync failure")
        real_fsync(descriptor)

    monkeypatch.setattr(module.os, "fsync", fail_first_directory_fsync)
    monkeypatch.setattr(module.signal, "signal", lambda *_args: None)

    with pytest.raises(SystemExit) as error:
        module._write(
            state_dir,
            repo_root,
            "a" * 32,
            "release",
            "b" * 40,
            "c" * 40,
            str(backup_path),
        )

    assert error.value.code == 1
    assert not (state_dir / "deployment-state.json").exists()
    assert legacy_release.read_text() == "b" * 12 + "\n"
    assert legacy_commit.read_text() == "b" * 40 + "\n"
    assert not list(state_dir.glob(".deployment-state.json.tmp.*"))


def test_failed_manifest_recovery_retains_visible_target_for_shell_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_helper()
    repo_root, state_dir, _backup_dir, backup_path = _paths(tmp_path)
    real_fsync = module.os.fsync
    real_unlink = module.os.unlink
    directory_fsyncs = 0

    def fail_first_directory_fsync(descriptor: int) -> None:
        nonlocal directory_fsyncs
        if stat.S_ISDIR(os.fstat(descriptor).st_mode):
            directory_fsyncs += 1
            if directory_fsyncs == 1:
                raise OSError("directory fsync failure")
        real_fsync(descriptor)

    def fail_manifest_removal(path: str, *arguments: object, **kwargs: object) -> None:
        if path == module._STATE_NAME:
            raise OSError("manifest recovery failure")
        real_unlink(path, *arguments, **kwargs)

    monkeypatch.setattr(module.os, "fsync", fail_first_directory_fsync)
    monkeypatch.setattr(module.os, "unlink", fail_manifest_removal)
    monkeypatch.setattr(module.signal, "signal", lambda *_args: None)

    module._write(
        state_dir,
        repo_root,
        "a" * 32,
        "release",
        "b" * 40,
        "c" * 40,
        str(backup_path),
    )

    state_payload = json.loads((state_dir / "deployment-state.json").read_text())
    assert state_payload["current_commit"] == "b" * 40
    assert not list(state_dir.glob(".deployment-state.json.tmp.*"))


def test_atomic_write_blocks_catchable_signals_until_directory_fsync_completes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_helper()
    repo_root, state_dir, _backup_dir, backup_path = _paths(tmp_path)
    real_pthread_sigmask = module.signal.pthread_sigmask
    calls: list[tuple[int, set[object]]] = []

    def record_sigmask(how: int, signals: set[object]) -> set[object]:
        calls.append((how, set(signals)))
        return real_pthread_sigmask(how, signals)

    monkeypatch.setattr(module.signal, "pthread_sigmask", record_sigmask)
    monkeypatch.setattr(module.signal, "signal", lambda *_args: None)

    module._write(
        state_dir,
        repo_root,
        "a" * 32,
        "release",
        "b" * 40,
        "c" * 40,
        str(backup_path),
    )

    assert calls[0][0] == module.signal.SIG_BLOCK
    assert set(module._BLOCKED_SIGNALS) <= calls[0][1]
    assert calls[-1][0] == module.signal.SIG_SETMASK


def test_targeted_child_term_during_critical_transaction_is_swallowed(
    tmp_path: Path,
) -> None:
    repo_root, state_dir, _backup_dir, backup_path = _paths(tmp_path)
    sitecustomize_dir = tmp_path / "sitecustomize"
    sitecustomize_dir.mkdir()
    (sitecustomize_dir / "sitecustomize.py").write_text(
        "import os\n"
        "import signal\n"
        "real_fsync = os.fsync\n"
        "sent = False\n"
        "def fsync(descriptor):\n"
        "    global sent\n"
        "    result = real_fsync(descriptor)\n"
        "    if not sent:\n"
        "        sent = True\n"
        "        os.kill(os.getpid(), signal.SIGTERM)\n"
        "    return result\n"
        "os.fsync = fsync\n"
    )
    python_path = str(sitecustomize_dir)
    inherited_python_path = os.environ.get("PYTHONPATH")
    if inherited_python_path:
        python_path = f"{python_path}{os.pathsep}{inherited_python_path}"

    result = _run(
        "write",
        str(state_dir),
        str(repo_root),
        "a" * 32,
        "release",
        "b" * 40,
        "c" * 40,
        str(backup_path),
        environment=os.environ | {"PYTHONPATH": python_path},
    )

    assert result.returncode == 0, result.stderr
    state_payload = json.loads((state_dir / "deployment-state.json").read_text())
    assert state_payload["current_commit"] == "b" * 40
