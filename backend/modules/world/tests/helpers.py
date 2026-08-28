"""World 模块测试共享 helper 工厂函数。

非 pytest fixture 的普通 async 工厂，供需要精细控制 setup 的测试直接调用。
"""

from __future__ import annotations

import uuid

from httpx import AsyncClient, Response
from sqlalchemy.ext.asyncio import AsyncSession

from tests.utils import _create_entity as _create_entity
from tests.utils import _create_project as _create_project


async def publish_bible_draft(
    client: AsyncClient,
    novel_id: str,
    draft_id: str,
    *,
    expected_impact_scope_hash: str | None = None,
) -> Response:
    """Publish through the owner-confirmed canon adapter."""
    head = await client.get("/api/world/canon/head", params={"novel_id": novel_id})
    assert head.status_code == 200, head.text
    params = {
        "novel_id": novel_id,
        "expected_canon_head": head.json()["current_revision"]["id"],
        "canon_decision_id": str(uuid.uuid4()),
    }
    if expected_impact_scope_hash is not None:
        params["expected_impact_scope_hash"] = expected_impact_scope_hash
    return await client.post(f"/api/world/bible/drafts/{draft_id}/publish", params=params)


async def _create_location_entity(
    db_session: AsyncSession,
    novel_id: str,
    name: str = "洛阳",
) -> str:
    """创建一个 location 类型的 CoreEntity，返回 id。"""
    entity = await _create_entity(
        db_session,
        novel_id,
        entity_type="location",
        name=name,
        summary=f"{name}地点",
    )
    return str(entity.id)


async def _create_organization(
    db_session: AsyncSession,
    novel_id: str,
    name: str = "天机阁",
) -> str:
    """创建一个 organization 类型的 CoreEntity，返回 id。"""
    entity = await _create_entity(
        db_session,
        novel_id,
        entity_type="organization",
        name=name,
        summary=f"{name}组织",
    )
    return str(entity.id)
