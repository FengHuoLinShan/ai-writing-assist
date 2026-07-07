import pytest

from core.container import Injected, get, register, reset


def setup_function():
    reset()


def teardown_function():
    reset()


def test_register_and_get():
    register("test_svc", lambda: "hello")
    assert get("test_svc")() == "hello"


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
        "world.run_entity_extraction",
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
