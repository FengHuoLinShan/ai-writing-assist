"""Imports 对外契约

定义其他模块可以安全依赖的 Imports 接口和数据类。
"""

from __future__ import annotations


class TaskNotFoundError(Exception):
    """任务不存在"""

    def __init__(self, task_id: str) -> None:
        self.task_id = task_id
        super().__init__(f"Task not found: {task_id}")
