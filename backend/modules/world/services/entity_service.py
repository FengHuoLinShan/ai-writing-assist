"""WorldEntityService — 核心实体 CRUD。继承 BaseCRUDService (ADR-0002)。

list 加 entity_type / status filter + 返 ListResponse (per design B3,
subclass override)。
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from modules.world.repositories import CoreEntityRepository
from modules.world.schemas import (
    CoreEntityCreate,
    CoreEntityListResponse,
    CoreEntityResponse,
    CoreEntityUpdate,
    WorldContextBundle,
)
from modules.world.services.base import CrudService
from modules.world.services.entity_alias_service import EntityAliasService
from modules.world.services.entity_context_service import EntityContextService
from modules.world.services.entity_embedding_service import EntityEmbeddingService
from modules.world.services.helpers import parse_uuid
from shared.constants import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE

_alias_service = EntityAliasService()
_context_service = EntityContextService()
_embedding_service = EntityEmbeddingService()


class WorldEntityService(
    CrudService[
        Any,
        CoreEntityCreate,
        CoreEntityUpdate,
        CoreEntityResponse,
    ],
):
    """核心实体业务服务。

    5 verb 继承自 base; list 加 filter (entity_type / status) + 返 ListResponse;
    扩展行为（别名、embedding、上下文）已拆分到独立服务。
    """

    repo = CoreEntityRepository()
    response = CoreEntityResponse
    label = "CoreEntity"
    id_param = "entity_id"

    # ============================================================
    # Override: create 加重复确认
    # ============================================================

    async def create(
        self,
        db: AsyncSession,
        novel_id: str,
        data: CoreEntityCreate,
    ) -> CoreEntityResponse:
        nid = parse_uuid(novel_id, "novel_id")

        # 手动创建默认标记来源
        if not data.created_by:
            data = data.model_copy(update={"created_by": "manual"})

        if not data.force_create:
            similar = await self.repo.find_similar_by_search_text(
                db,
                nid,
                data.name,
                entity_type=data.entity_type,
                status_filter=["canonical", "draft"],
                min_similarity=0.9,
                top_k=5,
            )
            if similar:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "requires_confirmation": True,
                        "similar_entities": [
                            {
                                "id": str(e.id),
                                "name": e.name,
                                "similarity_score": round(score, 2),
                            }
                            for e, score in similar[:5]
                        ],
                    },
                )

        obj = await self.repo.create(db, nid, data)
        return self._to_response(obj)

    # ============================================================
    # Override: list 加 filter kwargs + 返 ListResponse 包装
    # ============================================================

    async def list(  # type: ignore[override]
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        entity_type: str | None = None,
        status: str | None = None,
        q: str | None = None,
        skip: int = 0,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> CoreEntityListResponse:
        """带 filter 的 list, 返 ListResponse 包装 (不是 tuple)。"""
        nid = parse_uuid(novel_id, "novel_id")
        limit = min(limit, MAX_PAGE_SIZE)
        items, total = await self.repo.get_by_novel(
            db,
            nid,
            entity_type=entity_type,
            status=status,
            q=q,
            skip=skip,
            limit=limit,
        )
        return CoreEntityListResponse(
            items=[CoreEntityResponse.model_validate(e) for e in items],
            total=total,
        )

    # ============================================================
    # Compatibility shims: delegate to dedicated services
    # ============================================================

    async def get_entity_context(
        self,
        db: AsyncSession,
        novel_id: str,
        entity_ids: list[str] | None = None,
        reveal_mode: str = "author_safe",
        limit: int = 20,
        current_chapter: int | None = None,
    ) -> WorldContextBundle:
        return await _context_service.get_entity_context(
            db,
            novel_id,
            entity_ids=entity_ids,
            reveal_mode=reveal_mode,
            limit=limit,
            current_chapter=current_chapter,
        )

    async def list_entity_summaries(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        entity_type: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        return await _context_service.list_entity_summaries(
            db, novel_id, entity_type=entity_type, limit=limit
        )

    async def list_entity_terms(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        limit: int = 500,
    ) -> list[dict]:
        return await _context_service.list_entity_terms(
            db, novel_id, limit=limit
        )

    async def find_by_name(
        self,
        db: AsyncSession,
        novel_id: str,
        name: str,
        entity_type: str | None = None,
    ) -> str | None:
        return await _context_service.find_by_name(
            db, novel_id, name, entity_type=entity_type
        )

    async def list_entity_batches(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        limit: int = 10,
    ) -> list[dict]:
        return await _context_service.list_entity_batches(
            db, novel_id, limit=limit
        )

    async def list_aliases(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        skip: int = 0,
        limit: int = 100,
    ) -> list[dict]:
        return await _alias_service.list_aliases(
            db, novel_id, skip=skip, limit=limit
        )

    async def create_alias(
        self,
        db: AsyncSession,
        novel_id: str,
        entity_id: str,
        alias: str,
        alias_type: str = "name",
    ) -> dict:
        return await _alias_service.create_alias(
            db, novel_id, entity_id, alias, alias_type=alias_type
        )

    async def delete_alias(
        self,
        db: AsyncSession,
        novel_id: str,
        entity_id: str,
        alias: str,
    ) -> dict:
        return await _alias_service.delete_alias(
            db, novel_id, entity_id, alias
        )

    async def backfill_embeddings(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        batch_size: int = 64,
    ) -> int:
        return await _embedding_service.backfill_embeddings(
            db, novel_id, batch_size=batch_size
        )
