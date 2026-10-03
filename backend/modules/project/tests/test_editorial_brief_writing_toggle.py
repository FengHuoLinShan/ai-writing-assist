"""「编辑约定也用于 AI 写作」开关契约：PUT 返回与 GET 同口径的 effective。"""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_writing_toggle_put_reports_effective_state(
    async_client: AsyncClient,
) -> None:
    """首开时 effective 不继承旧值：约定非空即生效，为空则明示。"""
    created = await async_client.post("/api/projects", json={"title": "开关契约"})
    project_id = created.json()["id"]

    # 约定尚未保存：开启后 effective 仍为 false
    turned_on_before_brief = (
        await async_client.put(
            f"/api/projects/{project_id}/editorial-brief/for-writing",
            json={"enabled": True},
        )
    ).json()
    assert turned_on_before_brief == {"enabled": True, "effective": False}

    # 保存非空约定后重新开启：effective 为 true，不继承开启前的 false
    saved = await async_client.put(
        f"/api/projects/{project_id}/editorial-brief",
        json={"expected_version": 0, "brief": {"voice": "短句为主"}},
    )
    assert saved.status_code == 200
    await async_client.put(
        f"/api/projects/{project_id}/editorial-brief/for-writing",
        json={"enabled": False},
    )
    effective_on = (
        await async_client.put(
            f"/api/projects/{project_id}/editorial-brief/for-writing",
            json={"enabled": True},
        )
    ).json()
    assert effective_on == {"enabled": True, "effective": True}

    state = (
        await async_client.get(f"/api/projects/{project_id}/editorial-brief/for-writing")
    ).json()
    assert state["enabled"] is True
    assert state["effective"] is True
