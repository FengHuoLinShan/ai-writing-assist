"""
Writing API 层测试

验证 HTTP 契约：多 Tab 冲突检测、获取草稿、版本历史等。
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.fixture
async def sample_draft(async_client: AsyncClient):
    project_resp = await async_client.post(
        "/api/projects",
        json={"title": "冲突测试项目"},
    )
    assert project_resp.status_code == 201
    novel_id = project_resp.json()["id"]

    resp = await async_client.post(
        "/api/writing/drafts",
        json={
            "novel_id": novel_id,
            "chapter_index": 1,
            "title": "v1 标题",
            "content": "v1 内容",
        },
    )
    assert resp.status_code == 201
    return resp.json()["draft"]


@pytest.mark.asyncio
async def test_update_draft_conflict_on_stale_updated_at(
    async_client: AsyncClient,
    sample_draft: dict,
) -> None:
    """Tab A 暂存后，Tab B 使用旧的 expected_updated_at 应收到 409"""
    draft_id = sample_draft["id"]
    novel_id = sample_draft["novel_id"]
    stale_updated_at = sample_draft["updated_at"]

    # Tab A 暂存
    resp = await async_client.put(
        f"/api/writing/drafts/{draft_id}?novel_id={novel_id}",
        json={
            "title": "Tab A 标题",
            "content": "Tab A 内容",
            "expected_updated_at": stale_updated_at,
        },
    )
    assert resp.status_code == 200

    # Tab B 仍使用旧的 expected_updated_at 保存
    resp = await async_client.put(
        f"/api/writing/drafts/{draft_id}?novel_id={novel_id}",
        json={
            "title": "Tab B 标题",
            "content": "Tab B 内容",
            "expected_updated_at": stale_updated_at,
        },
    )
    assert resp.status_code == 409
