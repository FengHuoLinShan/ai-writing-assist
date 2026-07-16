import pytest

from core.container import (
    Injected,
    container_scope,
    get,
    override,
    register,
    register_factory,
    reset,
    shutdown,
)


def setup_function():
    reset()


def teardown_function():
    reset()


def test_register_and_get():
    register("test_svc", lambda: "hello")
    assert get("test_svc")() == "hello"


def test_register_callable_keeps_callable_as_instance():
    calls = 0

    def service():
        nonlocal calls
        calls += 1
        return "hello"

    register("test_svc", service)

    assert get("test_svc") is service
    assert calls == 0


def test_get_missing_raises_keyerror():
    reset()
    with pytest.raises(KeyError, match="not registered"):
        get("nonexistent")


def test_duplicate_register_raises_valueerror():
    register("dup", "a")
    with pytest.raises(ValueError, match="already registered"):
        register("dup", "b")


def test_bootstrap_registers_app_and_worker_services():
    from app.bootstrap import register_container_services

    register_container_services()

    expected_services = [
        "world.list_characters",
        "world.list_entity_terms",
        "world.list_entities",
        "world.run_scene_entity_extraction",
        "world.run_alias_relation_extraction",
        "world.create_character",
        "world.get_character_id_by_world_entity",
        "rag.index_chapter",
        "rag.get_ordered_chapter_chunks",
        "writing.list_chapter_indices",
        "writing.get_latest_draft_for_chapter",
        "writing.list_latest_drafts_for_chapters",
        "outline.generate_structure",
        "outline.arc_service",
        "outline.thread_service",
        "outline.scene_service",
        "outline.foreshadowing_service",
        "outline.reveal_service",
        "context.compile",
        "memory.service",
        "memory.capture_snapshot",
    ]
    for service_name in expected_services:
        assert get(service_name) is not None

    alias_relation_port = get("world.run_alias_relation_extraction")
    assert callable(alias_relation_port.prepare_alias_relation_task)
    assert callable(alias_relation_port.execute_alias_relation_task)
    assert callable(alias_relation_port.finalize_alias_relation_task)


def test_bootstrap_duplicate_register_raises_by_default():
    from app.bootstrap import register_container_services

    register_container_services()

    with pytest.raises(ValueError, match="already registered"):
        register_container_services()


def test_bootstrap_ignore_existing_keeps_registered_object():
    from app.bootstrap import register_container_services

    sentinel = object()
    register("world.list_characters", sentinel)

    register_container_services(ignore_existing=True)

    assert get("world.list_characters") is sentinel
    assert callable(get("memory.capture_snapshot"))


def test_reset_clears_all():
    register("x", 1)
    reset()
    with pytest.raises(KeyError):
        get("x")


def test_singleton_factory_is_lazy_and_cached():
    created = 0

    def factory():
        nonlocal created
        created += 1
        return object()

    register_factory("svc", factory)

    assert created == 0
    first = get("svc")
    second = get("svc")

    assert first is second
    assert created == 1


def test_transient_factory_creates_each_time():
    created = 0

    def factory():
        nonlocal created
        created += 1
        return object()

    register_factory("svc", factory, scope="transient")

    first = get("svc")
    second = get("svc")

    assert first is not second
    assert created == 2


def test_container_scope_restores_existing_and_removes_new_service():
    original = object()
    scoped = object()
    temporary = object()
    register("svc", original)

    with container_scope({"svc": scoped, "temp": temporary}):
        assert get("svc") is scoped
        assert get("temp") is temporary

    assert get("svc") is original
    with pytest.raises(KeyError):
        get("temp")


def test_override_restores_existing_service():
    original = object()
    scoped = object()
    register("svc", original)

    with override("svc", scoped):
        assert get("svc") is scoped

    assert get("svc") is original


@pytest.mark.asyncio
async def test_shutdown_closes_created_singletons_in_reverse_order_and_clears():
    events: list[str] = []

    class AsyncClose:
        async def aclose(self):
            events.append("async")

    class SyncClose:
        def close(self):
            events.append("sync")

    class AwaitableClose:
        def close(self):
            async def _close():
                events.append("awaitable")

            return _close()

    register("one", AsyncClose())
    register("two", SyncClose())
    register("three", AwaitableClose())

    await shutdown()

    assert events == ["awaitable", "sync", "async"]
    with pytest.raises(KeyError):
        get("one")


@pytest.mark.asyncio
async def test_shutdown_prefers_aclose_over_close():
    events: list[str] = []

    class Service:
        async def aclose(self):
            events.append("aclose")

        def close(self):
            events.append("close")

    register("svc", Service())

    await shutdown()

    assert events == ["aclose"]


@pytest.mark.asyncio
async def test_shutdown_does_not_create_unused_singleton_or_track_transient():
    created_singleton = 0
    transient_closed = 0

    class TransientService:
        def close(self):
            nonlocal transient_closed
            transient_closed += 1

    def singleton_factory():
        nonlocal created_singleton
        created_singleton += 1
        return object()

    register_factory("lazy", singleton_factory)
    register_factory("transient", TransientService, scope="transient")

    assert get("transient") is not get("transient")
    await shutdown()

    assert created_singleton == 0
    assert transient_closed == 0


@pytest.mark.asyncio
async def test_shutdown_attempts_all_services_and_raises_aggregate_error():
    events: list[str] = []

    class Broken:
        def close(self):
            events.append("broken")
            raise RuntimeError("boom")

    class StillCloses:
        def close(self):
            events.append("still-closes")

    class AlsoBroken:
        async def aclose(self):
            events.append("also-broken")
            raise ValueError("bad")

    register("first", Broken())
    register("second", StillCloses())
    register("third", AlsoBroken())

    with pytest.raises(ExceptionGroup) as exc_info:
        await shutdown()

    assert events == ["also-broken", "still-closes", "broken"]
    assert len(exc_info.value.exceptions) == 2
    with pytest.raises(KeyError):
        get("first")


class TestInjected:
    def setup_method(self):
        reset()

    def test_injected_descriptor_resolves(self):
        register("world.list_characters", lambda: ["char1"])

        class MyService:
            list_chars = Injected("world.list_characters")

        svc = MyService()
        assert svc.list_chars() == ["char1"]

    def test_injected_descriptor_missing_raises(self):
        class MyService:
            missing = Injected("not.registered")

        svc = MyService()
        with pytest.raises(KeyError):
            svc.missing
