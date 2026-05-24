"""
任务注册中心

提供 TaskRegistry 单例，用于注册和查找任务处理器。
业务模块通过 @task_handler 装饰器注册任务处理函数。
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)


class TaskRegistry:
    """任务处理器注册中心（单例）

    业务模块通过注册处理器来声明自己能处理哪些任务类型。
    """

    _instance: TaskRegistry | None = None
    _handlers: dict[str, Callable[..., Any]]

    def __new__(cls) -> TaskRegistry:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._handlers = {}
        return cls._instance

    def register(self, task_type: str, handler: Callable[..., Any]) -> None:
        """注册一个任务类型的处理器

        Args:
            task_type: 任务类型标识
            handler: 处理异步函数（接受 (db, task) 参数）

        Raises:
            ValueError: 该任务类型已注册
        """
        if task_type in self._handlers:
            raise ValueError(f"Handler already registered for task type: {task_type}")
        self._handlers[task_type] = handler
        logger.info("Task handler registered: %s -> %s", task_type, handler.__name__)

    def get_handler(self, task_type: str) -> Callable[..., Any] | None:
        """获取指定任务类型的处理器

        Args:
            task_type: 任务类型标识

        Returns:
            处理器函数，如果未注册则返回 None
        """
        return self._handlers.get(task_type)

    def unregister(self, task_type: str) -> None:
        """注销一个任务类型的处理器（主要用于测试）"""
        self._handlers.pop(task_type, None)
        logger.info("Task handler unregistered: %s", task_type)

    @property
    def registered_types(self) -> list[str]:
        """返回所有已注册的任务类型"""
        return list(self._handlers.keys())

    def __contains__(self, task_type: str) -> bool:
        return task_type in self._handlers


# 全局单例
_registry = TaskRegistry()


def get_registry() -> TaskRegistry:
    """获取全局 TaskRegistry 单例"""
    return _registry


def task_handler(task_type: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """装饰器：将函数注册为指定任务类型的处理器

    用法:
        @task_handler("embedding_build")
        async def handle_embedding_build(db, task):
            ...
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        _registry.register(task_type, func)
        return func

    return decorator
