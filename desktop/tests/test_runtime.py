import json
import sys

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
