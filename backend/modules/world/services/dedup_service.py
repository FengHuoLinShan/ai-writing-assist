"""EntityDedupService — 已废弃（候选池去重不再需要）"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from modules.world.repositories import CoreEntityRepository
from modules.world.schemas import (
    CoreEntityUpdate,
    DuplicateSuggestionResult,
    WorldEntityResponse,
)
from modules.world.services.helpers import parse_uuid
from shared.constants import SIMILARITY_HIGH_CONFIDENCE, SIMILARITY_MEDIUM_CONFIDENCE


class EntityDedupService:
    """去重服务（已废弃 — AI 直写 canonical 不再需要去重）"""

    def __init__(self) -> None:
        self._entity_repo = CoreEntityRepository()

    async def find_duplicates(
        self,
        db: AsyncSession,
        novel_id: str,
        candidate_id: str,
    ) -> list[DuplicateSuggestionResult]:
        return []

    async def find_similar_entities(
        self,
        db: AsyncSession,
        novel_id: str,
        name: str,
        aliases: list[str] | None = None,
        entity_type: str | None = None,
    ) -> list[DuplicateSuggestionResult]:
        return []

    async def merge_candidate_into_entity(
        self,
        db: AsyncSession,
        novel_id: str,
        candidate_id: str,
        target_entity_id: str,
    ) -> Any:
        """合并候选到正史对象（已废弃 — 直接更新 entity status）"""
        cid = parse_uuid(candidate_id, "candidate_id")
        teid = parse_uuid(target_entity_id, "target_entity_id")

        entity = await self._entity_repo.get(db, cid)
        if entity is None:
            from fastapi import HTTPException
            from fastapi import status as http_status
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"Entity {candidate_id} not found",
            )

        update_data = CoreEntityUpdate(status="canonical")
        entity = await self._entity_repo.update(db, teid, update_data)
        return entity
