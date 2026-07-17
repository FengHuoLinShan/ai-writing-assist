"""WorldEntityService — 核心实体 CRUD。继承 BaseCRUDService (ADR-0002)。

list 加 entity_type / status filter + 返 ListResponse (per design B3,
subclass override)。
"""

from __future__ import annotations

import logging
import math
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from core.container import get as _container_get
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
    EntityRankingContext,
    EntityRankingFacets,
    EntityRankingResponse,
    EntityTypeCatalogResponse,
    EntityTypeFacet,
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
            if obj.entity_type == "character":
                from modules.world.services.core.character_service import (
                    CharacterService,
                )

                await CharacterService().ensure_for_core_entity(db, obj)
            from modules.world.services.worldbuilding.synopsis_invalidation import (
                mark_synopsis_source_changed,
            )

            await mark_synopsis_source_changed(
                db,
                novel_id,
                source_type="core_entity",
                source_id=str(obj.id),
            )
            from modules.world.services.core.entity_activity_invalidation import (
                request_entity_activity_reannotation,
            )

            await request_entity_activity_reannotation(db, novel_id)
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
        view_mode: str = "normal",
        focus: str | None = None,
        skip: int = 0,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> CoreEntityListResponse:
        """带 filter 的 list, 返 ListResponse 包装 (不是 tuple)。"""
        nid = parse_uuid(novel_id, "novel_id")
        if display_state not in {None, "active", "review", "archived"}:
            raise ValidationError("Invalid display_state")
        limit = min(limit, MAX_PAGE_SIZE)
        if view_mode not in {"normal", "hot"}:
            raise ValidationError("Invalid view_mode")
        if focus not in {None, "important", "hot", "other"}:
            raise ValidationError("Invalid focus")
        if focus is not None and view_mode != "hot":
            raise ValidationError("focus requires hot view_mode")
        filter_kwargs = {
            "entity_type": entity_type,
            "status": status,
            "display_state": display_state,
            "q": q,
            "source": source,
            "workflow_id": workflow_id,
            "needs_review": needs_review,
            "auto_ingested": auto_ingested,
            "suggested_action": suggested_action,
            "scene_id": scene_id,
            "scene_index": scene_index,
            "source_chapter_index": source_chapter_index,
            "confidence_min": confidence_min,
            "confidence_max": confidence_max,
        }
        if view_mode == "hot":
            return await self._list_hot(
                db,
                nid,
                novel_id=novel_id,
                focus=focus,
                skip=skip,
                limit=limit,
                filter_kwargs=filter_kwargs,
            )

        items, total = await self.repo.get_by_novel(
            db,
            nid,
            **filter_kwargs,
            skip=skip,
            limit=limit,
        )
        return CoreEntityListResponse(
            items=[CoreEntityResponse.model_validate(e) for e in items],
            total=total,
        )

    async def _list_hot(
        self,
        db: AsyncSession,
        nid,
        *,
        novel_id: str,
        focus: str | None,
        skip: int,
        limit: int,
        filter_kwargs: dict[str, Any],
    ) -> CoreEntityListResponse:
        candidates = await self.repo.list_ranking_candidates(
            db,
            nid,
            **filter_kwargs,
        )
        activity = None
        try:
            activity = await _container_get("rag.get_entity_activity_stats")(
                db,
                novel_id,
            )
        except Exception:
            logger.warning(
                "world_entity_hot_activity_unavailable novel_id=%s",
                novel_id,
                exc_info=True,
            )
        activity_by_id = {
            item.entity_id: item for item in (getattr(activity, "items", None) or [])
        }
        as_of_chapter = getattr(activity, "as_of_chapter", None)
        ranked: list[dict[str, Any]] = []
        type_counts: dict[str, int] = {}
        important_count = 0
        hot_count = 0
        other_count = 0
        for candidate in candidates:
            entity_id = str(candidate["id"])
            semantic = self._semantic_importance(
                candidate.get("importance"),
                candidate.get("importance_level"),
            )
            stat = activity_by_id.get(entity_id)
            chapters = list(getattr(stat, "appearance_chapters", None) or [])
            heat = self._recent_heat(chapters, as_of_chapter)
            combined = 0.65 * semantic + 0.35 * heat
            important = (
                semantic >= 0.75
                or candidate.get("importance_level") in {"core", "important"}
            )
            hot = heat >= 0.55
            labels = [
                label
                for label, enabled in (("important", important), ("hot", hot))
                if enabled
            ]
            ranking = EntityRankingResponse(
                semantic_importance=semantic,
                recent_heat=heat,
                combined_score=min(1.0, max(0.0, combined)),
                labels=labels,
                last_appearance_chapter=(max(chapters) if chapters else None),
                recent_12_chapter_occurrences=(
                    sum(
                        1
                        for chapter in chapters
                        if as_of_chapter is not None
                        and as_of_chapter - 11 <= chapter <= as_of_chapter
                    )
                ),
            )
            candidate["ranking"] = ranking
            candidate["is_important"] = important
            candidate["is_hot"] = hot
            type_name = str(candidate.get("entity_type") or "unknown")
            type_counts[type_name] = type_counts.get(type_name, 0) + 1
            important_count += int(important)
            hot_count += int(hot)
            other_count += int(not important and not hot)
            ranked.append(candidate)

        facets = EntityRankingFacets(
            important=important_count,
            hot=hot_count,
            other=other_count,
            by_type=[
                EntityTypeFacet(entity_type=entity_type, count=count)
                for entity_type, count in sorted(
                    type_counts.items(),
                    key=lambda item: (-item[1], item[0]),
                )
            ],
        )
        if focus == "important":
            ranked = [item for item in ranked if item["is_important"]]
        elif focus == "hot":
            ranked = [item for item in ranked if item["is_hot"]]
        elif focus == "other":
            ranked = [
                item
                for item in ranked
                if not item["is_important"] and not item["is_hot"]
            ]

        has_query = bool(str(filter_kwargs.get("q") or "").strip())
        ranked.sort(
            key=lambda item: (
                -float(item.get("search_rank") or 0) if has_query else 0,
                -item["ranking"].combined_score,
                -(item["ranking"].last_appearance_chapter or 0),
                str(item.get("name") or ""),
                str(item["id"]),
            )
        )
        total = len(ranked)
        page = ranked[skip : skip + limit]
        page_ids = [item["id"] for item in page]
        models = await self.repo.get_by_ids(db, nid, page_ids)
        models_by_id = {model.id: model for model in models}
        responses = []
        for item in page:
            model = models_by_id.get(item["id"])
            if model is None:
                continue
            responses.append(
                CoreEntityResponse.model_validate(model).model_copy(
                    update={"ranking": item["ranking"]}
                )
            )
        return CoreEntityListResponse(
            items=responses,
            total=total,
            facets=facets,
            ranking_context=EntityRankingContext(
                status=getattr(activity, "status", "unavailable"),
                as_of_chapter=as_of_chapter,
                covered_chapters=getattr(activity, "covered_chapters", 0),
                total_chapters=getattr(activity, "total_chapters", 0),
            ),
        )

    @staticmethod
    def _semantic_importance(value: Any, level: Any) -> float:
        try:
            importance = float(value)
        except (TypeError, ValueError):
            importance = 0.5
        importance = min(1.0, max(0.0, importance))
        if level == "core":
            return max(importance, 0.85)
        if level == "important":
            return max(importance, 0.65)
        return importance

    @staticmethod
    def _recent_heat(chapters: list[int], as_of_chapter: int | None) -> float:
        if as_of_chapter is None:
            return 0.0
        weighted = sum(
            2 ** (-(as_of_chapter - chapter) / 6)
            for chapter in chapters
            if chapter <= as_of_chapter
        )
        return min(1.0, max(0.0, 1 - math.exp(-weighted / 3)))

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
        if updated.status == "canonical" and updated.entity_type == "character":
            from modules.world.services.core.character_service import CharacterService

            await CharacterService().ensure_for_core_entity(db, updated)
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
        if {"name", "entity_type", "status", "content_json"}.intersection(changed):
            from modules.world.services.core.entity_activity_invalidation import (
                request_entity_activity_reannotation,
            )

            await request_entity_activity_reannotation(db, novel_id)
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
        from modules.world.services.core.entity_activity_invalidation import (
            request_entity_activity_reannotation,
        )

        await request_entity_activity_reannotation(db, novel_id)

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
        if updated.entity_type == "character":
            from modules.world.services.core.character_service import CharacterService

            await CharacterService().ensure_for_core_entity(db, updated)
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
        from modules.world.services.core.entity_activity_invalidation import (
            request_entity_activity_reannotation,
        )

        await request_entity_activity_reannotation(db, novel_id)

        return EntityPromoteResponse(
            entity_id=str(updated.id),
            status=updated.status,
            approved_by=updated.approved_by,
        )
