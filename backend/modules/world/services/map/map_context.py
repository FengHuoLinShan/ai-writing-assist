"""地图子系统共享上下文守卫。

把地图操作中最常见的横切校验收敛到一个可注入的 depth module：
- novel_id 隔离（map / entity 属同 novel）
- hex 坐标在 grid 范围内
- entity 存在且类型符合预期
- 正式地图图层只引用已采用（canonical）实体

service 层通过构造注入 MapContext，测试时可替换为 fake。
"""

from __future__ import annotations

from collections.abc import Container
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import NotFoundError, ValidationError
from modules.world.map_repositories import MapConfigRepository
from modules.world.repositories import CoreEntityRepository
from modules.world.services.common import parse_uuid

if TYPE_CHECKING:
    from modules.world.map_models import MapConfig
    from modules.world.models import CoreEntity


class MapContext:
    """地图操作上下文守卫。

    接口很小，但把之前散落在各 service 中的重复校验集中到一个 seam 后。
    """

    def __init__(
        self,
        config_repo: MapConfigRepository | None = None,
        entity_repo: CoreEntityRepository | None = None,
    ) -> None:
        self._config_repo = config_repo or MapConfigRepository()
        self._entity_repo = entity_repo or CoreEntityRepository()

    async def require_map(
        self,
        db: AsyncSession,
        novel_id: str,
        map_id: str,
        *,
        allow_archived: bool = False,
    ) -> MapConfig:
        """校验 map 存在且属于指定 novel，返回 MapConfig；否则 404。"""
        nid = parse_uuid(novel_id, "novel_id")
        mid = parse_uuid(map_id, "map_id")
        config = await self._config_repo.get(db, mid)
        if config is None or config.novel_id != nid:
            raise NotFoundError(f"地图 {map_id} 不存在", code="map_not_found")
        if config.status != "active" and not allow_archived:
            raise NotFoundError(f"地图 {map_id} 不存在", code="map_not_found")
        if config.parent_entity_id is not None:
            owner = await self._entity_repo.get(db, config.parent_entity_id)
            if (
                owner is None
                or owner.novel_id != nid
                or owner.entity_type != "location"
                or owner.status != "canonical"
            ):
                raise NotFoundError(f"地图 {map_id} 不存在", code="map_not_found")
        return config

    async def require_entity(
        self,
        db: AsyncSession,
        novel_id: str,
        entity_id: str,
        *,
        allowed_types: Container[str] | None = None,
    ) -> CoreEntity:
        """校验 entity 存在、属于指定 novel 且类型符合预期，返回 CoreEntity；否则抛错。"""
        nid = parse_uuid(novel_id, "novel_id")
        eid = parse_uuid(entity_id, "entity_id")
        entity = await self._entity_repo.get(db, eid)
        if entity is None or entity.novel_id != nid:
            raise NotFoundError(f"实体 {entity_id} 不存在", code="entity_not_found")
        if allowed_types and entity.entity_type not in allowed_types:
            raise ValidationError(
                f"实体 {entity.name} 类型为 {entity.entity_type}，"
                f"只接受 {','.join(sorted(allowed_types))} 类型",
                code="invalid_entity_type",
            )
        return entity

    async def require_entities(
        self,
        db: AsyncSession,
        novel_id: str,
        entity_ids: list[str],
        *,
        allowed_types: Container[str] | None = None,
    ) -> list[CoreEntity]:
        """批量校验 entity 存在、属于指定 novel 且类型符合预期，保持输入顺序。"""
        nid = parse_uuid(novel_id, "novel_id")
        parsed_ids = [parse_uuid(entity_id, "entity_id") for entity_id in entity_ids]
        unique_ids = list(dict.fromkeys(parsed_ids))
        entities = await self._entity_repo.get_by_ids(db, nid, unique_ids)
        entity_by_id = {entity.id: entity for entity in entities}
        for raw_id, parsed_id in zip(entity_ids, parsed_ids, strict=True):
            entity = entity_by_id.get(parsed_id)
            if entity is None:
                raise NotFoundError(f"实体 {raw_id} 不存在", code="entity_not_found")
            if allowed_types and entity.entity_type not in allowed_types:
                raise ValidationError(
                    f"实体 {entity.name} 类型为 {entity.entity_type}，"
                    f"只接受 {','.join(sorted(allowed_types))} 类型",
                    code="invalid_entity_type",
                )
        return [entity_by_id[entity_id] for entity_id in parsed_ids]

    async def require_canonical_entity(
        self,
        db: AsyncSession,
        novel_id: str,
        entity_id: str,
        *,
        allowed_types: Container[str] | None = None,
    ) -> CoreEntity:
        """校验正式地图图层引用的实体。

        待处理实体可以被 observation / candidate 图层读取，但不能绕过
        采用流程直接写入 binding / marker / territory 正式图层。
        """
        entity = await self.require_entity(
            db,
            novel_id,
            entity_id,
            allowed_types=allowed_types,
        )
        self._assert_canonical(entity)
        return entity

    async def require_canonical_entities(
        self,
        db: AsyncSession,
        novel_id: str,
        entity_ids: list[str],
        *,
        allowed_types: Container[str] | None = None,
    ) -> list[CoreEntity]:
        """批量校验正式地图图层引用，并保持输入顺序。"""
        entities = await self.require_entities(
            db,
            novel_id,
            entity_ids,
            allowed_types=allowed_types,
        )
        for entity in entities:
            self._assert_canonical(entity)
        return entities

    def _assert_canonical(self, entity: CoreEntity) -> None:
        if entity.status == "canonical":
            return
        raise ValidationError(
            f"实体 {entity.name} 尚未采用，不能写入地图正式图层",
            code="unadopted_map_entity",
        )

    def assert_hex_in_bounds(
        self,
        config: MapConfig,
        hex_q: int,
        hex_r: int,
    ) -> None:
        """校验 hex 坐标在 grid 范围内，否则 400。"""
        if not (0 <= hex_q < config.grid_width):
            raise ValidationError(
                f"hex_q {hex_q} 超出网格宽度 {config.grid_width}",
                code="hex_out_of_bounds",
            )
        if not (0 <= hex_r < config.grid_height):
            raise ValidationError(
                f"hex_r {hex_r} 超出网格高度 {config.grid_height}",
                code="hex_out_of_bounds",
            )
