"""CoreEntityService — 共享核心实体 CRUD + 统一去重入口"""

from __future__ import annotations

from fastapi import HTTPException
from fastapi import status as http_status
from sqlalchemy.ext.asyncio import AsyncSession

from modules.world.models import CoreEntity
from modules.world.repositories import CoreEntityRepository
from modules.world.schemas import (
    CoreEntityContext,
    CoreEntityCreate,
    CoreEntityListResponse,
    CoreEntityResponse,
    CoreEntityUpdate,
    WorldContextBundle,
)
from modules.world.services.helpers import parse_uuid
from shared.constants import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE


class CoreEntityService:
    """共享核心实体业务服务 — 统一创建/去重入口"""

    def __init__(self) -> None:
        self._repo = CoreEntityRepository()

    async def create(
        self,
        db: AsyncSession,
        novel_id: str,
        data: CoreEntityCreate,
        skip_dedup: bool = False,
    ) -> CoreEntityResponse:
        """创建核心实体（统一入口）

        在此处进行去重检查，确保同名同类型不重复创建。
        创建后，调用方可通过 facade 联动创建扩展表记录。
        """
        nid = parse_uuid(novel_id, "novel_id")

        if not skip_dedup:
            await self._check_duplicate(db, nid, data.name, data.entity_type)

        entity = await self._repo.create(db, nid, data)
        return CoreEntityResponse.model_validate(entity)

    async def _check_duplicate(
        self,
        db: AsyncSession,
        novel_id,
        name: str,
        entity_type: str,
    ) -> None:
        """检查同名同类型实体是否已存在"""
        existing_id = await self._repo.find_entity_by_name(
            db, novel_id, name, entity_type=entity_type,
        )
        if existing_id is not None:
            raise HTTPException(
                status_code=http_status.HTTP_409_CONFLICT,
                detail=f'实体 "{name}"（类型 {entity_type}）已存在（id={existing_id}）',
            )

    async def get(
        self,
        db: AsyncSession,
        entity_id: str,
        novel_id: str | None = None,
    ) -> CoreEntityResponse:
        """获取核心实体详情"""
        eid = parse_uuid(entity_id, "entity_id")
        entity = await self._repo.get(db, eid)
        if entity is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"CoreEntity {entity_id} not found",
            )
        if novel_id and str(entity.novel_id) != novel_id:
            raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND)
        return CoreEntityResponse.model_validate(entity)

    async def list(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        entity_type: str | None = None,
        status: str | None = None,
        skip: int = 0,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> CoreEntityListResponse:
        """获取核心实体列表"""
        nid = parse_uuid(novel_id, "novel_id")
        limit = min(limit, MAX_PAGE_SIZE)
        items, total = await self._repo.get_by_novel(
            db, nid,
            entity_type=entity_type,
            status=status,
            skip=skip,
            limit=limit,
        )
        return CoreEntityListResponse(
            items=[CoreEntityResponse.model_validate(e) for e in items],
            total=total,
        )

    async def update(
        self,
        db: AsyncSession,
        entity_id: str,
        data: CoreEntityUpdate,
        novel_id: str | None = None,
    ) -> CoreEntityResponse:
        """更新核心实体 — 公共字段一次修改，全域生效"""
        eid = parse_uuid(entity_id, "entity_id")
        if novel_id:
            existing = await self._repo.get(db, eid)
            if existing is None or str(existing.novel_id) != novel_id:
                raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND)
        entity = await self._repo.update(db, eid, data)
        if entity is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"CoreEntity {entity_id} not found",
            )
        return CoreEntityResponse.model_validate(entity)

    async def delete(
        self,
        db: AsyncSession,
        entity_id: str,
        novel_id: str | None = None,
    ) -> None:
        """删除核心实体（ON DELETE CASCADE 自动清理扩展表）"""
        eid = parse_uuid(entity_id, "entity_id")
        if novel_id:
            existing = await self._repo.get(db, eid)
            if existing is None or str(existing.novel_id) != novel_id:
                raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND)
        deleted = await self._repo.delete(db, eid)
        if not deleted:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"CoreEntity {entity_id} not found",
            )

    async def get_entity_context(
        self,
        db: AsyncSession,
        novel_id: str,
        entity_ids: list[str] | None = None,
        reveal_mode: str = "author_safe",
        limit: int = 20,
    ) -> WorldContextBundle:
        """获取核心实体上下文包（供其他模块使用）"""
        nid = parse_uuid(novel_id, "novel_id")

        if entity_ids:
            eids = [parse_uuid(eid, "entity_id") for eid in entity_ids]
            entities = await self._repo.get_by_ids(db, nid, eids)
        else:
            entities, _ = await self._repo.get_by_novel(db, nid, limit=limit)

        contexts: list[CoreEntityContext] = []
        for entity in entities:
            ctx = _entity_to_context(entity, reveal_mode)
            contexts.append(ctx)

        return WorldContextBundle(
            novel_id=novel_id,
            entities=contexts,
            total_count=len(contexts),
            reveal_mode=reveal_mode,
        )

    async def add_alias(
        self,
        db: AsyncSession,
        entity_id: str,
        alias: str,
        alias_type: str = "name",
    ) -> bool:
        """添加别名到实体的 aliases JSONB"""
        eid = parse_uuid(entity_id, "entity_id")
        return await self._repo.add_alias(db, eid, alias, alias_type)

    async def remove_alias(
        self,
        db: AsyncSession,
        entity_id: str,
        alias: str,
    ) -> bool:
        """从实体的 aliases JSONB 移除别名"""
        eid = parse_uuid(entity_id, "entity_id")
        return await self._repo.remove_alias(db, eid, alias)


def _entity_to_context(
    entity: CoreEntity,
    reveal_mode: str,
) -> CoreEntityContext:
    """将 ORM 模型转为上下文对象，根据 reveal_mode 过滤信息"""
    hidden = None
    if reveal_mode == "author_only":
        hidden = entity.hidden_truth

    return CoreEntityContext(
        entity_id=str(entity.id),
        entity_type=entity.entity_type,
        name=entity.name,
        summary=entity.summary,
        public_info=entity.public_info,
        hidden_truth=hidden,
        importance=entity.importance,
        importance_level=entity.importance_level,
        reveal_level=entity.reveal_level,
        status=entity.status,
        aliases=entity.aliases or [],
    )
