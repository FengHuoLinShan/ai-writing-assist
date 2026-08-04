from __future__ import annotations

import importlib.util
import os
import stat
from pathlib import Path

SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "ensure_private_directory.py"


def _load_helper():
    spec = importlib.util.spec_from_file_location("ensure_private_directory", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_owner_owned_permissive_directory_is_normalized(tmp_path: Path) -> None:
    helper = _load_helper()
    directory = tmp_path / "backups"
    directory.mkdir(mode=0o755)
    directory.chmod(0o755)

    assert helper.main([str(directory)]) == 0
    assert stat.S_IMODE(directory.stat().st_mode) == 0o700


def test_absent_directory_is_created_private_and_owner_owned(tmp_path: Path) -> None:
    helper = _load_helper()
    directory = tmp_path / "backups"

    assert helper.main([str(directory)]) == 0
    metadata = directory.stat()
    assert directory.is_dir()
    assert not directory.is_symlink()
    assert metadata.st_uid == os.getuid()
    assert stat.S_IMODE(metadata.st_mode) == 0o700


def test_rejects_directory_with_another_owner(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    helper = _load_helper()
    directory = tmp_path / "backups"
    directory.mkdir()
    current_uid = os.getuid()
    monkeypatch.setattr(helper.os, "getuid", lambda: current_uid + 1)

    assert helper.main([str(directory)]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "Private directory is unsafe.\n"


def test_rejects_non_directory(tmp_path: Path, capsys) -> None:
    helper = _load_helper()
    directory = tmp_path / "backups"
    directory.write_text("not a directory")

    assert helper.main([str(directory)]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "Private directory is unsafe.\n"


def test_rejects_path_swap_after_open(tmp_path: Path, monkeypatch, capsys) -> None:
    helper = _load_helper()
    directory = tmp_path / "backups"
    replacement = tmp_path / "replacement"
    directory.mkdir()
    replacement.mkdir()
    directory.chmod(0o700)
    replacement.chmod(0o700)
    assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    assert stat.S_IMODE(replacement.stat().st_mode) == 0o700
    real_lstat = helper.os.lstat
    calls = 0

    def swapped_lstat(path: Path):
        nonlocal calls
        calls += 1
        return real_lstat(path if calls == 1 else replacement)

    monkeypatch.setattr(helper.os, "lstat", swapped_lstat)

    assert helper.main([str(directory)]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "Private directory is unsafe.\n"
