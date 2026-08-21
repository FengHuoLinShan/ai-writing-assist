"""Settings API tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from httpx import AsyncClient

XHR_HEADERS = {"X-Requested-With": "XMLHttpRequest"}


@pytest.mark.asyncio
async def test_get_global_llm_defaults_missing_returns_200_null(  # noqa: E501
    async_client: AsyncClient,
):
    r = await async_client.get("/api/settings/llm-defaults")
    assert r.status_code == 200
    assert r.json() is None


@pytest.mark.asyncio
async def test_get_settings_does_not_require_xhr_header(async_client: AsyncClient):
    r = await async_client.get("/api/settings/author-preferences")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_put_global_llm_defaults_requires_xhr_header(
    raw_async_client: AsyncClient,
):
    r = await raw_async_client.put(
        "/api/settings/llm-defaults",
        json={"provider_id": "deepseek"},
    )
    assert r.status_code == 403
    assert r.json()["detail"] == "Missing X-Requested-With header"


@pytest.mark.asyncio
async def test_put_global_llm_defaults_rejects_api_key(async_client: AsyncClient):
    r = await async_client.put(
        "/api/settings/llm-defaults",
        headers=XHR_HEADERS,
        json={
            "provider_id": "deepseek",
            "api_key": "sk-leak",
        },
    )
    # Pydantic extra="forbid" 直接拒
    assert r.status_code in (400, 422)


@pytest.mark.asyncio
async def test_put_global_llm_defaults_round_trip(async_client: AsyncClient):
    r = await async_client.put(
        "/api/settings/llm-defaults",
        headers=XHR_HEADERS,
        json={
            "max_tokens": 8192,
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["provider_id"] is None
    assert body["max_tokens"] == 8192
    assert body["deep_import"] is None
    assert "api_key" not in body

    r2 = await async_client.get("/api/settings/llm-defaults")
    assert r2.status_code == 200
    assert r2.json()["provider_id"] is None
    assert r2.json()["max_tokens"] == 8192


@pytest.mark.asyncio
async def test_global_author_prefs_system_fallback_is_in_service(  # noqa: E501
    async_client: AsyncClient,
):
    # endpoint 直接返回 null（未配置）。system fallback 由 effective 接口处理（Task 5）
    r = await async_client.get("/api/settings/author-preferences")
    assert r.status_code == 200
    assert r.json() is None


@pytest.mark.asyncio
async def test_put_global_author_prefs_accepts_xhr_header(async_client: AsyncClient):
    r = await async_client.put(
        "/api/settings/author-preferences",
        headers=XHR_HEADERS,
        json={"daily_goal": 1200, "editor_font": "serif"},
    )
    assert r.status_code == 200
    assert r.json()["daily_goal"] == 1200


@pytest.mark.asyncio
async def test_project_author_prefs_missing_returns_empty_object(  # noqa: E501
    async_client: AsyncClient,
    factory,
):
    pid = await factory.create_project()
    r = await async_client.get(f"/api/settings/projects/{pid}/author-preferences")
    assert r.status_code == 200
    body = r.json()
    assert body == {"daily_goal": None, "editor_font": None, "default_focus_mode": None}


@pytest.mark.asyncio
async def test_project_author_prefs_field_reset_returns_400_for_unknown(  # noqa: E501
    async_client: AsyncClient,
    factory,
):
    pid = await factory.create_project()
    r = await async_client.delete(
        f"/api/settings/projects/{pid}/author-preferences/field/malicious_field",
        headers=XHR_HEADERS,
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_projects_using_defaults_lists_inheriting(  # noqa: E501
    async_client: AsyncClient,
    factory,
):
    p1 = await factory.create_project(title="a")
    await factory.create_project(title="b")
    await async_client.put(
        f"/api/settings/projects/{p1}/author-preferences",
        headers=XHR_HEADERS,
        json={
            "daily_goal": 1000,
            "editor_font": "serif",
            "default_focus_mode": True,
        },
    )
    # p1 全字段覆盖 → 不在列表；p2 全 NULL（行不存在）→ 在列表
    r = await async_client.get("/api/settings/projects-using-defaults")
    assert r.status_code == 200
    titles = [it["title"] for it in r.json()["items"]]
    assert "b" in titles
    assert "a" not in titles


@pytest.mark.asyncio
async def test_refresh_endpoint(async_client: AsyncClient):
    r = await async_client.post("/api/settings/refresh", headers=XHR_HEADERS)
    assert r.status_code == 200
    assert r.json() == {"ok": True}


@pytest.mark.asyncio
async def test_project_preferences_hide_recycled_project(
    async_client: AsyncClient,
    factory,
):
    pid = await factory.create_project(deleted_at=datetime.now(UTC))

    get_response = await async_client.get(
        f"/api/settings/projects/{pid}/author-preferences"
    )
    put_response = await async_client.put(
        f"/api/settings/projects/{pid}/author-preferences",
        headers=XHR_HEADERS,
        json={"daily_goal": 800},
    )
    delete_response = await async_client.delete(
        f"/api/settings/projects/{pid}/author-preferences/field/daily_goal",
        headers=XHR_HEADERS,
    )

    assert get_response.status_code == 404
    assert put_response.status_code == 404
    assert delete_response.status_code == 404


@pytest.mark.asyncio
async def test_global_settings_endpoints_remain_project_guard_exempt(
    async_client: AsyncClient,
):
    response = await async_client.get("/api/settings/llm-defaults")
    assert response.status_code == 200
