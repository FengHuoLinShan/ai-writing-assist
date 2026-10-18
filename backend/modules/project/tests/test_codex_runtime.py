"""No-secret account connections still use the ordinary isolated project runtime."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from sqlalchemy.exc import IntegrityError

from modules.account.contracts import BOOTSTRAP_ACCOUNT_ID
from modules.account.settings_constants import ACCOUNT_LLM_PROVIDER_TEMPLATES
from modules.account.settings_repositories import (
    AccountLLMCredentialRepository,
    GlobalLLMDefaultsRepository,
)
from modules.account.settings_service import SettingsService
from modules.project.contracts import ProjectLLMConfigurationError
from modules.project.facade import (
    build_project_llm_execution_snapshot,
    open_project_llm_client,
    restore_project_llm_execution_settings,
)


async def seed(db):
    await AccountLLMCredentialRepository().upsert(
        db,
        dict(
            owner_id=BOOTSTRAP_ACCOUNT_ID,
            provider_id="codex",
            encrypted_api_key=None,
            key_fingerprint="test-host",
            verified_at=datetime.now(UTC),
        ),
    )
    await GlobalLLMDefaultsRepository().upsert(
        db, dict(owner_id=BOOTSTRAP_ACCOUNT_ID, **ACCOUNT_LLM_PROVIDER_TEMPLATES["codex"])
    )


@pytest.mark.asyncio
async def test_codex_snapshot_has_no_fake_secret_and_clear_blocks_restore(
    db_session, test_project_id
):
    with (
        patch(
            "infrastructure.llm.codex_provider.codex_text_enabled",
            autospec=True,
            return_value=True,
        ),
        patch(
            "infrastructure.llm.codex_provider.codex_connection_fingerprint",
            autospec=True,
            return_value="test-host",
        ),
    ):
        await seed(db_session)
        async with open_project_llm_client(db_session, test_project_id) as client:
            assert client.model_name == "gpt-6-luna" and client.provider == "codex"
            assert client.profile_summary["api_key_configured"] is False
        snapshot = await build_project_llm_execution_snapshot(db_session, test_project_id)
        assert "test-host" not in str(snapshot)
        assert (
            snapshot["deep_import"]["phase2"]["parallel_provider_timeout_seconds"] == 900
        )
        await restore_project_llm_execution_settings(
            db_session, test_project_id, snapshot
        )
        await AccountLLMCredentialRepository().delete(
            db_session, BOOTSTRAP_ACCOUNT_ID, "codex"
        )
        with pytest.raises(ProjectLLMConfigurationError, match="尚未连接"):
            await restore_project_llm_execution_settings(
                db_session, test_project_id, snapshot
            )


@pytest.mark.asyncio
async def test_codex_cannot_use_foreign_owner_or_stale_host(db_session):
    with (
        patch(
            "infrastructure.llm.codex_provider.codex_text_enabled",
            autospec=True,
            return_value=True,
        ),
        patch(
            "infrastructure.llm.codex_provider.codex_connection_fingerprint",
            autospec=True,
            return_value="changed-host",
        ),
    ):
        await seed(db_session)
        with pytest.raises(ValueError, match="其他账户"):
            await SettingsService().resolve_account_llm_runtime_profile(
                db_session, owner_id=uuid.uuid4(), provider_id="codex"
            )
        with pytest.raises(ValueError, match="重新验证"):
            await SettingsService().resolve_account_llm_runtime_profile(
                db_session, provider_id="codex"
            )


@pytest.mark.asyncio
async def test_public_mode_excludes_local_codex(db_session):
    with patch(
        "infrastructure.llm.codex_provider.codex_text_enabled",
        autospec=True,
        return_value=False,
    ):
        connections = await SettingsService().get_account_llm_connections(db_session)
        assert "codex" not in {p.provider_id for p in connections.providers}
        with pytest.raises(ValueError):
            await SettingsService().connect_account_llm_provider(
                db_session, "codex", None
            )


@pytest.mark.asyncio
async def test_connection_verification_keeps_native_unknown_diagnostic(db_session):
    from infrastructure.llm.errors import LLMError

    evidence = {"exit_code": 17, "turn_started": False, "failure_label": "unknown"}
    with (
        patch(
            "infrastructure.llm.codex_provider.codex_text_enabled",
            autospec=True,
            return_value=True,
        ),
        patch(
            "infrastructure.llm.codex_provider.verify_codex_connection",
            autospec=True,
            side_effect=LLMError(
                "private original CLI text",
                provider="codex",
                error_kind="codex_result_unknown",
                diagnostic=evidence,
            ),
        ) as verify,
    ):
        with pytest.raises(ValueError) as caught:
            await SettingsService().connect_account_llm_provider(
                db_session, "codex", None
            )
        assert caught.value.error_kind == "codex_result_unknown"
        assert caught.value.diagnostic == evidence
        assert "private" not in str(caught.value)
        assert verify.await_count == 1


@pytest.mark.asyncio
async def test_api_connection_cannot_persist_without_secret(db_session):
    with pytest.raises(IntegrityError):
        await AccountLLMCredentialRepository().upsert(
            db_session,
            dict(
                owner_id=BOOTSTRAP_ACCOUNT_ID,
                provider_id="deepseek",
                encrypted_api_key=None,
                key_fingerprint="invalid",
                verified_at=datetime.now(UTC),
            ),
        )


@pytest.mark.asyncio
async def test_verified_codex_is_ready_without_claiming_api_key(
    db_session, test_project_id, async_client
):
    with (
        patch(
            "infrastructure.llm.codex_provider.codex_text_enabled",
            autospec=True,
            return_value=True,
        ),
        patch(
            "infrastructure.llm.codex_provider.codex_connection_fingerprint",
            autospec=True,
            return_value="test-host",
        ),
    ):
        await seed(db_session)
        response = await async_client.get(
            "/api/assistant/capabilities", params={"novel_id": test_project_id}
        )
        assert response.status_code == 200
        assert response.json()["model"]["available"] is True
        from modules.project.settings_service import (
            ProjectSettingsService,
        )

        settings = await ProjectSettingsService().get_effective_llm_settings(
            db_session, {}
        )
        assert settings.api_key_configured.value is False
        assert "codex" not in settings.api_key_configured_providers.value


@pytest.mark.asyncio
async def test_codex_wrapper_version_change_blocks_old_snapshot(
    db_session, test_project_id, monkeypatch
):
    with (
        patch(
            "infrastructure.llm.codex_provider.codex_text_enabled",
            autospec=True,
            return_value=True,
        ),
        patch(
            "infrastructure.llm.codex_provider.codex_connection_fingerprint",
            autospec=True,
            return_value="test-host",
        ),
    ):
        await seed(db_session)
        snapshot = await build_project_llm_execution_snapshot(db_session, test_project_id)
        changed = {
            **ACCOUNT_LLM_PROVIDER_TEMPLATES["codex"],
            "extra": {
                "reasoning_effort": "max",
                "codex_text_adapter_version": "changed-adapter-version",
            },
        }
        monkeypatch.setitem(ACCOUNT_LLM_PROVIDER_TEMPLATES, "codex", changed)
        with pytest.raises(ProjectLLMConfigurationError):
            await restore_project_llm_execution_settings(
                db_session, test_project_id, snapshot
            )


@pytest.mark.asyncio
async def test_cached_codex_client_rechecks_current_authorization_before_reservation(
    db_session, test_project_id, tmp_path
):
    from infrastructure.llm.schemas import LLMCallRequest

    with (
        patch(
            "infrastructure.llm.codex_provider.codex_text_enabled",
            autospec=True,
            return_value=True,
        ),
        patch(
            "infrastructure.llm.codex_provider.codex_connection_fingerprint",
            autospec=True,
            return_value="test-host",
        ),
        patch(
            "infrastructure.llm.codex_identity.codex_login_identity",
            autospec=True,
            return_value="test-account",
        ),
        patch(
            "infrastructure.llm.model_admission._admission_directory",
            autospec=True,
            return_value=tmp_path,
        ),
        patch(
            "infrastructure.llm.client._reserve_ai_run_request", autospec=True
        ) as reserve,
        patch("infrastructure.llm.codex_provider.run_cli_agent", autospec=True) as native,
    ):
        await seed(db_session)
        async with open_project_llm_client(db_session, test_project_id) as client:
            await AccountLLMCredentialRepository().delete(
                db_session, BOOTSTRAP_ACCOUNT_ID, "codex"
            )
            with pytest.raises(ProjectLLMConfigurationError, match="尚未连接"):
                await client.generate(LLMCallRequest())
        native.assert_not_called()
        reserve.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["missing", "version", "instructions_hash"])
async def test_wrapper_stamp_drift_is_closed_and_original_snapshot_is_preserved(
    db_session, test_project_id, field
):
    from copy import deepcopy

    from infrastructure.stable_hash import stable_hash

    with (
        patch(
            "infrastructure.llm.codex_provider.codex_text_enabled",
            autospec=True,
            return_value=True,
        ),
        patch(
            "infrastructure.llm.codex_provider.codex_connection_fingerprint",
            autospec=True,
            return_value="test-host",
        ),
    ):
        await seed(db_session)
        snapshot = await build_project_llm_execution_snapshot(db_session, test_project_id)
        original = deepcopy(snapshot)
        if field == "missing":
            snapshot["profile"].pop("native_wrapper")
        else:
            snapshot["profile"]["native_wrapper"][field] = "old-wrapper"
        snapshot["profile_hash"] = stable_hash(
            {k: v for k, v in snapshot.items() if k != "profile_hash"}
        )
        frozen = deepcopy(snapshot)
        with pytest.raises(ProjectLLMConfigurationError, match="wrapper"):
            await restore_project_llm_execution_settings(
                db_session, test_project_id, snapshot
            )
        assert (
            snapshot == frozen
            and original["profile"]["native_wrapper"]["version"] == "codex-text-v3"
        )


@pytest.mark.asyncio
async def test_old_local_agent_text_blocks_resume_but_history_is_readable(
    db_session, test_project_id, async_client
):
    from copy import deepcopy

    from infrastructure.stable_hash import stable_hash
    from infrastructure.tasks.models import AsyncTask

    snapshot = {
        "version": "1",
        "novel_id": test_project_id,
        "local_agent": {"version": "legacy-synthetic"},
        "profile": {"provider_id": "codex", "model": "gpt-6-luna"},
    }
    snapshot["profile_hash"] = stable_hash(snapshot)
    original = deepcopy(snapshot)
    receipt = {"synthetic": True, "usage_status": "unknown", "outcome": "failed"}
    task = AsyncTask(
        id=uuid.uuid4(),
        novel_id=uuid.UUID(test_project_id),
        task_type="deep_import",
        status="failed",
        meta={"llm_snapshot": snapshot},
        result={"historical_receipt": receipt},
    )
    db_session.add(task)
    await db_session.flush()
    with patch(
        "infrastructure.llm.codex_provider.run_cli_agent", autospec=True
    ) as native:
        with pytest.raises(ProjectLLMConfigurationError, match="Local CLI"):
            await restore_project_llm_execution_settings(
                db_session, test_project_id, snapshot
            )
        response = await async_client.get(
            f"/api/tasks/{task.id}", params={"novel_id": test_project_id}
        )
        assert response.status_code == 200
        assert response.json()["result"]["historical_receipt"] == receipt
        assert task.meta["llm_snapshot"] == original
        native.assert_not_called()


def test_native_project_snapshot_requires_scope_before_provider_creation():
    from modules.project.facade import create_project_snapshot_llm_client

    profile = {
        "llm": {
            **ACCOUNT_LLM_PROVIDER_TEMPLATES["codex"],
            "extra": {
                **ACCOUNT_LLM_PROVIDER_TEMPLATES["codex"]["extra"],
                "codex_connection_fingerprint": "test-host",
            },
        }
    }
    with patch("infrastructure.llm.providers.get_provider", autospec=True) as provider:
        with pytest.raises(ProjectLLMConfigurationError, match="requires novel_id"):
            create_project_snapshot_llm_client(profile)
        provider.assert_not_called()


async def test_approval_snapshot_restores_low_and_rechecks_same_owner_connection(
    db_session, test_project_id
):
    from infrastructure.llm.schemas import LLMCallRequest
    from modules.project.facade import open_project_snapshot_llm_client

    with (
        patch(
            "infrastructure.llm.codex_provider.codex_text_enabled",
            autospec=True,
            return_value=True,
        ),
        patch(
            "infrastructure.llm.codex_provider.codex_connection_fingerprint",
            autospec=True,
            return_value="test-host",
        ),
    ):
        await seed(db_session)
        snapshot = await build_project_llm_execution_snapshot(
            db_session, test_project_id, purpose="approval_judgment"
        )
        assert snapshot["profile"]["reasoning_effort"] == "low"
        assert "test-host" not in str(snapshot)
        async with open_project_snapshot_llm_client(
            db_session, test_project_id, snapshot
        ) as client:
            await client.authorize_request()
            request = client.resolve_request_defaults(
                LLMCallRequest(response_format={"type": "json_schema"})
            )
            assert request.extra["reasoning_effort"] == "low"
            client._validate_input_budget(request)
            await AccountLLMCredentialRepository().delete(
                db_session, BOOTSTRAP_ACCOUNT_ID, "codex"
            )
            with pytest.raises(ProjectLLMConfigurationError, match="尚未连接"):
                await client.authorize_request()
