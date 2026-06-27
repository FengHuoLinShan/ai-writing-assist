"""AliasService — 别名 CRUD"""

from __future__ import annotations

from fastapi import HTTPException
from fastapi import status as http_status
from sqlalchemy.ext.asyncio import AsyncSession

from modules.world.repositories import EntityAliasRepository
from modules.world.schemas import EntityAliasCreate, EntityAliasResponse
from modules.world.services.helpers import parse_uuid
from shared.constants import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE


class AliasService:
    """别名业务服务"""

    def __init__(self) -> None:
        self._repo = EntityAliasRepository()

    async def create(
        self,
        db: AsyncSession,
        novel_id: str,
        data: EntityAliasCreate,
    ) -> EntityAliasResponse:
        """创建别名"""
        nid = parse_uuid(novel_id, "novel_id")
        alias = await self._repo.create(db, nid, data)
        return EntityAliasResponse.model_validate(alias)

    async def list(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        entity_id: str | None = None,
        skip: int = 0,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> tuple[list[EntityAliasResponse], int]:
        """获取别名列表"""
        nid = parse_uuid(novel_id, "novel_id")
        limit = min(limit, MAX_PAGE_SIZE)
        eid = parse_uuid(entity_id, "entity_id") if entity_id else None
        items, total = await self._repo.get_by_novel(
            db,
            nid,
            entity_id=eid,
            skip=skip,
            limit=limit,
        )
        return [EntityAliasResponse.model_validate(a) for a in items], total

    async def delete(
        self,
        db: AsyncSession,
        alias_id: str,
        novel_id: str | None = None,
    ) -> None:
        """删除别名"""
        aid = parse_uuid(alias_id, "alias_id")
        if novel_id:
            existing = await self._repo.get(db, aid)
            if existing is None or str(existing.novel_id) != novel_id:
                raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND)
        deleted = await self._repo.delete(db, aid)
        if not deleted:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"EntityAlias {alias_id} not found",
            )
