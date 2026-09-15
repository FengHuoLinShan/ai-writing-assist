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
        assert definition.owner_scope == "project"

    def test_register_freezes_explicit_global_owner_scope(self) -> None:
        registry = get_registry()

        async def handler(db, task):
            return {"ok": True}

        registry.register("test_type", handler, owner_scope="global")
        definition = registry.get_definition("test_type")
        assert definition is not None
        assert definition.owner_scope == "global"

    def test_register_rejects_unknown_owner_scope(self) -> None:
        registry = get_registry()

        async def handler(db, task):
            return {"ok": True}

        with pytest.raises(ValueError, match="owner scope"):
            registry.register("test_type", handler, owner_scope="other")  # type: ignore[arg-type]

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

    def test_root_capability_is_optional_and_frozen_per_task_type(self) -> None:
        registry = get_registry()

        async def handler(db, task):
            return {"ok": True}

        registry.register("test_type", handler, root_capability_id="writing.generate")
        assert registry.get_root_capability("test_type") == "writing.generate"
        registry.register("dup_type", handler)
        assert registry.get_root_capability("dup_type") is None
        registry.unregister("dup_type")
        assert "dup_type" not in registry.registered_types

    @pytest.mark.parametrize(
        "capability",
        ["", "has space", "bad/slash", "a" * 161, 7],
        ids=["empty", "space", "slash", "too-long", "not-a-string"],
    )
    def test_register_rejects_non_canonical_root_capability(self, capability) -> None:
        registry = get_registry()

        async def handler(db, task):
            return {"ok": True}

        with pytest.raises(ValueError, match="root_capability_id"):
            registry.register("test_type", handler, root_capability_id=capability)
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


def test_production_root_capabilities_freeze_request_limits() -> None:
    from app.task_runtime import register_task_handlers
    from modules.evidence.contracts import CAPABILITY_REGISTRY

    register_task_handlers()
    registry = get_registry()
    missing = [
        task_type
        for task_type in registry.registered_types
        if registry.get_root_capability(task_type)
        and registry.get_definition(task_type).run_request_limit is None
    ]

    assert missing == []
    unknown = [
        (task_type, root)
        for task_type in registry.registered_types
        for root in [registry.get_root_capability(task_type)]
        if root and root not in CAPABILITY_REGISTRY
    ]
    assert unknown == []
