from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from modules.story.continuity.models import MemoryEvent
from modules.story.outline_state.models import Scene


@pytest.mark.asyncio
async def test_fact_timeline_http_filters_real_recorded_events_by_scene_and_source(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_project_id: str,
) -> None:
    novel_id = uuid.UUID(test_project_id)
    early_scene = Scene(
        novel_id=novel_id,
        scene_index=1,
        title="桥边相遇",
        chapter_ids=["1"],
        scene_chunks=[],
    )
    later_scene = Scene(
        novel_id=novel_id,
        scene_index=2,
        title="灯下回信",
        chapter_ids=["2"],
        scene_chunks=[],
    )
    entity_id = uuid.uuid4()
    db_session.add_all([early_scene, later_scene])
    await db_session.flush()
    db_session.add_all(
        [
            MemoryEvent(
                novel_id=novel_id,
                chapter_index=1,
                sequence=1,
                scene_id=early_scene.id,
                scene_index=1,
                scene_sequence=1,
                event_type="entity_updated",
                entity_type="character",
                entity_id=entity_id,
                snapshot_after={"name": "阿蘅", "state": "拿到钥匙"},
                source="author",
                created_at=datetime(2026, 10, 16, 1, 0, tzinfo=UTC),
            ),
            MemoryEvent(
                novel_id=novel_id,
                chapter_index=2,
                sequence=1,
                scene_id=later_scene.id,
                scene_index=2,
                scene_sequence=1,
                event_type="entity_updated",
                entity_type="character",
                entity_id=entity_id,
                snapshot_after={"name": "阿蘅", "state": "点亮灯塔"},
                source="author",
                created_at=datetime(2026, 10, 16, 2, 0, tzinfo=UTC),
            ),
        ]
    )
    await db_session.flush()

    response = await async_client.get(
        f"/api/novels/{test_project_id}/memories/fact-timeline",
        params={
            "entity_id": str(entity_id),
            "cutoff_scene_id": str(early_scene.id),
            "source": "author",
            "status": "current",
            "skip": 0,
            "limit": 1,
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["consumer_scope"] == "author"
    assert body["cutoff_scene"]["scene_id"] == str(early_scene.id)
    assert body["total"] == 1
    assert len(body["items"]) == 1
    assert body["items"][0]["snapshot_after"]["state"] == "拿到钥匙"
    assert body["items"][0]["current_scene_index"] == 1
    assert body["items"][0]["current_chapter_index"] == 1
    assert body["items"][0]["time_status"] == "current"

    next_page = await async_client.get(
        f"/api/novels/{test_project_id}/memories/fact-timeline",
        params={"entity_id": str(entity_id), "source": "author", "skip": 1, "limit": 1},
    )
    assert next_page.status_code == 200, next_page.text
    assert next_page.json()["total"] == 2
    assert len(next_page.json()["items"]) == 1
    assert next_page.json()["items"][0]["snapshot_after"]["state"] == "点亮灯塔"
