"""EntityCandidateService — 候选对象池 CRUD + 晋升/合并"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import HTTPException
from fastapi import status as http_status
from sqlalchemy.ext.asyncio import AsyncSession

from modules.world.repositories import (
    CoreEntityRepository,
    EntityCandidateRepository,
)
from modules.world.schemas import (
    CoreEntityCreate,
    CoreEntityResponse,
    CoreEntityUpdate,
    EntityCandidateCreate,
    EntityCandidateListResponse,
    EntityCandidateResponse,
    EntityCandidateUpdate,
)
from modules.world.services.helpers import parse_uuid
from shared.constants import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE

logger = logging.getLogger(__name__)


class EntityCandidateService:
    """候选对象池业务服务"""

    def __init__(self) -> None:
        self._repo = EntityCandidateRepository()

    async def create(
        self, db: AsyncSession, novel_id: str, data: EntityCandidateCreate,
    ) -> EntityCandidateResponse:
        nid = parse_uuid(novel_id, "novel_id")
        candidate = await self._repo.create(db, nid, data)
        return EntityCandidateResponse.model_validate(candidate)

    async def get(
        self, db: AsyncSession, candidate_id: str, novel_id: str | None = None,
    ) -> EntityCandidateResponse:
        cid = parse_uuid(candidate_id, "candidate_id")
        candidate = await self._repo.get(db, cid)
        if candidate is None:
            raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND,
                               detail=f"EntityCandidate {candidate_id} not found")
        if novel_id and str(candidate.novel_id) != novel_id:
            raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND)
        return EntityCandidateResponse.model_validate(candidate)

    async def list(
        self, db: AsyncSession, novel_id: str, *,
        status: str | None = None, suggested_action: str | None = None,
        skip: int = 0, limit: int = DEFAULT_PAGE_SIZE,
    ) -> EntityCandidateListResponse:
        nid = parse_uuid(novel_id, "novel_id")
        limit = min(limit, MAX_PAGE_SIZE)
        items, total = await self._repo.get_by_novel(
            db, nid, status=status, suggested_action=suggested_action, skip=skip, limit=limit,
        )
        return EntityCandidateListResponse(
            items=[EntityCandidateResponse.model_validate(c) for c in items], total=total,
        )

    async def update(
        self, db: AsyncSession, candidate_id: str, data: EntityCandidateUpdate,
        novel_id: str | None = None,
    ) -> EntityCandidateResponse:
        cid = parse_uuid(candidate_id, "candidate_id")
        if novel_id:
            existing = await self._repo.get(db, cid)
            if existing is None or str(existing.novel_id) != novel_id:
                raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND)
        candidate = await self._repo.update(db, cid, data)
        if candidate is None:
            raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND,
                               detail=f"EntityCandidate {candidate_id} not found")
        return EntityCandidateResponse.model_validate(candidate)

    async def delete(
        self, db: AsyncSession, candidate_id: str, novel_id: str | None = None,
    ) -> None:
        cid = parse_uuid(candidate_id, "candidate_id")
        if novel_id:
            existing = await self._repo.get(db, cid)
            if existing is None or str(existing.novel_id) != novel_id:
                raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND)
        deleted = await self._repo.delete(db, cid)
        if not deleted:
            raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND,
                               detail=f"EntityCandidate {candidate_id} not found")

    async def accept_candidate(
        self, db: AsyncSession, novel_id: str, candidate_id: str, *,
        user_edits: dict[str, Any] | None = None,
    ) -> CoreEntityResponse:
        """将候选对象晋升为 CoreEntity"""
        nid = parse_uuid(novel_id, "novel_id")
        cid = parse_uuid(candidate_id, "candidate_id")
        candidate = await self._repo.get(db, cid)
        if candidate is None:
            raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND,
                               detail=f"EntityCandidate {candidate_id} not found")

        action = candidate.suggested_action
        edits = user_edits or {}

        if action in ("ignore", "temporary_only"):
            await self._repo.update_status(db, cid, "ignored")
            raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST,
                               detail=f"Candidate suggested action is '{action}', cannot promote")

        entity_repo = CoreEntityRepository()

        if action == "alias_of_existing" and candidate.suggested_existing_entity_id:
            existing_eid = parse_uuid(candidate.suggested_existing_entity_id, "entity_id")
            entity = await entity_repo.get(db, existing_eid)
            if entity is None:
                raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND,
                                   detail=f"Suggested entity {candidate.suggested_existing_entity_id} not found")
            if str(entity.novel_id) != str(nid):
                raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST,
                                   detail="Suggested entity does not belong to the same novel")
            # Add alias to core_entities.aliases JSONB
            await entity_repo.add_alias(db, existing_eid, candidate.name, "name")
            await self._repo.update_status(db, cid, "canonical")
            return CoreEntityResponse.model_validate(entity)

        if action == "merge_with_existing" and candidate.suggested_existing_entity_id:
            existing_eid = parse_uuid(candidate.suggested_existing_entity_id, "entity_id")
            entity = await entity_repo.get(db, existing_eid)
            if entity is None:
                raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND,
                                   detail=f"Entity to merge into {candidate.suggested_existing_entity_id} not found")
            if str(entity.novel_id) != str(nid):
                raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST,
                                   detail="Suggested entity does not belong to the same novel")

            merge_fields: dict[str, Any] = {
                "summary": candidate.summary or None,
                "importance": candidate.importance_score,
            }
            if edits:
                merge_fields.update(edits)
            update_data = CoreEntityUpdate(**{k: v for k, v in merge_fields.items() if v is not None})
            entity = await entity_repo.update(db, existing_eid, update_data)
            if entity is None:
                raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND,
                                   detail=f"Entity {candidate.suggested_existing_entity_id} not found")
            await self._repo.update_status(db, cid, "canonical")
            return CoreEntityResponse.model_validate(entity)

        # create_new
        from modules.world.services.entity_types import map_entity_type
        raw_type = edits.get("entity_type", candidate.entity_type)
        mapped_type = map_entity_type(raw_type)
        create_fields: dict[str, Any] = {
            "name": edits.get("name", candidate.name),
            "entity_type": mapped_type,
            "summary": edits.get("summary", candidate.summary or ""),
            "public_info": edits.get("public_info", ""),
            "hidden_truth": edits.get("hidden_truth", ""),
            "importance": edits.get("importance", candidate.importance_score),
            "importance_level": edits.get("importance_level", "normal"),
            "reveal_level": edits.get("reveal_level", "author_only"),
        }
        create_data = CoreEntityCreate(**create_fields)
        entity = await entity_repo.create(db, nid, create_data)
        await self._repo.update_status(db, cid, "canonical")

        # 自动创建扩展表记录
        if mapped_type in ("character", "character_ref"):
            try:
                from modules.character.facade import create_character_extension
                await create_character_extension(
                    db=db, entity_id=str(entity.id), novel_id=novel_id,
                )
            except Exception as exc:
                logger.warning("Failed to auto-create Character extension for %s: %s", candidate.name, exc)

        return CoreEntityResponse.model_validate(entity)
