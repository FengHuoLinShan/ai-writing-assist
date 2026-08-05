"""PostgreSQL visibility contracts for world API results consumed immediately."""

from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport
from sqlalchemy import select

from app.main import app
from core.database import get_manager
from infrastructure.tasks.models import AsyncTask
from modules.world import api as world_api
from modules.world import map_api
from modules.world.map_models import MapObservation
from modules.world.map_schemas import MapObservationCreate
from tests.support.http import XhrAsyncClient

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e]


async def _cleanup_project(client: XhrAsyncClient, project_id: str | None) -> None:
    if project_id is None:
        return
    await client.delete(f"/api/projects/{project_id}")
    await client.delete(
        f"/api/projects/{project_id}/permanent",
        params={"confirmed": True},
    )


async def test_map_observation_201_is_visible_before_follow_up_action() -> None:
    transport = ASGITransport(app=app)
    project_id: str | None = None

    async with XhrAsyncClient(transport=transport, base_url="http://test") as client:
        try:
            project_response = await client.post(
                "/api/projects",
                json={"title": "地图动态提交可见性测试"},
            )
            assert project_response.status_code == 201, project_response.text
            project_id = project_response.json()["id"]

            map_response = await client.post(
                "/api/world/maps",
                params={"novel_id": project_id},
                json={
                    "name": "事务可见性地图",
                    "map_type": "world",
                    "grid_width": 4,
                    "grid_height": 4,
                    "template": "blank",
                },
            )
            assert map_response.status_code == 201, map_response.text
            map_id = map_response.json()["id"]

            async with get_manager().session_factory() as writer:
                response = await map_api.create_map_observation(
                    writer,
                    map_id,
                    MapObservationCreate(
                        target_name="城门警戒",
                        dynamic_type="status",
                        value_json={
                            "schema_version": 1,
                            "type": "status",
                            "field_key": "警戒",
                            "value": "封锁",
                        },
                        source_ref={"source": "commit_visibility_test"},
                    ),
                    novel_id=project_id,
                )

                async with get_manager().session_factory() as observer:
                    persisted = await observer.scalar(
                        select(MapObservation).where(
                            MapObservation.id == uuid.UUID(response.id)
                        )
                    )

            assert persisted is not None
            assert str(persisted.novel_id) == project_id
            assert str(persisted.map_id) == map_id
            assert persisted.review_state == "candidate"
        finally:
            await _cleanup_project(client, project_id)


async def test_projection_refresh_task_is_visible_before_task_polling() -> None:
    transport = ASGITransport(app=app)
    project_id: str | None = None

    async with XhrAsyncClient(transport=transport, base_url="http://test") as client:
        try:
            project_response = await client.post(
                "/api/projects",
                json={"title": "世界书投影任务提交可见性测试"},
            )
            assert project_response.status_code == 201, project_response.text
            project_id = project_response.json()["id"]

            draft_response = await client.post(
                "/api/world/bible/drafts",
                json={
                    "novel_id": project_id,
                    "title": "北境贸易",
                    "page_type": "background",
                },
            )
            assert draft_response.status_code == 201, draft_response.text
            draft_id = draft_response.json()["id"]
            publish_response = await client.post(
                f"/api/world/bible/drafts/{draft_id}/publish",
                params={"novel_id": project_id},
            )
            assert publish_response.status_code == 200, publish_response.text
            page_id = publish_response.json()["id"]

            async with get_manager().session_factory() as writer:
                response = await world_api.refresh_bible_projection(
                    writer,
                    page_id,
                    novel_id=project_id,
                    projection_type="context_brief",
                    force=False,
                )

                async with get_manager().session_factory() as observer:
                    task = await observer.scalar(
                        select(AsyncTask).where(
                            AsyncTask.id == uuid.UUID(response.task_id)
                        )
                    )

            assert task is not None
            assert task.meta["novel_id"] == project_id
            assert task.task_type == "world_bible_projection_refresh"
            assert task.status == "pending"
        finally:
            await _cleanup_project(client, project_id)
