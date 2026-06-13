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
)
from modules.world.services.base import CrudService
from modules.world.services.helpers import parse_uuid
from shared.constants import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE


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
