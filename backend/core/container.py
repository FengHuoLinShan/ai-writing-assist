"""轻量 DI 容器 — 消除模块间 facade 直连的循环依赖。

服务在 main.py 启动时注册，模块间通过 container.get() 获取依赖，
不再直接 import 其他模块的 facade/service。
"""

from __future__ import annotations

from typing import Any

_container: dict[str, Any] = {}


def register(name: str, instance: Any) -> None:
    if name in _container:
        raise ValueError(f"Service {name!r} already registered")
    _container[name] = instance


def get(name: str) -> Any:
    if name not in _container:
        available = ", ".join(sorted(_container))
        raise KeyError(f"Service {name!r} not registered. Available: {available}")
    return _container[name]


def reset() -> None:
    _container.clear()


class Injected:
    """描述符 — 延迟从容器获取服务。

    用法:
        class RagService:
            list_characters = Injected("world.list_characters")

            async def some_method(self, db, novel_id):
                chars = await self.list_characters(db, novel_id)
    """

    def __init__(self, name: str) -> None:
        self._name = name

    def __set_name__(self, owner: type, name: str) -> None:
        self._attr = name

    def __get__(self, obj: object, objtype: type | None = None) -> Any:
        return get(self._name)
