"""MapEntityRepository 泛型基类行为测试。

验证放置型实体 repository 共享的 CRUD 不变量：
- novel_id / map_id 隔离
- update 只应用传入的 values dict
- delete 按 id 执行
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import Delete, Select, Update

from modules.world.map_models import (
    MapLocationBinding,
    MapMarker,
    MapTerritoryTile,
)
from modules.world.map_repositories import (
    MapEntityRepository,
    MapLocationBindingRepository,
    MapMarkerRepository,
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
    async def test_update_applies_values_dict(self):
        repo = MapTerritoryRepository()
        db = AsyncMock()
        tid = uuid.uuid4()

        from unittest.mock import MagicMock

        update_result = MagicMock()
        update_result.rowcount = 1
        get_result = MagicMock()
        get_result.scalar_one_or_none.return_value = None
        db.execute.side_effect = [update_result, get_result]

        await repo.update(db, tid, {"style_override": {"color": "#f00"}})

        assert db.execute.call_count == 2  # update + get
        stmt = db.execute.call_args_list[0][0][0]
        assert isinstance(stmt, Update)
        # 更新语句应作用于 territory 表且包含 style_override 绑定参数
        stmt_str = str(stmt.compile())
        assert "map_territory_tiles" in stmt_str
        assert "style_override" in stmt_str

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
