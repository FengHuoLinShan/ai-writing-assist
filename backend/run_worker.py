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
    asyncio.run(main())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Task queue worker")
    parser.add_argument(
        "--reload", action="store_true",
        help="Auto-reload on file changes (uses watchfiles)",
    )
    args = parser.parse_args()

    if args.reload:
        from watchfiles import run_process

        print("Worker starting with --reload (watching for file changes)...")
        run_process(".", target=_run_sync)
    else:
        setup_logging()
        try:
            asyncio.run(main())
        except KeyboardInterrupt:
            pass
