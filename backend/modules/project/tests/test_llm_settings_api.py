"""
Project LLM settings API tests.

These tests pin the user-facing contract: provider templates are exposed for the
console, while stored API keys are write-only and never echoed in project
responses.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.project.facade import get_project_context
from modules.project.models import Project

XHR_HEADERS = {"X-Requested-With": "XMLHttpRequest"}


@pytest.fixture
async def sample_project(async_client: AsyncClient) -> dict:
    resp = await async_client.post("/api/projects", json={"title": "LLM 配置测试"})
    assert resp.status_code == 201
    return resp.json()


@pytest.mark.asyncio
async def test_llm_provider_templates_include_common_suppliers(
    async_client: AsyncClient,
) -> None:
    resp = await async_client.get("/api/projects/llm/provider-templates")

    assert resp.status_code == 200
    items = resp.json()["items"]
    ids = {item["id"] for item in items}
    assert {
        "deepseek",
        "kimi",
        "qwen-dashscope",
        "zhipu",
        "baichuan",
        "minimax",
        "hunyuan",
        "qianfan",
        "stepfun",
        "yi",
        "mimo",
        "openrouter",
        "siliconflow",
        "volcengine-ark",
        "openai-compatible",
    }.issubset(ids)
    by_id = {item["id"]: item for item in items}
    assert by_id["deepseek"]["default_model"] == "deepseek-v4-flash"
    assert by_id["deepseek"]["base_url"] == "https://api.deepseek.com"
    assert by_id["qwen-dashscope"]["default_parameters"]["timeout"] == 180
    assert all("api_key" not in item for item in items)


@pytest.mark.asyncio
async def test_get_project_llm_settings_does_not_require_xhr_header(
    async_client: AsyncClient,
    sample_project: dict,
) -> None:
    resp = await async_client.get(f"/api/projects/{sample_project['id']}/llm-settings")
    assert resp.status_code == 200


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
async def test_update_and_get_project_llm_settings_masks_api_key(
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
            "api_key": "sk-secret-value",
        },
    )

    assert resp.status_code == 200
    assert "sk-secret-value" not in resp.text
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
    assert data["api_key_configured"] is True
    assert "api_key" not in data

    stored = (
        await db_session.execute(select(Project).where(Project.id == uuid.UUID(pid)))
    ).scalar_one()
    stored_api_key = stored.settings["llm"]["api_key"]
    assert stored_api_key != "sk-secret-value"
    assert stored_api_key["encrypted"] is True
    assert stored_api_key["version"] == "fernet-v1"
    assert "sk-secret-value" not in str(stored.settings)

    resp = await async_client.get(f"/api/projects/{pid}/llm-settings")
    assert resp.status_code == 200
    assert "sk-secret-value" not in resp.text
    assert resp.json()["api_key_configured"] is True
    assert resp.json()["deep_import"]["phase0"]["max_tokens_per_input_char"] == 0.36

    project_resp = await async_client.get(f"/api/projects/{pid}")
    assert project_resp.status_code == 200
    assert "sk-secret-value" not in project_resp.text
    llm_settings = project_resp.json()["settings"]["llm"]
    assert llm_settings["provider_id"] == "deepseek"
    assert llm_settings["api_key_configured"] is True
    assert "api_key" not in llm_settings


@pytest.mark.asyncio
async def test_update_project_settings_encrypts_generic_llm_api_key(
    async_client: AsyncClient,
    db_session: AsyncSession,
    sample_project: dict,
) -> None:
    pid = sample_project["id"]

    resp = await async_client.put(
        f"/api/projects/{pid}",
        json={"settings": {"llm": {"provider_id": "deepseek", "api_key": "sk-generic"}}},
    )

    assert resp.status_code == 200
    assert "sk-generic" not in resp.text
    stored = (
        await db_session.execute(select(Project).where(Project.id == uuid.UUID(pid)))
    ).scalar_one()
    stored_api_key = stored.settings["llm"]["api_key"]
    assert stored_api_key["encrypted"] is True
    assert "sk-generic" not in str(stored.settings)


@pytest.mark.asyncio
async def test_update_project_llm_settings_preserves_existing_key_when_empty(
    async_client: AsyncClient,
    sample_project: dict,
) -> None:
    pid = sample_project["id"]
    first = await async_client.put(
        f"/api/projects/{pid}/llm-settings",
        headers=XHR_HEADERS,
        json={
            "provider_id": "deepseek",
            "base_url": "https://api.deepseek.com/v1",
            "model": "deepseek-chat",
            "api_key": "sk-secret-value",
        },
    )
    assert first.status_code == 200

    second = await async_client.put(
        f"/api/projects/{pid}/llm-settings",
        headers=XHR_HEADERS,
        json={
            "provider_id": "kimi",
            "base_url": "https://api.moonshot.cn/v1",
            "model": "moonshot-v1-8k",
            "api_key": "",
        },
    )

    assert second.status_code == 200
    assert "sk-secret-value" not in second.text
    data = second.json()
    assert data["provider_id"] == "kimi"
    assert data["api_key_configured"] is True


@pytest.mark.asyncio
async def test_project_update_response_sanitizes_llm_key(
    async_client: AsyncClient,
    sample_project: dict,
) -> None:
    pid = sample_project["id"]

    resp = await async_client.put(
        f"/api/projects/{pid}",
        json={"settings": {"llm": {"api_key": "sk-from-generic-update"}}},
    )

    assert resp.status_code == 200
    assert "sk-from-generic-update" not in resp.text
    assert resp.json()["settings"]["llm"]["api_key_configured"] is True


@pytest.mark.asyncio
async def test_effective_llm_settings_all_system_when_no_config(async_client, factory):
    pid = await factory.create_project()
    r = await async_client.get(f"/api/projects/{pid}/effective-llm-settings")
    assert r.status_code == 200
    body = r.json()
    for f in ("provider_id", "base_url", "model", "timeout", "max_tokens", "temperature"):
        assert body[f]["source"] == "system"
    assert body["provider_id"]["value"] == "deepseek"
    assert body["base_url"]["value"] == "https://api.deepseek.com"
    assert body["model"]["value"] == "deepseek-v4-flash"
    assert body["timeout"]["value"] == 180
    assert body["max_tokens"]["value"] == 12_000
    assert body["api_key_configured"]["source"] == "unset"
    assert body["api_key_configured"]["value"] is False


@pytest.mark.asyncio
async def test_effective_llm_settings_global_then_project(async_client, factory):
    pid = await factory.create_project()
    await async_client.put(
        "/api/settings/llm-defaults",
        headers=XHR_HEADERS,
        json={
            "provider_id": "deepseek",
            "base_url": "https://api.deepseek.com/v1",
            "model": "deepseek-v4-flash",
        },
    )
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
    assert body2["model"]["source"] == "project"
    assert body2["model"]["value"] == "deepseek-chat"
    assert body2["provider_id"]["source"] == "project"


@pytest.mark.asyncio
async def test_reset_llm_field_restores_global(async_client, factory):
    pid = await factory.create_project()
    await async_client.put(
        "/api/settings/llm-defaults",
        headers=XHR_HEADERS,
        json={"provider_id": "openai-compatible"},
    )
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
    assert r2.json()["provider_id"]["value"] == "openai-compatible"


@pytest.mark.asyncio
async def test_reset_llm_field_rejects_unknown(async_client, factory):
    pid = await factory.create_project()
    r = await async_client.delete(
        f"/api/projects/{pid}/llm-settings/field/malicious",
        headers=XHR_HEADERS,
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_put_llm_settings_with_nulls_inherits_global(async_client, factory):
    """D3: 项目 PUT 缺失字段（null）应继承全局默认，而非写入空字符串。"""
    pid = await factory.create_project()
    await async_client.put(
        "/api/settings/llm-defaults",
        headers=XHR_HEADERS,
        json={
            "provider_id": "deepseek",
            "base_url": "https://api.deepseek.com/v1",
            "model": "deepseek-v4-flash",
        },
    )
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
    assert body["model"]["source"] == "project"
    assert body["model"]["value"] == "custom-model"
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
async def test_project_context_materializes_effective_llm_without_env(
    async_client,
    db_session,
    factory,
    monkeypatch,
):
    monkeypatch.setenv("LLM_BASE_URL", "https://env.example/v1")
    monkeypatch.setenv("LLM_MODEL", "env-model")
    pid = await factory.create_project()

    context = await get_project_context(db_session, str(pid))

    assert context is not None
    assert context.settings["llm"]["provider_id"] == "deepseek"
    assert context.settings["llm"]["base_url"] == "https://api.deepseek.com"
    assert context.settings["llm"]["model"] == "deepseek-v4-flash"

    await async_client.put(
        "/api/settings/llm-defaults",
        headers=XHR_HEADERS,
        json={
            "provider_id": "kimi",
            "base_url": "https://api.moonshot.cn/v1",
            "model": "kimi-k2.6",
        },
    )
    context_with_global = await get_project_context(db_session, str(pid))

    assert context_with_global.settings["llm"]["provider_id"] == "kimi"
    assert context_with_global.settings["llm"]["base_url"] == "https://api.moonshot.cn/v1"
    assert context_with_global.settings["llm"]["model"] == "kimi-k2.6"
