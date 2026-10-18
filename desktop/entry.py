"""Frozen desktop executable and its owned child roles."""

from __future__ import annotations

import argparse
import asyncio
import html
import json
import multiprocessing
import os
import subprocess
import sys
import threading
from pathlib import Path

ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).parents[1]))
sys.path.insert(0, str(ROOT))
if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(ROOT / "backend"))


def watch_parent(callback):
    def watch():
        os.read(sys.stdin.fileno(), 1)
        callback()

    threading.Thread(target=watch, daemon=True).start()


def run_role(role):
    from desktop.runtime import LocalRuntime, backend_root, data_directory

    if role == "supervisor":
        runtime = LocalRuntime(data_directory())
        watch_parent(runtime.stopping.set)
        try:
            url = runtime.start()
            print(json.dumps({"url": url}), flush=True)
            while not runtime.stopping.wait(0.5):
                if any(p.poll() is not None for _, p in runtime.processes):
                    raise RuntimeError("本机服务已停止，请重新打开应用。")
        finally:
            runtime.close()
    elif role == "migrate":
        from alembic import command
        from alembic.config import Config

        configuration = Config(str(backend_root() / "alembic.ini"))
        configuration.set_main_option(
            "script_location", str(backend_root() / "alembic")
        )
        command.upgrade(configuration, "head")
    elif role == "api":
        import uvicorn
        from app.main import app

        from desktop.gateway import DesktopGateway

        origin = os.environ["PUBLIC_BASE_URL"]
        frontend = ROOT / (
            "frontend" if getattr(sys, "frozen", False) else "frontend-console/dist"
        )
        gateway = DesktopGateway(
            app, frontend, origin, os.environ["NOVELCRAFT_DESKTOP_TOKEN"]
        )
        server = uvicorn.Server(
            uvicorn.Config(
                gateway,
                host="127.0.0.1",
                port=int(origin.rsplit(":", 1)[1]),
                access_log=False,
                proxy_headers=False,
                ws="none",
            )
        )
        watch_parent(lambda: setattr(server, "should_exit", True))
        server.run()
    elif role == "worker":
        import run_worker

        async def work():
            loop = asyncio.get_running_loop()
            shutdown = asyncio.Event()
            watch_parent(lambda: loop.call_soon_threadsafe(shutdown.set))
            await run_worker.main(shutdown_event=shutdown)

        run_worker.setup_logging()
        asyncio.run(work())
    elif role == "embedding-check":
        import math

        from infrastructure.embedding.worker import BgeOnnxWorker

        assets = (
            ROOT if getattr(sys, "frozen", False) else ROOT / "desktop/build/assets"
        )
        worker = BgeOnnxWorker(str(assets / "model"), timeout=60)
        try:
            worker.start()
            vectors = worker.encode(
                ["合成安装检查", "用于检查不同长度输入的另一句话", "合成长文本。" * 600]
            )
            assert len(vectors) == 3
            assert all(len(vector) == 768 for vector in vectors)
            assert all(math.isfinite(x) for vector in vectors for x in vector)
            assert all(abs(sum(x * x for x in v) - 1) < 0.001 for v in vectors)
        finally:
            worker.stop()


def desktop():
    import webview
    from infrastructure.os_security import private_directory

    from desktop.runtime import data_directory, entry_command

    directory = private_directory(data_directory())
    webview.settings["ALLOW_DOWNLOADS"] = True

    window = webview.create_window(
        "NovelCraft",
        html="<html lang='zh-CN'><meta charset='utf-8'>"
        "<title>NovelCraft</title><body style='font:18px system-ui;padding:48px'>"
        "<h1>NovelCraft</h1><p>正在准备你的创作空间…</p>"
        "<p>首次启动可能需要几分钟，请稍候。</p></body></html>",
        width=1280,
        height=860,
        min_size=(800, 600),
        confirm_close=True,
    )
    supervisor = None
    closed = threading.Event()

    def start():
        nonlocal supervisor
        with (directory / "desktop.log").open("ab") as log:
            supervisor = subprocess.Popen(
                entry_command("supervisor"),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=log,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            try:
                result = json.loads(supervisor.stdout.readline())
                if not closed.is_set():
                    window.load_url(result["url"])
                supervisor.wait()
                if not closed.is_set():
                    raise RuntimeError("服务已停止")
            except (ValueError, KeyError, OSError, RuntimeError):
                if not closed.is_set():
                    window.load_html(
                        "<html lang='zh-CN'><meta charset='utf-8'><body "
                        "style='font:18px system-ui;padding:48px'><h1>暂时无法打开</h1>"
                        "<p>请关闭应用后重试。作品数据会保留。</p><p>如果应用已打开，"
                        "请切换到原窗口。诊断日志位于：</p><code>"
                        + html.escape(str(directory))
                        + "</code></body></html>"
                    )

    def closing():
        closed.set()

    window.events.closed += closing
    try:
        webview.start(
            start,
            private_mode=False,
            storage_path=str(directory / "webview"),
            localization={
                "global.quitConfirmation": "退出后本机任务将停止。确定退出 NovelCraft？"
            },
        )
    finally:
        closed.set()
        if supervisor and supervisor.poll() is None:
            supervisor.stdin.close()
            supervisor.wait(timeout=180)


if __name__ == "__main__":
    if os.name == "nt":
        import ctypes

        # Loader failures must reach the supervisor, not wait on an invisible dialog.
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.SetErrorMode(kernel.GetErrorMode() | 0x0001 | 0x8000)
    multiprocessing.freeze_support()
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--role", choices=["supervisor", "api", "worker", "migrate", "embedding-check"]
    )
    arguments = parser.parse_args()
    if arguments.role == "migrate":
        import faulthandler

        print("Starting desktop schema preparation", file=sys.stderr, flush=True)
        faulthandler.dump_traceback_later(30, repeat=True)
        try:
            run_role(arguments.role)
        finally:
            faulthandler.cancel_dump_traceback_later()
    elif arguments.role:
        run_role(arguments.role)
    else:
        desktop()
