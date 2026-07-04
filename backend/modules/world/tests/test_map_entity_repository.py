"""MapEntityRepository 泛型基类行为测试。

验证放置型实体 repository 共享的 CRUD 不变量：
- novel_id / map_id 隔离
- update 只应用传入的 values dict
- delete 按 id 执行
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import Delete, Select

from modules.world.map_models import (
    MapConfig,
    MapFact,
    MapLocationBinding,
    MapMarker,
    MapObservation,
    MapTerritoryTile,
)
from modules.world.map_repositories import (
    MapConfigRepository,
    MapEntityRepository,
    MapFactRepository,
    MapLocationBindingRepository,
    MapMarkerRepository,
    MapObservationRepository,
    MapTerritoryRepository,
)


class TestMapEntityRepositoryInheritance:
    def test_placement_repositories_inherit_base(self):
        assert issubclass(MapLocationBindingRepository, MapEntityRepository)
        assert issubclass(MapMarkerRepository, MapEntityRepository)
        assert issubclass(MapTerritoryRepository, MapEntityRepository)

    def test_model_class_set(self):
        assert MapLocationBindingRepository.model_class is MapLocationBinding
        assert MapMarkerRepository.model_class is MapMarker
        assert MapTerritoryRepository.model_class is MapTerritoryTile


class TestMapEntityRepositoryQueries:
    @pytest.mark.asyncio
    async def test_get_by_map_filters_by_novel_and_map(self):
        repo = MapMarkerRepository()
        db = AsyncMock()
        nid = uuid.uuid4()
        mid = uuid.uuid4()

        from unittest.mock import MagicMock

        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = []
        db.execute.return_value = result_mock

        result = await repo.get_by_map(db, nid, mid)

        assert result == []
        assert db.execute.call_count == 1
        stmt = db.execute.call_args[0][0]
        assert isinstance(stmt, Select)
        # 语句中应包含 novel_id 与 map_id 过滤（UUID 编译后无横线）
        stmt_str = str(stmt.compile())
        assert "map_markers.novel_id" in stmt_str
        assert "map_markers.map_id" in stmt_str

    @pytest.mark.asyncio
    async def test_update_reuses_loaded_entity(self, monkeypatch: pytest.MonkeyPatch):
        repo = MapTerritoryRepository()
        db = MagicMock()
        db.flush = AsyncMock()
        tid = uuid.uuid4()
        territory = MapTerritoryTile(id=tid, style_override={})
        get_calls = 0

        async def fake_get(_db, entity_id):
            nonlocal get_calls
            get_calls += 1
            assert entity_id == tid
            return territory

        monkeypatch.setattr(repo, "get", fake_get)

        updated = await repo.update(db, tid, {"style_override": {"color": "#f00"}})

        assert updated is territory
        assert get_calls == 1
        db.add.assert_called_once_with(territory)
        db.flush.assert_awaited_once()
        assert territory.style_override == {"color": "#f00"}

    @pytest.mark.asyncio
    async def test_update_loaded_entity_does_not_fetch_again(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ):
        repo = MapMarkerRepository()
        db = MagicMock()
        db.flush = AsyncMock()
        marker = MapMarker(id=uuid.uuid4(), marker_type="poi", label="旧标签")

        async def fail_get(*_args, **_kwargs):
            raise AssertionError("loaded map entity should not be fetched again")

        monkeypatch.setattr(repo, "get", fail_get)

        updated = await repo.update(db, marker, {"label": "新标签"})

        assert updated is marker
        db.add.assert_called_once_with(marker)
        db.flush.assert_awaited_once()
        assert marker.label == "新标签"

    @pytest.mark.asyncio
    async def test_update_empty_values_returns_loaded_entity_without_flush(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ):
        repo = MapMarkerRepository()
        db = MagicMock()
        db.flush = AsyncMock()
        marker_id = uuid.uuid4()
        marker = MapMarker(id=marker_id, marker_type="poi")

        async def fake_get(_db, entity_id):
            assert entity_id == marker_id
            return marker

        monkeypatch.setattr(repo, "get", fake_get)

        updated = await repo.update(db, marker_id, {})

        assert updated is marker
        db.add.assert_not_called()
        db.flush.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_update_missing_entity_returns_none(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ):
        repo = MapLocationBindingRepository()
        db = MagicMock()
        db.flush = AsyncMock()

        async def fake_get(_db, _entity_id):
            return None

        monkeypatch.setattr(repo, "get", fake_get)

        assert await repo.update(db, uuid.uuid4(), {"hex_q": 1}) is None
        db.add.assert_not_called()
        db.flush.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_delete_applies_id_filter(self):
        repo = MapLocationBindingRepository()
        db = AsyncMock()
        bid = uuid.uuid4()

        from unittest.mock import MagicMock

        result_mock = MagicMock()
        result_mock.rowcount = 1
        db.execute.return_value = result_mock

        result = await repo.delete(db, bid)

        assert result is True
        stmt = db.execute.call_args[0][0]
        assert isinstance(stmt, Delete)
        stmt_str = str(stmt.compile())
        assert "map_location_bindings" in stmt_str
        assert ":id_1" in stmt_str

    @pytest.mark.asyncio
    async def test_territory_create_batch_uses_add_all(self):
        repo = MapTerritoryRepository()
        db = MagicMock()
        db.flush = AsyncMock()
        novel_id = uuid.uuid4()
        map_id = uuid.uuid4()
        faction_id = uuid.uuid4()

        tiles = await repo.create_batch(
            db,
            novel_id,
            map_id,
            faction_id,
            [{"hex_q": 1, "hex_r": 2}, {"hex_q": 2, "hex_r": 3}],
        )

        assert [(tile.hex_q, tile.hex_r) for tile in tiles] == [(1, 2), (2, 3)]
        db.add.assert_not_called()
        db.add_all.assert_called_once_with(tiles)
        db.flush.assert_awaited_once()


class TestMapConfigRepository:
    @pytest.mark.asyncio
    async def test_update_reuses_loaded_config(self, monkeypatch: pytest.MonkeyPatch):
        repo = MapConfigRepository()
        db = MagicMock()
        db.flush = AsyncMock()
        map_id = uuid.uuid4()
        config = MapConfig(id=map_id, name="旧名", sort_order=0)
        get_calls = 0

        async def fake_get(_db, entity_id):
            nonlocal get_calls
            get_calls += 1
            assert entity_id == map_id
            return config

        monkeypatch.setattr(repo, "get", fake_get)

        updated = await repo.update(db, map_id, {"name": "新名", "sort_order": 3})

        assert updated is config
        assert get_calls == 1
        db.add.assert_called_once_with(config)
        db.flush.assert_awaited_once()
        assert config.name == "新名"
        assert config.sort_order == 3

    @pytest.mark.asyncio
    async def test_update_loaded_config_does_not_fetch_again(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ):
        repo = MapConfigRepository()
        db = MagicMock()
        db.flush = AsyncMock()
        config = MapConfig(id=uuid.uuid4(), name="旧名", sort_order=0)

        async def fail_get(*_args, **_kwargs):
            raise AssertionError("loaded map config should not be fetched again")

        monkeypatch.setattr(repo, "get", fail_get)

        updated = await repo.update(db, config, {"name": "新名", "sort_order": 3})

        assert updated is config
        db.add.assert_called_once_with(config)
        db.flush.assert_awaited_once()
        assert config.name == "新名"
        assert config.sort_order == 3

    @pytest.mark.asyncio
    async def test_update_missing_config_returns_none(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ):
        repo = MapConfigRepository()
        db = MagicMock()
        db.flush = AsyncMock()

        async def fake_get(_db, _map_id):
            return None

        monkeypatch.setattr(repo, "get", fake_get)

        assert await repo.update(db, uuid.uuid4(), {"name": "新名"}) is None
        db.add.assert_not_called()
        db.flush.assert_not_awaited()


class TestMapObservationRepository:
    @pytest.mark.asyncio
    async def test_update_review_state_reuses_loaded_observation(self):
        repo = MapObservationRepository()
        db = MagicMock()
        db.flush = AsyncMock()
        observation = MapObservation(id=uuid.uuid4(), review_state="candidate")

        updated = await repo.update_review_state(db, observation, "confirmed")

        assert updated is observation
        db.add.assert_called_once_with(observation)
        db.flush.assert_awaited_once()
        assert observation.review_state == "confirmed"

    @pytest.mark.asyncio
    async def test_update_reuses_loaded_observation_without_get(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ):
        repo = MapObservationRepository()
        db = MagicMock()
        db.flush = AsyncMock()
        observation = MapObservation(id=uuid.uuid4(), review_state="candidate")

        async def fail_get(*_args, **_kwargs):
            raise AssertionError("loaded observation should not be fetched again")

        monkeypatch.setattr(repo, "get", fail_get)

        updated = await repo.update(db, observation, {"review_state": "ignored"})

        assert updated is observation
        db.add.assert_called_once_with(observation)
        db.flush.assert_awaited_once()
        assert observation.review_state == "ignored"

    @pytest.mark.asyncio
    async def test_update_review_state_keeps_id_compatibility(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ):
        repo = MapObservationRepository()
        db = MagicMock()
        db.flush = AsyncMock()
        observation_id = uuid.uuid4()
        observation = MapObservation(id=observation_id, review_state="candidate")

        async def fake_get(_db, oid):
            assert oid == observation_id
            return observation

        monkeypatch.setattr(repo, "get", fake_get)

        updated = await repo.update_review_state(db, observation_id, "confirmed")

        assert updated is observation
        assert observation.review_state == "confirmed"


class TestMapFactRepository:
    @pytest.mark.asyncio
    async def test_update_status_reuses_loaded_fact(self):
        repo = MapFactRepository()
        db = MagicMock()
        db.flush = AsyncMock()
        fact = MapFact(id=uuid.uuid4(), fact_status="confirmed")

        updated = await repo.update_status(db, fact, "rolled_back")

        assert updated is fact
        db.add.assert_called_once_with(fact)
        db.flush.assert_awaited_once()
        assert fact.fact_status == "rolled_back"

    @pytest.mark.asyncio
    async def test_update_status_keeps_id_compatibility(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ):
        repo = MapFactRepository()
        db = MagicMock()
        db.flush = AsyncMock()
        fact_id = uuid.uuid4()
        fact = MapFact(id=fact_id, fact_status="confirmed")

        async def fake_get(_db, fid):
            assert fid == fact_id
            return fact

        monkeypatch.setattr(repo, "get", fake_get)

        updated = await repo.update_status(db, fact_id, "rolled_back")

        assert updated is fact
        assert fact.fact_status == "rolled_back"
