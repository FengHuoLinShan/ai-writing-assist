from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

DEPLOY_ROOT = Path(__file__).parents[1]
HELPER = DEPLOY_ROOT / "scripts" / "first_release_state.py"


def _run(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(HELPER), *arguments],
        capture_output=True,
        text=True,
        timeout=5,
    )


def _state_dir(tmp_path: Path) -> Path:
    state_dir = tmp_path / ".state"
    state_dir.mkdir(mode=0o700, parents=True)
    return state_dir


def test_write_read_and_clear_private_prepared_state(tmp_path: Path) -> None:
    state_dir = _state_dir(tmp_path)
    commit = "a" * 40

    written = _run("write", str(state_dir), commit)
    read = _run("read", str(state_dir))

    assert written.returncode == 0, written.stderr
    assert read.returncode == 0, read.stderr
    assert read.stdout == f"{commit}\n"
    state_path = state_dir / "first-release-prepared.json"
    assert stat.S_IMODE(state_path.stat().st_mode) == 0o600
    assert json.loads(state_path.read_text()) == {
        "schema_version": 1,
        "prepared_commit": commit,
    }
    assert not list(state_dir.glob(".first-release-prepared.json.tmp.*"))

    cleared = _run("clear", str(state_dir))

    assert cleared.returncode == 0, cleared.stderr
    assert not state_path.exists()


def test_write_is_idempotent_but_rejects_a_different_prepared_commit(
    tmp_path: Path,
) -> None:
    state_dir = _state_dir(tmp_path)
    first = _run("write", str(state_dir), "a" * 40)
    same = _run("write", str(state_dir), "a" * 40)
    different = _run("write", str(state_dir), "b" * 40)

    assert first.returncode == 0, first.stderr
    assert same.returncode == 0, same.stderr
    assert different.returncode == 1
    assert different.stderr == "First-release recovery state is unsafe.\n"
    assert _run("read", str(state_dir)).stdout == "a" * 40 + "\n"


@pytest.mark.parametrize(
    "contents",
    [
        "{}",
        '{"schema_version":1,"prepared_commit":"bad"}',
        '{"schema_version":true,"prepared_commit":"' + "a" * 40 + '"}',
        '{"schema_version":1,"schema_version":1}',
        '{"schema_version":1,"prepared_commit":"' + "a" * 40 + '","extra":1}',
    ],
)
def test_read_and_clear_reject_malformed_state(tmp_path: Path, contents: str) -> None:
    state_dir = _state_dir(tmp_path)
    state_path = state_dir / "first-release-prepared.json"
    state_path.write_text(contents)
    state_path.chmod(0o600)

    for command in ("read", "clear"):
        result = _run(command, str(state_dir))
        assert result.returncode == 1
        assert result.stderr == "First-release recovery state is unsafe.\n"
        assert state_path.exists()


def test_rejects_symlink_hardlink_permissions_and_unsafe_directory(
    tmp_path: Path,
) -> None:
    commit = "a" * 40

    symlink_dir = _state_dir(tmp_path / "symlink")
    outside = tmp_path / "outside.json"
    outside.write_text(json.dumps({"schema_version": 1, "prepared_commit": commit}))
    (symlink_dir / "first-release-prepared.json").symlink_to(outside)
    assert _run("read", str(symlink_dir)).returncode == 1

    hardlink_dir = _state_dir(tmp_path / "hardlink")
    assert _run("write", str(hardlink_dir), commit).returncode == 0
    os.link(
        hardlink_dir / "first-release-prepared.json",
        hardlink_dir / "second-link.json",
    )
    assert _run("read", str(hardlink_dir)).returncode == 1

    mode_dir = _state_dir(tmp_path / "mode")
    assert _run("write", str(mode_dir), commit).returncode == 0
    (mode_dir / "first-release-prepared.json").chmod(0o644)
    assert _run("read", str(mode_dir)).returncode == 1

    unsafe_dir = _state_dir(tmp_path / "directory")
    unsafe_dir.chmod(0o755)
    assert _run("write", str(unsafe_dir), commit).returncode == 1


def test_clear_is_idempotent(tmp_path: Path) -> None:
    state_dir = _state_dir(tmp_path)

    result = _run("clear", str(state_dir))

    assert result.returncode == 0, result.stderr
