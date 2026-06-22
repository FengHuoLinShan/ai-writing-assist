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

from modules.project.models import Project
from modules.world.map_models import MapConfig
from modules.world.models import CoreEntity
from modules.world.services.map_context import MapContext


async def _create_project(db_session: AsyncSession, novel_id: str) -> None:
    project = Project(
        id=uuid.UUID(hex=novel_id),
        title="测试项目",
        genre="fantasy",
        language="zh",
        target_length="novel",
        current_stage="worldbuilding",
    )
    db_session.add(project)
    await db_session.flush()


async def _create_map(
    db_session: AsyncSession,
    novel_id: str,
    *,
    grid_width: int = 10,
    grid_height: int = 10,
) -> MapConfig:
    config = MapConfig(
        id=uuid.uuid4(),
        novel_id=uuid.UUID(hex=novel_id),
        name="测试地图",
        map_type="world",
        grid_width=grid_width,
        grid_height=grid_height,
        hex_size=30,
        default_center_x=0.5,
        default_center_y=0.5,
        default_zoom=1.0,
        sort_order=0,
    )
    db_session.add(config)
    await db_session.flush()
    return config


async def _create_entity(
    db_session: AsyncSession,
    novel_id: str,
    entity_type: str,
    name: str = "测试实体",
) -> CoreEntity:
    entity = CoreEntity(
        id=uuid.uuid4(),
        novel_id=uuid.UUID(hex=novel_id),
        entity_type=entity_type,
        name=name,
        status="canonical",
    )
    db_session.add(entity)
    await db_session.flush()
    return entity


@pytest.mark.asyncio
async def test_require_map_returns_config(db_session: AsyncSession) -> None:
    nid = uuid.uuid4().hex
    await _create_project(db_session, nid)
    config = await _create_map(db_session, nid)

    ctx = MapContext()
    result = await ctx.require_map(db_session, nid, str(config.id))

    assert result.id == config.id
    assert result.novel_id == uuid.UUID(hex=nid)


@pytest.mark.asyncio
async def test_require_map_missing_returns_404(db_session: AsyncSession) -> None:
    nid = uuid.uuid4().hex
    await _create_project(db_session, nid)
    ctx = MapContext()

    with pytest.raises(HTTPException) as exc:
        await ctx.require_map(db_session, nid, uuid.uuid4().hex)
    assert exc.value.status_code == 404
    assert "不存在" in exc.value.detail


@pytest.mark.asyncio
async def test_require_map_cross_novel_returns_404(db_session: AsyncSession) -> None:
    nid1 = uuid.uuid4().hex
    nid2 = uuid.uuid4().hex
    await _create_project(db_session, nid1)
    await _create_project(db_session, nid2)
    config = await _create_map(db_session, nid1)

    ctx = MapContext()
    with pytest.raises(HTTPException) as exc:
        await ctx.require_map(db_session, nid2, str(config.id))
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_require_entity_returns_entity(db_session: AsyncSession) -> None:
    nid = uuid.uuid4().hex
    await _create_project(db_session, nid)
    entity = await _create_entity(db_session, nid, "location", name="洛阳")

    ctx = MapContext()
    result = await ctx.require_entity(db_session, nid, str(entity.id))

    assert result.id == entity.id


@pytest.mark.asyncio
async def test_require_entity_with_allowed_types(db_session: AsyncSession) -> None:
    nid = uuid.uuid4().hex
    await _create_project(db_session, nid)
    entity = await _create_entity(db_session, nid, "organization", name="天机阁")

    ctx = MapContext()
    result = await ctx.require_entity(
        db_session, nid, str(entity.id), allowed_types={"organization"}
    )
    assert result.id == entity.id

    with pytest.raises(HTTPException) as exc:
        await ctx.require_entity(
            db_session, nid, str(entity.id), allowed_types={"location"}
        )
    assert exc.value.status_code == 400
    assert "organization" in exc.value.detail
    assert "location" in exc.value.detail


@pytest.mark.asyncio
async def test_require_entity_missing_returns_404(db_session: AsyncSession) -> None:
    nid = uuid.uuid4().hex
    await _create_project(db_session, nid)
    ctx = MapContext()

    with pytest.raises(HTTPException) as exc:
        await ctx.require_entity(db_session, nid, uuid.uuid4().hex)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_require_entity_cross_novel_returns_404(db_session: AsyncSession) -> None:
    nid1 = uuid.uuid4().hex
    nid2 = uuid.uuid4().hex
    await _create_project(db_session, nid1)
    await _create_project(db_session, nid2)
    entity = await _create_entity(db_session, nid1, "location")

    ctx = MapContext()
    with pytest.raises(HTTPException) as exc:
        await ctx.require_entity(db_session, nid2, str(entity.id))
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_assert_hex_in_bounds_passes(db_session: AsyncSession) -> None:
    nid = uuid.uuid4().hex
    await _create_project(db_session, nid)
    config = await _create_map(db_session, nid, grid_width=5, grid_height=5)

    ctx = MapContext()
    ctx.assert_hex_in_bounds(config, 0, 0)
    ctx.assert_hex_in_bounds(config, 4, 4)


@pytest.mark.asyncio
async def test_assert_hex_in_bounds_out_of_range_returns_400(
    db_session: AsyncSession,
) -> None:
    nid = uuid.uuid4().hex
    await _create_project(db_session, nid)
    config = await _create_map(db_session, nid, grid_width=5, grid_height=5)

    ctx = MapContext()

    with pytest.raises(HTTPException) as exc:
        ctx.assert_hex_in_bounds(config, 5, 0)
    assert exc.value.status_code == 400
    assert "hex_q" in exc.value.detail

    with pytest.raises(HTTPException) as exc:
        ctx.assert_hex_in_bounds(config, 0, 5)
    assert exc.value.status_code == 400
    assert "hex_r" in exc.value.detail
