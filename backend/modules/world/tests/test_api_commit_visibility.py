"""Route-level commit contracts for immediately consumed world API results."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import DomainError
from modules.world import api as world_api
from modules.world import map_api
from modules.world.map_schemas import MapObservationCreate


@pytest.mark.asyncio
async def test_map_observation_commits_before_returning_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    expected = object()

    async def create_observation(*_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
        events.append("service-finished")
        return expected

    async def commit() -> None:
        events.append("committed")

    db = AsyncMock(spec=AsyncSession)
    db.commit.side_effect = commit
    monkeypatch.setattr(
        map_api,
        "_dynamic_fact_service",
        SimpleNamespace(create_observation=create_observation),
    )

    result = await map_api.create_map_observation(
        db,
        "map-id",
        MapObservationCreate(
            dynamic_type="status",
            value_json={
                "schema_version": 1,
                "type": "status",
                "field_key": "警戒",
                "value": "封锁",
            },
        ),
        novel_id="novel-id",
    )

    assert result is expected
    assert events == ["service-finished", "committed"]
    db.rollback.assert_not_awaited()


@pytest.mark.asyncio
async def test_map_observation_commit_failure_rolls_back_with_safe_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        map_api,
        "_dynamic_fact_service",
        SimpleNamespace(create_observation=AsyncMock(return_value=object())),
    )
    db = AsyncMock(spec=AsyncSession)
    db.commit.side_effect = RuntimeError("postgres password=should-not-leak")

    with pytest.raises(DomainError) as captured:
        await map_api.create_map_observation(
            db,
            "map-id",
            MapObservationCreate(
                dynamic_type="status",
                value_json={
                    "schema_version": 1,
                    "type": "status",
                    "field_key": "警戒",
                    "value": "封锁",
                },
            ),
            novel_id="novel-id",
        )

    assert captured.value.code == "map_observation_commit_failed"
    assert captured.value.status_code == 500
    assert captured.value.message == "地图动态保存失败，请重试"
    assert "password" not in captured.value.message
    db.rollback.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_projection_refresh_commits_before_returning_task_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    async def refresh_projection_task(*_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
        events.append("service-finished")
        return "task-id", "pending", False

    async def commit() -> None:
        events.append("committed")

    db = AsyncMock(spec=AsyncSession)
    db.commit.side_effect = commit
    monkeypatch.setattr(
        world_api,
        "_bible_service",
        SimpleNamespace(refresh_projection_task=refresh_projection_task),
    )

    result = await world_api.refresh_bible_projection(
        db,
        "page-id",
        novel_id="novel-id",
        projection_type="context_brief",
        force=False,
    )

    assert result.task_id == "task-id"
    assert result.status == "pending"
    assert result.existing is False
    assert events == ["service-finished", "committed"]
    db.rollback.assert_not_awaited()


@pytest.mark.asyncio
async def test_projection_refresh_commit_failure_rolls_back_with_safe_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        world_api,
        "_bible_service",
        SimpleNamespace(
            refresh_projection_task=AsyncMock(return_value=("task-id", "pending", False))
        ),
    )
    db = AsyncMock(spec=AsyncSession)
    db.commit.side_effect = RuntimeError("postgres password=should-not-leak")

    with pytest.raises(DomainError) as captured:
        await world_api.refresh_bible_projection(
            db,
            "page-id",
            novel_id="novel-id",
            projection_type="context_brief",
            force=False,
        )

    assert captured.value.code == "world_bible_projection_commit_failed"
    assert captured.value.status_code == 500
    assert captured.value.message == "投影刷新任务保存失败，请重试"
    assert "password" not in captured.value.message
    db.rollback.assert_awaited_once_with()
