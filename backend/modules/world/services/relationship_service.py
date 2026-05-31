"""RelationshipService — 旧关系 CRUD（委派到新 EntityRelationService）"""

from __future__ import annotations

from fastapi import HTTPException
from fastapi import status as http_status
from sqlalchemy.ext.asyncio import AsyncSession

from modules.world.repositories import CoreEntityRepository, EntityRelationRepository
from modules.world.schemas import (
    EntityRelationCreate,
    EntityRelationResponse,
    EntityRelationUpdate,
    RelationshipCreate,
    RelationshipResponse,
    WorldEntityContext,
)
from modules.world.services.helpers import parse_uuid
from shared.constants import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE


class RelationshipService:
    """关系业务服务（向后兼容，内部委托给 EntityRelationService）"""

    def __init__(self) -> None:
        self._repo = EntityRelationRepository()
        self._entity_repo = CoreEntityRepository()

    async def create(
        self,
        db: AsyncSession,
        novel_id: str,
        data: RelationshipCreate,
    ) -> RelationshipResponse:
        nid = parse_uuid(novel_id, "novel_id")
        # 将旧 RelationshipCreate 转为新 EntityRelationCreate
        new_data = EntityRelationCreate(
            source_id=data.source_id,
            target_id=data.target_id,
            relation_type=data.relation_type,
            description=data.description,
            strength=data.strength,
        )
        rel = await self._repo.create(db, nid, new_data)
        return RelationshipResponse(
            id=str(rel.id),
            novel_id=str(rel.novel_id),
            source_type="",
            source_id=str(rel.source_id),
            target_type="",
            target_id=str(rel.target_id),
            relation_type=rel.relation_type,
            description=rel.description,
            strength=rel.strength,
            status=rel.status,
            visibility=getattr(data, 'visibility', 'author_only'),
        )

    async def get(
        self,
        db: AsyncSession,
        rel_id: str,
        novel_id: str | None = None,
    ) -> RelationshipResponse:
        rid = parse_uuid(rel_id, "relationship_id")
        rel = await self._repo.get(db, rid)
        if rel is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"Relationship {rel_id} not found",
            )
        if novel_id and str(rel.novel_id) != novel_id:
            raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND)
        return RelationshipResponse(
            id=str(rel.id),
            novel_id=str(rel.novel_id),
            source_type="",
            source_id=str(rel.source_id),
            target_type="",
            target_id=str(rel.target_id),
            relation_type=rel.relation_type,
            description=rel.description,
            strength=rel.strength,
            status=rel.status,
        )

    async def list(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        skip: int = 0,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> tuple[list[RelationshipResponse], int]:
        nid = parse_uuid(novel_id, "novel_id")
        limit = min(limit, MAX_PAGE_SIZE)
        items, total = await self._repo.get_by_novel(db, nid, skip=skip, limit=limit)
        result = []
        for r in items:
            result.append(RelationshipResponse(
                id=str(r.id),
                novel_id=str(r.novel_id),
                source_type="",
                source_id=str(r.source_id),
                target_type="",
                target_id=str(r.target_id),
                relation_type=r.relation_type,
                description=r.description,
                strength=r.strength,
                status=r.status,
            ))
        return result, total

    async def update(
        self,
        db: AsyncSession,
        rel_id: str,
        data: RelationshipUpdate,
        novel_id: str | None = None,
    ) -> RelationshipResponse:
        rid = parse_uuid(rel_id, "relationship_id")
        if novel_id:
            existing = await self._repo.get(db, rid)
            if existing is None or str(existing.novel_id) != novel_id:
                raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND)
        new_data = EntityRelationUpdate(
            relation_type=data.relation_type,
            description=data.description,
            strength=data.strength,
            status=data.status,
        )
        rel = await self._repo.update(db, rid, new_data)
        if rel is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"Relationship {rel_id} not found",
            )
        return RelationshipResponse(
            id=str(rel.id),
            novel_id=str(rel.novel_id),
            source_type="",
            source_id=str(rel.source_id),
            target_type="",
            target_id=str(rel.target_id),
            relation_type=rel.relation_type,
            description=rel.description,
            strength=rel.strength,
            status=rel.status,
        )

    async def delete(
        self,
        db: AsyncSession,
        rel_id: str,
        novel_id: str | None = None,
    ) -> None:
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
