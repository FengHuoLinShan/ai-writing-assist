"""WorldEntityService — 核心实体 CRUD。继承 BaseCRUDService (ADR-0002)。

list 加 entity_type / status filter + 返 ListResponse (per design B3,
subclass override)。
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from core.crud import CrudService
from core.errors import ConflictError, ValidationError
from modules.world.repositories import CoreEntityRepository
from modules.world.schemas import (
    CoreEntityCreate,
    CoreEntityListResponse,
    CoreEntityResponse,
    CoreEntityUpdate,
    EntityPromoteRequest,
    EntityPromoteResponse,
    EntityTypeCatalogResponse,
    EntityTypeOption,
)
from modules.world.services.common import parse_uuid
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

        # 人工创建本身已经表达采用意图。显式传入 draft/candidate 的旧调用方
        # 仍保持原状态，只有默认创建收敛为 canonical。
        create_updates: dict[str, str] = {}
        if not data.created_by:
            create_updates["created_by"] = "manual"
        if data.status == "canonical" and not data.approved_by:
            create_updates["approved_by"] = data.created_by or "manual"
        if create_updates:
            data = data.model_copy(update=create_updates)

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
                raise ConflictError(
                    {
                        "requires_confirmation": True,
                        "similar_entities": [
                            {
                                "id": str(e.id),
                                "name": e.name,
                                "entity_type": e.entity_type,
                                "status": e.status,
                                "similarity_score": round(score, 2),
                            }
                            for e, score in similar[:5]
                        ],
                    },
                )

        obj = await self.repo.create(db, nid, data)
        if obj.status == "canonical":
            from modules.world.services.worldbuilding.synopsis_invalidation import (
                mark_synopsis_source_changed,
            )

            await mark_synopsis_source_changed(
                db,
                novel_id,
                source_type="core_entity",
                source_id=str(obj.id),
            )
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
        display_state: str | None = None,
        q: str | None = None,
        source: str | None = None,
        workflow_id: str | None = None,
        needs_review: bool | None = None,
        auto_ingested: bool | None = None,
        suggested_action: str | None = None,
        scene_id: str | None = None,
        scene_index: int | None = None,
        source_chapter_index: int | None = None,
        confidence_min: float | None = None,
        confidence_max: float | None = None,
        skip: int = 0,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> CoreEntityListResponse:
        """带 filter 的 list, 返 ListResponse 包装 (不是 tuple)。"""
        nid = parse_uuid(novel_id, "novel_id")
        if display_state not in {None, "active", "review", "archived"}:
            raise ValidationError("Invalid display_state")
        limit = min(limit, MAX_PAGE_SIZE)
        items, total = await self.repo.get_by_novel(
            db,
            nid,
            entity_type=entity_type,
            status=status,
            display_state=display_state,
            q=q,
            source=source,
            workflow_id=workflow_id,
            needs_review=needs_review,
            auto_ingested=auto_ingested,
            suggested_action=suggested_action,
            scene_id=scene_id,
            scene_index=scene_index,
            source_chapter_index=source_chapter_index,
            confidence_min=confidence_min,
            confidence_max=confidence_max,
            skip=skip,
            limit=limit,
        )
        return CoreEntityListResponse(
            items=[CoreEntityResponse.model_validate(e) for e in items],
            total=total,
        )

    async def list_entity_types(
        self,
        db: AsyncSession,
        novel_id: str,
    ) -> EntityTypeCatalogResponse:
        from modules.world.services.core.entity_types import (
            SUPPORTED_ENTITY_TYPES,
            SYSTEM_ENTITY_TYPE_CATALOG,
        )

        nid = parse_uuid(novel_id, "novel_id")
        stored = await self.repo.list_distinct_entity_types(db, nid)
        items = [
            EntityTypeOption(value=value, label=label, kind="system")
            for value, label in SYSTEM_ENTITY_TYPE_CATALOG
        ]
        items.extend(
            EntityTypeOption(value=value, label=value, kind="custom")
            for value in sorted(
                (value for value in stored if value not in SUPPORTED_ENTITY_TYPES),
                key=str.casefold,
            )
        )
        return EntityTypeCatalogResponse(items=items)

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
        _from_suggestion_queue: bool = False,
    ) -> CoreEntityResponse:
        """更新实体前打快照；类型转换时 snapshot 属于原子迁移契约。"""
        from modules.world.services.core.entity_revision_service import (
            EntityRevisionService,
        )

        rid = parse_uuid(id, "entity_id")
        nid = parse_uuid(novel_id, "novel_id")
        existing = await self.repo.get_for_update(db, rid)
        self._assert_found_in_novel(existing, id, nid)
        assert existing is not None

        if self._is_suggestion_compatibility_shadow(existing) and not (
            _from_suggestion_queue
        ):
            raise ValidationError("该实体由待处理建议管理，请通过对应建议执行编辑或裁决")

        changed = data.model_dump(exclude_unset=True)
        new_type = changed.get("entity_type")
        type_changed = new_type is not None and new_type != existing.entity_type
        if changed.get("status") == "canonical" and existing.status != "canonical":
            raise ValidationError(
                "Use /entities/{entity_id}/promote to promote entities to canonical"
            )

        if self._should_mark_user_edited(existing, changed):
            submitted_content = changed.get("content_json")
            content_json = dict(
                submitted_content
                if isinstance(submitted_content, dict)
                else (existing.content_json or {})
            )
            meta = {
                **dict((existing.content_json or {}).get("_meta") or {}),
                **dict(content_json.get("_meta") or {}),
            }
            meta.update(
                {
                    "user_edited": True,
                    "edited_at": datetime.now(UTC).isoformat(),
                }
            )
            content_json["_meta"] = meta
            data = data.model_copy(update={"content_json": content_json})

        revision_service = EntityRevisionService()
        if type_changed:
            await revision_service.create_snapshot(
                db,
                entity_id=id,
                novel_id=novel_id,
                revision_reason="manual_update",
            )
        else:
            try:
                await revision_service.create_snapshot(
                    db,
                    entity_id=id,
                    novel_id=novel_id,
                    revision_reason="manual_update",
                )
            except Exception:
                logger.warning("实体 %s 手动编辑前快照失败", id, exc_info=True)

        if type_changed:
            from modules.world.services.core.entity_type_transition_service import (
                EntityTypeTransitionService,
            )

            await EntityTypeTransitionService().transition(
                db,
                entity=existing,
                new_type=new_type,
                changed_by="manual",
            )

        updated = await self.repo.update(db, existing, data)
        self._assert_found_in_novel(updated, id, nid)
        result = self._to_response(updated)
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
        if type_changed:
            from modules.context.facade import mark_asset_context_changed

            await mark_asset_context_changed(
                db,
                novel_id=novel_id,
                asset_type="world_entity",
                asset_id=id,
                reason="entity_type_changed",
            )
        if existing.status == "canonical" or updated.status == "canonical":
            from modules.world.services.worldbuilding.synopsis_invalidation import (
                mark_synopsis_source_changed,
            )

            await mark_synopsis_source_changed(
                db,
                novel_id,
                source_type="core_entity",
                source_id=id,
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

    @staticmethod
    def _is_suggestion_compatibility_shadow(entity: Any) -> bool:
        meta = (getattr(entity, "content_json", None) or {}).get("_meta") or {}
        return (
            getattr(entity, "status", None) in {"draft", "candidate"}
            and meta.get("compatibility_shadow") is True
            and bool(meta.get("suggestion_id"))
        )

    async def delete(
        self,
        db: AsyncSession,
        id: str,
        *,
        novel_id: str,
    ) -> None:
        from modules.world.services.core.entity_revision_service import (
            EntityRevisionService,
        )

        rid = parse_uuid(id, "entity_id")
        nid = parse_uuid(novel_id, "novel_id")
        existing = await self.repo.get(db, rid)
        self._assert_found_in_novel(existing, id, nid)
        assert existing is not None
        if self._is_suggestion_compatibility_shadow(existing):
            raise ValidationError("该实体由待处理建议管理，请通过对应建议执行忽略")
        if existing.status == "deprecated":
            return

        try:
            async with db.begin_nested():
                await EntityRevisionService().create_snapshot(
                    db,
                    entity_id=id,
                    novel_id=novel_id,
                    revision_reason="manual_delete",
                )
        except Exception:
            logger.warning("实体 %s 手动废弃前快照失败", id, exc_info=True)

        existing.status = "deprecated"
        await db.flush()

        from modules.world.services.worldbuilding.synopsis_invalidation import (
            mark_synopsis_source_changed,
        )

        await mark_synopsis_source_changed(
            db,
            novel_id,
            source_type="core_entity",
            source_id=id,
        )

        try:
            async with db.begin_nested():
                from modules.context.facade import mark_asset_context_changed

                await mark_asset_context_changed(
                    db,
                    novel_id=novel_id,
                    asset_type="world_entity",
                    asset_id=id,
                    reason="entity_deprecated",
                )
        except Exception:
            logger.warning(
                "实体 %s 手动废弃后标记上下文确认失效失败",
                id,
                exc_info=True,
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
        _from_suggestion_queue: bool = False,
    ) -> EntityPromoteResponse:
        """将 draft/candidate 状态实体提升为 canonical。

        - 仅允许从 draft/candidate 提升；其他状态返回 400。
        - 自动设置 approved_by 与 status=canonical。
        """
        rid = parse_uuid(entity_id, "entity_id")
        nid = parse_uuid(novel_id, "novel_id")

        entity = await self.repo.get_for_update(db, rid)
        self._assert_found_in_novel(entity, entity_id, nid)
        assert entity is not None

        if entity.status not in {"draft", "candidate"}:
            raise ValidationError(
                f"无法提升状态为 '{entity.status}' 的实体，"
                "只有待处理的 draft/candidate 实体可以采用"
            )

        content_json = dict(entity.content_json or {})
        meta = dict(content_json.get("_meta") or {})
        if meta.get("compatibility_shadow") is True and not _from_suggestion_queue:
            raise ValidationError("该实体由待处理建议管理，请通过对应建议执行采用")

        changes = {
            key: value
            for key, value in data.model_dump(
                exclude_unset=True,
                exclude={"approved_by"},
            ).items()
            if value is not None
        }
        new_type = changes.get("entity_type")
        type_changed = new_type is not None and new_type != entity.entity_type
        if changes:
            from modules.world.services.core.entity_revision_service import (
                EntityRevisionService,
            )

            if type_changed:
                await EntityRevisionService().create_snapshot(
                    db,
                    entity_id=entity_id,
                    novel_id=novel_id,
                    revision_reason="manual_update",
                )
            else:
                try:
                    async with db.begin_nested():
                        await EntityRevisionService().create_snapshot(
                            db,
                            entity_id=entity_id,
                            novel_id=novel_id,
                            revision_reason="manual_update",
                        )
                except Exception:
                    logger.warning(
                        "实体 %s 编辑后采用前快照失败",
                        entity_id,
                        exc_info=True,
                    )

        approved_by = data.approved_by or "manual"
        if _from_suggestion_queue:
            meta["compatibility_shadow"] = False
            meta["compatibility_shadow_adopted"] = True
            meta["suggestion_disposition"] = "accepted"
        meta["needs_review"] = False
        if changes:
            meta["user_edited"] = True
            meta["edited_at"] = datetime.now(UTC).isoformat()
        meta["reviewed_at"] = datetime.now(UTC).isoformat()
        meta["reviewed_by"] = approved_by
        meta["reviewed_from"] = (
            "entity_edit_promote" if changes else "entity_promote"
        )
        content_json["_meta"] = meta
        update_data = CoreEntityUpdate(
            **changes,
            status="canonical",
            approved_by=approved_by,
            content_json=content_json,
        )
        if type_changed:
            from modules.world.services.core.entity_type_transition_service import (
                EntityTypeTransitionService,
            )

            await EntityTypeTransitionService().transition(
                db,
                entity=entity,
                new_type=new_type,
                changed_by=approved_by,
            )
        updated = await self.repo.update(db, entity, update_data)
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
        if type_changed:
            from modules.context.facade import mark_asset_context_changed

            await mark_asset_context_changed(
                db,
                novel_id=novel_id,
                asset_type="world_entity",
                asset_id=entity_id,
                reason="entity_type_changed",
            )

        from modules.world.services.worldbuilding.synopsis_invalidation import (
            mark_synopsis_source_changed,
        )

        await mark_synopsis_source_changed(
            db,
            novel_id,
            source_type="core_entity",
            source_id=entity_id,
        )

        return EntityPromoteResponse(
            entity_id=str(updated.id),
            status=updated.status,
            approved_by=updated.approved_by,
        )
