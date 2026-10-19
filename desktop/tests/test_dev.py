import os
import subprocess
import sys

import pytest

from desktop import dev


@pytest.fixture
def prepared(monkeypatch, tmp_path):
    monkeypatch.setattr(dev, "ROOT", tmp_path)
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.delenv("NOVELCRAFT_DESKTOP_DATA_DIR", raising=False)
    postgres = "postgres.exe" if os.name == "nt" else "postgres"
    for name in ("manifest.json", f"postgres/bin/{postgres}", "model/model.onnx"):
        path = tmp_path / "desktop/build/assets" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    return tmp_path


@pytest.mark.parametrize("override", [None, "/explicit/dev-library"])
def test_dev_builds_frontend_then_executes_source_with_separate_data(
    prepared, monkeypatch, override
):
    if override:
        monkeypatch.setenv("NOVELCRAFT_DESKTOP_DATA_DIR", override)
    calls = []
    monkeypatch.setattr(
        subprocess, "run", lambda command, **kwargs: calls.append((command, kwargs))
    )
    monkeypatch.setattr(os, "execv", lambda *args: calls.append(args))
    dev.main()
    assert calls == [
        (
            ["npm.cmd" if os.name == "nt" else "npm", "run", "build"],
            {"cwd": prepared / "frontend-console", "check": True},
        ),
        (sys.executable, [sys.executable, str(prepared / "desktop/entry.py")]),
    ]
    assert os.environ["NOVELCRAFT_DESKTOP_DATA_DIR"] == (
        override or str(prepared / "desktop/build/dev-data")
    )
    assert os.environ["PYTHONUTF8"] == "1"


def test_dev_missing_resources_stops_before_build_or_launch(prepared, monkeypatch):
    (prepared / "desktop/build/assets/model/model.onnx").unlink()
    monkeypatch.setattr(
        subprocess, "run", lambda *_args, **_kwargs: pytest.fail("must not build")
    )
    with pytest.raises(SystemExit, match="desktop-prepare"):
        dev.main()


def test_dev_frontend_build_failure_never_opens_stale_ui(prepared, monkeypatch):
    def fail(command, **kwargs):
        raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(subprocess, "run", fail)
    monkeypatch.setattr(os, "execv", lambda *_args: pytest.fail("must not launch"))
    with pytest.raises(subprocess.CalledProcessError):
        dev.main()


def test_dev_rejects_unsupported_platform(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    with pytest.raises(SystemExit, match="macOS or Windows"):
        dev.main()
