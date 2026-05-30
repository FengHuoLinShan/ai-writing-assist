"""RelationshipService — 关系 CRUD"""

from __future__ import annotations

from fastapi import HTTPException
from fastapi import status as http_status
from sqlalchemy.ext.asyncio import AsyncSession

from modules.world.repositories import RelationshipRepository, CoreEntityRepository
from modules.world.schemas import (
    RelationshipCreate,
    RelationshipResponse,
    RelationshipUpdate,
    CoreEntityContext,
)
from modules.world.services.helpers import parse_uuid
from shared.constants import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE


class RelationshipService:
    """关系业务服务"""

    def __init__(self) -> None:
        self._repo = RelationshipRepository()
        self._entity_repo = CoreEntityRepository()

    async def create(
        self,
        db: AsyncSession,
        novel_id: str,
        data: RelationshipCreate,
    ) -> RelationshipResponse:
        """创建关系"""
        nid = parse_uuid(novel_id, "novel_id")
        rel = await self._repo.create(db, nid, data)
        return RelationshipResponse.model_validate(rel)

    async def get(
        self,
        db: AsyncSession,
        rel_id: str,
        novel_id: str | None = None,
    ) -> RelationshipResponse:
        """获取关系详情"""
        rid = parse_uuid(rel_id, "relationship_id")
        rel = await self._repo.get(db, rid)
        if rel is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"Relationship {rel_id} not found",
            )
        if novel_id and str(rel.novel_id) != novel_id:
            raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND)
        return RelationshipResponse.model_validate(rel)

    async def list(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        skip: int = 0,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> tuple[list[RelationshipResponse], int]:
        """获取关系列表"""
        nid = parse_uuid(novel_id, "novel_id")
        limit = min(limit, MAX_PAGE_SIZE)
        items, total = await self._repo.get_by_novel(db, nid, skip=skip, limit=limit)
        return [RelationshipResponse.model_validate(r) for r in items], total

    async def update(
        self,
        db: AsyncSession,
        rel_id: str,
        data: RelationshipUpdate,
        novel_id: str | None = None,
    ) -> RelationshipResponse:
        """更新关系"""
        rid = parse_uuid(rel_id, "relationship_id")
        if novel_id:
            existing = await self._repo.get(db, rid)
            if existing is None or str(existing.novel_id) != novel_id:
                raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND)
        rel = await self._repo.update(db, rid, data)
        if rel is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"Relationship {rel_id} not found",
            )
        return RelationshipResponse.model_validate(rel)

    async def delete(
        self,
        db: AsyncSession,
        rel_id: str,
        novel_id: str | None = None,
    ) -> None:
        """删除关系"""
        rid = parse_uuid(rel_id, "relationship_id")
        if novel_id:
            existing = await self._repo.get(db, rid)
            if existing is None or str(existing.novel_id) != novel_id:
                raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND)
        deleted = await self._repo.delete(db, rid)
        if not deleted:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"Relationship {rel_id} not found",
            )

    async def expand_related(
        self,
        db: AsyncSession,
        novel_id: str,
        seed_entity_ids: list[str],
        depth: int = 1,
        limit: int = 20,
    ) -> list[CoreEntityContext]:
        """关系一跳/二跳扩展，返回相关对象的上下文列表"""
        nid = parse_uuid(novel_id, "novel_id")
        limit = min(limit, MAX_PAGE_SIZE)

        # 收集所有相关实体 ID
        related_ids: set[str] = set()
        for seed_id in seed_entity_ids:
            new_related = await self._repo.get_related_entity_ids(
                db, nid, seed_id, depth=depth, limit=limit,
            )
            related_ids.update(new_related)

        if not related_ids:
            return []

        # 按 limit 截断
        related_list = list(related_ids)[:limit]

        # 获取实体信息
        eids = [parse_uuid(eid, "entity_id") for eid in related_list]
        entities = await self._entity_repo.get_by_ids(db, nid, eids)

        contexts: list[CoreEntityContext] = []
        for entity in entities:
            contexts.append(CoreEntityContext(
                entity_id=str(entity.id),
                entity_type=entity.entity_type,
                name=entity.name,
                summary=entity.summary,
                public_info=entity.public_info,
                importance=entity.importance,
                importance_level=entity.importance_level,
                reveal_level=entity.reveal_level,
                status=entity.status,
                related_entity_ids=list(related_ids),
            ))

        return contexts
