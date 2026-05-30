"""EntityCandidateService — 已废弃，仅保持接口兼容"""

from __future__ import annotations

from fastapi import HTTPException
from fastapi import status as http_status
from sqlalchemy.ext.asyncio import AsyncSession

from modules.world.repositories import CoreEntityRepository
from modules.world.schemas import (
    CoreEntityCreate,
    CoreEntityListResponse,
    CoreEntityResponse,
    EntityCandidateCreate,
    EntityCandidateListResponse,
    EntityCandidateResponse,
    EntityCandidateUpdate,
    WorldEntityResponse,
)
from modules.world.services.helpers import parse_uuid
from shared.constants import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE


class EntityCandidateService:
    """候选对象服务（已废弃 — AI 直写 canonical + 快照）"""

    def __init__(self) -> None:
        self._repo = CoreEntityRepository()

    async def create(
        self,
        db: AsyncSession,
        novel_id: str,
        data: EntityCandidateCreate,
    ) -> EntityCandidateResponse:
        nid = parse_uuid(novel_id, "novel_id")
        create_data = CoreEntityCreate(
            entity_type=data.entity_type or "unknown",
            name=data.name,
            summary=data.summary,
            status=data.status or "pending",
        )
        entity = await self._repo.create(db, nid, create_data)
        return EntityCandidateResponse(
            id=str(entity.id),
            novel_id=str(entity.novel_id),
            name=entity.name,
            entity_type=entity.entity_type,
            summary=entity.summary,
            status=entity.status,
        )

    async def get(
        self,
        db: AsyncSession,
        candidate_id: str,
        novel_id: str | None = None,
    ) -> EntityCandidateResponse:
        cid = parse_uuid(candidate_id, "candidate_id")
        entity = await self._repo.get(db, cid)
        if entity is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"Entity {candidate_id} not found",
            )
        return EntityCandidateResponse(
            id=str(entity.id),
            novel_id=str(entity.novel_id),
            name=entity.name,
            entity_type=entity.entity_type,
            summary=entity.summary,
            status=entity.status,
        )

    async def list(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        status: str | None = None,
        suggested_action: str | None = None,
        skip: int = 0,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> EntityCandidateListResponse:
        nid = parse_uuid(novel_id, "novel_id")
        limit = min(limit, MAX_PAGE_SIZE)
        items, total = await self._repo.get_by_novel(
            db, nid, status=status, skip=skip, limit=limit,
        )
        return EntityCandidateListResponse(
            items=[EntityCandidateResponse(
                id=str(e.id),
                novel_id=str(e.novel_id),
                name=e.name,
                entity_type=e.entity_type,
                summary=e.summary,
                status=e.status,
            ) for e in items],
            total=total,
        )

    async def update(
        self,
        db: AsyncSession,
        candidate_id: str,
        data: EntityCandidateUpdate,
        novel_id: str | None = None,
    ) -> EntityCandidateResponse:
        cid = parse_uuid(candidate_id, "candidate_id")
        if novel_id:
            existing = await self._repo.get(db, cid)
            if existing is None or str(existing.novel_id) != novel_id:
                raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND)
        from modules.world.schemas import CoreEntityUpdate
        update_data = CoreEntityUpdate(
            name=data.name,
            entity_type=data.entity_type,
            summary=data.summary,
            status=data.status,
        )
        entity = await self._repo.update(db, cid, update_data)
        return EntityCandidateResponse(
            id=str(entity.id),
            novel_id=str(entity.novel_id),
            name=entity.name,
            entity_type=entity.entity_type,
            summary=entity.summary,
            status=entity.status,
        )

    async def delete(
        self,
        db: AsyncSession,
        candidate_id: str,
        novel_id: str | None = None,
    ) -> None:
        cid = parse_uuid(candidate_id, "candidate_id")
        deleted = await self._repo.delete(db, cid)
        if not deleted:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"Entity {candidate_id} not found",
            )

    async def accept_candidate(
        self,
        db: AsyncSession,
        novel_id: str,
        candidate_id: str,
        user_edits: dict | None = None,
    ) -> WorldEntityResponse:
        """接受候选（已废弃 — 简单晋升为 canonical）"""
        cid = parse_uuid(candidate_id, "candidate_id")
        nid = parse_uuid(novel_id, "novel_id")

        existing = await self._repo.get(db, cid)
        if existing is None:
            raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND)

        from modules.world.schemas import CoreEntityUpdate
        update_data = CoreEntityUpdate(status="canonical")
        if user_edits:
            if "name" in user_edits:
                update_data.name = user_edits["name"]
            if "entity_type" in user_edits:
                update_data.entity_type = user_edits["entity_type"]
            if "summary" in user_edits:
                update_data.summary = user_edits["summary"]

        entity = await self._repo.update(db, cid, update_data)
        return WorldEntityResponse.model_validate(entity)
