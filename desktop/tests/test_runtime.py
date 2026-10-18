import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from desktop.runtime import LocalRuntime


def test_private_instance_state_and_stable_origin(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "postgresql://unrelated-private-db")
    monkeypatch.setenv("OPENAI_API_KEY", "do-not-inherit")
    root = tmp_path / "desktop"
    runtime = LocalRuntime(root)
    try:
        assert "unrelated-private-db" not in runtime.env["DATABASE_URL"]
        assert "OPENAI_API_KEY" not in runtime.env
        assert "LLM_MODEL_ADMISSION_DIRECTORY" not in runtime.env
        origin = runtime.origin
        token = runtime.env["NOVELCRAFT_DESKTOP_TOKEN"]
        password = runtime.env["PGPASSWORD"]
    finally:
        runtime.close()
    reopened = LocalRuntime(root)
    try:
        assert reopened.origin == origin
        assert reopened.env["NOVELCRAFT_DESKTOP_TOKEN"] != token
        assert reopened.env["PGPASSWORD"] == password
        assert json.loads((root / "secrets.json").read_text())["api_port"]
    finally:
        reopened.close()


def test_failed_pg_control_still_stops_owned_process(monkeypatch, tmp_path):
    runtime = LocalRuntime(tmp_path / "desktop")
    process = runtime.spawn(
        "database", [sys.executable, "-c", "import time; time.sleep(30)"],
    )
    monkeypatch.setattr(runtime, "pg", lambda name: "missing-novelcraft-test-pg-control")
    runtime.close()
    assert process.poll() is not None
    reopened = LocalRuntime(runtime.directory)
    reopened.close()


def test_close_cancels_cold_setup_and_reaps_the_child(tmp_path):
    runtime = LocalRuntime(tmp_path / "desktop")
    timer = threading.Timer(0.1, runtime.stopping.set)
    timer.start()
    started = time.monotonic()
    try:
        with pytest.raises(RuntimeError, match="启动已取消"):
            runtime.run(
                [sys.executable, "-c", "import time; time.sleep(30)"],
                timeout=60,
                cancellable=True,
            )
        assert time.monotonic() - started < 5
    finally:
        timer.cancel()
        runtime.close()


def test_setup_does_not_inherit_the_parent_control_pipe(tmp_path):
    root = Path(__file__).resolve().parents[2]
    script = (
        "import sys; from pathlib import Path; "
        "from desktop.runtime import LocalRuntime; "
        "runtime = LocalRuntime(Path(sys.argv[1])); "
        "runtime.run([sys.executable, '-c', "
        "'import sys; assert not sys.stdin.read()'], timeout=3); "
        "runtime.close()"
    )
    with subprocess.Popen(
        [sys.executable, "-c", script, str(tmp_path / "desktop")],
        stdin=subprocess.PIPE,
        env={
            **os.environ,
            "PYTHONPATH": os.pathsep.join([str(root), str(root / "backend")]),
        },
    ) as process:
        try:
            assert process.wait(timeout=8) == 0
        finally:
            process.stdin.close()
            if process.poll() is None:
                process.kill()
