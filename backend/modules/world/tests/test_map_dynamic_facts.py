"""Map dynamic fact P0 tests."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from modules.world.tests.helpers import _create_entity, _create_project


@pytest.mark.asyncio
async def test_map_observation_confirm_flow_keeps_candidate_until_confirmed(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    nid = uuid.uuid4().hex
    await _create_project(db_session, nid)
    character = await _create_entity(
        db_session,
        nid,
        entity_type="character",
        name="沈砚",
        status="canonical",
    )
    map_resp = await async_client.post(
        "/api/world/maps",
        params={"novel_id": nid},
        json={"name": "九州", "map_type": "world", "grid_width": 8, "grid_height": 8},
    )
    map_id = map_resp.json()["id"]

    create_resp = await async_client.post(
        f"/api/world/maps/{map_id}/observations",
        params={"novel_id": nid},
        json={
            "target_entity_id": str(character.id),
            "target_entity_type": "character",
            "target_name": "沈砚",
            "dynamic_type": "location",
            "time_anchor": {"scene_index": 42},
            "spatial_anchor": {"hex_q": 2, "hex_r": 3},
            "value_json": {"state": "arrived"},
            "confidence": 0.82,
            "source_ref": {"source": "deep_import", "chapter_index": 12},
            "evidence_text": "沈砚穿过东门。",
            "scene_index": 42,
            "source_chapter_index": 12,
        },
    )
    assert create_resp.status_code == 201, create_resp.text
    observation = create_resp.json()
    assert observation["review_state"] == "candidate"
    assert observation["target_name"] == "沈砚"
    assert observation["source_ref"]["source"] == "deep_import"

    facts_before = await async_client.get(
        f"/api/world/maps/{map_id}/facts",
        params={"novel_id": nid},
    )
    assert facts_before.status_code == 200
    assert facts_before.json()["total"] == 0

    confirm_resp = await async_client.post(
        f"/api/world/maps/{map_id}/observations/{observation['id']}/confirm",
        params={"novel_id": nid},
    )
    assert confirm_resp.status_code == 200, confirm_resp.text
    fact = confirm_resp.json()
    assert fact["observation_id"] == observation["id"]
    assert fact["target_name"] == "沈砚"
    assert fact["dynamic_type"] == "location"
    assert fact["fact_status"] == "confirmed"

    observations = await async_client.get(
        f"/api/world/maps/{map_id}/observations",
        params={"novel_id": nid, "review_state": "confirmed"},
    )
    assert observations.status_code == 200
    assert observations.json()["total"] == 1
    assert observations.json()["items"][0]["review_state"] == "confirmed"


@pytest.mark.asyncio
async def test_map_observation_can_be_ignored_without_creating_fact(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    nid = uuid.uuid4().hex
    await _create_project(db_session, nid)
    map_resp = await async_client.post(
        "/api/world/maps",
        params={"novel_id": nid},
        json={"name": "九州", "map_type": "world", "grid_width": 4, "grid_height": 4},
    )
    map_id = map_resp.json()["id"]
    create_resp = await async_client.post(
        f"/api/world/maps/{map_id}/observations",
        params={"novel_id": nid},
        json={
            "target_name": "可疑封锁",
            "dynamic_type": "crisis",
            "confidence": 0.3,
            "source_ref": {"source": "draft_analysis"},
        },
    )
    observation_id = create_resp.json()["id"]

    ignore_resp = await async_client.post(
        f"/api/world/maps/{map_id}/observations/{observation_id}/ignore",
        params={"novel_id": nid},
    )
    assert ignore_resp.status_code == 200
    assert ignore_resp.json()["review_state"] == "ignored"

    facts = await async_client.get(
        f"/api/world/maps/{map_id}/facts",
        params={"novel_id": nid},
    )
    assert facts.json()["total"] == 0


@pytest.mark.asyncio
async def test_dashboard_includes_candidate_queue_inspector_and_batch_groups(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    nid = uuid.uuid4().hex
    await _create_project(db_session, nid)
    map_resp = await async_client.post(
        "/api/world/maps",
        params={"novel_id": nid},
        json={"name": "九州", "map_type": "world", "grid_width": 4, "grid_height": 4},
    )
    map_id = map_resp.json()["id"]

    from modules.world.services.map_service import MapDynamicFactService

    await MapDynamicFactService().create_observation_from_delta_event(
        db_session,
        nid,
        event={
            "category": "CRISIS_SPREAD",
            "field": "city_state",
            "old": "open",
            "new": "blocked",
            "meta": {
                "dynamic_type": "crisis",
                "target_name": "洛阳外城",
                "target_entity_type": "location",
                "confidence": 0.41,
                "evidence_text": "城门忽然封闭。",
            },
        },
        scene_index=12,
        context_snapshot_id="snapshot-1",
        delta_log_id="delta-1",
    )
    create_resp = await async_client.post(
        f"/api/world/maps/{map_id}/observations",
        params={"novel_id": nid},
        json={
            "target_name": "偏门哨塔",
            "target_entity_type": "location",
            "dynamic_type": "position_change",
            "confidence": 0.6,
            "source_ref": {"source": "manual_test"},
            "evidence_text": "偏门哨塔亮起火光。",
            "scene_index": 13,
        },
    )
    assert create_resp.status_code == 201, create_resp.text

    resp = await async_client.get(
        f"/api/world/maps/{map_id}/dashboard",
        params={"novel_id": nid},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["mode"] == "dashboard"
    assert body["title"] == "世界动态总控台"
    assert body["dynamic_queue"][0]["title"] == "洛阳外城"
    assert body["dynamic_queue"][0]["item_kind"] == "observation"
    assert body["dynamic_queue"][0]["status_label"] == "待确认"
    assert body["dynamic_queue"][0]["risk_level"] == "danger"
    assert body["first_visual_layer"]["main_crisis"] == "洛阳外城"
    assert body["inspector"]["ai_candidates"][0]["title"] == "洛阳外城"
    assert body["batch_groups"][0]["group_label"] == "地点"
    assert "洛阳外城：待确认" in body["risk_summary"]

    facts = await async_client.get(
        f"/api/world/maps/{map_id}/facts",
        params={"novel_id": nid},
    )
    assert facts.json()["total"] == 0

    focus_item_id = next(
        item["item_id"] for item in body["dynamic_queue"] if item["title"] == "偏门哨塔"
    )
    focused = await async_client.get(
        f"/api/world/maps/{map_id}/dashboard",
        params={"novel_id": nid, "focus_item_id": focus_item_id},
    )
    assert focused.status_code == 200, focused.text
    focused_body = focused.json()
    assert focused_body["inspector"]["title"] == "偏门哨塔"
    assert focused_body["inspector"]["ai_candidates"][0]["item_id"] == focus_item_id


@pytest.mark.asyncio
async def test_dashboard_formats_deep_import_delta_candidates_for_authors(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    nid = uuid.uuid4().hex
    await _create_project(db_session, nid)
    map_resp = await async_client.post(
        "/api/world/maps",
        params={"novel_id": nid},
        json={"name": "廷根", "map_type": "world", "grid_width": 4, "grid_height": 4},
    )
    map_id = map_resp.json()["id"]

    from modules.world.services.map_service import MapDynamicFactService

    await MapDynamicFactService().create_observation_from_delta_event(
        db_session,
        nid,
        event={
            "category": "ENTITY_CREATED",
            "field": "entities[4]",
            "old": None,
            "new": {
                "entity_type": "concept",
                "name": "公务员考试制度",
                "summary": "克莱恩在塔罗会提出的政治改革方案。",
            },
            "meta": {
                "dynamic_type": "entity_created",
                "target_name": "entity_created",
                "confidence": 0.5,
            },
        },
        scene_index=0,
        context_snapshot_id="snapshot-entity",
        delta_log_id="delta-entity",
    )

    resp = await async_client.get(
        f"/api/world/maps/{map_id}/dashboard",
        params={"novel_id": nid},
    )

    assert resp.status_code == 200, resp.text
    item = resp.json()["dynamic_queue"][0]
    assert item["title"] == "公务员考试制度"
    assert item["object_type"] == "concept"
    assert item["type_label"] == "概念"
    assert (
        item["source_summary"]
        == "deep_import_delta_event · 对象候选：公务员考试制度（concept）："
        "克莱恩在塔罗会提出的政治改革方案。"
    )
    assert "entities[4]" not in item["source_summary"]
    assert "{" not in item["source_summary"]

    playback_resp = await async_client.get(
        f"/api/world/maps/{map_id}/playback",
        params={"novel_id": nid},
    )
    assert playback_resp.status_code == 200, playback_resp.text
    event = playback_resp.json()["events"][0]
    assert event["title"] == "公务员考试制度"
    assert event["change_summary"] == (
        "对象候选：公务员考试制度（concept）："
        "克莱恩在塔罗会提出的政治改革方案。"
    )


@pytest.mark.asyncio
async def test_dashboard_uses_scalar_delta_candidate_as_title(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    nid = uuid.uuid4().hex
    await _create_project(db_session, nid)
    map_resp = await async_client.post(
        "/api/world/maps",
        params={"novel_id": nid},
        json={"name": "廷根", "map_type": "world", "grid_width": 4, "grid_height": 4},
    )
    map_id = map_resp.json()["id"]

    from modules.world.services.map_service import MapDynamicFactService

    await MapDynamicFactService().create_observation_from_delta_event(
        db_session,
        nid,
        event={
            "category": "ENTITY_CREATED",
            "field": "entities",
            "old": None,
            "new": "离奇自杀事件",
            "meta": {
                "dynamic_type": "entity_created",
                "confidence": 0.5,
            },
        },
        scene_index=0,
        context_snapshot_id="snapshot-scalar-entity",
        delta_log_id="delta-scalar-entity",
    )

    resp = await async_client.get(
        f"/api/world/maps/{map_id}/dashboard",
        params={"novel_id": nid},
    )

    assert resp.status_code == 200, resp.text
    item = resp.json()["dynamic_queue"][0]
    assert item["title"] == "离奇自杀事件"
    assert item["source_summary"] == "deep_import_delta_event · 对象候选：离奇自杀事件"

    playback_resp = await async_client.get(
        f"/api/world/maps/{map_id}/playback",
        params={"novel_id": nid},
    )
    assert playback_resp.status_code == 200, playback_resp.text
    assert playback_resp.json()["events"][0]["title"] == "离奇自杀事件"


@pytest.mark.asyncio
async def test_dashboard_uses_named_delta_field_as_title(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    nid = uuid.uuid4().hex
    await _create_project(db_session, nid)
    map_resp = await async_client.post(
        "/api/world/maps",
        params={"novel_id": nid},
        json={"name": "廷根", "map_type": "world", "grid_width": 4, "grid_height": 4},
    )
    map_id = map_resp.json()["id"]

    from modules.world.services.map_service import MapDynamicFactService

    await MapDynamicFactService().create_observation_from_delta_event(
        db_session,
        nid,
        event={
            "category": "ENTITY_CREATED",
            "field": "序列途径",
            "old": None,
            "new": {
                "summary": "魔药序列的晋升途径，每途径有多个序列。",
            },
            "meta": {
                "dynamic_type": "entity_created",
                "confidence": 0.5,
            },
        },
        scene_index=0,
        context_snapshot_id="snapshot-field-entity",
        delta_log_id="delta-field-entity",
    )

    resp = await async_client.get(
        f"/api/world/maps/{map_id}/dashboard",
        params={"novel_id": nid},
    )

    assert resp.status_code == 200, resp.text
    item = resp.json()["dynamic_queue"][0]
    assert item["title"] == "序列途径"
    assert item["object_type"] == "entity_candidate"
    assert item["type_label"] == "对象候选"
    assert item["source_summary"] == (
        "deep_import_delta_event · 序列途径：summary："
        "魔药序列的晋升途径，每途径有多个序列。"
    )


@pytest.mark.asyncio
async def test_dashboard_uses_scalar_when_delta_field_is_technical(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    nid = uuid.uuid4().hex
    await _create_project(db_session, nid)
    map_resp = await async_client.post(
        "/api/world/maps",
        params={"novel_id": nid},
        json={"name": "廷根", "map_type": "world", "grid_width": 4, "grid_height": 4},
    )
    map_id = map_resp.json()["id"]

    from modules.world.services.map_service import MapDynamicFactService

    await MapDynamicFactService().create_observation_from_delta_event(
        db_session,
        nid,
        event={
            "category": "ENTITY_CREATED",
            "field": "entity",
            "old": None,
            "new": "占卜家扮演法",
            "meta": {
                "dynamic_type": "entity_created",
                "confidence": 0.5,
            },
        },
        scene_index=0,
        context_snapshot_id="snapshot-technical-field",
        delta_log_id="delta-technical-field",
    )

    resp = await async_client.get(
        f"/api/world/maps/{map_id}/dashboard",
        params={"novel_id": nid},
    )

    assert resp.status_code == 200, resp.text
    item = resp.json()["dynamic_queue"][0]
    assert item["title"] == "占卜家扮演法"
    assert item["type_label"] == "对象候选"


@pytest.mark.asyncio
async def test_dashboard_formats_entity_updated_delta_title(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    nid = uuid.uuid4().hex
    await _create_project(db_session, nid)
    map_resp = await async_client.post(
        "/api/world/maps",
        params={"novel_id": nid},
        json={"name": "廷根", "map_type": "world", "grid_width": 4, "grid_height": 4},
    )
    map_id = map_resp.json()["id"]

    from modules.world.services.map_service import MapDynamicFactService

    await MapDynamicFactService().create_observation_from_delta_event(
        db_session,
        nid,
        event={
            "category": "ENTITY_UPDATED",
            "field": "普利兹号的状态",
            "old": "未下水",
            "new": "已下水并试射",
            "meta": {
                "dynamic_type": "entity_updated",
                "confidence": 0.5,
            },
        },
        scene_index=0,
        context_snapshot_id="snapshot-updated-field",
        delta_log_id="delta-updated-field",
    )

    resp = await async_client.get(
        f"/api/world/maps/{map_id}/dashboard",
        params={"novel_id": nid},
    )

    assert resp.status_code == 200, resp.text
    item = resp.json()["dynamic_queue"][0]
    assert item["title"] == "普利兹号的状态"
    assert item["object_type"] == "entity_candidate"
    assert item["type_label"] == "对象候选"
    assert item["source_summary"] == (
        "deep_import_delta_event · 普利兹号的状态：未下水 → 已下水并试射"
    )


@pytest.mark.asyncio
async def test_dashboard_deduplicates_confirmed_observations_and_main_characters(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    nid = uuid.uuid4().hex
    await _create_project(db_session, nid)
    character = await _create_entity(
        db_session,
        nid,
        entity_type="character",
        name="沈砚",
        status="canonical",
    )
    map_resp = await async_client.post(
        "/api/world/maps",
        params={"novel_id": nid},
        json={"name": "九州", "map_type": "world", "grid_width": 6, "grid_height": 6},
    )
    map_id = map_resp.json()["id"]

    character_obs = await async_client.post(
        f"/api/world/maps/{map_id}/observations",
        params={"novel_id": nid},
        json={
            "target_entity_id": str(character.id),
            "target_entity_type": "character",
            "target_name": "沈砚",
            "dynamic_type": "position_change",
            "confidence": 0.82,
            "scene_index": 1,
        },
    )
    assert character_obs.status_code == 201, character_obs.text
    await async_client.post(
        f"/api/world/maps/{map_id}/observations/{character_obs.json()['id']}/confirm",
        params={"novel_id": nid},
    )

    location_obs = await async_client.post(
        f"/api/world/maps/{map_id}/observations",
        params={"novel_id": nid},
        json={
            "target_entity_type": "location",
            "target_name": "洛阳外城",
            "dynamic_type": "location",
            "confidence": 0.7,
            "scene_index": 2,
        },
    )
    assert location_obs.status_code == 201, location_obs.text

    resp = await async_client.get(
        f"/api/world/maps/{map_id}/dashboard",
        params={"novel_id": nid},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    queue = body["dynamic_queue"]
    assert [item["title"] for item in queue].count("沈砚") == 1
    assert next(item for item in queue if item["title"] == "沈砚")["item_kind"] == "fact"
    assert "沈砚" in body["first_visual_layer"]["main_characters"]
    assert "洛阳外城" not in body["first_visual_layer"]["main_characters"]


@pytest.mark.asyncio
async def test_dashboard_focus_entity_scopes_inspector(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    nid = uuid.uuid4().hex
    await _create_project(db_session, nid)
    shen = await _create_entity(
        db_session,
        nid,
        entity_type="character",
        name="沈砚",
        status="canonical",
    )
    lin = await _create_entity(
        db_session,
        nid,
        entity_type="character",
        name="林照",
        status="canonical",
    )
    map_resp = await async_client.post(
        "/api/world/maps",
        params={"novel_id": nid},
        json={"name": "九州", "map_type": "world", "grid_width": 6, "grid_height": 6},
    )
    map_id = map_resp.json()["id"]

    for entity, name in [(shen, "沈砚"), (lin, "林照")]:
        resp = await async_client.post(
            f"/api/world/maps/{map_id}/observations",
            params={"novel_id": nid},
            json={
                "target_entity_id": str(entity.id),
                "target_entity_type": "character",
                "target_name": name,
                "dynamic_type": "position_change",
                "confidence": 0.72,
                "scene_index": 3,
                "evidence_text": f"{name}进入内城。",
            },
        )
        assert resp.status_code == 201, resp.text

    focused = await async_client.get(
        f"/api/world/maps/{map_id}/dashboard",
        params={"novel_id": nid, "focus_entity_id": str(shen.id)},
    )
    assert focused.status_code == 200, focused.text
    inspector = focused.json()["inspector"]
    assert inspector["focus_entity_id"] == str(shen.id)
    assert inspector["object_name"] == "沈砚"
    assert [item["title"] for item in inspector["related_dynamics"]] == ["沈砚"]
    assert inspector["timeline"][0]["title"] == "沈砚"
    assert "林照" not in focused.text


@pytest.mark.asyncio
async def test_open_target_resolves_focus_entity_to_map_context(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    nid = uuid.uuid4().hex
    await _create_project(db_session, nid)
    location = await _create_entity(
        db_session,
        nid,
        entity_type="location",
        name="洛阳外城",
        status="canonical",
    )
    map_resp = await async_client.post(
        "/api/world/maps",
        params={"novel_id": nid},
        json={"name": "九州", "map_type": "world", "grid_width": 6, "grid_height": 6},
    )
    map_id = map_resp.json()["id"]
    bind_resp = await async_client.post(
        f"/api/world/maps/{map_id}/location-bindings",
        params={"novel_id": nid},
        json={
            "location_entity_id": str(location.id),
            "hexes": [{"hex_q": 2, "hex_r": 3, "is_center": True}],
        },
    )
    assert bind_resp.status_code == 201, bind_resp.text

    target = await async_client.get(
        "/api/world/maps/open-target",
        params={"novel_id": nid, "focus_entity_id": str(location.id)},
    )

    assert target.status_code == 200, target.text
    assert target.json() == {
        "mode": "map",
        "map_id": map_id,
        "scene_id": None,
        "focus_entity_id": str(location.id),
        "observation_id": None,
        "fallback_reason": None,
        "fallback_message": None,
    }


@pytest.mark.asyncio
async def test_open_target_falls_back_with_visible_message(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    nid = uuid.uuid4().hex
    await _create_project(db_session, nid)
    entity = await _create_entity(
        db_session,
        nid,
        entity_type="character",
        name="沈砚",
        status="canonical",
    )

    target = await async_client.get(
        "/api/world/maps/open-target",
        params={"novel_id": nid, "focus_entity_id": str(entity.id)},
    )

    assert target.status_code == 200, target.text
    body = target.json()
    assert body["mode"] == "recent"
    assert body["map_id"] is None
    assert body["focus_entity_id"] == str(entity.id)
    assert body["fallback_reason"] == "focus_without_map"
    assert body["fallback_message"] == "该对象暂无地图位置，已回退到最近地图"


@pytest.mark.asyncio
async def test_dashboard_scene_filter_and_object_labels_are_author_facing(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    nid = uuid.uuid4().hex
    await _create_project(db_session, nid)
    map_resp = await async_client.post(
        "/api/world/maps",
        params={"novel_id": nid},
        json={"name": "九州", "map_type": "world", "grid_width": 6, "grid_height": 6},
    )
    map_id = map_resp.json()["id"]
    scene_a = uuid.uuid4()
    scene_b = uuid.uuid4()

    for scene_id, name, scene_index in [
        (scene_a, "东门封锁", 1),
        (scene_b, "北境叛乱", 2),
    ]:
        resp = await async_client.post(
            f"/api/world/maps/{map_id}/observations",
            params={"novel_id": nid},
            json={
                "scene_id": str(scene_id),
                "target_entity_type": "event",
                "target_name": name,
                "dynamic_type": "crisis",
                "time_anchor": {"scene_index": scene_index},
                "spatial_anchor": {"hex_q": scene_index, "hex_r": scene_index + 1},
                "source_ref": {"source": "scene_summary"},
                "confidence": 0.44,
                "scene_index": scene_index,
            },
        )
        assert resp.status_code == 201, resp.text

    dashboard = await async_client.get(
        f"/api/world/maps/{map_id}/dashboard",
        params={"novel_id": nid, "scene_id": str(scene_a)},
    )

    assert dashboard.status_code == 200, dashboard.text
    body = dashboard.json()
    assert [item["title"] for item in body["dynamic_queue"]] == ["东门封锁"]
    item = body["dynamic_queue"][0]
    assert item["type_label"] == "事件"
    assert item["spatial_anchor_label"] == "坐标 1,2"
    assert item["debug_ref"]["id"] == item["item_id"]
    assert body["first_visual_layer"]["current_scene_events"] == ["东门封锁"]
    assert body["first_visual_layer"]["current_storyline"] == "Scene 1"


@pytest.mark.asyncio
async def test_observation_review_rejects_cross_map_and_public_confirmed_create(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    nid = uuid.uuid4().hex
    await _create_project(db_session, nid)
    map_a = await async_client.post(
        "/api/world/maps",
        params={"novel_id": nid},
        json={"name": "九州", "map_type": "world", "grid_width": 6, "grid_height": 6},
    )
    map_b = await async_client.post(
        "/api/world/maps",
        params={"novel_id": nid},
        json={"name": "北境", "map_type": "world", "grid_width": 6, "grid_height": 6},
    )
    map_a_id = map_a.json()["id"]
    map_b_id = map_b.json()["id"]

    rejected = await async_client.post(
        f"/api/world/maps/{map_a_id}/observations",
        params={"novel_id": nid},
        json={
            "target_name": "直接确认",
            "dynamic_type": "location",
            "review_state": "confirmed",
        },
    )
    assert rejected.status_code == 422

    created = await async_client.post(
        f"/api/world/maps/{map_a_id}/observations",
        params={"novel_id": nid},
        json={"target_name": "沈砚", "dynamic_type": "location"},
    )
    assert created.status_code == 201, created.text
    observation_id = created.json()["id"]

    patch_resp = await async_client.patch(
        f"/api/world/maps/{map_b_id}/observations/{observation_id}",
        params={"novel_id": nid},
        json={"review_state": "conflicted"},
    )
    assert patch_resp.status_code == 404

    ignore_resp = await async_client.post(
        f"/api/world/maps/{map_b_id}/observations/{observation_id}/ignore",
        params={"novel_id": nid},
    )
    assert ignore_resp.status_code == 404

    confirm_resp = await async_client.post(
        f"/api/world/maps/{map_b_id}/observations/{observation_id}/confirm",
        params={"novel_id": nid},
    )
    assert confirm_resp.status_code == 404


@pytest.mark.asyncio
async def test_batch_review_and_fact_status_soft_updates_dashboard_and_playback(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    nid = uuid.uuid4().hex
    await _create_project(db_session, nid)
    map_resp = await async_client.post(
        "/api/world/maps",
        params={"novel_id": nid},
        json={"name": "九州", "map_type": "world", "grid_width": 6, "grid_height": 6},
    )
    map_id = map_resp.json()["id"]
    created_ids = []
    for name in ["沈砚", "林照"]:
        resp = await async_client.post(
            f"/api/world/maps/{map_id}/observations",
            params={"novel_id": nid},
            json={
                "target_name": name,
                "target_entity_type": "character",
                "dynamic_type": "position_change",
                "confidence": 0.8,
            },
        )
        assert resp.status_code == 201, resp.text
        created_ids.append(resp.json()["id"])

    batch = await async_client.post(
        f"/api/world/maps/{map_id}/observations/batch-review",
        params={"novel_id": nid},
        json={"observation_ids": created_ids, "action": "confirm"},
    )
    assert batch.status_code == 200, batch.text
    batch_body = batch.json()
    assert batch_body["requested_count"] == 2
    assert batch_body["updated_count"] == 2
    assert batch_body["created_fact_count"] == 2
    fact_id = batch_body["facts"][0]["id"]

    dashboard = await async_client.get(
        f"/api/world/maps/{map_id}/dashboard",
        params={"novel_id": nid},
    )
    assert [item["item_kind"] for item in dashboard.json()["dynamic_queue"]] == [
        "fact",
        "fact",
    ]

    rolled_back = await async_client.patch(
        f"/api/world/maps/{map_id}/facts/{fact_id}",
        params={"novel_id": nid},
        json={"fact_status": "rolled_back"},
    )
    assert rolled_back.status_code == 200, rolled_back.text
    assert rolled_back.json()["fact_status"] == "rolled_back"

    dashboard_after = await async_client.get(
        f"/api/world/maps/{map_id}/dashboard",
        params={"novel_id": nid},
    )
    dashboard_ids = [
        item["item_id"] for item in dashboard_after.json()["dynamic_queue"]
    ]
    assert fact_id not in dashboard_ids

    playback_after = await async_client.get(
        f"/api/world/maps/{map_id}/playback",
        params={"novel_id": nid, "include_candidates": False},
    )
    assert fact_id not in [event["event_id"] for event in playback_after.json()["events"]]

    restored = await async_client.patch(
        f"/api/world/maps/{map_id}/facts/{fact_id}",
        params={"novel_id": nid},
        json={"fact_status": "confirmed"},
    )
    assert restored.status_code == 200
    assert restored.json()["fact_status"] == "confirmed"


@pytest.mark.asyncio
async def test_batch_actions_review_candidates_and_update_fact_status(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    nid = uuid.uuid4().hex
    await _create_project(db_session, nid)
    map_resp = await async_client.post(
        "/api/world/maps",
        params={"novel_id": nid},
        json={"name": "九州", "map_type": "world", "grid_width": 6, "grid_height": 6},
    )
    map_id = map_resp.json()["id"]
    obs_resp = await async_client.post(
        f"/api/world/maps/{map_id}/observations",
        params={"novel_id": nid},
        json={
            "target_name": "沈砚",
            "target_entity_type": "character",
            "dynamic_type": "position_change",
            "confidence": 0.8,
        },
    )
    observation_id = obs_resp.json()["id"]

    confirmed = await async_client.post(
        f"/api/world/maps/{map_id}/batch-actions",
        params={"novel_id": nid},
        json={
            "action": "confirm_observations",
            "observation_ids": [observation_id],
            "confirmation_text": "确认批量修改",
        },
    )

    assert confirmed.status_code == 200, confirmed.text
    body = confirmed.json()
    assert body["action"] == "confirm_observations"
    assert body["updated_count"] == 1
    fact_id = body["facts"][0]["id"]

    rolled_back = await async_client.post(
        f"/api/world/maps/{map_id}/batch-actions",
        params={"novel_id": nid},
        json={
            "action": "update_fact_status",
            "fact_ids": [fact_id],
            "patch": {"fact_status": "rolled_back"},
            "confirmation_text": "确认批量修改",
        },
    )

    assert rolled_back.status_code == 200, rolled_back.text
    assert rolled_back.json()["facts"][0]["fact_status"] == "rolled_back"


@pytest.mark.asyncio
async def test_batch_actions_reject_cross_novel_fact(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    nid_a = uuid.uuid4().hex
    nid_b = uuid.uuid4().hex
    await _create_project(db_session, nid_a)
    await _create_project(db_session, nid_b)
    map_a = await async_client.post(
        "/api/world/maps",
        params={"novel_id": nid_a},
        json={"name": "九州", "map_type": "world", "grid_width": 6, "grid_height": 6},
    )
    map_b = await async_client.post(
        "/api/world/maps",
        params={"novel_id": nid_b},
        json={"name": "北境", "map_type": "world", "grid_width": 6, "grid_height": 6},
    )
    obs_resp = await async_client.post(
        f"/api/world/maps/{map_a.json()['id']}/observations",
        params={"novel_id": nid_a},
        json={"target_name": "沈砚", "dynamic_type": "position_change"},
    )
    fact = await async_client.post(
        f"/api/world/maps/{map_a.json()['id']}/observations/{obs_resp.json()['id']}/confirm",
        params={"novel_id": nid_a},
    )

    rejected = await async_client.post(
        f"/api/world/maps/{map_b.json()['id']}/batch-actions",
        params={"novel_id": nid_b},
        json={
            "action": "update_fact_status",
            "fact_ids": [fact.json()["id"]],
            "patch": {"fact_status": "rolled_back"},
            "confirmation_text": "确认批量修改",
        },
    )

    assert rejected.status_code == 404


@pytest.mark.asyncio
async def test_playback_derives_typed_tracks_from_facts_and_candidates(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    nid = uuid.uuid4().hex
    await _create_project(db_session, nid)
    character = await _create_entity(
        db_session,
        nid,
        entity_type="character",
        name="沈砚",
        status="canonical",
    )
    map_resp = await async_client.post(
        "/api/world/maps",
        params={"novel_id": nid},
        json={"name": "九州", "map_type": "world", "grid_width": 6, "grid_height": 6},
    )
    map_id = map_resp.json()["id"]

    position_resp = await async_client.post(
        f"/api/world/maps/{map_id}/observations",
        params={"novel_id": nid},
        json={
            "target_entity_id": str(character.id),
            "target_entity_type": "character",
            "target_name": "沈砚",
            "dynamic_type": "position_change",
            "value_json": {"field": "位置", "old": "东门", "new": "内城"},
            "spatial_anchor": {"hex_q": 2, "hex_r": 2},
            "confidence": 0.9,
            "scene_index": 1,
            "source_ref": {"source": "deep_import"},
            "evidence_text": "沈砚进入内城。",
        },
    )
    assert position_resp.status_code == 201, position_resp.text
    await async_client.post(
        f"/api/world/maps/{map_id}/observations/{position_resp.json()['id']}/confirm",
        params={"novel_id": nid},
    )

    crisis_resp = await async_client.post(
        f"/api/world/maps/{map_id}/observations",
        params={"novel_id": nid},
        json={
            "target_entity_type": "location",
            "target_name": "洛阳外城",
            "dynamic_type": "crisis_spread",
            "value_json": {"field": "封锁", "old": "无", "new": "扩散"},
            "confidence": 0.42,
            "scene_index": 2,
            "source_ref": {"source": "deep_import"},
            "evidence_text": "封锁向外城扩散。",
        },
    )
    assert crisis_resp.status_code == 201, crisis_resp.text

    playback = await async_client.get(
        f"/api/world/maps/{map_id}/playback",
        params={"novel_id": nid},
    )
    assert playback.status_code == 200, playback.text
    body = playback.json()
    assert [track["track"] for track in body["tracks"]] == ["journey", "crisis"]
    assert body["events"][0]["typed_observation"] == "position_change"
    assert body["events"][0]["track"] == "journey"
    assert body["events"][0]["change_summary"] == "位置：东门 → 内城"
    assert body["events"][1]["typed_observation"] == "crisis_spread"
    assert body["events"][1]["track"] == "crisis"
    assert body["events"][1]["status_label"] == "待确认"

    confirmed_only = await async_client.get(
        f"/api/world/maps/{map_id}/playback",
        params={"novel_id": nid, "include_candidates": False},
    )
    assert confirmed_only.status_code == 200
    assert [event["track"] for event in confirmed_only.json()["events"]] == ["journey"]


@pytest.mark.asyncio
async def test_playback_accepts_structured_change_values(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    nid = uuid.uuid4().hex
    await _create_project(db_session, nid)
    map_resp = await async_client.post(
        "/api/world/maps",
        params={"novel_id": nid},
        json={"name": "九州", "map_type": "world", "grid_width": 6, "grid_height": 6},
    )
    map_id = map_resp.json()["id"]

    observation_resp = await async_client.post(
        f"/api/world/maps/{map_id}/observations",
        params={"novel_id": nid},
        json={
            "target_entity_type": "location",
            "target_name": "廷根",
            "dynamic_type": "status_change",
            "value_json": {
                "field": "地点状态",
                "new": {"danger": "升高", "source": "深度导入"},
            },
            "confidence": 0.72,
            "source_ref": {"source": "deep_import"},
            "evidence_text": "廷根的危险等级发生变化。",
        },
    )
    assert observation_resp.status_code == 201, observation_resp.text

    playback = await async_client.get(
        f"/api/world/maps/{map_id}/playback",
        params={"novel_id": nid},
    )

    assert playback.status_code == 200, playback.text
    assert (
        playback.json()["events"][0]["change_summary"]
        == "地点状态：danger：升高；source：深度导入"
    )
