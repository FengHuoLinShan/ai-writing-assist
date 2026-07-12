from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from modules.imports.entity_extraction.scene_entity_config import (
    current_phase2_novel_id,
    current_phase2_project_settings,
    current_phase2_request_model,
    phase2_project_settings_context,
)
from modules.imports.entity_extraction.scene_entity_extraction import (
    SceneEntityExtractionService,
)
from modules.imports.entity_extraction.scene_entity_llm_adapters import (
    call_alias_relation_extraction,
    call_llm_extraction,
)


class _FakeClient:
    model_name = "project-model"
    profile_summary = {"provider_id": "fixture"}

    def __init__(self) -> None:
        self.requests = []
        self.close = AsyncMock()

    async def generate_structured(self, request, schema, **_kwargs):
        self.requests.append(request)
        return schema()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "call",
    [
        lambda: call_llm_extraction("text", "entities", "memory"),
        lambda: call_alias_relation_extraction("text", "entities"),
    ],
)
async def test_phase2_llm_adapters_consume_project_snapshot_and_close(
    monkeypatch: pytest.MonkeyPatch,
    call,
) -> None:
    fake = _FakeClient()
    captured = []

    def create_from_snapshot(settings, **overrides):
        captured.append((settings, overrides))
        return fake

    monkeypatch.setattr(
        "modules.project.facade.create_project_snapshot_llm_client",
        create_from_snapshot,
    )
    project_settings = {
        "llm": {
            "api_key": "sk-test-only",
            "base_url": "https://project.test/v1",
            "model": "project-model",
        }
    }
    with phase2_project_settings_context(
        project_settings,
        novel_id="phase2-novel-id",
    ):
        await call()

    assert captured[0][0] is project_settings
    assert captured[0][1]["timeout_override"] > 0
    assert captured[0][1]["novel_id"] == "phase2-novel-id"
    assert fake.requests[0].model == "project-model"
    fake.close.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_phase2_llm_adapter_fails_closed_without_project_snapshot() -> None:
    with pytest.raises(RuntimeError, match="project LLM settings context"):
        await call_llm_extraction("text", "entities", "memory")


@pytest.mark.asyncio
async def test_manual_alias_relation_entry_establishes_and_resets_project_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    novel_id = "00000000-0000-0000-0000-000000000001"
    project_settings = {
        "llm": {
            "api_key": "sk-test-only",
            "base_url": "https://project.test/v1",
            "model": "project-model",
        }
    }
    service = SceneEntityExtractionService()
    monkeypatch.setattr(service, "_get_scenes", AsyncMock(return_value=[]))

    async def run_phase(*_args, **_kwargs):
        assert current_phase2_project_settings() is project_settings
        assert current_phase2_novel_id() == novel_id
        assert current_phase2_request_model() == "project-model"
        return {"alias_relation_failed_scenes": []}

    monkeypatch.setattr(service, "_run_alias_relation_phase", run_phase)
    monkeypatch.setattr(
        service,
        "_phase2_flush_with_timeout",
        AsyncMock(
            return_value={
                "degraded": False,
                "error_kind": None,
                "error_message": None,
            }
        ),
    )

    result = await service.extract_alias_relations(
        AsyncMock(),
        novel_id,
        project_settings=project_settings,
    )

    assert result["degraded"] is False
    assert current_phase2_project_settings() is None
    assert current_phase2_novel_id() is None
    assert current_phase2_request_model() is None


@pytest.mark.asyncio
async def test_manual_alias_relation_entry_fails_closed_without_project_context() -> None:
    with pytest.raises(RuntimeError, match="project LLM settings context"):
        await SceneEntityExtractionService().extract_alias_relations(
            AsyncMock(),
            "00000000-0000-0000-0000-000000000001",
        )


@pytest.mark.asyncio
async def test_phase2_deepseek_normal_mode_uses_high_reasoning_for_all_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeClient()
    fake.model_name = "deepseek-v4-flash"
    fake.profile_summary = {"provider_id": "deepseek"}

    monkeypatch.setattr(
        "modules.project.facade.create_project_snapshot_llm_client",
        lambda *_args, **_kwargs: fake,
    )
    with phase2_project_settings_context(
        {"llm": {"model": "deepseek-v4-flash"}},
        novel_id="phase2-novel-id",
    ):
        await call_llm_extraction("text", "entities", "memory")
        await call_alias_relation_extraction("text", "entities")

    main_request, alias_request = fake.requests
    assert main_request.extra["thinking"] == {"type": "enabled"}
    assert main_request.extra["reasoning_effort"] == "high"
    assert alias_request.max_tokens == 32_768
    assert alias_request.extra == {
        "thinking": {"type": "enabled"},
        "reasoning_effort": "high",
    }


@pytest.mark.asyncio
async def test_phase2_high_quality_keeps_selected_model_and_uses_max_reasoning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeClient()
    fake.model_name = "deepseek-v4-flash"
    fake.profile_summary = {"provider_id": "deepseek"}
    monkeypatch.setattr(
        "modules.project.facade.create_project_snapshot_llm_client",
        lambda *_args, **_kwargs: fake,
    )

    with phase2_project_settings_context(
        {"llm": {"model": "deepseek-v4-flash"}},
        novel_id="phase2-novel-id",
        request_model="deepseek-v4-flash",
        high_quality=True,
    ):
        await call_llm_extraction("text", "entities", "memory")
        await call_alias_relation_extraction("text", "entities")

    assert [request.model for request in fake.requests] == [
        "deepseek-v4-flash",
        "deepseek-v4-flash",
    ]
    assert all(
        request.extra["reasoning_effort"] == "max" for request in fake.requests
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("fails", [False, True])
async def test_main_workflow_structured_call_closes_client(
    monkeypatch: pytest.MonkeyPatch,
    fails: bool,
) -> None:
    from pydantic import BaseModel

    from modules.imports import workflow_llm_adapters

    class Output(BaseModel):
        ok: bool = True

    client = _FakeClient()

    async def run(*_args, **_kwargs):
        if fails:
            raise RuntimeError("fixture failure")
        return Output()

    monkeypatch.setattr(workflow_llm_adapters, "run_managed_structured", run)
    call = workflow_llm_adapters._run_deep_import_structured_call(
        client,
        object(),
        Output,
        step_name="fixture",
        transport_retries=False,
        fix_prompt="fixture",
        project_settings={"llm": {"timeout": 10}},
    )
    if fails:
        with pytest.raises(RuntimeError, match="fixture failure"):
            await call
    else:
        await call

    client.close.assert_awaited_once_with()
