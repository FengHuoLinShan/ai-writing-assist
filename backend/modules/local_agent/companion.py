"""macOS companion: outbound-only local CLI execution for a paired project."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import uuid
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from infrastructure.llm.cli_agent import CLIAgentError, CLIEvent, CLISpec, run_cli_agent

_HOME = Path.home() / ".local" / "share" / "novelcraft-agent"
_SHIM = """#!/usr/bin/env python3
from modules.local_agent.companion import tool_main
tool_main()
"""


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        raise CLIAgentError("服务器重定向已拒绝，设备凭据未转发")


_OPENER = build_opener(_NoRedirect)


def _server(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme != "https" and not (
        parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost"}
    ):
        raise ValueError("服务地址必须使用 HTTPS；仅本机开发可用 HTTP")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("服务地址格式错误")
    return value.rstrip("/")


def _request(
    base: str,
    method: str,
    path: str,
    *,
    token: str | None = None,
    payload: dict | None = None,
) -> dict:
    headers = {"Accept": "application/json"}
    body = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(payload, ensure_ascii=False).encode()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(base + path, data=body, headers=headers, method=method)
    try:
        with _OPENER.open(request, timeout=30) as response:
            data = response.read(2 * 1024 * 1024)
    except HTTPError as exc:
        raise CLIAgentError(f"服务器拒绝本机任务：HTTP {exc.code}") from exc
    except URLError as exc:
        raise CLIAgentError("无法连接产品服务器") from exc
    value = json.loads(data)
    if not isinstance(value, dict):
        raise CLIAgentError("服务器返回格式错误")
    return value


def pair(base: str, code: str) -> str:
    base = _server(base)
    response = _request(
        base,
        "POST",
        "/api/local-agent/companion/activate",
        payload={"code": code},
    )
    device_id = str(uuid.UUID(response["device_id"]))
    folder = _HOME / "devices"
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    target = folder / f"{device_id}.json"
    payload = json.dumps({"server": base, "token": response["token"]}).encode()
    descriptor = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    return device_id


def _load(device_id: str) -> tuple[str, str]:
    target = _HOME / "devices" / f"{uuid.UUID(device_id)}.json"
    if target.stat().st_mode & 0o077:
        raise CLIAgentError("本机设备凭据权限过宽")
    data = json.loads(target.read_text(encoding="utf-8"))
    return _server(data["server"]), data["token"]


async def _job(base: str, token: str, job: dict) -> None:
    invocation = str(uuid.UUID(job["id"]))
    lease = str(uuid.UUID(job["lease_id"]))
    request = job["request"]
    root = _HOME / "runs" / invocation
    root.mkdir(parents=True, exist_ok=False, mode=0o700)
    shim = root / "novelcraft-tool"
    shim.write_text(_SHIM, encoding="utf-8")
    shim.chmod(0o700)
    socket_path = root / "tool.sock"
    sequence = 0

    async def relay_tool(
        reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            line = await asyncio.wait_for(reader.readline(), timeout=10)
            call = json.loads(line)
            call_id = str(uuid.uuid4())
            route = f"/api/local-agent/companion/jobs/{invocation}/tools"
            payload = {
                "lease_id": lease,
                "call_id": call_id,
                "name": call["name"],
                "arguments": call["arguments"],
            }
            await asyncio.to_thread(
                _request, base, "POST", route, token=token, payload=payload
            )
            for _ in range(45):
                query = urlencode({"lease_id": lease})
                state = await asyncio.to_thread(
                    _request,
                    base,
                    "GET",
                    f"{route}/{call_id}?{query}",
                    token=token,
                )
                if not state["pending"]:
                    writer.write((json.dumps(state, ensure_ascii=False) + "\n").encode())
                    await writer.drain()
                    return
                await asyncio.sleep(1)
            raise CLIAgentError("产品工具执行超时")
        except Exception as exc:
            writer.write((json.dumps({"error": str(exc)[:500]}) + "\n").encode())
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    server = await asyncio.start_unix_server(relay_tool, path=str(socket_path))
    job_path = f"/api/local-agent/companion/jobs/{invocation}"

    async def on_event(event: CLIEvent) -> None:
        nonlocal sequence
        sequence += 1
        await asyncio.to_thread(
            _request,
            base,
            "POST",
            job_path + "/events",
            token=token,
            payload={
                "lease_id": lease,
                "sequence": sequence,
                "kind": event.kind,
                "text": event.text,
                "tool_name": event.tool_name,
                "usage": event.usage,
            },
        )

    async def heartbeat() -> None:
        while True:
            await asyncio.sleep(5)
            await asyncio.to_thread(
                _request,
                base,
                "POST",
                job_path + "/heartbeat",
                token=token,
                payload={"lease_id": lease},
            )

    result = None
    error = None
    try:
        async with server:
            async with asyncio.TaskGroup() as group:
                running = group.create_task(
                    run_cli_agent(
                        CLISpec(
                            kind=job["cli"],
                            prompt=request["prompt"],
                            workspace=root,
                            timeout_seconds=float(request["timeout_seconds"]),
                            max_tool_attempts=int(request["max_tool_attempts"]),
                            model=os.environ.get(
                                "NOVELCRAFT_CODEX_MODEL"
                                if job["cli"] == "codex"
                                else "NOVELCRAFT_PI_MODEL"
                            )
                            if job["cli"] in {"codex", "pi"}
                            else None,
                            env={
                                "PATH": f"{root}{os.pathsep}{os.environ.get('PATH', '')}",
                                "NOVELCRAFT_TOOL_SOCKET": str(socket_path),
                            },
                        ),
                        on_event=on_event,
                    )
                )
                watcher = group.create_task(heartbeat())
                await running
                watcher.cancel()
            result = running.result()
    except BaseException as exc:
        error = str(exc)[:2000]
    finally:
        socket_path.unlink(missing_ok=True)
        (root / ".novelcraft-task.md").unlink(missing_ok=True)
    await asyncio.to_thread(
        _request,
        base,
        "POST",
        job_path + "/finish",
        token=token,
        payload={
            "lease_id": lease,
            "status": "completed" if result else "failed",
            "answer": result.answer if result else "",
            "error": error or "",
            "tool_attempts": result.tool_attempts if result else 0,
            "usage": result.usage if result else None,
        },
    )


async def run(device_id: str) -> None:
    base, token = _load(device_id)
    while True:
        try:
            response = await asyncio.to_thread(
                _request,
                base,
                "POST",
                "/api/local-agent/companion/claim",
                token=token,
                payload={},
            )
        except CLIAgentError as exc:
            if "HTTP 401" in str(exc) or "HTTP 404" in str(exc):
                raise
            await asyncio.sleep(5)
            continue
        if response.get("job"):
            try:
                await _job(base, token, response["job"])
            except CLIAgentError as exc:
                if "HTTP 401" in str(exc) or "HTTP 404" in str(exc):
                    raise
                print(f"本机任务已中断：{exc}", file=sys.stderr)
                await asyncio.sleep(5)
        else:
            await asyncio.sleep(2)


def tool_main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: novelcraft-tool NAME JSON_ARGUMENTS")
    socket = os.environ.get("NOVELCRAFT_TOOL_SOCKET")
    if not socket:
        raise SystemExit("本次任务没有产品工具通道")
    try:
        arguments = json.loads(sys.stdin.read() if sys.argv[2] == "-" else sys.argv[2])
        if not isinstance(arguments, dict):
            raise ValueError("arguments must be an object")

        async def call() -> dict:
            reader, writer = await asyncio.open_unix_connection(socket)
            writer.write(
                (
                    json.dumps({"name": sys.argv[1], "arguments": arguments}) + "\n"
                ).encode()
            )
            await writer.drain()
            line = await asyncio.wait_for(reader.readline(), timeout=45)
            writer.close()
            await writer.wait_closed()
            return json.loads(line)

        print(json.dumps(asyncio.run(call()), ensure_ascii=False))
    except (OSError, ValueError, TimeoutError) as exc:
        raise SystemExit(str(exc)) from exc


def main() -> None:
    parser = argparse.ArgumentParser(description="NovelCraft local CLI companion")
    commands = parser.add_subparsers(dest="command", required=True)
    pairing = commands.add_parser("pair")
    pairing.add_argument("server")
    pairing.add_argument("code")
    running = commands.add_parser("run")
    running.add_argument("device_id")
    args = parser.parse_args()
    if args.command == "pair":
        print(pair(args.server, args.code))
    else:
        asyncio.run(run(args.device_id))


if __name__ == "__main__":
    main()
