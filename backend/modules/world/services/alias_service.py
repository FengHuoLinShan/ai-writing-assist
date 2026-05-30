"""AliasService — 别名 CRUD（已废弃，保持兼容）"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from modules.world.schemas import EntityAliasCreate, EntityAliasResponse
from shared.constants import DEFAULT_PAGE_SIZE


class AliasService:
    """别名业务服务（已废弃，别名存储在 core_entities.content_json.aliases 中）"""

    async def create(
        self,
        db: AsyncSession,
        novel_id: str,
        data: EntityAliasCreate,
    ) -> EntityAliasResponse:
        return EntityAliasResponse(
            id=str(data.entity_id),
            novel_id=novel_id,
            entity_id=str(data.entity_id),
            alias=data.alias,
            alias_type=data.alias_type,
            source_chapter_index=data.source_chapter_index,
            confidence=data.confidence,
            status="confirmed",
        )

    async def list(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        entity_id: str | None = None,
        skip: int = 0,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> tuple[list[EntityAliasResponse], int]:
        return [], 0

    async def get(
        self,
        db: AsyncSession,
        alias_id: str,
        novel_id: str | None = None,
    ) -> EntityAliasResponse | None:
        return None

    async def delete(
        self,
        db: AsyncSession,
        alias_id: str,
        novel_id: str | None = None,
    ) -> None:
        pass
