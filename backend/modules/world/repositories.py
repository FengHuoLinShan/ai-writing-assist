"""
World 数据访问层 — v3 因果时空网

封装所有表的基本数据库操作。
只处理 ORM ↔ DB 的基本 CRUD，不含业务逻辑。
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import Text, delete, func, or_, select, text, update
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

from modules.world.models import (  # noqa: E402
    Character,
    CharacterKnowledge,
    CoreEntity,
    EntityRelation,
    EntityRevision,
    Event,
)
from modules.world.schemas import (  # noqa: E402
    CharacterCreate,
    CharacterKnowledgeCreate,
    CharacterKnowledgeUpdate,
    CharacterUpdate,
    CoreEntityCreate,
    CoreEntityUpdate,
    EntityRelationCreate,
    EntityRelationUpdate,
    EventCreate,
    EventUpdate,
)
from shared.constants import DEFAULT_PAGE_SIZE  # noqa: E402
from shared.utils import parse_uuid  # noqa: E402

# ============================================================
# CoreEntityRepository
# ============================================================


class CoreEntityRepository:
    """核心实体数据访问"""

    async def create(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        data: CoreEntityCreate,
    ) -> CoreEntity:
        entity = CoreEntity(
            novel_id=novel_id,
            entity_type=data.entity_type,
            name=data.name,
            summary=data.summary,
            public_info=data.public_info,
            hidden_truth=data.hidden_truth,
            content_json=data.content_json or {},
            importance=data.importance or 0.5,
            importance_level=data.importance_level or "normal",
            reveal_level=data.reveal_level or "author_only",
            status=data.status or "draft",
            created_by=data.created_by,
        )
        db.add(entity)
        await db.flush()
        return entity

    async def create_raw(
        self,
        db: AsyncSession,
        *,
        novel_id: uuid.UUID,
        entity_type: str,
        name: str,
        summary: str | None = None,
        content_json: dict | None = None,
        status: str = "draft",
    ) -> CoreEntity:
        entity = CoreEntity(
            novel_id=novel_id,
            entity_type=entity_type,
            name=name,
            summary=summary,
            content_json=content_json or {},
            status=status,
        )
        db.add(entity)
        await db.flush()
        return entity

    async def create_candidate(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        data,  # EntityCandidateCreate
    ) -> CoreEntity:
        """从旧 EntityCandidateCreate 创建候选（兼容 v2→v3 迁移）"""
        entity = CoreEntity(
            novel_id=novel_id,
            entity_type=data.entity_type,
            name=data.name,
            summary=data.summary,
            importance=data.importance_score or 0.5,
            importance_level="normal",
            status="pending",
            content_json={
                "source_text": data.source_text,
                "source_chapter_index": data.source_chapter_index,
                "confidence": data.confidence,
                "candidate_reason": data.candidate_reason,
                "suggested_action": data.suggested_action,
                "suggested_existing_entity_id": data.suggested_existing_entity_id,
            },
        )
        db.add(entity)
        await db.flush()
        return entity

    async def get(
        self,
        db: AsyncSession,
        entity_id: uuid.UUID,
    ) -> CoreEntity | None:
        stmt = select(CoreEntity).where(CoreEntity.id == entity_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_novel(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        *,
        entity_type: str | None = None,
        status: str | None = None,
        q: str | None = None,
        skip: int = 0,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> tuple[list[CoreEntity], int]:
        conditions = [CoreEntity.novel_id == novel_id]
        if entity_type:
            conditions.append(CoreEntity.entity_type == entity_type)
        if status:
            conditions.append(CoreEntity.status == status)
        if q:
            query = q.strip()
            if query:
                like_expr = f"%{query}%"
                # SQLite 中 SQLAlchemy JSON 序列化会转义非 ASCII 字符，
                # 因此同时用原始值和其 JSON 转义形式匹配 content_json。
                escaped_expr = f"%{json.dumps(query)[1:-1]}%"
                conditions.append(
                    or_(
                        CoreEntity.name.ilike(like_expr),
                        CoreEntity.content_json.cast(Text).ilike(like_expr),
                        CoreEntity.content_json.cast(Text).ilike(escaped_expr),
                    )
                )

        count_stmt = select(func.count(CoreEntity.id)).where(*conditions)
        count_result = await db.execute(count_stmt)
        total = count_result.scalar() or 0

        stmt = (
            select(CoreEntity)
            .where(*conditions)
            .offset(skip)
            .limit(limit)
            .order_by(CoreEntity.importance.desc(), CoreEntity.name)
        )
        result = await db.execute(stmt)
        items: Sequence[CoreEntity] = result.scalars().all()
        return list(items), total

    async def get_by_ids(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        entity_ids: list[uuid.UUID],
    ) -> list[CoreEntity]:
        if not entity_ids:
            return []
        stmt = select(CoreEntity).where(
            CoreEntity.novel_id == novel_id,
            CoreEntity.id.in_(entity_ids),
        )
        result = await db.execute(stmt)
        items: Sequence[CoreEntity] = result.scalars().all()
        return list(items)

    async def get_by_type_and_status(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        entity_type: str | None = None,
        status: str | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> list[CoreEntity]:
        conditions = [CoreEntity.novel_id == novel_id]
        if entity_type:
            conditions.append(CoreEntity.entity_type == entity_type)
        if status:
            conditions.append(CoreEntity.status == status)

        stmt = (
            select(CoreEntity)
            .where(*conditions)
            .limit(limit)
            .order_by(CoreEntity.importance.desc())
        )
        result = await db.execute(stmt)
        items: Sequence[CoreEntity] = result.scalars().all()
        return list(items)

    async def update(
        self,
        db: AsyncSession,
        entity_id: uuid.UUID,
        data: CoreEntityUpdate,
    ) -> CoreEntity | None:
        entity = await self.get(db, entity_id)
        if entity is None:
            return None

        update_values: dict[str, Any] = {}
        for field in (
            "entity_type",
            "name",
            "summary",
            "public_info",
            "hidden_truth",
            "importance",
            "importance_level",
            "reveal_level",
            "status",
            "approved_by",
        ):
            value = getattr(data, field, None)
            if value is not None:
                update_values[field] = value

        if data.content_json is not None:
            update_values["content_json"] = data.content_json

        if update_values:
            stmt = (
                update(CoreEntity)
                .where(CoreEntity.id == entity_id)
                .values(**update_values)
            )
            await db.execute(stmt)
            await db.flush()

        return await self.get(db, entity_id)

    async def delete(
        self,
        db: AsyncSession,
        entity_id: uuid.UUID,
    ) -> bool:
        stmt = delete(CoreEntity).where(CoreEntity.id == entity_id)
        result = await db.execute(stmt)
        await db.flush()
        return result.rowcount > 0

    async def count_entities(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        *,
        status_filter: list[str] | None = None,
    ) -> int:
        """统计指定 novel 的 CoreEntity 数量。"""
        conditions = [CoreEntity.novel_id == novel_id]
        if status_filter:
            conditions.append(CoreEntity.status.in_(status_filter))
        stmt = select(func.count(CoreEntity.id)).where(*conditions)
        result = await db.execute(stmt)
        return result.scalar() or 0

    async def find_entity_by_name(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        name: str,
        entity_type: str | None = None,
    ) -> str | None:
        conditions = [
            CoreEntity.novel_id == novel_id,
            CoreEntity.name == name,
            CoreEntity.status == "canonical",
        ]
        if entity_type:
            conditions.append(CoreEntity.entity_type == entity_type)
        stmt = select(CoreEntity.id).where(*conditions).limit(1)
        result = await db.execute(stmt)
        row = result.scalar_one_or_none()
        if row is not None:
            return str(row)
        return None

    async def find_by_name_fuzzy(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        name: str,
        entity_type: str | None = None,
    ) -> list[CoreEntity]:
        """模糊名称搜索（使用 LIKE）"""
        conditions = [
            CoreEntity.novel_id == novel_id,
            CoreEntity.name.ilike(f"%{name}%"),
            CoreEntity.status == "canonical",
        ]
        if entity_type:
            conditions.append(CoreEntity.entity_type == entity_type)
        stmt = (
            select(CoreEntity)
            .where(*conditions)
            .limit(10)
            .order_by(CoreEntity.importance.desc())
        )
        result = await db.execute(stmt)
        items: Sequence[CoreEntity] = result.scalars().all()
        return list(items)

    async def find_similar_by_search_text(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        query_name: str,
        *,
        entity_type: str | None = None,
        status_filter: list[str] | None = None,
        min_similarity: float = 0.4,
        top_k: int = 50,
    ) -> list[tuple[CoreEntity, float]]:
        """使用 pg_trgm similarity() 对 search_text 虚拟列做模糊匹配。

        search_text 是虚拟生成列（name + content_json->>'aliases'），
        一行 similarity() 同时匹配 name 和所有 JSONB 别名。

        SQLite 环境自动回退为 ILIKE + Python 端 difflib 评分。
        """
        statuses = status_filter or ["canonical", "draft"]
        conditions = [
            CoreEntity.novel_id == novel_id,
            CoreEntity.status.in_(statuses),
        ]
        if entity_type:
            conditions.append(CoreEntity.entity_type == entity_type)

        try:
            sim_expr = func.similarity(CoreEntity.search_text, query_name)
            conditions.append(sim_expr >= min_similarity)
            stmt = (
                select(CoreEntity, sim_expr.label("similarity"))
                .where(*conditions)
                .order_by(text("similarity DESC"))
                .limit(top_k)
            )
            result = await db.execute(stmt)
            rows = result.all()
            return [(row[0], float(row[1])) for row in rows]
        except (OperationalError, ProgrammingError):
            logger.warning("pg_trgm similarity() unavailable, falling back to ILIKE")
            # SQLite / 缺失 pg_trgm 回退：ILIKE name + JSON alias 粗筛
            conditions = [
                CoreEntity.novel_id == novel_id,
                CoreEntity.status.in_(statuses),
                or_(
                    CoreEntity.name.ilike(f"%{query_name}%"),
                    # JSON 别名也做 LIKE 匹配（content_json 在 SQLite 中为 Text）
                    CoreEntity.content_json.cast(Text).ilike(f"%{query_name}%"),
                ),
            ]
            if entity_type:
                conditions.append(CoreEntity.entity_type == entity_type)
            stmt = (
                select(CoreEntity)
                .where(*conditions)
                .limit(top_k)
                .order_by(CoreEntity.importance.desc())
            )
            result = await db.execute(stmt)
            items: Sequence[CoreEntity] = result.scalars().all()
            return [(entity, 0.0) for entity in items]

    async def find_similar_by_embedding(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        query_embedding: list[float],
        *,
        entity_type: str | None = None,
        status_filter: list[str] | None = None,
        top_k: int = 50,
    ) -> list[tuple[CoreEntity, float]]:
        """使用 pgvector <=> 余弦距离做向量相似度搜索。

        返回余弦相似度（1=完全相同，0=完全无关）。
        无 embedding 的实体自动跳过。
        SQLite 环境返回空列表。
        """
        try:
            statuses = status_filter or ["canonical", "draft"]
            conditions = [
                CoreEntity.novel_id == novel_id,
                CoreEntity.status.in_(statuses),
                CoreEntity.embedding.isnot(None),
            ]
            if entity_type:
                conditions.append(CoreEntity.entity_type == entity_type)

            # pgvector <=> 是余弦距离（0=相同，2=相反），转换为相似度
            stmt = (
                select(
                    CoreEntity,
                    text("1.0 - (embedding <=> :emb)").label("similarity"),
                )
                .where(*conditions)
                .order_by(text("embedding <=> :emb"))
                .limit(top_k)
            )
            result = await db.execute(stmt, {"emb": query_embedding})
            rows = result.all()
            return [(row[0], max(0.0, float(row[1]))) for row in rows]
        except (OperationalError, ProgrammingError):
            logger.warning("pgvector embedding search unavailable, returning empty")
            return []

    async def has_embeddings(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
    ) -> bool:
        """检查该 novel 是否有任何实体已生成 embedding。"""
        try:
            stmt = (
                select(func.count(CoreEntity.id))
                .where(
                    CoreEntity.novel_id == novel_id,
                    CoreEntity.embedding.isnot(None),
                )
                .limit(1)
            )
            result = await db.execute(stmt)
            return (result.scalar() or 0) > 0
        except (OperationalError, ProgrammingError):
            logger.warning("pgvector has_embeddings check failed, returning False")
            return False

    async def get_recent_auto_ingested(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        *,
        since: str | None = None,
        limit: int = 50,
    ) -> list[CoreEntity]:
        """查询最近自动入库的实体

        通过 content_json['_meta']['auto_ingested'] 过滤。
        支持 PostgreSQL JSONB 和 SQLite。
        """
        from sqlalchemy import Text, cast

        conditions = [
            CoreEntity.novel_id == novel_id,
            CoreEntity.status == "canonical",
        ]
        # 通过 JSON 文本包含来判断
        conditions.append(
            cast(CoreEntity.content_json, Text).contains('"auto_ingested": true')
        )

        if since:
            conditions.append(CoreEntity.created_at >= since)

        stmt = (
            select(CoreEntity)
            .where(*conditions)
            .order_by(CoreEntity.created_at.desc())
            .limit(limit)
        )
        result = await db.execute(stmt)
        items: Sequence[CoreEntity] = result.scalars().all()
        return list(items)

    async def get_entity_batches(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        *,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """按批次分组查询自动入库的实体

        返回每个 batch 的概要信息及实体列表。
        SQLite 兼容模式 — 在内存中分组。
        """
        recent = await self.get_recent_auto_ingested(db, novel_id, limit=200)
        batches: dict[str, dict[str, Any]] = {}
        for entity in recent:
            meta = entity.content_json.get("_meta", {}) if entity.content_json else {}
            batch_id = meta.get("batch_id", "_unknown")
            if batch_id not in batches:
                batches[batch_id] = {
                    "batch_id": batch_id,
                    "ingested_at": meta.get("ingested_at", ""),
                    "entity_count": 0,
                    "entities": [],
                }
            batches[batch_id]["entity_count"] += 1
            batches[batch_id]["entities"].append(
                {
                    "id": str(entity.id),
                    "name": entity.name,
                    "entity_type": entity.entity_type,
                }
            )

        sorted_batches = sorted(
            batches.values(),
            key=lambda b: b["ingested_at"],
            reverse=True,
        )
        return sorted_batches[:limit]


# ============================================================
# EventRepository
# ============================================================


class EventRepository:
    """事件数据访问"""

    async def create(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        data: EventCreate,
    ) -> Event:
        event = Event(
            entity_id=parse_uuid(data.entity_id),
            novel_id=novel_id,
            source_chapter_id=parse_uuid(data.source_chapter_id),
            location_entity_id=parse_uuid(data.location_entity_id),
            timeline_order=data.timeline_order,
            occurrence_time_label=data.occurrence_time_label,
        )
        db.add(event)
        await db.flush()
        return event

    async def get(
        self,
        db: AsyncSession,
        entity_id: uuid.UUID,
    ) -> Event | None:
        stmt = select(Event).where(Event.entity_id == entity_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_novel(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        *,
        skip: int = 0,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> tuple[list[Event], int]:
        conditions = [Event.novel_id == novel_id]
        count_stmt = select(func.count(Event.entity_id)).where(*conditions)
        total = (await db.execute(count_stmt)).scalar() or 0

        stmt = (
            select(Event)
            .where(*conditions)
            .offset(skip)
            .limit(limit)
            .order_by(Event.timeline_order)
        )
        result = await db.execute(stmt)
        items: Sequence[Event] = result.scalars().all()
        return list(items), total

    async def get_events_for_chapter(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        chapter_id: uuid.UUID,
    ) -> list[Event]:
        stmt = (
            select(Event)
            .where(
                Event.novel_id == novel_id,
                Event.source_chapter_id == chapter_id,
            )
            .order_by(Event.timeline_order)
        )
        result = await db.execute(stmt)
        items: Sequence[Event] = result.scalars().all()
        return list(items)

    async def get_events_in_order(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        limit: int = 50,
    ) -> list[Event]:
        stmt = (
            select(Event)
            .where(Event.novel_id == novel_id)
            .order_by(Event.timeline_order)
            .limit(limit)
        )
        result = await db.execute(stmt)
        items: Sequence[Event] = result.scalars().all()
        return list(items)

    async def update(
        self,
        db: AsyncSession,
        entity_id: uuid.UUID,
        data: EventUpdate,
    ) -> Event | None:
        event = await self.get(db, entity_id)
        if event is None:
            return None

        update_values: dict[str, Any] = {}
        if data.source_chapter_id is not None:
            update_values["source_chapter_id"] = parse_uuid(data.source_chapter_id)
        if data.location_entity_id is not None:
            update_values["location_entity_id"] = parse_uuid(data.location_entity_id)
        if data.timeline_order is not None:
            update_values["timeline_order"] = data.timeline_order
        if data.occurrence_time_label is not None:
            update_values["occurrence_time_label"] = data.occurrence_time_label

        if update_values:
            stmt = (
                update(Event).where(Event.entity_id == entity_id).values(**update_values)
            )
            await db.execute(stmt)
            await db.flush()

        return await self.get(db, entity_id)

    async def delete(
        self,
        db: AsyncSession,
        entity_id: uuid.UUID,
    ) -> bool:
        stmt = delete(Event).where(Event.entity_id == entity_id)
        result = await db.execute(stmt)
        await db.flush()
        return result.rowcount > 0


# ============================================================
# EntityRelationRepository
# ============================================================


class EntityRelationRepository:
    """关系数据访问"""

    async def create(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        data: EntityRelationCreate,
    ) -> EntityRelation:
        rel = EntityRelation(
            novel_id=novel_id,
            source_id=parse_uuid(data.source_id),
            target_id=parse_uuid(data.target_id),
            relation_type=data.relation_type,
            description=data.description,
            strength=data.strength or 0.5,
            source_chapter_id=parse_uuid(data.source_chapter_id)
            if data.source_chapter_id
            else None,
            caused_by_event_id=parse_uuid(data.caused_by_event_id)
            if data.caused_by_event_id
            else None,
            quote=data.quote,
            status=data.status or "canonical",
        )
        db.add(rel)
        await db.flush()
        return rel

    async def get(
        self,
        db: AsyncSession,
        rel_id: uuid.UUID,
    ) -> EntityRelation | None:
        stmt = select(EntityRelation).where(EntityRelation.id == rel_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_novel(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        *,
        skip: int = 0,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> tuple[list[EntityRelation], int]:
        conditions = [EntityRelation.novel_id == novel_id]
        count_stmt = select(func.count(EntityRelation.id)).where(*conditions)
        total = (await db.execute(count_stmt)).scalar() or 0

        stmt = (
            select(EntityRelation)
            .where(*conditions)
            .offset(skip)
            .limit(limit)
            .order_by(EntityRelation.created_at.desc())
        )
        result = await db.execute(stmt)
        items: Sequence[EntityRelation] = result.scalars().all()
        return list(items), total

    async def get_by_source(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        source_id: uuid.UUID,
        *,
        relation_type: str | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> list[EntityRelation]:
        conditions = [
            EntityRelation.novel_id == novel_id,
            EntityRelation.source_id == source_id,
        ]
        if relation_type:
            conditions.append(EntityRelation.relation_type == relation_type)

        stmt = (
            select(EntityRelation)
            .where(*conditions)
            .limit(limit)
            .order_by(EntityRelation.strength.desc())
        )
        result = await db.execute(stmt)
        items: Sequence[EntityRelation] = result.scalars().all()
        return list(items)

    async def get_by_target(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        target_id: uuid.UUID,
        *,
        relation_type: str | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> list[EntityRelation]:
        conditions = [
            EntityRelation.novel_id == novel_id,
            EntityRelation.target_id == target_id,
        ]
        if relation_type:
            conditions.append(EntityRelation.relation_type == relation_type)

        stmt = (
            select(EntityRelation)
            .where(*conditions)
            .limit(limit)
            .order_by(EntityRelation.strength.desc())
        )
        result = await db.execute(stmt)
        items: Sequence[EntityRelation] = result.scalars().all()
        return list(items)

    async def get_traceable_relations(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        chapter_id: uuid.UUID,
    ) -> list[EntityRelation]:
        """获取某章节建立的所有可追溯关系"""
        stmt = (
            select(EntityRelation)
            .where(
                EntityRelation.novel_id == novel_id,
                EntityRelation.source_chapter_id == chapter_id,
            )
            .order_by(EntityRelation.created_at)
        )
        result = await db.execute(stmt)
        items: Sequence[EntityRelation] = result.scalars().all()
        return list(items)

    async def get_related_entity_ids(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        entity_id: uuid.UUID,
        depth: int = 1,
        limit: int = 20,
    ) -> set[uuid.UUID]:

        related: set[uuid.UUID] = set()

        one_hop = await self._get_one_hop_ids(db, novel_id, entity_id)
        related.update(one_hop)

        if depth >= 2:
            for hop_id in list(one_hop):
                if len(related) >= limit:
                    break
                second_hop = await self._get_one_hop_ids(db, novel_id, hop_id)
                related.update(second_hop)
                if len(related) >= limit:
                    break

        return related

    async def _get_one_hop_ids(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        entity_id: uuid.UUID,
    ) -> set[uuid.UUID]:
        from sqlalchemy import union_all

        src_stmt = select(EntityRelation.target_id.label("related_id")).where(
            EntityRelation.novel_id == novel_id,
            EntityRelation.source_id == entity_id,
        )
        tgt_stmt = select(EntityRelation.source_id.label("related_id")).where(
            EntityRelation.novel_id == novel_id,
            EntityRelation.target_id == entity_id,
        )
        combined = union_all(src_stmt, tgt_stmt)
        result = await db.execute(combined)
        return {row[0] for row in result.all()}

    async def update(
        self,
        db: AsyncSession,
        rel_id: uuid.UUID,
        data: EntityRelationUpdate,
    ) -> EntityRelation | None:
        rel = await self.get(db, rel_id)
        if rel is None:
            return None

        update_values: dict[str, Any] = {}
        for field in ("relation_type", "description", "strength", "status"):
            value = getattr(data, field, None)
            if value is not None:
                update_values[field] = value

        if update_values:
            stmt = (
                update(EntityRelation)
                .where(EntityRelation.id == rel_id)
                .values(**update_values)
            )
            await db.execute(stmt)
            await db.flush()

        return await self.get(db, rel_id)

    async def delete(
        self,
        db: AsyncSession,
        rel_id: uuid.UUID,
    ) -> bool:
        stmt = delete(EntityRelation).where(EntityRelation.id == rel_id)
        result = await db.execute(stmt)
        await db.flush()
        return result.rowcount > 0

    async def upsert(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        source_id: uuid.UUID,
        target_id: uuid.UUID,
        relation_type: str,
        description: str | None = None,
    ) -> EntityRelation:
        stmt = (
            select(EntityRelation)
            .where(
                EntityRelation.novel_id == novel_id,
                EntityRelation.source_id == source_id,
                EntityRelation.target_id == target_id,
                EntityRelation.relation_type == relation_type,
                EntityRelation.status == "canonical",
            )
            .limit(1)
        )
        result = await db.execute(stmt)
        existing = result.scalar_one_or_none()

        if existing is not None:
            if description:
                existing.description = description
            await db.flush()
            return existing

        rel = EntityRelation(
            novel_id=novel_id,
            source_id=source_id,
            target_id=target_id,
            relation_type=relation_type,
            description=description,
            status="canonical",
        )
        db.add(rel)
        await db.flush()
        return rel

    async def get_all_for_entity(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        entity_id: uuid.UUID,
    ) -> list[EntityRelation]:
        """获取某实体参与的所有关系（作为 source 或 target）。"""
        stmt = select(EntityRelation).where(
            EntityRelation.novel_id == novel_id,
            or_(
                EntityRelation.source_id == entity_id,
                EntityRelation.target_id == entity_id,
            ),
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def update_endpoint(
        self,
        db: AsyncSession,
        rel_id: uuid.UUID,
        *,
        source_id: uuid.UUID | None = None,
        target_id: uuid.UUID | None = None,
    ) -> None:
        """重定向关系端点。绕过 EntityRelationUpdate 不含 source_id/target_id 的限制。"""
        values: dict[str, Any] = {}
        if source_id is not None:
            values["source_id"] = source_id
        if target_id is not None:
            values["target_id"] = target_id
        if values:
            stmt = (
                update(EntityRelation).where(EntityRelation.id == rel_id).values(**values)
            )
            await db.execute(stmt)

    async def find_duplicate_relation(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        source_id: uuid.UUID,
        target_id: uuid.UUID,
        relation_type: str,
    ) -> EntityRelation | None:
        """查找已存在的同类型同方向关系。"""
        stmt = (
            select(EntityRelation)
            .where(
                EntityRelation.novel_id == novel_id,
                EntityRelation.source_id == source_id,
                EntityRelation.target_id == target_id,
                EntityRelation.relation_type == relation_type,
                EntityRelation.status != "deprecated",
            )
            .limit(1)
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def delete_self_loops(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        entity_id: uuid.UUID,
    ) -> int:
        """删除自环关系（source == target），返回删除数。"""
        stmt = delete(EntityRelation).where(
            EntityRelation.novel_id == novel_id,
            EntityRelation.source_id == entity_id,
            EntityRelation.target_id == entity_id,
        )
        result = await db.execute(stmt)
        await db.flush()
        return result.rowcount or 0


# ============================================================
# EntityRevisionRepository
# ============================================================


class EntityRevisionRepository:
    """版本快照数据访问"""

    async def create(
        self,
        db: AsyncSession,
        *,
        entity_id: uuid.UUID,
        novel_id: uuid.UUID,
        snapshot: dict,
        source_chapter_id: uuid.UUID | None = None,
        revision_reason: str = "ai_import",
    ) -> EntityRevision:
        revision = EntityRevision(
            entity_id=entity_id,
            novel_id=novel_id,
            snapshot=snapshot,
            source_chapter_id=source_chapter_id,
            revision_reason=revision_reason,
        )
        db.add(revision)
        await db.flush()
        return revision

    async def get_revisions(
        self,
        db: AsyncSession,
        entity_id: uuid.UUID,
        *,
        skip: int = 0,
        limit: int = 20,
    ) -> tuple[list[EntityRevision], int]:
        conditions = [EntityRevision.entity_id == entity_id]
        count_stmt = select(func.count(EntityRevision.id)).where(*conditions)
        total = (await db.execute(count_stmt)).scalar() or 0

        stmt = (
            select(EntityRevision)
            .where(*conditions)
            .offset(skip)
            .limit(limit)
            .order_by(EntityRevision.created_at.desc())
        )
        result = await db.execute(stmt)
        items: Sequence[EntityRevision] = result.scalars().all()
        return list(items), total

    async def get_revision(
        self,
        db: AsyncSession,
        revision_id: uuid.UUID,
    ) -> EntityRevision | None:
        stmt = select(EntityRevision).where(EntityRevision.id == revision_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()


# ============================================================
# CharacterRepository（从 character 模块迁入）
# ============================================================


class CharacterRepository:
    """人物数据访问"""

    async def create(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        data: CharacterCreate,
    ) -> Character:
        character = Character(
            entity_id=parse_uuid(data.entity_id),
            novel_id=novel_id,
            name=data.name,
            aliases=data.aliases or [],
            role=data.role,
            appearance=data.appearance,
            personality=data.personality,
            desire=data.desire,
            fear=data.fear,
            secret=data.secret,
            weakness=data.weakness,
            current_goal=data.current_goal,
            current_state=data.current_state,
            current_emotion=data.current_emotion,
            stance=data.stance,
            voice_style=data.voice_style,
            behavior_rules=data.behavior_rules or [],
            relationship_summary=data.relationship_summary,
            meta=data.meta or {},
            status=data.status or "canonical",
        )
        db.add(character)
        await db.flush()
        return character

    async def get(
        self,
        db: AsyncSession,
        character_id: uuid.UUID,
    ) -> Character | None:
        stmt = select(Character).where(Character.entity_id == character_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_novel(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        *,
        skip: int = 0,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> tuple[list[Character], int]:
        conditions = [Character.novel_id == novel_id]
        count_stmt = select(func.count(Character.entity_id)).where(*conditions)
        total = (await db.execute(count_stmt)).scalar() or 0

        stmt = (
            select(Character)
            .where(*conditions)
            .offset(skip)
            .limit(limit)
            .order_by(Character.name)
        )
        result = await db.execute(stmt)
        items: Sequence[Character] = result.scalars().all()
        return list(items), total

    async def get_by_ids(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        character_ids: list[uuid.UUID],
    ) -> list[Character]:
        if not character_ids:
            return []
        stmt = select(Character).where(
            Character.novel_id == novel_id,
            Character.entity_id.in_(character_ids),
        )
        result = await db.execute(stmt)
        items: Sequence[Character] = result.scalars().all()
        return list(items)

    async def update(
        self,
        db: AsyncSession,
        character_id: uuid.UUID,
        data: CharacterUpdate,
    ) -> Character | None:
        character = await self.get(db, character_id)
        if character is None:
            return None

        update_values: dict[str, Any] = {}
        for field in (
            "name",
            "role",
            "appearance",
            "personality",
            "desire",
            "fear",
            "secret",
            "weakness",
            "current_goal",
            "current_state",
            "current_emotion",
            "stance",
            "voice_style",
            "relationship_summary",
            "status",
        ):
            value = getattr(data, field, None)
            if value is not None:
                update_values[field] = value

        if data.aliases is not None:
            update_values["aliases"] = data.aliases
        if data.behavior_rules is not None:
            update_values["behavior_rules"] = data.behavior_rules
        if data.meta is not None:
            update_values["meta"] = data.meta

        if update_values:
            stmt = (
                update(Character)
                .where(Character.entity_id == character_id)
                .values(**update_values)
            )
            await db.execute(stmt)
            await db.flush()

        return await self.get(db, character_id)

    async def migrate_entity_id(
        self,
        db: AsyncSession,
        source_entity_id: uuid.UUID,
        target_entity_id: uuid.UUID,
    ) -> bool:
        """将 Character 行从 source_entity_id 迁移到 target_entity_id（用于合并）。"""
        stmt = (
            update(Character)
            .where(Character.entity_id == source_entity_id)
            .values(entity_id=target_entity_id)
        )
        result = await db.execute(stmt)
        await db.flush()
        return result.rowcount > 0

    async def delete(
        self,
        db: AsyncSession,
        character_id: uuid.UUID,
    ) -> bool:
        stmt = delete(Character).where(Character.entity_id == character_id)
        result = await db.execute(stmt)
        await db.flush()
        return result.rowcount > 0

    async def find_character_by_name(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        name: str,
    ) -> str | None:
        stmt = (
            select(Character.entity_id)
            .where(
                Character.novel_id == novel_id,
                Character.name == name,
                Character.status == "canonical",
            )
            .limit(1)
        )
        result = await db.execute(stmt)
        row = result.scalar_one_or_none()
        return str(row) if row is not None else None

    async def update_character_meta_location(
        self,
        db: AsyncSession,
        character_id: uuid.UUID,
        location_id: uuid.UUID,
        text_state: str,
        chapter_index: int,
    ) -> None:
        meta = {}
        meta["location_id"] = str(location_id)
        meta["text_state"] = text_state
        meta["chapter_index"] = chapter_index

        stmt = (
            update(Character).where(Character.entity_id == character_id).values(meta=meta)
        )
        await db.execute(stmt)
        await db.flush()

    async def find_characters_by_location(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        location_id: uuid.UUID,
    ) -> list[dict[str, Any]]:
        """获取当前位于某地点的活跃人物列表"""
        stmt = select(Character).where(
            Character.novel_id == novel_id,
            Character.status == "canonical",
        )
        result = await db.execute(stmt)
        characters: Sequence[Character] = result.scalars().all()

        items: list[dict[str, Any]] = []
        for c in characters:
            meta = c.meta or {}
            if str(meta.get("location_id", "")) == str(location_id):
                items.append(
                    {
                        "id": str(c.entity_id),
                        "name": c.name,
                        "current_state": c.current_state,
                    }
                )
        return items

    async def get_character_location_id(
        self,
        db: AsyncSession,
        character_id: uuid.UUID,
    ) -> str | None:
        char = await self.get(db, character_id)
        if char is None:
            return None
        meta = char.meta or {}
        return meta.get("location_id")


# ============================================================
# CharacterKnowledgeRepository（从 character 模块迁入）
# ============================================================


class CharacterKnowledgeRepository:
    """人物知识数据访问"""

    async def create(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        data: CharacterKnowledgeCreate,
    ) -> CharacterKnowledge:
        knowledge = CharacterKnowledge(
            novel_id=novel_id,
            character_id=parse_uuid(data.character_id),
            target_type=data.target_type,
            target_id=parse_uuid(data.target_id),
            knowledge_level=data.knowledge_level,
            known_content=data.known_content,
            misconception=data.misconception,
            source_chapter_index=data.source_chapter_index,
            source_memory_id=parse_uuid(data.source_memory_id)
            if data.source_memory_id
            else None,
            status=data.status or "canonical",
        )
        db.add(knowledge)
        await db.flush()
        return knowledge

    async def get(
        self,
        db: AsyncSession,
        knowledge_id: uuid.UUID,
    ) -> CharacterKnowledge | None:
        stmt = select(CharacterKnowledge).where(CharacterKnowledge.id == knowledge_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_character(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        character_id: uuid.UUID,
        *,
        skip: int = 0,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> tuple[list[CharacterKnowledge], int]:
        conditions = [
            CharacterKnowledge.novel_id == novel_id,
            CharacterKnowledge.character_id == character_id,
        ]
        count_stmt = select(func.count(CharacterKnowledge.id)).where(*conditions)
        total = (await db.execute(count_stmt)).scalar() or 0

        stmt = (
            select(CharacterKnowledge)
            .where(*conditions)
            .offset(skip)
            .limit(limit)
            .order_by(CharacterKnowledge.target_type)
        )
        result = await db.execute(stmt)
        items: Sequence[CharacterKnowledge] = result.scalars().all()
        return list(items), total

    async def get_by_novel(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        *,
        skip: int = 0,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> tuple[list[CharacterKnowledge], int]:
        conditions = [CharacterKnowledge.novel_id == novel_id]
        count_stmt = select(func.count(CharacterKnowledge.id)).where(*conditions)
        total = (await db.execute(count_stmt)).scalar() or 0

        stmt = (
            select(CharacterKnowledge)
            .where(*conditions)
            .offset(skip)
            .limit(limit)
            .order_by(CharacterKnowledge.character_id)
        )
        result = await db.execute(stmt)
        items: Sequence[CharacterKnowledge] = result.scalars().all()
        return list(items), total

    async def get_by_target(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        character_id: uuid.UUID,
        target_ids: list[uuid.UUID] | None = None,
    ) -> list[CharacterKnowledge]:
        conditions = [
            CharacterKnowledge.novel_id == novel_id,
            CharacterKnowledge.character_id == character_id,
        ]
        if target_ids:
            conditions.append(CharacterKnowledge.target_id.in_(target_ids))

        stmt = select(CharacterKnowledge).where(*conditions)
        result = await db.execute(stmt)
        items: Sequence[CharacterKnowledge] = result.scalars().all()
        return list(items)

    async def update(
        self,
        db: AsyncSession,
        knowledge_id: uuid.UUID,
        data: CharacterKnowledgeUpdate,
    ) -> CharacterKnowledge | None:
        knowledge = await self.get(db, knowledge_id)
        if knowledge is None:
            return None

        update_values: dict[str, Any] = {}
        for field in (
            "knowledge_level",
            "known_content",
            "misconception",
            "source_chapter_index",
            "status",
        ):
            value = getattr(data, field, None)
            if value is not None:
                update_values[field] = value

        if data.source_memory_id is not None:
            update_values["source_memory_id"] = parse_uuid(data.source_memory_id)

        if update_values:
            stmt = (
                update(CharacterKnowledge)
                .where(CharacterKnowledge.id == knowledge_id)
                .values(**update_values)
            )
            await db.execute(stmt)
            await db.flush()

        return await self.get(db, knowledge_id)

    async def delete(
        self,
        db: AsyncSession,
        knowledge_id: uuid.UUID,
    ) -> bool:
        stmt = delete(CharacterKnowledge).where(CharacterKnowledge.id == knowledge_id)
        result = await db.execute(stmt)
        await db.flush()
        return result.rowcount > 0


RelationshipRepository = EntityRelationRepository
