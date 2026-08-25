"""轻量 DI 容器 — 消除模块间 facade 直连的循环依赖。

服务在 main.py 启动时注册，模块间通过 container.get() 获取依赖，
不再直接 import 其他模块的 facade/service。
"""

from __future__ import annotations

import inspect
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from typing import Any, Literal

ServiceScope = Literal["singleton", "transient"]


@dataclass
class _Registration:
    provider: Any
    scope: ServiceScope
    is_factory: bool = False
    instance: Any = None
    created: bool = False

    @classmethod
    def for_instance(cls, instance: Any) -> _Registration:
        return cls(
            provider=instance,
            scope="singleton",
            instance=instance,
            created=True,
        )

    @classmethod
    def for_factory(
        cls,
        factory: Callable[[], Any],
        *,
        scope: ServiceScope,
    ) -> _Registration:
        return cls(provider=factory, scope=scope, is_factory=True)

    def resolve(self) -> Any:
        if not self.is_factory:
            return self.instance
        if self.scope == "transient":
            return self.provider()
        if not self.created:
            self.instance = self.provider()
            self.created = True
        return self.instance

    def shutdown_instance(self) -> Any | None:
        if self.scope == "transient" or not self.created:
            return None
        return self.instance


_container: dict[str, _Registration] = {}


def register(name: str, instance: Any) -> None:
    if name in _container:
        raise ValueError(f"Service {name!r} already registered")
    _container[name] = _Registration.for_instance(instance)


def register_factory(
    name: str,
    factory: Callable[[], Any],
    *,
    scope: ServiceScope = "singleton",
) -> None:
    if name in _container:
        raise ValueError(f"Service {name!r} already registered")
    if scope not in ("singleton", "transient"):
        raise ValueError("scope must be 'singleton' or 'transient'")
    _container[name] = _Registration.for_factory(factory, scope=scope)


def get(name: str) -> Any:
    if name not in _container:
        available = ", ".join(sorted(_container))
        raise KeyError(f"Service {name!r} not registered. Available: {available}")
    return _container[name].resolve()


def reset() -> None:
    _container.clear()


@contextmanager
def container_scope(overrides: dict[str, Any] | None = None) -> Iterator[None]:
    """Temporarily override registered services with singleton instances."""
    overrides = overrides or {}
    previous = {name: _container.get(name) for name in overrides}
    try:
        for name, service in overrides.items():
            _container[name] = _Registration.for_instance(service)
        yield
    finally:
        for name in overrides:
            old_registration = previous[name]
            if old_registration is None:
                _container.pop(name, None)
            else:
                _container[name] = old_registration


def override(name: str, service: Any) -> AbstractContextManager[None]:
    return container_scope({name: service})


async def shutdown() -> None:
    """Close created singleton services in reverse registration order."""
    errors: list[Exception] = []
    registrations = list(_container.items())
    try:
        for name, registration in reversed(registrations):
            service = registration.shutdown_instance()
            if service is None:
                continue
            try:
                await _close_service(service)
            except Exception as exc:
                exc.add_note(f"while closing service {name!r}")
                errors.append(exc)
    finally:
        _container.clear()

    if errors:
        raise ExceptionGroup("Errors during container shutdown", errors)


async def _close_service(service: Any) -> None:
    close = getattr(service, "aclose", None)
    if not callable(close):
        close = getattr(service, "close", None)
    if not callable(close):
        return
    result = close()
    if inspect.isawaitable(result):
        await result
