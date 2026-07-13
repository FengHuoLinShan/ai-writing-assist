"""Tests for the project-owned business LLM runtime seam."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.project import llm_runtime
from modules.project.contracts import ProjectLLMConfigurationError
from modules.project.facade import (
    build_project_llm_execution_snapshot,
    create_project_snapshot_llm_client,
    open_project_llm_client,
    restore_project_llm_execution_settings,
)
from modules.project.models import Project
from modules.settings.services import SettingsService
from shared.deep_import_settings import (
    DEEP_IMPORT_FROZEN_SETTINGS_KEY,
    deep_import_int_setting,
)


async def _set_llm_profile(
    db: AsyncSession,
    project_id: str,
    profile: dict,
) -> None:
    project = (
        await db.execute(select(Project).where(Project.id == uuid.UUID(project_id)))
    ).scalar_one()
    project.settings = {"llm": profile}
    await db.flush()


@pytest.mark.asyncio
async def test_open_project_llm_client_uses_sanitized_effective_profile(
    db_session: AsyncSession,
    test_project_id: str,
) -> None:
    await _set_llm_profile(
        db_session,
        test_project_id,
        {
            "provider_id": "openai-compatible",
            "label": "Test Gateway",
            "api_key": "sk-runtime-secret",
            "base_url": "https://gateway.example.test/v1?token=hidden",
            "model": "project-model",
            "timeout": 41,
            "max_tokens": 8123,
        },
    )

    async with open_project_llm_client(db_session, test_project_id) as client:
        summary = client.profile_summary
        assert client.model_name == "project-model"
        assert summary["provider_id"] == "openai-compatible"
        assert summary["base_url_host"] == "gateway.example.test"
        assert summary["api_key_configured"] is True
        assert summary["sources"]["model"] == "project"
        assert summary["sources"]["temperature"] == "system"
        assert client.runtime_scope == {
            "novel_id": test_project_id,
            "profile_source": "project",
        }
        assert "sk-runtime-secret" not in str(summary)
        assert "token=hidden" not in str(summary)


@pytest.mark.asyncio
async def test_open_project_llm_client_inherits_global_defaults_before_system(
    db_session: AsyncSession,
    test_project_id: str,
) -> None:
    await SettingsService().upsert_global_llm_defaults(
        db_session,
        {
            "provider_id": "openai-compatible",
            "label": "Global Gateway",
            "base_url": "https://global.example.test/v1",
            "model": "global-model",
            "timeout": 77,
            "max_tokens": 6789,
        },
    )
    await _set_llm_profile(
        db_session,
        test_project_id,
        {"api_key": "sk-project-only-secret"},
    )

    async with open_project_llm_client(db_session, test_project_id) as client:
        summary = client.profile_summary
        assert client.model_name == "global-model"
        assert summary["base_url_host"] == "global.example.test"
        assert summary["timeout"] == 77
        assert summary["max_tokens"] == 6789
        assert summary["sources"]["provider_id"] == "global"
        assert summary["sources"]["base_url"] == "global"
        assert summary["sources"]["model"] == "global"
        assert summary["sources"]["api_key"] == "project"

    snapshot = await build_project_llm_execution_snapshot(
        db_session,
        test_project_id,
    )
    assert snapshot["profile"]["max_tokens"] == 6789
    assert snapshot["deep_import"]["phase1c"]["decision_max_tokens"] == 6789
    assert snapshot["deep_import"]["phase1c"]["timeout_seconds"] == 360


@pytest.mark.asyncio
async def test_open_project_llm_client_closes_on_workflow_failure(
    db_session: AsyncSession,
    test_project_id: str,
) -> None:
    await _set_llm_profile(
        db_session,
        test_project_id,
        {
            "api_key": "sk-close-test",
            "base_url": "https://gateway.example.test/v1",
            "model": "project-model",
        },
    )
    close = AsyncMock()

    with pytest.raises(RuntimeError, match="workflow failed"):
        async with open_project_llm_client(db_session, test_project_id) as client:
            client.close = close
            raise RuntimeError("workflow failed")

    close.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_open_project_llm_client_closes_on_cancellation(
    db_session: AsyncSession,
    test_project_id: str,
) -> None:
    await _set_llm_profile(
        db_session,
        test_project_id,
        {
            "api_key": "sk-cancel-test",
            "base_url": "https://gateway.example.test/v1",
            "model": "project-model",
        },
    )
    entered = asyncio.Event()
    close = AsyncMock()

    async def workflow() -> None:
        async with open_project_llm_client(db_session, test_project_id) as client:
            client.close = close
            entered.set()
            await asyncio.Future()

    task = asyncio.create_task(workflow())
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    close.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_open_project_llm_client_fails_closed_without_project_key(
    db_session: AsyncSession,
    test_project_id: str,
) -> None:
    with pytest.raises(
        ProjectLLMConfigurationError,
        match="API key is not configured",
    ):
        async with open_project_llm_client(db_session, test_project_id):
            pass


@pytest.mark.asyncio
async def test_open_project_llm_client_rejects_soft_deleted_project(
    db_session: AsyncSession,
    test_project_id: str,
) -> None:
    project = (
        await db_session.execute(
            select(Project).where(Project.id == uuid.UUID(test_project_id))
        )
    ).scalar_one()
    project.deleted_at = datetime.now(UTC)
    await db_session.flush()

    with pytest.raises(Exception, match="not found"):
        async with open_project_llm_client(db_session, test_project_id):
            pass


@pytest.mark.asyncio
async def test_open_project_llm_client_rejects_missing_project(
    db_session: AsyncSession,
) -> None:
    with pytest.raises(Exception, match="not found"):
        async with open_project_llm_client(db_session, str(uuid.uuid4())):
            pass


@pytest.mark.asyncio
async def test_open_project_llm_client_rejects_unbounded_timeout_override(
    db_session: AsyncSession,
    test_project_id: str,
) -> None:
    with pytest.raises(ProjectLLMConfigurationError, match="timeout_override"):
        async with open_project_llm_client(
            db_session,
            test_project_id,
            timeout_override=1801,
        ):
            pass


@pytest.mark.asyncio
async def test_project_snapshot_client_uses_same_fail_closed_runtime_rules() -> None:
    client = create_project_snapshot_llm_client(
        {
            "llm": {
                "api_key": "sk-snapshot-secret",
                "base_url": "https://snapshot.example.test/v1?token=hidden",
                "model": "snapshot-model",
            }
        },
        timeout_override=99,
        novel_id="snapshot-novel-id",
    )
    try:
        assert client.model_name == "snapshot-model"
        assert client.profile_summary["base_url_host"] == "snapshot.example.test"
        assert client.profile_summary["timeout"] == 99
        assert client.profile_summary["sources"]["timeout"] == "timeout_override"
        assert "sk-snapshot-secret" not in str(client.profile_summary)
        assert "token=hidden" not in str(client.profile_summary)
        assert client.runtime_scope == {
            "novel_id": "snapshot-novel-id",
            "profile_source": "project_snapshot",
        }
    finally:
        await client.close()

    with pytest.raises(ProjectLLMConfigurationError, match="API key"):
        create_project_snapshot_llm_client({"llm": {"model": "missing-key"}})


@pytest.mark.asyncio
async def test_execution_snapshot_is_secret_free_and_restores_frozen_profile(
    db_session: AsyncSession,
    test_project_id: str,
) -> None:
    await _set_llm_profile(
        db_session,
        test_project_id,
        {
            "provider_id": "openai-compatible",
            "api_key": "sk-execution-secret",
            "base_url": "https://snapshot.example.test/v1?token=hidden",
            "model": "snapshot-model",
            "timeout": 77,
            "extra": {"reasoning_effort": "medium"},
        },
    )

    snapshot = await build_project_llm_execution_snapshot(
        db_session,
        test_project_id,
    )

    serialized = str(snapshot)
    assert "sk-execution-secret" not in serialized
    assert "token=hidden" not in serialized
    assert "reasoning_effort': 'medium" not in serialized
    assert snapshot["profile"]["base_url_host"] == "snapshot.example.test"
    assert snapshot["sources"]["model"] == "project"

    restored = await restore_project_llm_execution_settings(
        db_session,
        test_project_id,
        snapshot,
    )
    client = create_project_snapshot_llm_client(
        restored,
        novel_id=test_project_id,
    )
    try:
        assert client.model_name == "snapshot-model"
        assert client.profile_summary["sources"]["model"] == "project"
        assert client.profile_summary["base_url_host"] == "snapshot.example.test"
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_execution_snapshot_freezes_model_and_rejects_endpoint_drift(
    db_session: AsyncSession,
    test_project_id: str,
) -> None:
    await _set_llm_profile(
        db_session,
        test_project_id,
        {
            "api_key": "sk-first",
            "base_url": "https://first.example.test/v1",
            "model": "first-model",
        },
    )
    snapshot = await build_project_llm_execution_snapshot(
        db_session,
        test_project_id,
    )

    await _set_llm_profile(
        db_session,
        test_project_id,
        {
            "api_key": "sk-rotated",
            "base_url": "https://first.example.test/v1",
            "model": "new-model-that-must-not-leak-into-the-task",
        },
    )
    restored = await restore_project_llm_execution_settings(
        db_session,
        test_project_id,
        snapshot,
    )
    assert restored["llm"]["model"] == "first-model"

    await _set_llm_profile(
        db_session,
        test_project_id,
        {
            "api_key": "sk-rotated",
            "base_url": "https://changed.example.test/v1",
            "model": "first-model",
        },
    )
    with pytest.raises(ProjectLLMConfigurationError, match="base_url changed"):
        await restore_project_llm_execution_settings(
            db_session,
            test_project_id,
            snapshot,
        )


@pytest.mark.asyncio
async def test_execution_snapshot_rejects_missing_original_key_before_db_lookup(
    db_session: AsyncSession,
    test_project_id: str,
) -> None:
    payload = {
        "version": llm_runtime.PROJECT_LLM_EXECUTION_SNAPSHOT_VERSION,
        "novel_id": test_project_id,
        "profile": {
            "api_key_configured": False,
            "model": "snapshot-model",
            "base_url_hash": llm_runtime._stable_hash("https://example.test/v1"),
        },
        "sources": {},
        "deep_import": {},
    }
    payload["profile_hash"] = llm_runtime._stable_hash(payload)

    with (
        patch(
            "modules.project.llm_runtime._resolve_project_runtime_profile",
            new=AsyncMock(side_effect=AssertionError("must not query project")),
        ),
        pytest.raises(ProjectLLMConfigurationError, match="was not configured"),
    ):
        await restore_project_llm_execution_settings(
            db_session,
            test_project_id,
            payload,
        )


@pytest.mark.asyncio
async def test_execution_snapshot_freezes_effective_deep_import_env_settings(
    db_session: AsyncSession,
    test_project_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _set_llm_profile(
        db_session,
        test_project_id,
        {
            "api_key": "sk-deep-import",
            "base_url": "https://snapshot.example.test/v1",
            "model": "snapshot-model",
        },
    )
    monkeypatch.setenv("PHASE2_BATCH_CONCURRENCY", "7")
    snapshot = await build_project_llm_execution_snapshot(
        db_session,
        test_project_id,
    )
    assert snapshot["deep_import"]["phase2"]["batch_concurrency"] == 7
    assert snapshot["deep_import"]["phase0"]["target_input_chars"] == 72_000
    assert snapshot["deep_import"]["phase1b"]["enrich_max_tokens"] == 32_768
    assert snapshot["deep_import"]["phase1c"]["decision_max_tokens"] == 12_000
    assert snapshot["deep_import"]["phase1c"]["timeout_seconds"] == 360
    assert snapshot["deep_import"]["phase2"]["world_min_max_tokens"] == 32_768
    assert snapshot["deep_import"]["phase3"]["structure_max_tokens"] == 32_768

    monkeypatch.setenv("PHASE2_BATCH_CONCURRENCY", "19")
    restored = await restore_project_llm_execution_settings(
        db_session,
        test_project_id,
        snapshot,
    )

    assert restored[DEEP_IMPORT_FROZEN_SETTINGS_KEY] is True
    assert (
        deep_import_int_setting(
            restored,
            "phase2",
            "batch_concurrency",
            env_name="PHASE2_BATCH_CONCURRENCY",
            default=6,
        )
        == 7
    )


@pytest.mark.asyncio
async def test_open_project_llm_clients_keep_two_project_profiles_isolated(
    db_session: AsyncSession,
    test_project_id: str,
    factory,
) -> None:
    second_id = str(await factory.create_project(title="Second LLM Project"))
    await _set_llm_profile(
        db_session,
        test_project_id,
        {
            "api_key": "sk-first-secret",
            "base_url": "https://first.example.test/v1",
            "model": "first-model",
        },
    )
    await _set_llm_profile(
        db_session,
        second_id,
        {
            "api_key": "sk-second-secret",
            "base_url": "https://second.example.test/v1",
            "model": "second-model",
        },
    )

    async with open_project_llm_client(db_session, test_project_id) as first:
        async with open_project_llm_client(db_session, second_id) as second:
            assert first.model_name == "first-model"
            assert first.profile_summary["base_url_host"] == "first.example.test"
            assert second.model_name == "second-model"
            assert second.profile_summary["base_url_host"] == "second.example.test"
            assert "second" not in str(first.profile_summary)
            assert "first" not in str(second.profile_summary)

    await _set_llm_profile(
        db_session,
        test_project_id,
        {
            "api_key": "sk-first-secret-updated",
            "base_url": "https://first-updated.example.test/v1",
            "model": "first-model-updated",
        },
    )
    async with open_project_llm_client(db_session, test_project_id) as first:
        async with open_project_llm_client(db_session, second_id) as second:
            assert first.model_name == "first-model-updated"
            assert first.profile_summary["base_url_host"] == (
                "first-updated.example.test"
            )
            assert second.model_name == "second-model"
            assert second.profile_summary["base_url_host"] == "second.example.test"


@pytest.mark.asyncio
async def test_two_projects_generate_concurrently_without_profile_or_result_crossover(
    db_session: AsyncSession,
    test_project_id: str,
    factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    second_id = str(await factory.create_project(title="Concurrent LLM Project"))
    await _set_llm_profile(
        db_session,
        test_project_id,
        {
            "api_key": "sk-concurrent-first",
            "base_url": "https://first.example.test/v1",
            "model": "first-model",
        },
    )
    await _set_llm_profile(
        db_session,
        second_id,
        {
            "api_key": "sk-concurrent-second",
            "base_url": "https://second.example.test/v1",
            "model": "second-model",
        },
    )
    constructed: list[tuple[str, str]] = []

    class FakeClient:
        def __init__(self, profile):
            self.model_name = profile.model
            self.profile_summary = profile.sanitized_summary()
            self.runtime_scope = {}
            self._api_key = profile.api_key
            self.close = AsyncMock()
            constructed.append((profile.model, profile.api_key))

        def bind_runtime_scope(self, *, novel_id, profile_source):
            self.runtime_scope = {
                "novel_id": novel_id,
                "profile_source": profile_source,
            }

        async def generate(self, _request):
            await asyncio.sleep(0)
            return SimpleNamespace(content=self.model_name, model=self.model_name)

    monkeypatch.setattr(
        "modules.project.llm_runtime.LLMClient.from_resolved_profile",
        lambda profile: FakeClient(profile),
    )

    async def run(novel_id: str) -> tuple[str, dict]:
        async with open_project_llm_client(db_session, novel_id) as client:
            response = await client.generate(object())
            return response.content, client.runtime_scope

    first, second = await asyncio.gather(
        run(test_project_id),
        run(second_id),
    )

    assert constructed == [
        ("first-model", "sk-concurrent-first"),
        ("second-model", "sk-concurrent-second"),
    ]
    assert first == (
        "first-model",
        {"novel_id": test_project_id, "profile_source": "project"},
    )
    assert second == (
        "second-model",
        {"novel_id": second_id, "profile_source": "project"},
    )
