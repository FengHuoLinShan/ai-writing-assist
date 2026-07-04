"""EntityRelationService — 关系 CRUD。继承 BaseCRUDService (ADR-0002)。"""

from __future__ import annotations

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
    EntityRelationUpdate,
    WorldEntityContext,
)
from modules.world.services.helpers import parse_uuid
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
        return created.model_copy(
            update={
                "source_name": getattr(source, "name", ""),
                "target_name": getattr(target, "name", ""),
            }
        )

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
            return {"action": "created", "relation": response}

        existing.description = _merge_text(existing.description, data.description)
        existing.quote = _merge_text(existing.quote, data.quote)
        existing.strength = max(float(existing.strength or 0.0), float(data.strength))
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
        return {"action": "merged", "relation": response}

    async def list(  # type: ignore[override]
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        skip: int = 0,
        limit: int = 100,
    ) -> EntityRelationListResponse:
        nid = parse_uuid(novel_id, "novel_id")
        limit = min(limit, MAX_PAGE_SIZE)
        relations, total = await self.repo.get_by_novel(
            db,
            nid,
            skip=skip,
            limit=limit,
        )
        return EntityRelationListResponse(
            items=[self._response_with_endpoint_names(rel) for rel in relations],
            total=total,
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
