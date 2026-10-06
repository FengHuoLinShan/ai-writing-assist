import pytest

from core.container import (
    container_scope,
    get,
    register,
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
        # AO-4 provider ports consumed by the project identity root.
        "project.workspace.writing_stats",
        "project.workspace.world_stats",
        "project.workspace.story_stats",
        "project.dedup.world",
        "project.dedup.story",
        "account.project_owner_ref",
        # AO-5 第三批（ADR-0031）：account/assistant/world/writing/project/
        # evidence 反方向导入清零对应的 facade DI 键。
        "account.project_context",
        "account.project_ids_for_owner",
        "account.project_purge_for_owner",
        "collaboration.changed_cases",
        "collaboration.submit_changed_case",
        "collaboration.stop_unavailable_runs",
        "collaboration.read_projected_run",
        "world.map_capabilities",
        "world.review_team_stress",
        "imports.get_active_organization",
        "interaction.read_continuity_review",
        "evolution.require_current_world_candidate",
        "evolution.record_writing_source_change",
        "imports.get_review_dispositions",
        "interaction.validate_public_demo_source_context",
        "story.get_scene_contract",
        "world.list_adopted_map_continuity_facts",
    ]
    for service_name in expected_services:
        assert get(service_name) is not None

    alias_relation_port = get("world.run_alias_relation_extraction")
    assert callable(alias_relation_port.prepare_alias_relation_task)
    assert callable(alias_relation_port.execute_alias_relation_task)
    assert callable(alias_relation_port.finalize_alias_relation_task)

    writing_stats = get("project.workspace.writing_stats")
    for method in (
        "get_project_stats",
        "list_project_stats",
        "list_chapter_indices",
        "list_latest_drafts",
        "get_attention_items",
    ):
        assert callable(getattr(writing_stats, method))
    assert callable(
        getattr(get("project.workspace.world_stats"), "get_attention_summary")
    )
    story_stats = get("project.workspace.story_stats")
    for method in ("count_scenes", "get_attention_items", "get_scene_focus"):
        assert callable(getattr(story_stats, method))
    world_dedup = get("project.dedup.world")
    for method in (
        "suggest_entity_fusion",
        "apply_entity_fusion_group",
        "apply_entity_fusion",
    ):
        assert callable(getattr(world_dedup, method))
    story_dedup = get("project.dedup.story")
    for method in (
        "suggest_structure_dedup",
        "apply_structure_dedup_group",
        "apply_structure_dedup",
    ):
        assert callable(getattr(story_dedup, method))
    assert callable(get("account.project_owner_ref"))
    for service_name in (
        "account.project_context",
        "account.project_ids_for_owner",
        "account.project_purge_for_owner",
        "collaboration.changed_cases",
        "collaboration.submit_changed_case",
        "collaboration.stop_unavailable_runs",
        "collaboration.read_projected_run",
        "world.map_capabilities",
        "world.review_team_stress",
        "imports.get_active_organization",
        "interaction.read_continuity_review",
        "evolution.require_current_world_candidate",
        "evolution.record_writing_source_change",
        "imports.get_review_dispositions",
        "interaction.validate_public_demo_source_context",
        "story.get_scene_contract",
        "world.list_adopted_map_continuity_facts",
    ):
        assert callable(get(service_name))


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


def test_reset_clears_all():
    register("x", 1)
    reset()
    with pytest.raises(KeyError):
        get("x")


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


# --- AO-10: ServiceKey 类型化键 ---------------------------------------------


def test_servicekey_typed_get_returns_registered_instance():
    from core.container import ServiceKey

    class Repo:
        pass

    key: ServiceKey[Repo] = ServiceKey("test_typed_svc")
    instance = Repo()
    register(key, instance)

    assert get(key) is instance


def test_string_key_get_keeps_legacy_behavior():
    from core.container import ServiceKey

    register("test_legacy_svc", "value")
    # 字符串键为过渡期兼容路径：与 ServiceKey 命中同一键槽。
    assert get("test_legacy_svc") == "value"
    assert get(ServiceKey("test_legacy_svc")) == "value"


def test_servicekey_name_is_the_storage_contract():
    from core.container import ServiceKey

    key = ServiceKey("test_contract_svc")
    assert str(key) == "test_contract_svc"
    assert key.name == "test_contract_svc"
    register("test_contract_svc", 1)
    with pytest.raises(ValueError, match="already registered"):
        register(key, 2)


def test_servicekey_is_frozen():
    from dataclasses import FrozenInstanceError

    from core.container import ServiceKey

    key = ServiceKey("test_frozen_svc")
    with pytest.raises(FrozenInstanceError):
        key.name = "other"


def test_container_scope_accepts_servicekey_overrides():
    from core.container import ServiceKey

    original = object()
    scoped = object()
    temporary = object()
    key = ServiceKey("test_scope_svc")
    register("test_scope_svc", original)

    with container_scope({key: scoped, ServiceKey("test_scope_temp"): temporary}):
        assert get(key) is scoped
        assert get("test_scope_temp") is temporary

    assert get("test_scope_svc") is original
    with pytest.raises(KeyError):
        get("test_scope_temp")


def test_ensure_registered_raises_for_missing_keys_and_passes_when_registered():
    from core.container import ServiceKey, ensure_registered

    present = ServiceKey("test_ensure_present")
    missing = ServiceKey("test_ensure_missing")
    another_missing = ServiceKey("test_ensure_missing_2")
    register(present, 1)

    with pytest.raises(RuntimeError) as exc_info:
        ensure_registered([present, missing, another_missing])
    message = str(exc_info.value)
    assert "test_ensure_missing" in message
    assert "test_ensure_missing_2" in message
    assert "test_ensure_present" not in message

    register(missing, 2)
    register(another_missing, 3)
    ensure_registered([present, missing, another_missing])


def test_bootstrap_declared_keys_match_registered_services():
    from app.bootstrap import register_container_services
    from core import container
    from core.service_keys import ALL_SERVICE_KEYS

    register_container_services()

    declared = {key.name for key in ALL_SERVICE_KEYS}
    assert len(declared) == len(ALL_SERVICE_KEYS), "登记表键名不得重复"
    for key in ALL_SERVICE_KEYS:
        get(key)  # 缺失即 KeyError
    assert set(container._container) == declared, (
        "容器与登记表漂移：新增键须登记常量，废弃键须同步清理"
    )


def test_bootstrap_validation_accepts_declared_keys_after_reassembly():
    from app.bootstrap import register_container_services
    from core.service_keys import ALL_SERVICE_KEYS, CONDITIONALLY_REGISTERED

    register_container_services(ignore_existing=True)
    # 装配完成点校验通过（缺键会在 register_container_services 内 raise）。
    required = [
        key for key in ALL_SERVICE_KEYS if key.name not in CONDITIONALLY_REGISTERED
    ]
    assert required  # 登记表非空
