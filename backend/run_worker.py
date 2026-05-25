"""Worker 入口：启动任务队列 Worker 常驻循环"""
import asyncio
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)

from infrastructure.tasks.worker import TaskWorker


async def main():
    worker = TaskWorker()
    await worker.run_forever()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
