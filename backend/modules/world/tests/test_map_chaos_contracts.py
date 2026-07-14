"""Chaos-oriented contract tests for the world dynamics map."""

from __future__ import annotations

import re
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from modules.outline.facade import create_scene
from modules.world.tests.helpers import _create_entity, _create_project

UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    re.IGNORECASE,
)


async def _create_map(
    async_client: AsyncClient, novel_id: str, name: str = "九州"
) -> str:
    resp = await async_client.post(
        "/api/world/maps",
        params={"novel_id": novel_id},
        json={"name": name, "map_type": "world", "grid_width": 12, "grid_height": 8},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _observation(
    async_client: AsyncClient,
    novel_id: str,
    map_id: str,
    *,
    target_name: str,
    target_entity_type: str,
    dynamic_type: str,
    scene_id: str | None = None,
    scene_index: int = 1,
    confidence: float = 0.8,
    review_state: str | None = None,
    target_entity_id: str | None = None,
    spatial_anchor: dict | None = None,
) -> dict:
    payload = {
        "target_entity_id": target_entity_id,
        "target_entity_type": target_entity_type,
        "target_name": target_name,
        "dynamic_type": dynamic_type,
        "time_anchor": {
            "scene_id": scene_id,
            "scene_index": scene_index,
            "chapter_index": 1,
        },
        "spatial_anchor": spatial_anchor
        or {
            "hex_q": scene_index,
            "hex_r": scene_index,
            "location_name": f"地点 {scene_index}",
        },
        "value_json": {"state": dynamic_type, "label": target_name},
        "confidence": confidence,
        "source_ref": {
            "source": "chaos_fixture",
            "scene_id": scene_id,
            "chapter_index": 1,
        },
        "evidence_text": f"{target_name} 在 Scene {scene_index} 发生变化。",
        "scene_id": scene_id,
        "scene_index": scene_index,
    }
    if review_state is not None:
        payload["review_state"] = review_state
    resp = await async_client.post(
        f"/api/world/maps/{map_id}/observations",
        params={"novel_id": novel_id},
        json=payload,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest.mark.asyncio
async def test_chaos_dataset_preserves_candidate_fact_boundaries_and_author_labels(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    novel_id = uuid.uuid4().hex
    other_novel_id = uuid.uuid4().hex
    await _create_project(db_session, novel_id)
    await _create_project(db_session, other_novel_id)

    character = await _create_entity(
        db_session, novel_id, entity_type="character", name="沈砚", status="canonical"
    )
    await _create_entity(
        db_session, novel_id, entity_type="character", name="陆青", status="canonical"
    )
    await _create_entity(
        db_session, novel_id, entity_type="character", name="林照", status="canonical"
    )
    locations = [
        await _create_entity(
            db_session,
            novel_id,
            entity_type="location",
            name=name,
            status="canonical",
        )
        for name in ["九州", "洛阳外城", "东门", "城下密室"]
    ]
    await _create_entity(
        db_session, novel_id, entity_type="organization", name="北府", status="canonical"
    )
    await _create_entity(
        db_session,
        novel_id,
        entity_type="organization",
        name="天机阁",
        status="canonical",
    )

    map_id = await _create_map(async_client, novel_id)
    other_map_id = await _create_map(async_client, other_novel_id, "异界")

    binding = await async_client.post(
        f"/api/world/maps/{map_id}/location-bindings",
        params={"novel_id": novel_id},
        json={
            "location_entity_id": str(locations[1].id),
            "hexes": [{"hex_q": 2, "hex_r": 2, "is_center": True}],
        },
    )
    assert binding.status_code == 201, binding.text

    scenes = [
        await create_scene(
            db_session,
            novel_id,
            {
                "scene_index": index,
                "title": f"Scene {index}",
                "status": "canonical",
            },
        )
        for index in (1, 2, 3)
    ]
    scene_a, scene_b, scene_c = (item["id"] for item in scenes)
    high_confidence = await _observation(
        async_client,
        novel_id,
        map_id,
        target_entity_id=str(character.id),
        target_name="沈砚",
        target_entity_type="character",
        dynamic_type="position_change",
        scene_id=scene_a,
        scene_index=1,
        confidence=0.91,
        spatial_anchor={"hex_q": 2, "hex_r": 2, "location_name": "洛阳外城"},
    )
    low_confidence = await _observation(
        async_client,
        novel_id,
        map_id,
        target_name="暗门传闻",
        target_entity_type="secret",
        dynamic_type="secret",
        scene_id=scene_b,
        scene_index=2,
        confidence=0.21,
    )
    conflict = await _observation(
        async_client,
        novel_id,
        map_id,
        target_entity_id=str(character.id),
        target_name="沈砚",
        target_entity_type="character",
        dynamic_type="position_change",
        scene_id=scene_b,
        scene_index=2,
        confidence=0.77,
        review_state="conflicted",
        spatial_anchor={"hex_q": 9, "hex_r": 6, "location_name": "远山谷"},
    )
    crisis = await _observation(
        async_client,
        novel_id,
        map_id,
        target_name="洛阳封锁",
        target_entity_type="location",
        dynamic_type="crisis",
        scene_id=scene_c,
        scene_index=3,
        confidence=0.66,
        spatial_anchor={"hex_q": 2, "hex_r": 2, "location_name": "洛阳外城"},
    )

    dashboard = await async_client.get(
        f"/api/world/maps/{map_id}/dashboard",
        params={"novel_id": novel_id, "scene_id": scene_b},
    )
    assert dashboard.status_code == 200, dashboard.text
    scene_queue = dashboard.json()["dynamic_queue"]
    assert {item["title"] for item in scene_queue} == {"暗门传闻", "沈砚"}
    assert all(item["debug_ref"]["scene_id"] == scene_b for item in scene_queue)
    assert "暗门传闻" in dashboard.text
    assert "scene_id" in dashboard.text
    visible_text = " ".join(
        [
            item["title"]
            + item["type_label"]
            + item["time_label"]
            + item["status_label"]
            + item["source_summary"]
            for item in scene_queue
        ]
    )
    assert not UUID_RE.search(visible_text)

    confirm = await async_client.post(
        f"/api/world/maps/{map_id}/observations/{high_confidence['id']}/confirm",
        params={"novel_id": novel_id},
    )
    assert confirm.status_code == 200, confirm.text
    fact = confirm.json()

    ignored = await async_client.post(
        f"/api/world/maps/{map_id}/observations/{low_confidence['id']}/ignore",
        params={"novel_id": novel_id},
    )
    assert ignored.status_code == 200, ignored.text
    facts = await async_client.get(
        f"/api/world/maps/{map_id}/facts",
        params={"novel_id": novel_id},
    )
    assert facts.json()["total"] == 1
    assert facts.json()["items"][0]["target_name"] == "沈砚"

    batch = await async_client.post(
        f"/api/world/maps/{map_id}/batch-actions",
        params={"novel_id": novel_id},
        json={
            "action": "mark_conflicted",
            "observation_ids": [crisis["id"]],
        },
    )
    assert batch.status_code == 200, batch.text
    assert batch.json()["updated_count"] == 1

    rollback = await async_client.post(
        f"/api/world/maps/{map_id}/batch-actions",
        params={"novel_id": novel_id},
        json={
            "action": "update_fact_status",
            "fact_ids": [fact["id"]],
            "patch": {"fact_status": "rolled_back"},
        },
    )
    assert rollback.status_code == 200, rollback.text

    playback = await async_client.get(
        f"/api/world/maps/{map_id}/playback",
        params={"novel_id": novel_id, "include_candidates": False},
    )
    assert playback.status_code == 200, playback.text
    assert fact["id"] not in [event["event_id"] for event in playback.json()["events"]]

    open_target = await async_client.get(
        "/api/world/maps/open-target",
        params={"novel_id": novel_id, "focus_entity_id": str(locations[1].id)},
    )
    assert open_target.status_code == 200, open_target.text
    assert open_target.json()["map_id"] == map_id
    assert open_target.json()["focus_entity_id"] == str(locations[1].id)

    cross_novel = await async_client.post(
        f"/api/world/maps/{other_map_id}/batch-actions",
        params={"novel_id": other_novel_id},
        json={
            "action": "mark_conflicted",
            "observation_ids": [conflict["id"]],
        },
    )
    assert cross_novel.status_code == 404
