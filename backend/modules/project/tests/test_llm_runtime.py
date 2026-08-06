"""Tests for the project-owned, account-configured business LLM runtime seam."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.llm.secret_store import encrypt_secret, fingerprint_secret
from modules.project import llm_runtime
from modules.project.contracts import ProjectLLMConfigurationError
from modules.project.facade import (
    build_project_llm_execution_snapshot,
    create_project_snapshot_llm_client,
    get_project_context,
    open_project_llm_client,
    restore_project_llm_execution_settings,
)
from modules.project.models import Project
from modules.settings.constants import ACCOUNT_LLM_PROVIDER_TEMPLATES, LOCAL_OWNER_ID
from modules.settings.repositories import (
    AccountLLMCredentialRepository,
    GlobalLLMDefaultsRepository,
)
from shared.deep_import_settings import (
    DEEP_IMPORT_FROZEN_SETTINGS_KEY,
    deep_import_int_setting,
)


async def _set_legacy_project_profile(
    db: AsyncSession,
    project_id: str,
    profile: dict,
    *,
    deep_import: dict | None = None,
) -> None:
    project = (
        await db.execute(select(Project).where(Project.id == uuid.UUID(project_id)))
    ).scalar_one()
    project.settings = {"llm": profile}
    if deep_import is not None:
        project.settings["deep_import"] = deep_import
    await db.flush()


async def _seed_account_connection(
    db: AsyncSession,
    *,
    owner_id: uuid.UUID = LOCAL_OWNER_ID,
    provider_id: str = "deepseek",
    api_key: str = "unit-test-account-key",
    activate: bool = True,
) -> None:
    await AccountLLMCredentialRepository().upsert(
        db,
        {
            "owner_id": owner_id,
            "provider_id": provider_id,
            "encrypted_api_key": encrypt_secret(api_key),
            "key_fingerprint": fingerprint_secret(
                api_key,
                purpose="account-llm-api-key",
            ),
            "verified_at": datetime.now(UTC),
        },
    )
    if activate:
        await GlobalLLMDefaultsRepository().upsert(
            db,
            {
                "owner_id": owner_id,
                **ACCOUNT_LLM_PROVIDER_TEMPLATES[provider_id],
            },
        )


@pytest.mark.asyncio
async def test_runtime_uses_account_profile_and_ignores_legacy_project_connection(
    db_session: AsyncSession,
    test_project_id: str,
) -> None:
    await _seed_account_connection(
        db_session,
        api_key="unit-test-account-runtime-key",
    )
    await _set_legacy_project_profile(
        db_session,
        test_project_id,
        {
            "provider_id": "openai-compatible",
            "api_key": "legacy-project-key-must-not-run",
            "base_url": "https://legacy.example.test/v1?token=hidden",
            "model": "legacy-project-model",
        },
    )

    async with open_project_llm_client(db_session, test_project_id) as client:
        summary = client.profile_summary
        assert client.model_name == "deepseek-v4-flash"
        assert summary["provider_id"] == "deepseek"
        assert summary["base_url_host"] == "api.deepseek.com"
        assert summary["api_key_configured"] is True
        assert summary["sources"]["model"] == "account"
        assert summary["sources"]["api_key"] == "account"
        assert client.runtime_scope == {
            "novel_id": test_project_id,
            "profile_source": "account",
        }
        assert "unit-test-account-runtime-key" not in str(summary)
        assert "legacy-project-key-must-not-run" not in str(summary)
        assert "token=hidden" not in str(summary)


@pytest.mark.asyncio
async def test_runtime_closes_on_workflow_failure(
    db_session: AsyncSession,
    test_project_id: str,
) -> None:
    await _seed_account_connection(db_session)
    close = AsyncMock()

    with pytest.raises(RuntimeError, match="workflow failed"):
        async with open_project_llm_client(db_session, test_project_id) as client:
            client.close = close
            raise RuntimeError("workflow failed")

    close.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_runtime_closes_on_cancellation(
    db_session: AsyncSession,
    test_project_id: str,
) -> None:
    await _seed_account_connection(db_session)
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
async def test_runtime_fails_closed_without_account_key(
    db_session: AsyncSession,
    test_project_id: str,
) -> None:
    await _set_legacy_project_profile(
        db_session,
        test_project_id,
        {"api_key": "legacy-key-cannot-rescue-runtime"},
    )
    with pytest.raises(ProjectLLMConfigurationError, match="账户模型尚未连接"):
        async with open_project_llm_client(db_session, test_project_id):
            pass


@pytest.mark.asyncio
async def test_runtime_rejects_soft_deleted_or_missing_project(
    db_session: AsyncSession,
    test_project_id: str,
) -> None:
    await _seed_account_connection(db_session)
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
    with pytest.raises(Exception, match="not found"):
        async with open_project_llm_client(db_session, str(uuid.uuid4())):
            pass


@pytest.mark.asyncio
async def test_runtime_rejects_unbounded_timeout_override(
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
async def test_snapshot_client_keeps_same_fail_closed_rules() -> None:
    client = create_project_snapshot_llm_client(
        {
            "llm": {
                "api_key": "unit-test-snapshot-key",
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
        assert client.runtime_scope == {
            "novel_id": "snapshot-novel-id",
            "profile_source": "project_snapshot",
        }
        assert "unit-test-snapshot-key" not in str(client.profile_summary)
        assert "token=hidden" not in str(client.profile_summary)
    finally:
        await client.close()

    with pytest.raises(ProjectLLMConfigurationError, match="API key"):
        create_project_snapshot_llm_client({"llm": {"model": "missing-key"}})


@pytest.mark.asyncio
async def test_execution_snapshot_is_secret_free_and_uses_rotated_provider_key(
    db_session: AsyncSession,
    test_project_id: str,
) -> None:
    await _seed_account_connection(
        db_session,
        api_key="unit-test-before-rotation",
    )
    snapshot = await build_project_llm_execution_snapshot(
        db_session,
        test_project_id,
    )
    context_before_rotation = await get_project_context(db_session, test_project_id)

    serialized = str(snapshot)
    assert "unit-test-before-rotation" not in serialized
    assert context_before_rotation is not None
    assert "unit-test-before-rotation" not in str(context_before_rotation.settings)
    assert snapshot["profile"]["provider_id"] == "deepseek"
    assert snapshot["profile"]["model"] == "deepseek-v4-flash"
    assert snapshot["sources"]["model"] == "account"

    await _seed_account_connection(
        db_session,
        api_key="unit-test-after-rotation",
    )
    restored = await restore_project_llm_execution_settings(
        db_session,
        test_project_id,
        snapshot,
    )
    context_after_rotation = await get_project_context(db_session, test_project_id)

    assert restored["llm"]["model"] == "deepseek-v4-flash"
    assert restored["llm"]["api_key"] == "unit-test-after-rotation"
    assert restored["llm"]["api_key"] != "unit-test-before-rotation"
    assert context_after_rotation is not None
    assert "unit-test-after-rotation" not in str(context_after_rotation.settings)
    assert "unit-test-after-rotation" not in serialized


@pytest.mark.asyncio
async def test_snapshot_provider_survives_active_template_hot_switch(
    db_session: AsyncSession,
    test_project_id: str,
    monkeypatch,
) -> None:
    monkeypatch.setenv("ENABLE_ACCOUNT_KIMI_K3", "1")
    await _seed_account_connection(
        db_session,
        provider_id="deepseek",
        api_key="unit-test-deepseek-key",
    )
    snapshot = await build_project_llm_execution_snapshot(
        db_session,
        test_project_id,
    )
    await _seed_account_connection(
        db_session,
        provider_id="kimi",
        api_key="unit-test-kimi-key",
    )

    async with open_project_llm_client(db_session, test_project_id) as current:
        assert current.model_name == "kimi-k3"

    restored = await restore_project_llm_execution_settings(
        db_session,
        test_project_id,
        snapshot,
    )
    assert restored["llm"]["provider_id"] == "deepseek"
    assert restored["llm"]["model"] == "deepseek-v4-flash"
    assert restored["llm"]["api_key"] == "unit-test-deepseek-key"


@pytest.mark.asyncio
async def test_snapshot_fails_when_original_provider_connection_was_cleared(
    db_session: AsyncSession,
    test_project_id: str,
) -> None:
    await _seed_account_connection(db_session)
    snapshot = await build_project_llm_execution_snapshot(
        db_session,
        test_project_id,
    )
    await AccountLLMCredentialRepository().delete(
        db_session,
        LOCAL_OWNER_ID,
        "deepseek",
    )

    with pytest.raises(ProjectLLMConfigurationError, match="尚未连接"):
        await restore_project_llm_execution_settings(
            db_session,
            test_project_id,
            snapshot,
        )


@pytest.mark.asyncio
async def test_snapshot_rejects_missing_original_key_before_db_lookup(
    db_session: AsyncSession,
    test_project_id: str,
    monkeypatch: pytest.MonkeyPatch,
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
    resolve = AsyncMock(side_effect=AssertionError("must not query project"))
    monkeypatch.setattr(
        "modules.project.llm_runtime._resolve_project_runtime_profile",
        resolve,
    )

    with pytest.raises(ProjectLLMConfigurationError, match="was not configured"):
        await restore_project_llm_execution_settings(
            db_session,
            test_project_id,
            payload,
        )
    resolve.assert_not_awaited()


@pytest.mark.asyncio
async def test_snapshot_freezes_effective_deep_import_settings(
    db_session: AsyncSession,
    test_project_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _seed_account_connection(db_session)
    monkeypatch.setenv("PHASE2_BATCH_CONCURRENCY", "7")
    snapshot = await build_project_llm_execution_snapshot(
        db_session,
        test_project_id,
    )
    assert snapshot["deep_import"]["phase2"]["batch_concurrency"] == 7
    assert snapshot["deep_import"]["phase1c"]["decision_max_tokens"] == 12_000

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
async def test_same_owner_projects_share_account_profile_not_legacy_profiles(
    db_session: AsyncSession,
    test_project_id: str,
    factory,
) -> None:
    second_id = str(await factory.create_project(title="Second Project"))
    await _seed_account_connection(db_session)
    await _set_legacy_project_profile(
        db_session,
        test_project_id,
        {"model": "legacy-first", "api_key": "legacy-first-key"},
    )
    await _set_legacy_project_profile(
        db_session,
        second_id,
        {"model": "legacy-second", "api_key": "legacy-second-key"},
    )

    async with open_project_llm_client(db_session, test_project_id) as first:
        async with open_project_llm_client(db_session, second_id) as second:
            assert first.model_name == "deepseek-v4-flash"
            assert second.model_name == "deepseek-v4-flash"
            assert first.profile_summary == second.profile_summary


@pytest.mark.asyncio
async def test_browser_runtime_cannot_open_another_owners_project(
    db_session: AsyncSession,
    test_project_id: str,
    factory,
) -> None:
    owner_b = uuid.uuid4()
    second_id = str(
        await factory.create_project(
            title="Other Owner Project",
            owner_id=owner_b,
        )
    )
    await _seed_account_connection(
        db_session,
        owner_id=LOCAL_OWNER_ID,
        provider_id="deepseek",
        api_key="unit-test-owner-a-key",
    )
    await _seed_account_connection(
        db_session,
        owner_id=owner_b,
        provider_id="kimi",
        api_key="unit-test-owner-b-key",
    )
    async with open_project_llm_client(db_session, test_project_id) as first:
        assert first.model_name == "deepseek-v4-flash"

    with pytest.raises(Exception, match="not found"):
        async with open_project_llm_client(db_session, second_id):
            pass
