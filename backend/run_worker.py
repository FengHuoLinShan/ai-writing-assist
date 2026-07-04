"""Worker 入口：启动任务队列 Worker 常驻循环

用法：
    python run_worker.py            # 常驻模式
    python run_worker.py --reload   # 开发模式，文件变化时自动重启
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent
RELOAD_DIRS = (
    "app",
    "core",
    "shared",
    "infrastructure",
    "modules",
    "prompts",
)


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stdout,
    )


async def main() -> None:
    from infrastructure.tasks.worker import TaskWorker

    worker = TaskWorker()
    await worker.run_forever()


def _run_sync() -> None:
    """同步包装器（给 watchfiles.run_process 使用）"""
    setup_logging()
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass


def _existing_reload_dirs() -> list[str]:
    return [
        str(BACKEND_ROOT / name)
        for name in RELOAD_DIRS
        if (BACKEND_ROOT / name).exists()
    ]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Task queue worker")
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Auto-reload on file changes (uses watchfiles)",
    )
    args = parser.parse_args()

    if args.reload:
        from watchfiles import run_process

        reload_dirs = _existing_reload_dirs() or [str(BACKEND_ROOT)]
        print(
            "Worker starting with --reload "
            f"(watching {', '.join(Path(path).name for path in reload_dirs)})..."
        )
        run_process(*reload_dirs, target=_run_sync)
    else:
        setup_logging()
        try:
            asyncio.run(main())
        except KeyboardInterrupt:
            pass
