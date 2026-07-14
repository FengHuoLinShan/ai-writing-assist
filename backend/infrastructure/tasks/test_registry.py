"""TaskRegistry 测试"""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from infrastructure.tasks.registry import TaskRegistry, get_registry


class _GenericTaskMeta(BaseModel):
    key: str


class TestTaskRegistry:
    """测试 TaskRegistry 注册、查找、去重"""

    def teardown_method(self) -> None:
        registry = get_registry()
        for task_type in ("test_type", "dup_type", "unreg_type"):
            registry.unregister(task_type)

    def test_register_and_get(self) -> None:
        registry = get_registry()

        async def handler(db, task):
            return {"ok": True}

        registry.register("test_type", handler)
        found = registry.get_handler("test_type")
        assert found is handler
        assert "test_type" in registry.registered_types

    def test_definition_freezes_recovery_metadata(self) -> None:
        registry = get_registry()

        async def handler(db, task):
            return {"ok": True}

        registry.register(
            "test_type",
            handler,
            recovery_policy="auto_requeue",
            max_attempts=2,
            generic_submit_schema=_GenericTaskMeta,
        )
        definition = registry.get_definition("test_type")
        assert definition is not None
        assert definition.handler is handler
        assert definition.recovery_policy == "auto_requeue"
        assert definition.max_attempts == 2
        assert definition.generic_submit_schema is _GenericTaskMeta

    def test_register_rejects_non_pydantic_generic_submit_schema(self) -> None:
        registry = get_registry()

        async def handler(db, task):
            return {"ok": True}

        with pytest.raises(TypeError, match="Pydantic BaseModel"):
            registry.register(
                "test_type",
                handler,
                generic_submit_schema=dict,  # type: ignore[arg-type]
            )
        assert "test_type" not in registry

    def test_duplicate_raises(self) -> None:
        registry = get_registry()

        async def h1(db, task):
            return {}

        async def h2(db, task):
            return {}

        registry.register("dup_type", h1)

        with pytest.raises(ValueError, match="already registered"):
            registry.register("dup_type", h2)

    def test_get_nonexistent_returns_none(self) -> None:
        registry = get_registry()
        assert registry.get_handler("nonexistent_type") is None

    def test_unregister(self) -> None:
        registry = get_registry()

        async def handler(db, task):
            return {}

        registry.register("unreg_type", handler)
        assert registry.get_handler("unreg_type") is not None
        registry.unregister("unreg_type")
        assert registry.get_handler("unreg_type") is None

    def test_singleton(self) -> None:
        r1 = get_registry()
        r2 = get_registry()
        assert r1 is r2
        assert r1 is TaskRegistry()
