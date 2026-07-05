"""Map Scene summary API tests."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from modules.outline.repositories import SceneRepository
from modules.outline.schemas import SceneCreate
from modules.world.map_facade import summarize_scene_map_for_writing
from modules.world.map_repositories import MapFactRepository
from modules.world.map_schemas import (
    BindingHex,
    MapConfigCreate,
    MapLocationBindingCreate,
    MapMarkerCreate,
    MapQuickCreateConfirmRequest,
    MapTerritoryCreate,
    TerritoryHex,
)
from modules.world.services.map_quick_create import MapQuickCreateService
from modules.world.services.map_service import (
    MapConfigService,
    MapLocationBindingService,
    MapMarkerService,
    MapTerritoryService,
)
from modules.world.tests.helpers import _create_entity, _create_project


@pytest.mark.asyncio
async def test_scene_summary_batches_territory_lookup_for_marker_hexes(
    db_session: AsyncSession,
) -> None:
    """Scene 摘要应批量查询 marker 所在 hex 的势力范围，避免 per-marker 查询。"""
    from modules.world.services.map_scene_summary import MapSceneSummaryService

    novel_id = uuid.uuid4()
    map_id = uuid.uuid4()
    faction_id = uuid.uuid4()
    batch_calls: list[list[tuple[int, int]]] = []

    class FakeTerritoryRepo:
        async def get_by_hex(self, *args, **kwargs):
            raise AssertionError("should not query territories one marker at a time")

        async def get_by_hexes(self, db, nid, mid, hexes):
            batch_calls.append(list(hexes))
            return [
                SimpleNamespace(
                    faction_entity_id=faction_id,
                    map_id=map_id,
                    hex_q=1,
                    hex_r=1,
                )
            ]

    class FakeEntityRepo:
        async def get_by_ids(self, db, nid, ids):
            return [
                SimpleNamespace(
                    id=faction_id,
                    name="东门守军",
                    status="canonical",
                )
            ]

    markers = [
        SimpleNamespace(map_id=map_id, hex_q=1, hex_r=1),
        SimpleNamespace(map_id=map_id, hex_q=2, hex_r=1),
        SimpleNamespace(map_id=map_id, hex_q=1, hex_r=1),
    ]
    service = MapSceneSummaryService(
        territory_repo=FakeTerritoryRepo(),  # type: ignore[arg-type]
        entity_repo=FakeEntityRepo(),  # type: ignore[arg-type]
    )

    items = await service._faction_items(db_session, novel_id, map_id, markers)

    assert batch_calls == [[(1, 1), (2, 1)]]
    assert [item.name for item in items] == ["东门守军"]


@pytest.mark.asyncio
async def test_scene_summary_batches_primary_location_binding_lookup(
    db_session: AsyncSession,
) -> None:
    """主地点只应批量查询 marker 所在 hex 的可见地点绑定。"""
    from modules.world.services.map_scene_summary import MapSceneSummaryService

    novel_id = uuid.uuid4()
    map_id = uuid.uuid4()
    location_id = uuid.uuid4()
    batch_calls: list[list[tuple[int, int]]] = []

    class FakeBindingRepo:
        async def get_by_map(self, *args, **kwargs):
            raise AssertionError("should not load every binding on the map")

        async def get_by_hexes_for_entity_statuses(
            self,
            db,
            nid,
            mid,
            hexes,
            *,
            statuses,
        ):
            batch_calls.append(list(hexes))
            assert statuses == ["canonical", "draft"]
            return [
                SimpleNamespace(
                    location_entity_id=uuid.uuid4(),
                    map_id=map_id,
                    hex_q=1,
                    hex_r=1,
                    is_center=False,
                ),
                SimpleNamespace(
                    location_entity_id=location_id,
                    map_id=map_id,
                    hex_q=1,
                    hex_r=1,
                    is_center=True,
                ),
            ]

    class FakeEntityRepo:
        async def get_by_ids(self, db, nid, ids):
            return [
                SimpleNamespace(
                    id=location_id,
                    name="东门",
                    status="canonical",
                )
            ]

    markers = [
        SimpleNamespace(map_id=map_id, hex_q=1, hex_r=1),
        SimpleNamespace(map_id=map_id, hex_q=2, hex_r=1),
        SimpleNamespace(map_id=map_id, hex_q=1, hex_r=1),
    ]
    service = MapSceneSummaryService(
        binding_repo=FakeBindingRepo(),  # type: ignore[arg-type]
        entity_repo=FakeEntityRepo(),  # type: ignore[arg-type]
    )

    item = await service._primary_location(db_session, novel_id, map_id, markers)

    assert batch_calls == [[(1, 1), (2, 1)]]
    assert item is not None
    assert item.entity_id == str(location_id)
    assert item.name == "东门"


@pytest.mark.asyncio
async def test_scene_summary_loads_marker_entities_once(
    db_session: AsyncSession,
) -> None:
    """marker 状态和展示名称应复用同一次实体加载结果。"""
    from modules.world.services.map_scene_summary import MapSceneSummaryService

    novel_id = uuid.uuid4()
    scene_id = uuid.uuid4()
    map_id = uuid.uuid4()
    entity_id = uuid.uuid4()
    non_empty_entity_calls: list[list[uuid.UUID]] = []

    class FakeMarkerRepo:
        async def get_by_scene(self, db, nid, *, scene_id, scene_index):
            return [
                SimpleNamespace(
                    entity_id=entity_id,
                    marker_type="character",
                    map_id=map_id,
                    hex_q=1,
                    hex_r=1,
                    start_scene_id=scene_id,
                    end_scene_id=None,
                    label="备用名",
                )
            ]

        async def get_latest_before_scene_for_entities(self, *args, **kwargs):
            return {}

    class FakeBindingRepo:
        async def get_by_hexes_for_entity_statuses(self, *args, **kwargs):
            return []

    class FakeTerritoryRepo:
        async def get_by_hexes(self, *args, **kwargs):
            return []

    class FakeFactRepo:
        async def find_map_for_scene(self, *args, **kwargs):
            return None

        async def list_for_scene_summary(self, *args, **kwargs):
            return []

    class FakeObservationRepo:
        async def find_map_for_scene(self, *args, **kwargs):
            return None

        async def list_for_scene_summary(self, *args, **kwargs):
            return []

    class FakeEntityRepo:
        async def get_by_ids(self, db, nid, ids):
            requested = list(ids)
            if requested:
                non_empty_entity_calls.append(requested)
            return [
                SimpleNamespace(
                    id=entity_id,
                    name="林照",
                    status="canonical",
                )
            ]

    async def fake_scene_lookup(db, nid, sid):
        return SimpleNamespace(scene_index=None)

    service = MapSceneSummaryService(
        marker_repo=FakeMarkerRepo(),  # type: ignore[arg-type]
        binding_repo=FakeBindingRepo(),  # type: ignore[arg-type]
        territory_repo=FakeTerritoryRepo(),  # type: ignore[arg-type]
        fact_repo=FakeFactRepo(),  # type: ignore[arg-type]
        observation_repo=FakeObservationRepo(),  # type: ignore[arg-type]
        entity_repo=FakeEntityRepo(),  # type: ignore[arg-type]
        scene_lookup=fake_scene_lookup,
    )

    summary = await service.summarize(
        db_session,
        novel_id.hex,
        str(scene_id),
    )

    assert non_empty_entity_calls == [[entity_id]]
    assert summary.characters[0].name == "林照"


async def _create_scene(
    db_session: AsyncSession,
    novel_id: str,
    *,
    scene_index: int = 7,
    title: str = "东门封锁",
):
    return await SceneRepository().create(
        db_session,
        uuid.UUID(hex=novel_id),
        SceneCreate(scene_index=scene_index, title=title, status="canonical"),
    )


@pytest.mark.asyncio
async def test_scene_summary_static_route_is_not_captured_by_map_id(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    nid = uuid.uuid4().hex
    await _create_project(db_session, nid)
    scene = await _create_scene(db_session, nid)

    resp = await async_client.get(
        "/api/world/maps/scene-summary",
        params={"novel_id": nid, "scene_id": str(scene.id)},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["scene_id"] == str(scene.id)
    assert body["open_target"]["mode"] == "recent"


@pytest.mark.asyncio
async def test_scene_summary_without_markers_returns_empty_summary_and_fallback(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    nid = uuid.uuid4().hex
    await _create_project(db_session, nid)
    scene = await _create_scene(db_session, nid)

    resp = await async_client.get(
        "/api/world/maps/scene-summary",
        params={"novel_id": nid, "scene_id": str(scene.id)},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["primary_location"] is None
    assert body["characters"] == []
    assert body["events"] == []
    assert body["factions"] == []
    assert body["open_target"] == {
        "mode": "recent",
        "map_id": None,
        "scene_id": str(scene.id),
        "focus_entity_id": None,
        "observation_id": None,
        "fallback_reason": "scene_without_map",
        "fallback_message": "当前 Scene 暂无地图上下文，已回退到最近地图",
    }
    assert body["warnings"][0]["code"] == "scene_without_map_context"
    assert body["warnings"][0]["message"] == "当前 Scene 暂无地图上下文"


@pytest.mark.asyncio
async def test_scene_summary_uses_quick_created_project_map_without_scene_markers(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    nid = uuid.uuid4().hex
    await _create_project(db_session, nid)
    scene = await _create_scene(db_session, nid)
    await _create_entity(
        db_session,
        nid,
        entity_type="location",
        name="琉璃湾",
        status="draft",
    )
    await _create_entity(
        db_session,
        nid,
        entity_type="location",
        name="归潮塔群",
        status="draft",
    )
    created = await MapQuickCreateService().confirm(
        db_session,
        nid,
        MapQuickCreateConfirmRequest(name="霭潮地图"),
    )

    resp = await async_client.get(
        "/api/world/maps/scene-summary",
        params={"novel_id": nid, "scene_id": str(scene.id)},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["open_target"]["mode"] == "map"
    assert body["open_target"]["map_id"] == created.map.id
    assert body["primary_location"]["name"] in {"琉璃湾", "归潮塔群"}
    assert all(
        warning["code"] != "scene_without_map_context"
        for warning in body["warnings"]
    )


@pytest.mark.asyncio
async def test_scene_summary_ignores_candidate_markers_for_default_context(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    nid = uuid.uuid4().hex
    await _create_project(db_session, nid)
    scene = await _create_scene(db_session, nid)
    map_resp = await MapConfigService().create(
        db_session,
        nid,
        MapConfigCreate(name="九州世界", map_type="world", grid_width=5, grid_height=5),
    )
    candidate_character = await _create_entity(
        db_session,
        nid,
        entity_type="character",
        name="待确认人物",
        status="candidate",
    )
    await MapMarkerService().create(
        db_session,
        nid,
        map_resp.id,
        MapMarkerCreate(
            entity_id=str(candidate_character.id),
            marker_type="character",
            hex_q=1,
            hex_r=1,
            start_scene_id=str(scene.id),
            start_scene_index=scene.scene_index,
            label="待确认人物",
        ),
    )

    resp = await async_client.get(
        "/api/world/maps/scene-summary",
        params={"novel_id": nid, "scene_id": str(scene.id)},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["characters"] == []
    assert body["open_target"]["mode"] == "recent"
    assert body["warnings"][0]["code"] == "scene_without_map_context"


@pytest.mark.asyncio
async def test_writing_map_facade_excludes_candidate_markers_by_default(
    db_session: AsyncSession,
) -> None:
    nid = uuid.uuid4().hex
    await _create_project(db_session, nid)
    scene = await _create_scene(db_session, nid)
    map_resp = await MapConfigService().create(
        db_session,
        nid,
        MapConfigCreate(name="九州世界", map_type="world", grid_width=5, grid_height=5),
    )
    candidate_character = await _create_entity(
        db_session,
        nid,
        entity_type="character",
        name="待确认人物",
        status="candidate",
    )
    await MapMarkerService().create(
        db_session,
        nid,
        map_resp.id,
        MapMarkerCreate(
            entity_id=str(candidate_character.id),
            marker_type="character",
            hex_q=1,
            hex_r=1,
            start_scene_id=str(scene.id),
            start_scene_index=scene.scene_index,
            label="待确认人物",
        ),
    )

    summary = await summarize_scene_map_for_writing(
        db_session,
        nid,
        str(scene.id),
    )

    assert summary["characters"] == []
    assert summary["open_target"]["mode"] == "recent"


@pytest.mark.asyncio
async def test_scene_summary_excludes_candidate_observations_by_default(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    novel_id = uuid.uuid4().hex
    await _create_project(db_session, novel_id)
    scene = await _create_scene(db_session, novel_id, scene_index=1)
    map_resp = await MapConfigService().create(
        db_session,
        novel_id,
        MapConfigCreate(name="九州世界", map_type="world", grid_width=5, grid_height=5),
    )
    observation_resp = await async_client.post(
        f"/api/world/maps/{map_resp.id}/observations",
        params={"novel_id": novel_id},
        json={
            "target_name": "粮仓起火",
            "target_entity_type": "event",
            "dynamic_type": "risk",
            "review_state": "candidate",
            "scene_id": str(scene.id),
            "scene_index": 1,
            "spatial_anchor": {"hex_q": 2, "hex_r": 3},
            "evidence_text": "粮仓火势正在扩大",
        },
    )
    assert observation_resp.status_code == 201, observation_resp.text

    summary = await summarize_scene_map_for_writing(
        db_session,
        novel_id,
        str(scene.id),
        include_candidates=False,
    )

    assert summary["candidate_support"] == "supported"
    assert summary["risks"] == []
    assert summary["open_target"]["mode"] == "recent"
    assert summary["open_target"]["map_id"] is None


@pytest.mark.asyncio
async def test_scene_summary_includes_confirmed_dynamic_fact_by_default(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    novel_id = uuid.uuid4().hex
    await _create_project(db_session, novel_id)
    scene = await _create_scene(db_session, novel_id, scene_index=1)
    map_resp = await MapConfigService().create(
        db_session,
        novel_id,
        MapConfigCreate(name="九州世界", map_type="world", grid_width=5, grid_height=5),
    )
    observation_resp = await async_client.post(
        f"/api/world/maps/{map_resp.id}/observations",
        params={"novel_id": novel_id},
        json={
            "target_name": "粮仓起火",
            "target_entity_type": "event",
            "dynamic_type": "risk",
            "review_state": "candidate",
            "scene_id": str(scene.id),
            "scene_index": 1,
            "spatial_anchor": {"hex_q": 2, "hex_r": 3},
            "evidence_text": "粮仓火势正在扩大",
        },
    )
    assert observation_resp.status_code == 201, observation_resp.text
    observation_id = observation_resp.json()["id"]
    confirm_resp = await async_client.post(
        f"/api/world/maps/{map_resp.id}/observations/{observation_id}/confirm",
        params={"novel_id": novel_id},
    )
    assert confirm_resp.status_code == 200, confirm_resp.text

    summary = await summarize_scene_map_for_writing(
        db_session,
        novel_id,
        str(scene.id),
        include_candidates=False,
    )

    assert summary["open_target"]["mode"] == "map"
    assert summary["open_target"]["map_id"] == map_resp.id
    assert summary["risks"][0]["depends_on_candidate"] is False
    assert summary["risks"][0]["candidate_review_state"] is None
    assert summary["risks"][0]["evidence_excerpt"] == "粮仓火势正在扩大"
    assert summary["risks"][0]["open_target"]["observation_id"] == observation_id


@pytest.mark.asyncio
async def test_scene_summary_queries_confirmed_facts_by_scene_before_limit(
    db_session: AsyncSession,
) -> None:
    novel_id = uuid.uuid4().hex
    await _create_project(db_session, novel_id)
    other_scene = await _create_scene(db_session, novel_id, scene_index=1)
    scene = await _create_scene(db_session, novel_id, scene_index=99)
    map_resp = await MapConfigService().create(
        db_session,
        novel_id,
        MapConfigCreate(name="九州世界", map_type="world", grid_width=5, grid_height=5),
    )
    fact_repo = MapFactRepository()
    nid = uuid.UUID(hex=novel_id)
    map_id = uuid.UUID(map_resp.id)
    for index in range(81):
        await fact_repo.create(
            db_session,
            nid,
            {
                "map_id": map_id,
                "target_name": f"其他风险 {index}",
                "target_entity_type": "event",
                "dynamic_type": "risk",
                "spatial_anchor": {"hex_q": index % 5, "hex_r": index % 7},
                "fact_status": "confirmed",
                "evidence_text": f"其他场景证据 {index}",
                "scene_id": other_scene.id,
                "scene_index": other_scene.scene_index,
            },
        )
    await fact_repo.create(
        db_session,
        nid,
        {
            "map_id": map_id,
            "target_name": "粮仓起火",
            "target_entity_type": "event",
            "dynamic_type": "risk",
            "spatial_anchor": {"hex_q": 2, "hex_r": 3},
            "fact_status": "confirmed",
            "evidence_text": "粮仓火势正在扩大",
            "scene_id": scene.id,
            "scene_index": scene.scene_index,
        },
    )

    summary = await summarize_scene_map_for_writing(
        db_session,
        novel_id,
        str(scene.id),
        include_candidates=False,
    )

    assert [risk["message"] for risk in summary["risks"]] == ["粮仓起火：已确认"]
    assert summary["risks"][0]["evidence_excerpt"] == "粮仓火势正在扩大"


@pytest.mark.asyncio
async def test_scene_summary_queries_dynamic_facts_before_limit(
    db_session: AsyncSession,
) -> None:
    novel_id = uuid.uuid4().hex
    await _create_project(db_session, novel_id)
    scene = await _create_scene(db_session, novel_id, scene_index=1)
    map_resp = await MapConfigService().create(
        db_session,
        novel_id,
        MapConfigCreate(name="九州世界", map_type="world", grid_width=5, grid_height=5),
    )
    fact_repo = MapFactRepository()
    nid = uuid.UUID(hex=novel_id)
    map_id = uuid.UUID(map_resp.id)
    for index in range(81):
        await fact_repo.create(
            db_session,
            nid,
            {
                "map_id": map_id,
                "target_name": f"地点变化 {index}",
                "target_entity_type": "location",
                "dynamic_type": "location",
                "spatial_anchor": {"hex_q": index % 5, "hex_r": index % 7},
                "fact_status": "confirmed",
                "evidence_text": f"地点变化证据 {index}",
                "scene_id": scene.id,
                "scene_index": scene.scene_index,
            },
        )
    await fact_repo.create(
        db_session,
        nid,
        {
            "map_id": map_id,
            "target_name": "粮仓起火",
            "target_entity_type": "event",
            "dynamic_type": "risk",
            "spatial_anchor": {"hex_q": 2, "hex_r": 3},
            "fact_status": "confirmed",
            "evidence_text": "粮仓火势正在扩大",
            "scene_id": scene.id,
            "scene_index": scene.scene_index,
        },
    )

    summary = await summarize_scene_map_for_writing(
        db_session,
        novel_id,
        str(scene.id),
        include_candidates=False,
    )

    assert [risk["message"] for risk in summary["risks"]] == ["粮仓起火：已确认"]


@pytest.mark.asyncio
async def test_scene_summary_suppresses_candidate_duplicate_of_confirmed_fact(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    novel_id = uuid.uuid4().hex
    await _create_project(db_session, novel_id)
    scene = await _create_scene(db_session, novel_id, scene_index=1)
    map_resp = await MapConfigService().create(
        db_session,
        novel_id,
        MapConfigCreate(name="九州世界", map_type="world", grid_width=5, grid_height=5),
    )
    confirmed_observation_resp = await async_client.post(
        f"/api/world/maps/{map_resp.id}/observations",
        params={"novel_id": novel_id},
        json={
            "target_name": "粮仓起火",
            "target_entity_type": "event",
            "dynamic_type": "risk",
            "review_state": "candidate",
            "scene_id": str(scene.id),
            "scene_index": 1,
            "spatial_anchor": {"hex_q": 2, "hex_r": 3},
            "evidence_text": "粮仓火势正在扩大",
        },
    )
    assert confirmed_observation_resp.status_code == 201
    observation_id = confirmed_observation_resp.json()["id"]
    confirm_resp = await async_client.post(
        f"/api/world/maps/{map_resp.id}/observations/{observation_id}/confirm",
        params={"novel_id": novel_id},
    )
    assert confirm_resp.status_code == 200, confirm_resp.text
    duplicate_resp = await async_client.post(
        f"/api/world/maps/{map_resp.id}/observations",
        params={"novel_id": novel_id},
        json={
            "target_name": "粮仓起火",
            "target_entity_type": "event",
            "dynamic_type": "risk",
            "review_state": "candidate",
            "scene_id": str(scene.id),
            "scene_index": 1,
            "spatial_anchor": {"hex_q": 2, "hex_r": 3},
            "evidence_text": "候选重复证据",
        },
    )
    assert duplicate_resp.status_code == 201, duplicate_resp.text

    summary = await summarize_scene_map_for_writing(
        db_session,
        novel_id,
        str(scene.id),
        include_candidates=True,
    )

    assert [risk["message"] for risk in summary["risks"]] == ["粮仓起火：已确认"]
    assert summary["risks"][0]["depends_on_candidate"] is False
    assert summary["risks"][0]["open_target"]["observation_id"] == observation_id


@pytest.mark.asyncio
async def test_scene_summary_marks_candidate_observation_evidence(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    novel_id = uuid.uuid4().hex
    await _create_project(db_session, novel_id)
    scene = await _create_scene(db_session, novel_id, scene_index=1)
    map_resp = await MapConfigService().create(
        db_session,
        novel_id,
        MapConfigCreate(name="九州世界", map_type="world", grid_width=5, grid_height=5),
    )
    observation_resp = await async_client.post(
        f"/api/world/maps/{map_resp.id}/observations",
        params={"novel_id": novel_id},
        json={
            "target_name": "粮仓起火",
            "target_entity_type": "event",
            "dynamic_type": "risk",
            "review_state": "candidate",
            "scene_id": str(scene.id),
            "scene_index": 1,
            "spatial_anchor": {"hex_q": 2, "hex_r": 3},
            "evidence_text": "粮仓火势正在扩大",
        },
    )
    observation_id = observation_resp.json()["id"]

    summary = await summarize_scene_map_for_writing(
        db_session,
        novel_id,
        str(scene.id),
        include_candidates=True,
    )

    assert summary["candidate_support"] == "supported"
    assert summary["risks"][0]["depends_on_candidate"] is True
    assert summary["risks"][0]["candidate_review_state"] == "candidate"
    assert summary["risks"][0]["evidence_excerpt"] == "粮仓火势正在扩大"
    assert summary["risks"][0]["open_target"]["observation_id"] == observation_id


@pytest.mark.asyncio
async def test_scene_summary_with_marker_but_no_bound_location_warns_missing_location(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    nid = uuid.uuid4().hex
    await _create_project(db_session, nid)
    scene = await _create_scene(db_session, nid)
    map_resp = await MapConfigService().create(
        db_session,
        nid,
        MapConfigCreate(name="九州世界", map_type="world", grid_width=5, grid_height=5),
    )
    character = await _create_entity(
        db_session, nid, entity_type="character", name="沈砚"
    )
    await MapMarkerService().create(
        db_session,
        nid,
        map_resp.id,
        MapMarkerCreate(
            entity_id=str(character.id),
            marker_type="character",
            hex_q=1,
            hex_r=1,
            start_scene_id=str(scene.id),
            start_scene_index=scene.scene_index,
            label="沈砚",
        ),
    )

    resp = await async_client.get(
        "/api/world/maps/scene-summary",
        params={"novel_id": nid, "scene_id": str(scene.id)},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["open_target"]["mode"] == "map"
    assert body["primary_location"] is None
    assert body["warnings"][0]["code"] == "scene_without_location"
    assert body["warnings"][0]["message"] == "当前 Scene 暂无主地点"


@pytest.mark.asyncio
async def test_scene_summary_returns_location_characters_events_and_factions(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    nid = uuid.uuid4().hex
    await _create_project(db_session, nid)
    scene = await _create_scene(db_session, nid)

    map_resp = await MapConfigService().create(
        db_session,
        nid,
        MapConfigCreate(name="九州世界", map_type="world", grid_width=5, grid_height=5),
    )
    map_id = map_resp.id

    location = await _create_entity(
        db_session, nid, entity_type="location", name="洛阳外城"
    )
    character = await _create_entity(
        db_session, nid, entity_type="character", name="沈砚"
    )
    event = await _create_entity(db_session, nid, entity_type="event", name="东门封锁")
    faction = await _create_entity(
        db_session, nid, entity_type="organization", name="北府"
    )

    await MapLocationBindingService().batch_create(
        db_session,
        nid,
        map_id,
        MapLocationBindingCreate(
            location_entity_id=str(location.id),
            hexes=[BindingHex(hex_q=1, hex_r=1, is_center=True)],
        ),
    )
    await MapMarkerService().create(
        db_session,
        nid,
        map_id,
        MapMarkerCreate(
            entity_id=str(character.id),
            marker_type="character",
            hex_q=1,
            hex_r=1,
            start_scene_id=str(scene.id),
            start_scene_index=scene.scene_index,
            label="沈砚",
        ),
    )
    await MapMarkerService().create(
        db_session,
        nid,
        map_id,
        MapMarkerCreate(
            entity_id=str(event.id),
            marker_type="event",
            hex_q=2,
            hex_r=1,
            start_scene_id=str(scene.id),
            start_scene_index=scene.scene_index,
            label="封锁",
        ),
    )
    await MapTerritoryService().create(
        db_session,
        nid,
        map_id,
        MapTerritoryCreate(
            faction_entity_id=str(faction.id),
            hexes=[TerritoryHex(hex_q=1, hex_r=1)],
        ),
    )

    resp = await async_client.get(
        "/api/world/maps/scene-summary",
        params={"novel_id": nid, "scene_id": str(scene.id)},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["open_target"]["mode"] == "map"
    assert body["open_target"]["map_id"] == map_id
    assert body["primary_location"]["name"] == "洛阳外城"
    assert body["primary_location"]["hex_q"] == 1
    assert [item["name"] for item in body["characters"]] == ["沈砚"]
    assert [item["name"] for item in body["events"]] == ["东门封锁"]
    assert [item["name"] for item in body["factions"]] == ["北府"]
    assert body["crises"] == []
    assert body["risks"] == []


@pytest.mark.asyncio
async def test_scene_summary_exposes_candidate_crises_when_facade_includes_candidates(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    nid = uuid.uuid4().hex
    await _create_project(db_session, nid)
    scene = await _create_scene(db_session, nid)
    map_resp = await MapConfigService().create(
        db_session,
        nid,
        MapConfigCreate(name="九州世界", map_type="world", grid_width=5, grid_height=5),
    )
    location = await _create_entity(
        db_session, nid, entity_type="location", name="洛阳外城"
    )
    await MapLocationBindingService().batch_create(
        db_session,
        nid,
        map_resp.id,
        MapLocationBindingCreate(
            location_entity_id=str(location.id),
            hexes=[BindingHex(hex_q=1, hex_r=1, is_center=True)],
        ),
    )
    crisis_resp = await async_client.post(
        f"/api/world/maps/{map_resp.id}/observations",
        params={"novel_id": nid},
        json={
            "scene_id": str(scene.id),
            "target_entity_type": "event",
            "target_name": "东门封锁",
            "dynamic_type": "crisis",
            "confidence": 0.39,
            "scene_index": scene.scene_index,
            "source_ref": {"source": "deep_import"},
        },
    )
    assert crisis_resp.status_code == 201, crisis_resp.text
    observation_id = crisis_resp.json()["id"]

    resp = await async_client.get(
        "/api/world/maps/scene-summary",
        params={"novel_id": nid, "scene_id": str(scene.id)},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["crises"] == []
    assert body["risks"] == []

    summary = await summarize_scene_map_for_writing(
        db_session,
        nid,
        str(scene.id),
        include_candidates=True,
    )

    assert [item["name"] for item in summary["crises"]] == ["东门封锁"]
    assert summary["crises"][0]["depends_on_candidate"] is True
    assert summary["crises"][0]["candidate_review_state"] == "candidate"
    assert summary["crises"][0]["open_target"]["observation_id"] == observation_id
    assert summary["risks"][0]["level"] == "warning"
    assert summary["risks"][0]["code"] == "map_dynamic_risk"
    assert summary["risks"][0]["message"] == "东门封锁：待确认"


@pytest.mark.asyncio
async def test_scene_summary_warns_when_character_previous_marker_is_on_other_map(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    nid = uuid.uuid4().hex
    await _create_project(db_session, nid)
    previous_scene = await _create_scene(
        db_session, nid, scene_index=6, title="江陵旧事"
    )
    current_scene = await _create_scene(
        db_session, nid, scene_index=7, title="洛阳外城"
    )
    old_map = await MapConfigService().create(
        db_session,
        nid,
        MapConfigCreate(name="江陵", map_type="world", grid_width=5, grid_height=5),
    )
    new_map = await MapConfigService().create(
        db_session,
        nid,
        MapConfigCreate(name="洛阳", map_type="world", grid_width=5, grid_height=5),
    )
    character = await _create_entity(
        db_session, nid, entity_type="character", name="陆青"
    )
    location = await _create_entity(
        db_session, nid, entity_type="location", name="洛阳外城"
    )
    await MapLocationBindingService().batch_create(
        db_session,
        nid,
        new_map.id,
        MapLocationBindingCreate(
            location_entity_id=str(location.id),
            hexes=[BindingHex(hex_q=1, hex_r=1, is_center=True)],
        ),
    )
    await MapMarkerService().create(
        db_session,
        nid,
        old_map.id,
        MapMarkerCreate(
            entity_id=str(character.id),
            marker_type="character",
            hex_q=1,
            hex_r=1,
            start_scene_id=str(previous_scene.id),
            start_scene_index=previous_scene.scene_index,
            label="陆青",
        ),
    )
    await MapMarkerService().create(
        db_session,
        nid,
        new_map.id,
        MapMarkerCreate(
            entity_id=str(character.id),
            marker_type="character",
            hex_q=1,
            hex_r=1,
            start_scene_id=str(current_scene.id),
            start_scene_index=current_scene.scene_index,
            label="陆青",
        ),
    )

    resp = await async_client.get(
        "/api/world/maps/scene-summary",
        params={"novel_id": nid, "scene_id": str(current_scene.id)},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["warnings"][0]["code"] == "character_cross_map"
    assert "陆青上一场在其他地图" in body["warnings"][0]["message"]


@pytest.mark.asyncio
async def test_scene_summary_cross_novel_scene_returns_404(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    nid1 = uuid.uuid4().hex
    nid2 = uuid.uuid4().hex
    await _create_project(db_session, nid1)
    await _create_project(db_session, nid2)
    scene = await _create_scene(db_session, nid1)

    resp = await async_client.get(
        "/api/world/maps/scene-summary",
        params={"novel_id": nid2, "scene_id": str(scene.id)},
    )

    assert resp.status_code == 404
