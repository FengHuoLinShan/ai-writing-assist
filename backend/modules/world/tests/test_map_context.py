"""MapContext 单元测试。

验证地图上下文守卫的三种不变量：
- novel_id 隔离（map / entity 属同 novel）
- hex 坐标在 grid 范围内
- entity 存在且类型符合预期
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from modules.world.map_models import MapConfig
from modules.world.models import CoreEntity
from modules.world.services.map_context import MapContext
from modules.world.tests.helpers import _create_entity, _create_map_config


@pytest.mark.asyncio
async def test_require_map_returns_config(
    db_session: AsyncSession,
    project_novel_id: str,
    world_map_config: MapConfig,
) -> None:
    ctx = MapContext()
    result = await ctx.require_map(db_session, project_novel_id, str(world_map_config.id))

    assert result.id == world_map_config.id
    assert result.novel_id == uuid.UUID(hex=project_novel_id)


@pytest.mark.asyncio
async def test_require_map_missing_returns_404(
    db_session: AsyncSession,
    project_novel_id: str,
) -> None:
    ctx = MapContext()

    with pytest.raises(HTTPException) as exc:
        await ctx.require_map(db_session, project_novel_id, uuid.uuid4().hex)
    assert exc.value.status_code == 404
    assert "不存在" in exc.value.detail


@pytest.mark.asyncio
async def test_require_map_cross_novel_returns_404(
    db_session: AsyncSession,
    two_projects: tuple[str, str],
    world_map_config: MapConfig,
) -> None:
    nid1, nid2 = two_projects
    ctx = MapContext()
    with pytest.raises(HTTPException) as exc:
        await ctx.require_map(db_session, nid2, str(world_map_config.id))
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_require_entity_returns_entity(
    db_session: AsyncSession,
    project_novel_id: str,
    location_entity_id: str,
) -> None:
    ctx = MapContext()
    result = await ctx.require_entity(db_session, project_novel_id, location_entity_id)

    assert result.id == uuid.UUID(hex=location_entity_id)


@pytest.mark.asyncio
async def test_require_entity_with_allowed_types(
    db_session: AsyncSession,
    project_novel_id: str,
    organization_entity_id: str,
) -> None:
    ctx = MapContext()
    result = await ctx.require_entity(
        db_session, project_novel_id, organization_entity_id, allowed_types={"organization"}
    )
    assert result.id == uuid.UUID(hex=organization_entity_id)

    with pytest.raises(HTTPException) as exc:
        await ctx.require_entity(
            db_session, project_novel_id, organization_entity_id, allowed_types={"location"}
        )
    assert exc.value.status_code == 400
    assert "organization" in exc.value.detail
    assert "location" in exc.value.detail


@pytest.mark.asyncio
async def test_require_entity_missing_returns_404(
    db_session: AsyncSession,
    project_novel_id: str,
) -> None:
    ctx = MapContext()

    with pytest.raises(HTTPException) as exc:
        await ctx.require_entity(db_session, project_novel_id, uuid.uuid4().hex)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_require_entity_cross_novel_returns_404(
    db_session: AsyncSession,
    two_projects: tuple[str, str],
) -> None:
    nid1, nid2 = two_projects

    entity = await _create_entity(db_session, nid1, "location")

    ctx = MapContext()
    with pytest.raises(HTTPException) as exc:
        await ctx.require_entity(db_session, nid2, str(entity.id))
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_assert_hex_in_bounds_passes(
    db_session: AsyncSession,
    project_novel_id: str,
) -> None:
    config = await _create_map_config(db_session, project_novel_id, grid_width=5, grid_height=5)

    ctx = MapContext()
    ctx.assert_hex_in_bounds(config, 0, 0)
    ctx.assert_hex_in_bounds(config, 4, 4)


@pytest.mark.asyncio
async def test_assert_hex_in_bounds_out_of_range_returns_400(
    db_session: AsyncSession,
    project_novel_id: str,
) -> None:
    config = await _create_map_config(db_session, project_novel_id, grid_width=5, grid_height=5)

    ctx = MapContext()

    with pytest.raises(HTTPException) as exc:
        ctx.assert_hex_in_bounds(config, 5, 0)
    assert exc.value.status_code == 400
    assert "hex_q" in exc.value.detail

    with pytest.raises(HTTPException) as exc:
        ctx.assert_hex_in_bounds(config, 0, 5)
    assert exc.value.status_code == 400
    assert "hex_r" in exc.value.detail
