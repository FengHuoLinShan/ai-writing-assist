"""
Project LLM settings API tests.

These tests pin the transition contract: project settings retain deep-import
overrides, while account connections are the only provider/model/key runtime
source.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import get_settings
from core.errors import ValidationError
from modules.project.facade import get_project_context
from modules.project.models import Project
from modules.project.schemas import ProjectUpdate
from modules.project.services import ProjectService

XHR_HEADERS = {"X-Requested-With": "XMLHttpRequest"}


def test_public_generic_project_settings_reject_non_public_base_url(
    monkeypatch,
) -> None:
    monkeypatch.setenv("AUTH_MODE", "public")
    get_settings.cache_clear()
    try:
        with pytest.raises(ValidationError, match="must use https"):
            ProjectService._encrypt_project_settings_update(
                ProjectUpdate(
                    settings={
                        "llm": {
                            "base_url": "http://127.0.0.1:9000/v1",
                        }
                    }
                )
            )
    finally:
        get_settings.cache_clear()


@pytest_asyncio.fixture
async def sample_project(async_client: AsyncClient) -> dict:
    resp = await async_client.post("/api/projects", json={"title": "LLM 配置测试"})
    assert resp.status_code == 201
    return resp.json()


@pytest.mark.asyncio
async def test_llm_provider_templates_only_expose_supported_account_connections(
    async_client: AsyncClient,
) -> None:
    resp = await async_client.get("/api/projects/llm/provider-templates")

    assert resp.status_code == 200
    items = resp.json()["items"]
    ids = {item["id"] for item in items}
    assert ids == {"deepseek", "kimi"}
    by_id = {item["id"]: item for item in items}
    assert by_id["deepseek"]["default_model"] == "deepseek-v4-flash"
    assert by_id["deepseek"]["base_url"] == "https://api.deepseek.com"
    assert by_id["kimi"]["default_model"] == "kimi-k3"
    assert all("api_key" not in item for item in items)


@pytest.mark.asyncio
async def test_get_project_llm_settings_does_not_require_xhr_header(
    async_client: AsyncClient,
    sample_project: dict,
) -> None:
    resp = await async_client.get(f"/api/projects/{sample_project['id']}/llm-settings")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_effective_settings_hide_recycled_project(
    async_client: AsyncClient,
    factory,
) -> None:
    pid = await factory.create_project()
    deleted = await async_client.delete(f"/api/projects/{pid}")
    assert deleted.status_code == 204

    llm_response = await async_client.get(f"/api/projects/{pid}/effective-llm-settings")
    author_response = await async_client.get(
        f"/api/projects/{pid}/effective-author-preferences"
    )

    assert llm_response.status_code == 404
    assert author_response.status_code == 404


@pytest.mark.asyncio
async def test_update_project_llm_settings_requires_xhr_header(
    raw_async_client: AsyncClient,
    sample_project: dict,
) -> None:
    resp = await raw_async_client.put(
        f"/api/projects/{sample_project['id']}/llm-settings",
        json={"provider_id": "deepseek"},
    )
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Missing X-Requested-With header"


@pytest.mark.asyncio
async def test_project_llm_settings_keep_deep_import_but_not_connection_secrets(
    async_client: AsyncClient,
    db_session: AsyncSession,
    sample_project: dict,
) -> None:
    pid = sample_project["id"]

    resp = await async_client.put(
        f"/api/projects/{pid}/llm-settings",
        headers=XHR_HEADERS,
        json={
            "provider_id": "deepseek",
            "base_url": "https://api.deepseek.com/v1",
            "model": "deepseek-chat",
            "timeout": 180,
            "max_tokens": 8192,
            "temperature": 0.2,
            "top_p": 0.8,
            "extra": {"reasoning_effort": "high"},
            "deep_import": {
                "phase0": {"max_tokens_per_input_char": 0.36},
                "phase1a": {"scene_slicing_timeout_seconds": 1200},
            },
        },
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["provider_id"] == "deepseek"
    assert data["base_url"] == "https://api.deepseek.com/v1"
    assert data["model"] == "deepseek-chat"
    assert data["timeout"] == 180
    assert data["max_tokens"] == 8192
    assert data["temperature"] == 0.2
    assert data["top_p"] == 0.8
    assert data["extra"] == {"reasoning_effort": "high"}
    assert data["deep_import"]["phase0"]["max_tokens_per_input_char"] == 0.36
    assert data["deep_import"]["phase1a"]["scene_slicing_timeout_seconds"] == 1200
    assert data["deep_import"]["phase2"]["batch_size_scenes"] == 12
    assert data["api_key_configured"] is False
    assert "api_key" not in data

    stored = (
        await db_session.execute(select(Project).where(Project.id == uuid.UUID(pid)))
    ).scalar_one()
    assert "api_key" not in stored.settings["llm"]
    assert "api_keys_by_provider" not in stored.settings["llm"]

    resp = await async_client.get(f"/api/projects/{pid}/llm-settings")
    assert resp.status_code == 200
    assert resp.json()["api_key_configured"] is False
    assert resp.json()["deep_import"]["phase0"]["max_tokens_per_input_char"] == 0.36

    project_resp = await async_client.get(f"/api/projects/{pid}")
    assert project_resp.status_code == 200
    llm_settings = project_resp.json()["settings"]["llm"]
    assert llm_settings["provider_id"] == "deepseek"
    assert llm_settings["api_key_configured"] is False
    assert "api_key" not in llm_settings


@pytest.mark.asyncio
async def test_llm_settings_validation_error_omits_api_key_input(
    async_client: AsyncClient,
    sample_project: dict,
) -> None:
    marker = "provider-key-without-known-prefix-" + ("x" * 4096)

    resp = await async_client.put(
        f"/api/projects/{sample_project['id']}/llm-settings",
        headers=XHR_HEADERS,
        json={"provider_id": "deepseek", "api_key": marker},
    )

    assert resp.status_code == 422
    assert marker not in resp.text
    detail = resp.json()["detail"]
    api_key_error = next(item for item in detail if item["loc"] == ["body", "api_key"])
    assert "input" not in api_key_error
    assert api_key_error["type"] == "string_too_long"
    assert api_key_error["msg"]


@pytest.mark.asyncio
async def test_generic_project_update_rejects_llm_api_key(
    async_client: AsyncClient,
    db_session: AsyncSession,
    sample_project: dict,
) -> None:
    pid = sample_project["id"]

    resp = await async_client.put(
        f"/api/projects/{pid}",
        json={"settings": {"llm": {"provider_id": "deepseek", "api_key": "sk-generic"}}},
    )

    assert resp.status_code == 400
    assert "sk-generic" not in resp.text
    stored = (
        await db_session.execute(select(Project).where(Project.id == uuid.UUID(pid)))
    ).scalar_one()
    assert "llm" not in stored.settings


@pytest.mark.asyncio
async def test_project_llm_endpoint_rejects_key_and_points_to_account_settings(
    async_client: AsyncClient,
    sample_project: dict,
) -> None:
    pid = sample_project["id"]
    response = await async_client.put(
        f"/api/projects/{pid}/llm-settings",
        headers=XHR_HEADERS,
        json={
            "provider_id": "deepseek",
            "api_key": "sk-secret-value",
        },
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "API Key 只能在账户设置中配置"
    assert "sk-secret-value" not in response.text


@pytest.mark.asyncio
async def test_nonsecret_project_settings_update_removes_legacy_key_fields(
    async_client: AsyncClient,
    db_session: AsyncSession,
    sample_project: dict,
) -> None:
    pid = sample_project["id"]
    stored = (
        await db_session.execute(select(Project).where(Project.id == uuid.UUID(pid)))
    ).scalar_one()
    stored.settings = {
        "llm": {
            "provider_id": "deepseek",
            "api_key": {"encrypted": True, "version": "legacy", "value": "x"},
            "api_keys_by_provider": {"deepseek": {"value": "x"}},
        }
    }
    await db_session.flush()

    response = await async_client.put(
        f"/api/projects/{pid}/llm-settings",
        headers=XHR_HEADERS,
        json={
            "deep_import": {"global": {"structured_max_fix_attempts": 3}},
        },
    )
    assert response.status_code == 200
    await db_session.refresh(stored)
    assert "api_key" not in stored.settings["llm"]
    assert "api_keys_by_provider" not in stored.settings["llm"]


@pytest.mark.asyncio
async def test_effective_llm_settings_use_account_template_when_unconnected(
    async_client,
    factory,
):
    pid = await factory.create_project()
    r = await async_client.get(f"/api/projects/{pid}/effective-llm-settings")
    assert r.status_code == 200
    body = r.json()
    for f in ("provider_id", "base_url", "model", "timeout", "max_tokens", "temperature"):
        assert body[f]["source"] == "global"
    assert body["provider_id"]["value"] == "deepseek"
    assert body["base_url"]["value"] == "https://api.deepseek.com"
    assert body["model"]["value"] == "deepseek-v4-flash"
    assert body["timeout"]["value"] == 180
    assert body["max_tokens"]["value"] == 12_000
    assert body["api_key_configured"]["source"] == "unset"
    assert body["api_key_configured"]["value"] is False


@pytest.mark.asyncio
async def test_effective_llm_settings_missing_project_returns_404(
    async_client: AsyncClient,
) -> None:
    response = await async_client.get(
        f"/api/projects/{uuid.uuid4()}/effective-llm-settings"
    )

    assert response.status_code == 404
    assert response.json()["error"] == "not_found"


@pytest.mark.asyncio
async def test_effective_llm_settings_deleted_project_returns_404(
    async_client: AsyncClient,
    factory,
) -> None:
    project_id = await factory.create_project()
    deleted = await async_client.delete(
        f"/api/projects/{project_id}",
        headers=XHR_HEADERS,
    )
    assert deleted.status_code == 204

    response = await async_client.get(
        f"/api/projects/{project_id}/effective-llm-settings"
    )

    assert response.status_code == 404
    assert response.json()["error"] == "not_found"


@pytest.mark.asyncio
async def test_project_connection_fields_cannot_override_account_template(
    async_client,
    factory,
):
    pid = await factory.create_project()
    rejected = await async_client.put(
        "/api/account/settings/llm-defaults",
        headers=XHR_HEADERS,
        json={
            "provider_id": "deepseek",
            "base_url": "https://api.deepseek.com/v1",
            "model": "deepseek-v4-flash",
        },
    )
    assert rejected.status_code == 400
    r = await async_client.get(f"/api/projects/{pid}/effective-llm-settings")
    body = r.json()
    assert body["provider_id"]["source"] == "global"
    assert body["provider_id"]["value"] == "deepseek"
    await async_client.put(
        f"/api/projects/{pid}/llm-settings",
        headers=XHR_HEADERS,
        json={
            "provider_id": "deepseek",
            "base_url": "https://api.deepseek.com/v1",
            "model": "deepseek-chat",
        },
    )
    r2 = await async_client.get(f"/api/projects/{pid}/effective-llm-settings")
    body2 = r2.json()
    assert body2["model"]["source"] == "global"
    assert body2["model"]["value"] == "deepseek-v4-flash"
    assert body2["provider_id"]["source"] == "global"


@pytest.mark.asyncio
async def test_reset_legacy_llm_field_keeps_account_template(async_client, factory):
    pid = await factory.create_project()
    await async_client.put(
        f"/api/projects/{pid}/llm-settings",
        headers=XHR_HEADERS,
        json={
            "provider_id": "deepseek",
            "base_url": "https://api.deepseek.com/v1",
            "model": "deepseek-chat",
        },
    )
    r = await async_client.delete(
        f"/api/projects/{pid}/llm-settings/field/provider_id",
        headers=XHR_HEADERS,
    )
    assert r.status_code == 200
    r2 = await async_client.get(f"/api/projects/{pid}/effective-llm-settings")
    assert r2.json()["provider_id"]["source"] == "global"
    assert r2.json()["provider_id"]["value"] == "deepseek"


@pytest.mark.asyncio
async def test_reset_llm_field_rejects_unknown(async_client, factory):
    pid = await factory.create_project()
    r = await async_client.delete(
        f"/api/projects/{pid}/llm-settings/field/malicious",
        headers=XHR_HEADERS,
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_put_project_model_does_not_change_effective_account_model(
    async_client,
    factory,
):
    pid = await factory.create_project()
    rejected = await async_client.put(
        "/api/account/settings/llm-defaults",
        headers=XHR_HEADERS,
        json={
            "provider_id": "deepseek",
            "base_url": "https://api.deepseek.com/v1",
            "model": "deepseek-v4-flash",
        },
    )
    assert rejected.status_code == 400
    r = await async_client.put(
        f"/api/projects/{pid}/llm-settings",
        headers=XHR_HEADERS,
        json={
            "provider_id": None,
            "base_url": None,
            "model": "custom-model",
        },
    )
    assert r.status_code == 200
    r2 = await async_client.get(f"/api/projects/{pid}/effective-llm-settings")
    body = r2.json()
    assert body["model"]["source"] == "global"
    assert body["model"]["value"] == "deepseek-v4-flash"
    assert body["provider_id"]["source"] == "global"
    assert body["base_url"]["source"] == "global"


@pytest.mark.asyncio
async def test_effective_deep_import_atomic_unit(async_client, factory):
    """D6: deep_import 是 atomic unit。项目保存后 effective 应反映 source=project
    与完整 dict；未配置时 source=system。"""
    pid = await factory.create_project()
    # 未配置 → system
    r0 = await async_client.get(f"/api/projects/{pid}/effective-llm-settings")
    assert r0.json()["deep_import"]["source"] == "system"
    assert r0.json()["deep_import"]["value"] is None
    # 保存整体覆盖
    di_payload = {
        "global": {
            "structured_timeout_grace_seconds": 30,
            "structured_max_fix_attempts": 5,
        },
        "phase0": {"target_input_chars": 80000},
    }
    r1 = await async_client.put(
        f"/api/projects/{pid}/llm-settings",
        headers=XHR_HEADERS,
        json={
            "provider_id": "deepseek",
            "base_url": "https://api.deepseek.com/v1",
            "model": "deepseek-chat",
            "deep_import": di_payload,
        },
    )
    assert r1.status_code == 200
    r2 = await async_client.get(f"/api/projects/{pid}/effective-llm-settings")
    body = r2.json()
    assert body["deep_import"]["source"] == "project"
    assert body["deep_import"]["value"] is not None
    assert (
        body["deep_import"]["value"]["global"]["structured_timeout_grace_seconds"] == 30
    )
    assert body["deep_import"]["value"]["phase0"]["target_input_chars"] == 80000


@pytest.mark.asyncio
async def test_reset_deep_import_field_restores_system(async_client, factory):
    """D5/D6: DELETE deep_import 字段应清除项目覆盖，effective 回到 source=system。"""
    pid = await factory.create_project()
    await async_client.put(
        f"/api/projects/{pid}/llm-settings",
        headers=XHR_HEADERS,
        json={
            "provider_id": "deepseek",
            "base_url": "https://api.deepseek.com/v1",
            "model": "deepseek-chat",
            "deep_import": {"global": {"structured_max_fix_attempts": 9}},
        },
    )
    r = await async_client.delete(
        f"/api/projects/{pid}/llm-settings/field/deep_import",
        headers=XHR_HEADERS,
    )
    assert r.status_code == 200
    r2 = await async_client.get(f"/api/projects/{pid}/effective-llm-settings")
    assert r2.json()["deep_import"]["source"] == "system"
    assert r2.json()["deep_import"]["value"] is None


@pytest.mark.asyncio
async def test_put_llm_settings_empty_deep_import_clears_key(async_client, factory):
    """D4/D6: PUT 传 deep_import={} 应清除项目覆盖（恢复继承），不应写入完整默认。"""
    pid = await factory.create_project()
    # 先保存一个非空 deep_import
    await async_client.put(
        f"/api/projects/{pid}/llm-settings",
        headers=XHR_HEADERS,
        json={
            "provider_id": "deepseek",
            "base_url": "https://api.deepseek.com/v1",
            "model": "deepseek-chat",
            "deep_import": {"global": {"structured_max_fix_attempts": 7}},
        },
    )
    # 再传空 dict 清除
    r = await async_client.put(
        f"/api/projects/{pid}/llm-settings",
        headers=XHR_HEADERS,
        json={
            "provider_id": "deepseek",
            "base_url": "https://api.deepseek.com/v1",
            "model": "deepseek-chat",
            "deep_import": {},
        },
    )
    assert r.status_code == 200
    r2 = await async_client.get(f"/api/projects/{pid}/effective-llm-settings")
    assert r2.json()["deep_import"]["source"] == "system"
    assert r2.json()["deep_import"]["value"] is None


@pytest.mark.asyncio
async def test_project_context_keeps_only_project_owned_nonsecret_settings(
    async_client,
    db_session,
    factory,
    monkeypatch,
):
    monkeypatch.setenv("ENABLE_ACCOUNT_KIMI_K3", "1")
    pid = await factory.create_project(
        settings={
            "temporary_entity_expiry_chapters": 18,
            "deep_import": {"global": {"structured_max_fix_attempts": 4}},
            "llm": {
                "provider_id": "legacy-project-provider",
                "api_key": "legacy-project-key",
            },
        }
    )

    context = await get_project_context(db_session, str(pid))

    assert context is not None
    assert context.settings["temporary_entity_expiry_chapters"] == 18
    assert context.settings["deep_import"]["global"]["structured_max_fix_attempts"] == 4
    assert context.settings["llm"]["provider_id"] == "legacy-project-provider"
    assert "api_key" not in context.settings["llm"]

    monkeypatch.setattr(
        "modules.account.settings_service._validate_account_llm_connection",
        AsyncMock(),
    )
    connected = await async_client.put(
        "/api/account/settings/llm-connections/kimi",
        headers=XHR_HEADERS,
        json={"api_key": "account-runtime-key"},
    )
    assert connected.status_code == 200
    context_with_global = await get_project_context(db_session, str(pid))

    assert context_with_global is not None
    assert context_with_global.settings == context.settings
    assert "account-runtime-key" not in str(context_with_global.model_dump())
