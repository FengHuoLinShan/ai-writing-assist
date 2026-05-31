"""CoreEntityService — 核心实体 CRUD"""

from __future__ import annotations

from fastapi import HTTPException
from fastapi import status as http_status
from sqlalchemy.ext.asyncio import AsyncSession

from modules.world.models import CoreEntity
from modules.world.repositories import CoreEntityRepository
from modules.world.schemas import (
    CoreEntityCreate,
    CoreEntityListResponse,
    CoreEntityResponse,
    CoreEntityUpdate,
    WorldContextBundle,
    WorldEntityContext,
)
from modules.world.services.helpers import parse_uuid
from shared.constants import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE


class WorldEntityService:
    """核心实体业务服务"""

    def __init__(self) -> None:
        self._repo = CoreEntityRepository()

    async def create(
        self,
        db: AsyncSession,
        novel_id: str,
        data: CoreEntityCreate,
    ) -> CoreEntityResponse:
        nid = parse_uuid(novel_id, "novel_id")
        entity = await self._repo.create(db, nid, data)
        return CoreEntityResponse.model_validate(entity)

    async def get(
        self,
        db: AsyncSession,
        entity_id: str,
        novel_id: str | None = None,
    ) -> CoreEntityResponse:
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
        nid = parse_uuid(novel_id, "novel_id")

        if entity_ids:
            eids = [parse_uuid(eid, "entity_id") for eid in entity_ids]
            entities = await self._repo.get_by_ids(db, nid, eids)
        else:
            entities, _ = await self._repo.get_by_novel(db, nid, limit=limit)

        contexts: list[WorldEntityContext] = []
        for entity in entities:
            ctx = _entity_to_context(entity, reveal_mode)
            contexts.append(ctx)

        return WorldContextBundle(
            novel_id=novel_id,
            entities=contexts,
            total_count=len(contexts),
            reveal_mode=reveal_mode,
        )

    async def list_entity_summaries(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        entity_type: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        nid = parse_uuid(novel_id, "novel_id")
        result = await self._repo.get_by_type_and_status(db, nid, entity_type=entity_type, limit=limit)
        return [
            {"id": item.id, "name": item.name, "entity_type": item.entity_type}
            for item in result
        ]


def _entity_to_context(
    entity: CoreEntity,
    reveal_mode: str,
) -> WorldEntityContext:
    hidden = None
    if reveal_mode == "author_only":
        hidden = entity.hidden_truth

    return WorldEntityContext(
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
    )
