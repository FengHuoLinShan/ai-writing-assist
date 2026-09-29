"""Companion-side image job handling: no product tools, always-cleaned workspace."""

from __future__ import annotations

import io
import os
import shutil
import tempfile
import uuid
from pathlib import Path

import pytest
from PIL import Image

from infrastructure.llm.cli_agent import CLIResult
from modules.local_agent import companion


def _png_bytes(size=(20, 12), color=(5, 6, 7)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.mark.asyncio
async def test_image_job_skips_shim_and_socket_and_uploads_output(tmp_path, monkeypatch):
    monkeypatch.setattr(companion, "_HOME", tmp_path)

    captured: dict = {}
    input_bytes = _png_bytes((8, 8))
    output_bytes = _png_bytes((20, 12))

    async def fake_run_cli_agent(spec, *, on_event=None):
        captured["spec"] = spec
        captured["reference_present"] = (spec.workspace / "reference-1.png").exists()
        captured["shim_present"] = (spec.workspace / "novelcraft-tool").exists()
        (spec.workspace / "output.png").write_bytes(output_bytes)
        return CLIResult(answer="", tool_attempts=0, usage=None)

    async def refuse_unix_server(*_args, **_kwargs):
        raise AssertionError("image jobs must not open a tool socket")

    def fake_download(base, path, *, token, max_bytes):
        captured.setdefault("downloads", []).append(path)
        return input_bytes

    def fake_upload(base, path, *, token, data, content_type):
        captured["upload"] = {"path": path, "data": data, "content_type": content_type}
        return {"sha256": "x" * 64, "width": 20, "height": 12}

    requests: list[tuple[str, str, dict | None]] = []

    def fake_request(base, method, path, *, token=None, payload=None):
        requests.append((method, path, payload))
        return {"accepted": True}

    monkeypatch.setattr(companion, "run_cli_agent", fake_run_cli_agent)
    monkeypatch.setattr(companion.asyncio, "start_unix_server", refuse_unix_server)
    monkeypatch.setattr(companion, "_download", fake_download)
    monkeypatch.setattr(companion, "_upload", fake_upload)
    monkeypatch.setattr(companion, "_request", fake_request)

    invocation_id = str(uuid.uuid4())
    job = {
        "id": invocation_id,
        "lease_id": str(uuid.uuid4()),
        "cli": "pi",
        "request": {
            "mode": "image",
            "prompt": "画一只猫",
            "inputs": [
                {
                    "ordinal": 0,
                    "name": "reference-1.png",
                    "media_type": "image/png",
                    "byte_size": len(input_bytes),
                    "sha256": "a" * 64,
                }
            ],
            "width": 20,
            "height": 12,
            "timeout_seconds": 30,
            "max_tool_attempts": 32,
        },
    }

    await companion._job("https://example.test", "device-token", job)

    assert captured["reference_present"] is True
    assert captured["shim_present"] is False
    assert captured["spec"].env == {"PATH": os.environ.get("PATH", "")}
    assert captured["upload"]["content_type"] == "image/png"
    assert captured["upload"]["data"] == output_bytes

    run_root = tmp_path / "runs" / invocation_id
    assert not run_root.exists()

    finish_calls = [item for item in requests if item[1].endswith("/finish")]
    assert len(finish_calls) == 1
    assert finish_calls[0][2]["status"] == "completed"
    assert finish_calls[0][2]["answer"] == ""


@pytest.mark.asyncio
async def test_image_job_without_output_file_finishes_failed(tmp_path, monkeypatch):
    monkeypatch.setattr(companion, "_HOME", tmp_path)

    async def fake_run_cli_agent(spec, *, on_event=None):
        return CLIResult(answer="", tool_attempts=0, usage=None)

    async def refuse_unix_server(*_args, **_kwargs):
        raise AssertionError("image jobs must not open a tool socket")

    requests: list[tuple[str, str, dict | None]] = []

    def fake_request(base, method, path, *, token=None, payload=None):
        requests.append((method, path, payload))
        return {"accepted": True}

    monkeypatch.setattr(companion, "run_cli_agent", fake_run_cli_agent)
    monkeypatch.setattr(companion.asyncio, "start_unix_server", refuse_unix_server)
    monkeypatch.setattr(companion, "_request", fake_request)

    invocation_id = str(uuid.uuid4())
    job = {
        "id": invocation_id,
        "lease_id": str(uuid.uuid4()),
        "cli": "pi",
        "request": {
            "mode": "image",
            "prompt": "画一只猫",
            "inputs": [],
            "width": 20,
            "height": 12,
            "timeout_seconds": 30,
            "max_tool_attempts": 32,
        },
    }

    await companion._job("https://example.test", "device-token", job)

    run_root = tmp_path / "runs" / invocation_id
    assert not run_root.exists()
    finish_calls = [item for item in requests if item[1].endswith("/finish")]
    assert len(finish_calls) == 1
    assert finish_calls[0][2]["status"] == "failed"
    assert finish_calls[0][2]["error"]


@pytest.mark.asyncio
async def test_text_job_still_removes_its_workspace(monkeypatch):
    # AF_UNIX socket paths are limited to roughly 104 bytes on macOS/BSD;
    # pytest's nested tmp_path would overflow that, so use a short /tmp root
    # like the real companion (whose HOME-relative path is always short).
    short_home = Path(tempfile.mkdtemp(prefix="nc-agent-", dir="/tmp"))
    monkeypatch.setattr(companion, "_HOME", short_home)
    try:
        await _run_text_job_case(monkeypatch)
    finally:
        shutil.rmtree(short_home, ignore_errors=True)


async def _run_text_job_case(monkeypatch):
    async def fake_run_cli_agent(spec, *, on_event=None):
        return CLIResult(answer='{"ok": true}', tool_attempts=0, usage=None)

    requests: list[tuple[str, str, dict | None]] = []

    def fake_request(base, method, path, *, token=None, payload=None):
        requests.append((method, path, payload))
        return {"accepted": True}

    monkeypatch.setattr(companion, "run_cli_agent", fake_run_cli_agent)
    monkeypatch.setattr(companion, "_request", fake_request)

    invocation_id = str(uuid.uuid4())
    job = {
        "id": invocation_id,
        "lease_id": str(uuid.uuid4()),
        "cli": "pi",
        "request": {
            "prompt": "synthetic text task",
            "tools": {},
            "timeout_seconds": 30,
            "max_tool_attempts": 4,
        },
    }

    await companion._job("https://example.test", "device-token", job)

    run_root = companion._HOME / "runs" / invocation_id
    assert not run_root.exists()
    finish_calls = [item for item in requests if item[1].endswith("/finish")]
    assert len(finish_calls) == 1
    assert finish_calls[0][2]["status"] == "completed"
    assert finish_calls[0][2]["answer"] == '{"ok": true}'
