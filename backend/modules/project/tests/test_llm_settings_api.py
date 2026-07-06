"""
Project LLM settings API tests.

These tests pin the user-facing contract: provider templates are exposed for the
console, while stored API keys are write-only and never echoed in project
responses.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient


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
async def test_update_and_get_project_llm_settings_masks_api_key(
    async_client: AsyncClient,
    sample_project: dict,
) -> None:
    pid = sample_project["id"]

    resp = await async_client.put(
        f"/api/projects/{pid}/llm-settings",
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
async def test_update_project_llm_settings_preserves_existing_key_when_empty(
    async_client: AsyncClient,
    sample_project: dict,
) -> None:
    pid = sample_project["id"]
    first = await async_client.put(
        f"/api/projects/{pid}/llm-settings",
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
