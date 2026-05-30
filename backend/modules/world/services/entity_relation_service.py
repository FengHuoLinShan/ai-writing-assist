"""EntityRelationService — 关系 CRUD"""

from __future__ import annotations

from fastapi import HTTPException
from fastapi import status as http_status
from sqlalchemy.ext.asyncio import AsyncSession

from modules.world.repositories import CoreEntityRepository, EntityRelationRepository
from modules.world.schemas import (
    EntityRelationCreate,
    EntityRelationListResponse,
    EntityRelationResponse,
    EntityRelationUpdate,
    WorldEntityContext,
)
from modules.world.services.helpers import parse_uuid
from shared.constants import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE


class EntityRelationService:
    """关系业务服务"""

    def __init__(self) -> None:
        self._repo = EntityRelationRepository()
        self._entity_repo = CoreEntityRepository()

    async def create(
        self,
        db: AsyncSession,
        novel_id: str,
        data: EntityRelationCreate,
    ) -> EntityRelationResponse:
        nid = parse_uuid(novel_id, "novel_id")
        rel = await self._repo.create(db, nid, data)
        return EntityRelationResponse.model_validate(rel)

    async def get(
        self,
        db: AsyncSession,
        rel_id: str,
        novel_id: str | None = None,
    ) -> EntityRelationResponse:
        rid = parse_uuid(rel_id, "relation_id")
        rel = await self._repo.get(db, rid)
        if rel is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"EntityRelation {rel_id} not found",
            )
        if novel_id and str(rel.novel_id) != novel_id:
            raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND)
        return EntityRelationResponse.model_validate(rel)

    async def list(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        skip: int = 0,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> tuple[list[EntityRelationResponse], int]:
        nid = parse_uuid(novel_id, "novel_id")
        limit = min(limit, MAX_PAGE_SIZE)
        items, total = await self._repo.get_by_novel(db, nid, skip=skip, limit=limit)
        return [EntityRelationResponse.model_validate(r) for r in items], total

    async def update(
        self,
        db: AsyncSession,
        rel_id: str,
        data: EntityRelationUpdate,
        novel_id: str | None = None,
    ) -> EntityRelationResponse:
        rid = parse_uuid(rel_id, "relation_id")
        if novel_id:
            existing = await self._repo.get(db, rid)
            if existing is None or str(existing.novel_id) != novel_id:
                raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND)
        rel = await self._repo.update(db, rid, data)
        if rel is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"EntityRelation {rel_id} not found",
            )
        return EntityRelationResponse.model_validate(rel)

    async def delete(
        self,
        db: AsyncSession,
        rel_id: str,
        novel_id: str | None = None,
    ) -> None:
        rid = parse_uuid(rel_id, "relation_id")
        if novel_id:
            existing = await self._repo.get(db, rid)
            if existing is None or str(existing.novel_id) != novel_id:
                raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND)
        deleted = await self._repo.delete(db, rid)
        if not deleted:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"EntityRelation {rel_id} not found",
            )

    async def get_traceable_relations(
        self,
        db: AsyncSession,
        novel_id: str,
        chapter_id: str,
    ) -> EntityRelationListResponse:
        """获取某章节建立的所有可追溯关系"""
        nid = parse_uuid(novel_id, "novel_id")
        cid = parse_uuid(chapter_id, "chapter_id")
        relations = await self._repo.get_traceable_relations(db, nid, cid)
        return EntityRelationListResponse(
            items=[EntityRelationResponse.model_validate(r) for r in relations],
            total=len(relations),
        )

    async def expand_related(
        self,
        db: AsyncSession,
        novel_id: str,
        seed_entity_ids: list[str],
        depth: int = 1,
        limit: int = 20,
    ) -> list[WorldEntityContext]:
        nid = parse_uuid(novel_id, "novel_id")
        limit = min(limit, MAX_PAGE_SIZE)

        related_ids: set[str] = set()
        for seed_id in seed_entity_ids:
            sid = parse_uuid(seed_id, "entity_id")
            new_related = await self._repo.get_related_entity_ids(
                db, nid, sid, depth=depth, limit=limit,
            )
            related_ids.update(str(rid) for rid in new_related)

        if not related_ids:
            return []

        related_list = list(related_ids)[:limit]
        eids = [parse_uuid(eid, "entity_id") for eid in related_list]
        entities = await self._entity_repo.get_by_ids(db, nid, eids)

        contexts: list[WorldEntityContext] = []
        for entity in entities:
            contexts.append(WorldEntityContext(
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

    async def upsert(
        self,
        db: AsyncSession,
        novel_id: str,
        source_id: str,
        target_id: str,
        relation_type: str,
        description: str | None = None,
    ) -> EntityRelationResponse:
        """创建或更新关系（按 source_id + target_id + relation_type 去重）"""
        nid = parse_uuid(novel_id, "novel_id")
        sid = parse_uuid(source_id, "source_id")
        tid = parse_uuid(target_id, "target_id")
        rel = await self._repo.upsert(
            db, nid, sid, tid, relation_type, description=description,
        )
        return EntityRelationResponse.model_validate(rel)
