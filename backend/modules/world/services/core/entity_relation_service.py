"""EntityRelationService — 关系 CRUD。继承 BaseCRUDService (ADR-0002)。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.crud import CrudService
from core.errors import ConflictError, NotFoundError, ValidationError
from modules.world.models import EntityRelation
from modules.world.repositories import (
    CoreEntityRepository,
    EntityRelationRepository,
)
from modules.world.schemas import (
    EntityRelationCreate,
    EntityRelationListResponse,
    EntityRelationResponse,
    EntityRelationReviewEditRequest,
    EntityRelationUpdate,
    WorldEntityContext,
)
from modules.world.services.common import parse_uuid
from shared.constants import MAX_PAGE_SIZE


def _merge_text(existing: str | None, incoming: str | None) -> str | None:
    current = (existing or "").strip()
    addition = (incoming or "").strip()
    if not addition:
        return current or None
    if not current:
        return addition
    if addition in current:
        return current
    return f"{current}\n{addition}"


_RETIRED_ENTITY_STATUSES = {"merged", "ignored", "deprecated"}
_RELATION_STATUSES = {"candidate", "canonical", "deprecated"}


class EntityRelationService(
    CrudService[
        EntityRelation, EntityRelationCreate, EntityRelationUpdate, EntityRelationResponse
    ],  # noqa: E501
):
    """关系业务服务。

    5 verb 继承自 base; expand_related 跨表, upsert 去重, 留作特例。
    """

    repo = EntityRelationRepository()
    response = EntityRelationResponse
    label = "EntityRelation"
    id_param = "relation_id"

    # expand_related 跨表, 需要第二个 repo — 留作 __init__ 注入
    # (避开 base 的单 repo 假设, 显式化)
    def __init__(self) -> None:
        # base 的 CrudService 假设单 repo, 跨表操作是例外
        self._entity_repo = CoreEntityRepository()

    async def _require_distinct_entities_in_novel(
        self,
        db: AsyncSession,
        nid,
        sid,
        tid,
    ):
        if sid == tid:
            raise ValidationError("source_id and target_id must be different")

        source = await self._entity_repo.get(db, sid)
        target = await self._entity_repo.get(db, tid)
        if (
            source is None
            or target is None
            or source.novel_id != nid
            or target.novel_id != nid
        ):
            raise NotFoundError("Source or target entity not found in this novel")
        return source, target

    def _assert_active_relation_endpoint(self, entity: Any, field_name: str) -> None:
        if getattr(entity, "status", None) in _RETIRED_ENTITY_STATUSES:
            raise ValidationError(f"{field_name} cannot be retired entity")
        meta = dict((getattr(entity, "content_json", None) or {}).get("_meta") or {})
        if (
            getattr(entity, "status", None) in {"draft", "candidate"}
            and meta.get("compatibility_shadow") is True
            and meta.get("suggestion_id")
        ):
            raise ValidationError(
                f"{field_name} must adopt its authoritative suggestion first"
            )

    def _relation_snapshot(self, rel: EntityRelation) -> dict[str, object]:
        return {
            "id": str(rel.id),
            "source_id": str(rel.source_id),
            "target_id": str(rel.target_id),
            "relation_type": rel.relation_type,
            "description": rel.description,
            "strength": rel.strength,
            "status": rel.status,
        }

    def _review_meta(
        self,
        *,
        action: str,
        before: dict[str, object],
        after: dict[str, object],
        reviewed_from: str,
    ) -> dict[str, object]:
        return {
            "reviewed_at": datetime.now(UTC).isoformat(),
            "reviewed_by": "manual",
            "reviewed_from": reviewed_from,
            "review_action": action,
            "review_before": before,
            "review_after": after,
        }

    def _response_with_endpoint_names(
        self,
        rel: EntityRelation,
    ) -> EntityRelationResponse:
        response = EntityRelationResponse.model_validate(rel)
        return response.model_copy(
            update={
                "source_name": rel.source.name if rel.source is not None else None,
                "target_name": rel.target.name if rel.target is not None else None,
            }
        )

    def _to_response(self, obj: EntityRelation) -> EntityRelationResponse:
        return self._response_with_endpoint_names(obj)

    async def rollback_deep_import_candidates_by_workflow(
        self,
        db: AsyncSession,
        novel_id: str,
        workflow_id: str,
    ) -> int:
        """Archive untouched candidate relations owned by one import workflow."""
        nid = parse_uuid(novel_id, "novel_id")
        result = await db.execute(
            select(EntityRelation)
            .where(
                EntityRelation.novel_id == nid,
                EntityRelation.status == "candidate",
            )
            .with_for_update()
        )
        rolled_back_at = datetime.now(UTC).isoformat()
        count = 0
        for relation in result.scalars().all():
            meta = dict(relation.review_meta or {})
            if (
                meta.get("workflow_id") != workflow_id
                or meta.get("user_edited") is True
                or meta.get("reviewed_by") == "manual"
            ):
                continue
            relation.status = "deprecated"
            relation.review_meta = {
                **meta,
                "rolled_back": True,
                "rolled_back_at": rolled_back_at,
                "rollback_reason": "workflow_abandoned",
            }
            db.add(relation)
            count += 1
        await db.flush()
        return count

    # ============================================================
    # Override: create 加端点有效性与重复校验
    # ============================================================

    async def create(  # type: ignore[override]
        self,
        db: AsyncSession,
        novel_id: str,
        data: EntityRelationCreate,
    ) -> EntityRelationResponse:
        nid = parse_uuid(novel_id, "novel_id")
        sid = parse_uuid(data.source_id, "source_id")
        tid = parse_uuid(data.target_id, "target_id")

        source, target = await self._require_distinct_entities_in_novel(
            db,
            nid,
            sid,
            tid,
        )
        self._assert_active_relation_endpoint(source, "source_id")
        self._assert_active_relation_endpoint(target, "target_id")

        duplicate = await self.repo.find_duplicate_relation(
            db,
            nid,
            sid,
            tid,
            data.relation_type,
        )
        if duplicate is not None:
            raise ConflictError("Relation already exists")

        created = await super().create(db, novel_id, data)
        response = created.model_copy(
            update={
                "source_name": getattr(source, "name", ""),
                "target_name": getattr(target, "name", ""),
            }
        )
        if created.status == "canonical":
            await self._mark_synopsis_changed(db, novel_id, created.id)
        return response

    async def create_or_merge(
        self,
        db: AsyncSession,
        novel_id: str,
        data: EntityRelationCreate,
    ) -> dict[str, object]:
        """Create a relation or merge evidence into an existing same edge."""

        nid = parse_uuid(novel_id, "novel_id")
        sid = parse_uuid(data.source_id, "source_id")
        tid = parse_uuid(data.target_id, "target_id")
        source, target = await self._require_distinct_entities_in_novel(
            db,
            nid,
            sid,
            tid,
        )
        self._assert_active_relation_endpoint(source, "source_id")
        self._assert_active_relation_endpoint(target, "target_id")

        existing = await self.repo.find_duplicate_relation(
            db,
            nid,
            sid,
            tid,
            data.relation_type,
        )
        if existing is None:
            created = await super().create(db, novel_id, data)
            response = created.model_copy(
                update={
                    "source_name": getattr(source, "name", ""),
                    "target_name": getattr(target, "name", ""),
                }
            )
            if created.status == "canonical":
                await self._mark_synopsis_changed(db, novel_id, created.id)
            return {"action": "created", "relation": response}

        # A review-only import must never mutate an already adopted relation.
        # Treat the matching active edge as deterministic dedup and leave its
        # content, provenance, and strength untouched until an author makes an
        # explicit decision through the suggestion/review flow.
        if existing.status == "canonical" and data.status != "canonical":
            return {
                "action": "deduplicated",
                "relation": self._response_with_endpoint_names(existing),
            }

        existing.description = _merge_text(existing.description, data.description)
        existing.quote = _merge_text(existing.quote, data.quote)
        existing.strength = max(float(existing.strength or 0.0), float(data.strength))
        if data.review_meta:
            existing.review_meta = {
                **(existing.review_meta or {}),
                **data.review_meta,
            }
        if existing.status != "canonical" and data.status:
            existing.status = data.status
        if existing.source_chapter_id is None and data.source_chapter_id:
            existing.source_chapter_id = parse_uuid(data.source_chapter_id)
        if existing.caused_by_event_id is None and data.caused_by_event_id:
            existing.caused_by_event_id = parse_uuid(data.caused_by_event_id)
        db.add(existing)
        await db.flush()
        response = EntityRelationResponse.model_validate(existing).model_copy(
            update={
                "source_name": getattr(source, "name", ""),
                "target_name": getattr(target, "name", ""),
            }
        )
        if existing.status == "canonical":
            await self._mark_synopsis_changed(db, novel_id, existing.id)
        return {"action": "merged", "relation": response}

    async def list(  # type: ignore[override]
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        status: str | None = None,
        relation_type: str | None = None,
        q: str | None = None,
        source_chapter_id: str | None = None,
        strength_min: float | None = None,
        strength_max: float | None = None,
        skip: int = 0,
        limit: int = 100,
    ) -> EntityRelationListResponse:
        nid = parse_uuid(novel_id, "novel_id")
        chapter_id = (
            parse_uuid(source_chapter_id, "source_chapter_id")
            if source_chapter_id
            else None
        )
        limit = min(limit, MAX_PAGE_SIZE)
        relations, total = await self.repo.get_by_novel(
            db,
            nid,
            status=status,
            relation_type=relation_type,
            q=q,
            source_chapter_id=chapter_id,
            strength_min=strength_min,
            strength_max=strength_max,
            skip=skip,
            limit=limit,
        )
        return EntityRelationListResponse(
            items=[self._response_with_endpoint_names(rel) for rel in relations],
            total=total,
        )

    async def update(  # type: ignore[override]
        self,
        db: AsyncSession,
        id: str,
        data: EntityRelationUpdate,
        *,
        novel_id: str,
    ) -> EntityRelationResponse:
        rid = parse_uuid(id, self.id_param)
        nid = parse_uuid(novel_id, "novel_id")
        rel = await self.repo.get(db, rid)
        if rel is None or rel.novel_id != nid:
            raise NotFoundError(f"EntityRelation {id} not found")
        before = self._relation_snapshot(rel)
        if data.status is not None and data.status not in _RELATION_STATUSES:
            raise ValidationError("Invalid relation status")
        updated = await self.repo.update(db, rel, data)
        if updated is None:
            raise NotFoundError(f"EntityRelation {id} not found")
        if data.status is not None and before["status"] != updated.status:
            after = self._relation_snapshot(updated)
            updated.review_meta = {
                **(updated.review_meta or {}),
                **self._review_meta(
                    action="relation_status_updated",
                    before=before,
                    after=after,
                    reviewed_from="world_relations_update",
                ),
            }
            db.add(updated)
            await db.flush()
        if before["status"] == "canonical" or updated.status == "canonical":
            await self._mark_synopsis_changed(db, novel_id, updated.id)
        return self._response_with_endpoint_names(updated)

    async def review_edit(
        self,
        db: AsyncSession,
        novel_id: str,
        rel_id: str,
        data: EntityRelationReviewEditRequest,
    ) -> dict[str, object]:
        nid = parse_uuid(novel_id, "novel_id")
        rid = parse_uuid(rel_id, self.id_param)
        rel = await self.repo.get(db, rid)
        if rel is None or rel.novel_id != nid:
            raise NotFoundError(f"EntityRelation {rel_id} not found")
        if rel.status == "deprecated":
            raise ValidationError("Deprecated relation cannot be reviewed")

        before = self._relation_snapshot(rel)
        sid = parse_uuid(data.source_id, "source_id") if data.source_id else rel.source_id
        tid = parse_uuid(data.target_id, "target_id") if data.target_id else rel.target_id
        relation_type = (data.relation_type or rel.relation_type or "").strip()
        if not relation_type:
            raise ValidationError("relation_type cannot be blank")
        source, target = await self._require_distinct_entities_in_novel(
            db,
            nid,
            sid,
            tid,
        )
        self._assert_active_relation_endpoint(source, "source_id")
        self._assert_active_relation_endpoint(target, "target_id")

        duplicate = await self.repo.find_duplicate_relation(
            db,
            nid,
            sid,
            tid,
            relation_type,
            exclude_rel_id=rid,
        )
        if duplicate is not None:
            raise ConflictError(f"Relation already exists: {duplicate.id}")

        rel.source_id = sid
        rel.target_id = tid
        rel.relation_type = relation_type
        if data.description is not None:
            rel.description = data.description
        if data.strength is not None:
            rel.strength = data.strength
        if data.confirm_review:
            rel.status = "canonical"

        after = self._relation_snapshot(rel)
        rel.review_meta = {
            **(rel.review_meta or {}),
            **self._review_meta(
                action="relation_review_edit",
                before=before,
                after=after,
                reviewed_from="world_relations_review_edit",
            ),
        }
        db.add(rel)
        await db.flush()
        rel = await self.repo.get(db, rid) or rel
        response = self._response_with_endpoint_names(rel)
        if before["status"] == "canonical" or rel.status == "canonical":
            await self._mark_synopsis_changed(db, novel_id, rel.id)
        return {
            "relation": response.model_dump(mode="json"),
            "affected_ids": [str(rel.id)],
            "review_meta": rel.review_meta or {},
        }

    @staticmethod
    async def _mark_synopsis_changed(
        db: AsyncSession,
        novel_id: str,
        relation_id,
    ) -> None:
        from modules.world.services.worldbuilding.synopsis_invalidation import (
            mark_synopsis_source_changed,
        )

        await mark_synopsis_source_changed(
            db,
            novel_id,
            source_type="entity_relation",
            source_id=str(relation_id),
        )

    # ============================================================
    # 特例方法
    # ============================================================

    async def get_traceable_relations(
        self,
        db: AsyncSession,
        novel_id: str,
        chapter_id: str,
    ) -> EntityRelationListResponse:
        """获取某章节建立的所有可追溯关系。"""
        nid = parse_uuid(novel_id, "novel_id")
        cid = parse_uuid(chapter_id, "chapter_id")
        relations = await self.repo.get_traceable_relations(db, nid, cid)
        return EntityRelationListResponse(
            items=[self._response_with_endpoint_names(r) for r in relations],
            total=len(relations),
        )

    async def expand_related(
        self,
        db: AsyncSession,
        novel_id: str,
        seed_entity_ids: list[str],
        depth: int = 1,
        limit: int = 20,
    ) -> list[WorldEntityContext]:
        """图遍历扩展 — 跨 CoreEntity 表, 留作特例。"""
        nid = parse_uuid(novel_id, "novel_id")
        limit = min(limit, MAX_PAGE_SIZE)

        seed_ids = [parse_uuid(seed_id, "entity_id") for seed_id in seed_entity_ids]
        related_ids = {
            str(rid)
            for rid in await self.repo.get_related_entity_ids_for_seeds(
                db,
                nid,
                seed_ids,
                depth=depth,
                limit=limit,
            )
        }

        if not related_ids:
            return []

        related_list = list(related_ids)[:limit]
        eids = [parse_uuid(eid, "entity_id") for eid in related_list]
        entities = await self._entity_repo.get_by_ids(db, nid, eids)

        return [
            WorldEntityContext(
                entity_id=str(entity.id),
                entity_type=entity.entity_type,
                name=entity.name,
                summary=entity.summary,
                public_info=entity.public_info,
                importance=entity.importance,
                importance_level=entity.importance_level,
                reveal_level=entity.reveal_level,
                status=entity.status,
                related_entity_ids=list(related_ids),
            )
            for entity in entities
        ]

    async def get_by_entity(
        self,
        db: AsyncSession,
        novel_id: str,
        entity_id: str,
    ) -> EntityRelationListResponse:
        """获取实体的关联关系（source + target）"""
        nid = parse_uuid(novel_id, "novel_id")
        eid = parse_uuid(entity_id, "entity_id")
        source_rels = await self.repo.get_by_source(
            db,
            nid,
            eid,
            limit=MAX_PAGE_SIZE,
        )
        target_rels = await self.repo.get_by_target(
            db,
            nid,
            eid,
            limit=MAX_PAGE_SIZE,
        )
        all_rels = source_rels + target_rels
        return EntityRelationListResponse(
            items=[self._response_with_endpoint_names(r) for r in all_rels],
            total=len(all_rels),
        )

    async def upsert(
        self,
        db: AsyncSession,
        novel_id: str,
        source_id: str,
        target_id: str,
        relation_type: str,
        description: str | None = None,
    ) -> EntityRelationResponse:
        """按 source + target + relation_type 去重创建/更新。"""
        nid = parse_uuid(novel_id, "novel_id")
        sid = parse_uuid(source_id, "source_id")
        tid = parse_uuid(target_id, "target_id")
        source, target = await self._require_distinct_entities_in_novel(
            db,
            nid,
            sid,
            tid,
        )
        self._assert_active_relation_endpoint(source, "source_id")
        self._assert_active_relation_endpoint(target, "target_id")
        rel = await self.repo.upsert(
            db,
            nid,
            sid,
            tid,
            relation_type,
            description=description,
        )
        return EntityRelationResponse.model_validate(rel).model_copy(
            update={
                "source_name": getattr(source, "name", ""),
                "target_name": getattr(target, "name", ""),
            }
        )
