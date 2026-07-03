"""WorldEntityService — 核心实体 CRUD。继承 BaseCRUDService (ADR-0002)。

list 加 entity_type / status filter + 返 ListResponse (per design B3,
subclass override)。
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from modules.world.repositories import CoreEntityRepository
from modules.world.schemas import (
    CoreEntityCreate,
    CoreEntityListResponse,
    CoreEntityResponse,
    CoreEntityUpdate,
    EntityPromoteRequest,
    EntityPromoteResponse,
)
from modules.world.services.base import CrudService
from modules.world.services.helpers import parse_uuid
from shared.constants import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE

logger = logging.getLogger(__name__)


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
        source: str | None = None,
        workflow_id: str | None = None,
        needs_review: bool | None = None,
        auto_ingested: bool | None = None,
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
            source=source,
            workflow_id=workflow_id,
            needs_review=needs_review,
            auto_ingested=auto_ingested,
            skip=skip,
            limit=limit,
        )
        return CoreEntityListResponse(
            items=[CoreEntityResponse.model_validate(e) for e in items],
            total=total,
        )

    # ============================================================
    # Override: update 前打快照，支持手动编辑后回滚
    # ============================================================

    async def update(
        self,
        db: AsyncSession,
        id: str,
        data: CoreEntityUpdate,
        *,
        novel_id: str,
    ) -> CoreEntityResponse:
        """更新实体前为当前状态打快照；snapshot 失败不阻断主流程。"""
        from modules.world.services.entity_revision_service import (
            EntityRevisionService,
        )

        rid = parse_uuid(id, "entity_id")
        nid = parse_uuid(novel_id, "novel_id")
        existing = await self.repo.get(db, rid)
        self._assert_found_in_novel(existing, id, nid)
        assert existing is not None

        changed = data.model_dump(exclude_unset=True)
        if changed.get("status") == "canonical" and existing.status != "canonical":
            raise HTTPException(
                status_code=400,
                detail=(
                    "Use /entities/{entity_id}/promote "
                    "to promote entities to canonical"
                ),
            )

        if self._should_mark_user_edited(existing, changed):
            content_json = dict(existing.content_json or {})
            meta = dict(content_json.get("_meta") or {})
            meta.update(
                {
                    "user_edited": True,
                    "edited_at": datetime.now(UTC).isoformat(),
                }
            )
            content_json["_meta"] = meta
            data = data.model_copy(update={"content_json": content_json})

        try:
            revision_service = EntityRevisionService()
            await revision_service.create_snapshot(
                db,
                entity_id=id,
                novel_id=novel_id,
                revision_reason="manual_update",
            )
        except Exception:
            # snapshot 创建失败不应阻断编辑主流程，但需要记录日志便于排障
            logger.warning("实体 %s 手动编辑前快照失败", id, exc_info=True)

        result = await super().update(db, id, data, novel_id=novel_id)
        stale_reasons: list[str] = []
        if "name" in changed:
            stale_reasons.append("entity_renamed")
        if changed.get("status") == "ignored":
            stale_reasons.append("entity_ignored")
        elif changed.get("status") == "deprecated":
            stale_reasons.append("entity_deprecated")

        for reason in stale_reasons:
            try:
                from modules.context.facade import mark_asset_context_changed

                await mark_asset_context_changed(
                    db,
                    novel_id=novel_id,
                    asset_type="world_entity",
                    asset_id=id,
                    reason=reason,
                )
            except Exception:
                logger.warning(
                    "实体 %s 更新后标记上下文确认失效失败",
                    id,
                    exc_info=True,
                )
        return result

    @staticmethod
    def _should_mark_user_edited(entity: Any, changed: dict[str, Any]) -> bool:
        meta = (getattr(entity, "content_json", None) or {}).get("_meta") or {}
        return (
            bool(changed)
            and meta.get("source") == "deep_import"
            and meta.get("auto_ingested") is True
            and meta.get("user_edited") is not True
        )

    # ============================================================
    # Promote: 将草稿/候选实体提升为正史
    # ============================================================

    async def promote(
        self,
        db: AsyncSession,
        entity_id: str,
        data: EntityPromoteRequest,
        *,
        novel_id: str,
    ) -> EntityPromoteResponse:
        """将 draft/candidate 状态实体提升为 canonical。

        - 仅允许从 draft/candidate 提升；其他状态返回 400。
        - 自动设置 approved_by 与 status=canonical。
        """
        from fastapi import status as http_status

        rid = parse_uuid(entity_id, "entity_id")
        nid = parse_uuid(novel_id, "novel_id")

        entity = await self.repo.get(db, rid)
        self._assert_found_in_novel(entity, entity_id, nid)
        assert entity is not None

        if entity.status not in {"draft", "candidate"}:
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"无法提升状态为 '{entity.status}' 的实体，"
                    "仅 draft/candidate 可被提升为正史"
                ),
            )

        update_data = CoreEntityUpdate(
            status="canonical",
            approved_by=data.approved_by or "manual",
        )
        updated = await self.repo.update(db, rid, update_data)
        self._assert_found_in_novel(updated, entity_id, nid)
        assert updated is not None
        try:
            from modules.context.facade import mark_asset_context_changed

            await mark_asset_context_changed(
                db,
                novel_id=novel_id,
                asset_type="world_entity",
                asset_id=entity_id,
                reason="candidate_promoted",
            )
        except Exception:
            logger.warning(
                "实体 %s 提升后标记上下文确认复核失败",
                entity_id,
                exc_info=True,
            )

        return EntityPromoteResponse(
            entity_id=str(updated.id),
            status=updated.status,
            approved_by=updated.approved_by,
        )
