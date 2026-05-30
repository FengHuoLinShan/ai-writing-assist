"""
World 数据访问层 — v3 因果时空网

<<<<<<< HEAD
封装 core_entities、relationships、entity_candidates 三张表的数据库操作。
别名已整合为 core_entities.aliases JSONB，不再使用独立的 entity_aliases 表。
=======
封装所有表的基本数据库操作。
只处理 ORM ↔ DB 的基本 CRUD，不含业务逻辑。
>>>>>>> origin/worktree-grill-v3
"""

from __future__ import annotations

import uuid
from typing import Any, Sequence

<<<<<<< HEAD
from sqlalchemy import delete, func, or_, select, update
=======
from sqlalchemy import delete, func, select, update
>>>>>>> origin/worktree-grill-v3
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import JSON

<<<<<<< HEAD
from modules.world.models import CoreEntity, EntityCandidate, Relationship
from modules.world.schemas import (
    CoreEntityCreate,
    CoreEntityUpdate,
    EntityCandidateCreate,
    EntityCandidateUpdate,
    RelationshipCreate,
    RelationshipUpdate,
=======
from modules.world.models import (
    Character,
    CharacterKnowledge,
    CoreEntity,
    EntityRelation,
    EntityRevision,
    Event,
)
from modules.world.schemas import (
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
>>>>>>> origin/worktree-grill-v3
)
from shared.constants import DEFAULT_PAGE_SIZE
from shared.utils import parse_uuid


# ============================================================
# CoreEntityRepository
# ============================================================

class CoreEntityRepository:
<<<<<<< HEAD
    """核心实体数据访问 — 取代原 WorldEntityRepository + EntityAliasRepository"""
=======
    """核心实体数据访问"""
>>>>>>> origin/worktree-grill-v3

    async def create(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        data: CoreEntityCreate,
    ) -> CoreEntity:
<<<<<<< HEAD
        """创建核心实体"""
=======
>>>>>>> origin/worktree-grill-v3
        entity = CoreEntity(
            novel_id=novel_id,
            entity_type=data.entity_type,
            name=data.name,
            aliases=data.aliases or [],
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

    async def get(
        self,
        db: AsyncSession,
        entity_id: uuid.UUID,
    ) -> CoreEntity | None:
<<<<<<< HEAD
        """根据 ID 获取核心实体"""
=======
>>>>>>> origin/worktree-grill-v3
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
        skip: int = 0,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> tuple[list[CoreEntity], int]:
<<<<<<< HEAD
        """获取小说的核心实体列表（分页）"""
=======
>>>>>>> origin/worktree-grill-v3
        conditions = [CoreEntity.novel_id == novel_id]
        if entity_type:
            conditions.append(CoreEntity.entity_type == entity_type)
        if status:
            conditions.append(CoreEntity.status == status)

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
<<<<<<< HEAD
        """批量获取指定 ID 的核心实体"""
=======
>>>>>>> origin/worktree-grill-v3
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
<<<<<<< HEAD
        """按类型和状态查询"""
=======
>>>>>>> origin/worktree-grill-v3
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
<<<<<<< HEAD
        """更新核心实体"""
=======
>>>>>>> origin/worktree-grill-v3
        entity = await self.get(db, entity_id)
        if entity is None:
            return None

        update_values: dict[str, Any] = {}
        for field in (
<<<<<<< HEAD
            "entity_type",
            "name",
            "aliases",
            "summary",
            "public_info",
            "hidden_truth",
            "importance",
            "importance_level",
            "reveal_level",
            "status",
            "approved_by",
=======
            "entity_type", "name", "summary", "public_info", "hidden_truth",
            "importance", "importance_level", "reveal_level", "status", "approved_by",
>>>>>>> origin/worktree-grill-v3
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
<<<<<<< HEAD
        """删除核心实体（ON DELETE CASCADE 自动清理扩展表）"""
=======
>>>>>>> origin/worktree-grill-v3
        stmt = delete(CoreEntity).where(CoreEntity.id == entity_id)
        result = await db.execute(stmt)
        await db.flush()
        return result.rowcount > 0

    async def find_entity_by_name(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        name: str,
        entity_type: str | None = None,
    ) -> str | None:
        """按名称查找实体 — 先精确匹配 name，再搜 aliases JSONB"""
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
<<<<<<< HEAD

        # Search aliases in Python so the lookup works on both PostgreSQL and
        # SQLite tests, and so alias text never gets interpolated into SQL.
        # Full scan (no LIMIT) is safe here because the exact-name match above
        # returns immediately for the common case; alias fallback only runs
        # when the name wasn't found as a primary name.
        from modules.world.services.helpers import find_alias_in_entity

        alias_conditions = [
            CoreEntity.novel_id == novel_id,
            CoreEntity.status == "canonical",
        ]
        if entity_type:
            alias_conditions.append(CoreEntity.entity_type == entity_type)
        alias_stmt = select(CoreEntity).where(*alias_conditions)
        alias_result = await db.execute(alias_stmt)
        for entity in alias_result.scalars().all():
            if find_alias_in_entity(entity, name):
                return str(entity.id)

        return None

    async def add_alias(
        self,
        db: AsyncSession,
        entity_id: uuid.UUID,
        alias: str,
        alias_type: str = "name",
        entity: CoreEntity | None = None,
    ) -> bool:
        """向实体的 aliases JSONB 数组添加别名（去重）"""
        if entity is None:
            entity = await self.get(db, entity_id)
        if entity is None:
            return False

        current_aliases: list[dict] = entity.aliases or []
        existing = {a.get("alias") for a in current_aliases if isinstance(a, dict)}
        if alias in existing:
            return True  # already exists

        current_aliases.append({"alias": alias, "type": alias_type})
        stmt = (
            update(CoreEntity)
            .where(CoreEntity.id == entity_id)
            .values(aliases=current_aliases)
        )
        await db.execute(stmt)
        await db.flush()
        return True

    async def remove_alias(
        self,
        db: AsyncSession,
        entity_id: uuid.UUID,
        alias: str,
        entity: CoreEntity | None = None,
    ) -> bool:
        """从实体的 aliases JSONB 数组移除别名"""
        if entity is None:
            entity = await self.get(db, entity_id)
        if entity is None:
            return False

        current_aliases: list[dict] = list(entity.aliases or [])
        filtered = [a for a in current_aliases if a.get("alias") != alias]
        if len(filtered) == len(current_aliases):
            return False  # nothing removed

        stmt = (
            update(CoreEntity)
            .where(CoreEntity.id == entity_id)
            .values(aliases=filtered)
        )
        await db.execute(stmt)
        await db.flush()
        return True


# ============================================================
# RelationshipRepository (unchanged except WorldEntity→CoreEntity)
=======
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


# ============================================================
# EventRepository
>>>>>>> origin/worktree-grill-v3
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
                update(Event)
                .where(Event.entity_id == entity_id)
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
<<<<<<< HEAD
        data: RelationshipCreate,
    ) -> Relationship:
        rel = Relationship(
=======
        data: EntityRelationCreate,
    ) -> EntityRelation:
        rel = EntityRelation(
>>>>>>> origin/worktree-grill-v3
            novel_id=novel_id,
            source_id=parse_uuid(data.source_id),
            target_id=parse_uuid(data.target_id),
            relation_type=data.relation_type,
            description=data.description,
            strength=data.strength or 0.5,
            source_chapter_id=parse_uuid(data.source_chapter_id) if data.source_chapter_id else None,
            caused_by_event_id=parse_uuid(data.caused_by_event_id) if data.caused_by_event_id else None,
            quote=data.quote,
            status=data.status or "canonical",
        )
        db.add(rel)
        await db.flush()
        return rel

<<<<<<< HEAD
    async def get(self, db: AsyncSession, rel_id: uuid.UUID) -> Relationship | None:
        stmt = select(Relationship).where(Relationship.id == rel_id)
=======
    async def get(
        self,
        db: AsyncSession,
        rel_id: uuid.UUID,
    ) -> EntityRelation | None:
        stmt = select(EntityRelation).where(EntityRelation.id == rel_id)
>>>>>>> origin/worktree-grill-v3
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_novel(
<<<<<<< HEAD
        self, db: AsyncSession, novel_id: uuid.UUID, *,
        skip: int = 0, limit: int = DEFAULT_PAGE_SIZE,
    ) -> tuple[list[Relationship], int]:
        conditions = [Relationship.novel_id == novel_id]
        count_stmt = select(func.count(Relationship.id)).where(*conditions)
        count_result = await db.execute(count_stmt)
        total = count_result.scalar() or 0
=======
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
>>>>>>> origin/worktree-grill-v3

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
<<<<<<< HEAD
        self, db: AsyncSession, novel_id: uuid.UUID, source_id: str, *,
        relation_type: str | None = None, limit: int = DEFAULT_PAGE_SIZE,
    ) -> list[Relationship]:
        conditions = [Relationship.novel_id == novel_id, Relationship.source_id == source_id]
        if relation_type:
            conditions.append(Relationship.relation_type == relation_type)
        stmt = (
            select(Relationship).where(*conditions)
            .limit(limit).order_by(Relationship.strength.desc())
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def get_by_target(
        self, db: AsyncSession, novel_id: uuid.UUID, target_id: str, *,
        relation_type: str | None = None, limit: int = DEFAULT_PAGE_SIZE,
    ) -> list[Relationship]:
        conditions = [Relationship.novel_id == novel_id, Relationship.target_id == target_id]
        if relation_type:
            conditions.append(Relationship.relation_type == relation_type)
        stmt = (
            select(Relationship).where(*conditions)
            .limit(limit).order_by(Relationship.strength.desc())
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def get_related_entity_ids(
        self, db: AsyncSession, novel_id: uuid.UUID, entity_id: str,
        depth: int = 1, limit: int = 20,
    ) -> set[str]:
        related: set[str] = set()
        one_hop_ids = await self._get_one_hop_ids(db, novel_id, entity_id)
        related.update(one_hop_ids)
=======
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
        from sqlalchemy import union_all

        related: set[uuid.UUID] = set()

        one_hop = await self._get_one_hop_ids(db, novel_id, entity_id)
        related.update(one_hop)

>>>>>>> origin/worktree-grill-v3
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
<<<<<<< HEAD
        self, db: AsyncSession, novel_id: uuid.UUID, entity_id: str,
    ) -> set[str]:
        from sqlalchemy import union_all
        src_stmt = select(Relationship.target_id.label("related_id")).where(
            Relationship.novel_id == novel_id, Relationship.source_id == entity_id,
        )
        tgt_stmt = select(Relationship.source_id.label("related_id")).where(
            Relationship.novel_id == novel_id, Relationship.target_id == entity_id,
=======
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
>>>>>>> origin/worktree-grill-v3
        )
        combined = union_all(src_stmt, tgt_stmt)
        result = await db.execute(combined)
        return {row[0] for row in result.all()}

    async def update(
<<<<<<< HEAD
        self, db: AsyncSession, rel_id: uuid.UUID, data: RelationshipUpdate,
    ) -> Relationship | None:
=======
        self,
        db: AsyncSession,
        rel_id: uuid.UUID,
        data: EntityRelationUpdate,
    ) -> EntityRelation | None:
>>>>>>> origin/worktree-grill-v3
        rel = await self.get(db, rel_id)
        if rel is None:
            return None
        update_values: dict[str, Any] = {}
<<<<<<< HEAD
        for field in ("source_type", "source_id", "target_type", "target_id",
                       "relation_type", "description", "visibility", "strength", "status"):
=======
        for field in ("relation_type", "description", "strength", "status"):
>>>>>>> origin/worktree-grill-v3
            value = getattr(data, field, None)
            if value is not None:
                update_values[field] = value
        if update_values:
<<<<<<< HEAD
            stmt = update(Relationship).where(Relationship.id == rel_id).values(**update_values)
            await db.execute(stmt)
            await db.flush()
            rel = await self.get(db, rel_id)
        return rel

    async def delete(self, db: AsyncSession, rel_id: uuid.UUID) -> bool:
        stmt = delete(Relationship).where(Relationship.id == rel_id)
=======
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
>>>>>>> origin/worktree-grill-v3
        result = await db.execute(stmt)
        await db.flush()
        return result.rowcount > 0

<<<<<<< HEAD
    async def upsert_relationship(
        self, db: AsyncSession, novel_id: uuid.UUID,
        source_id: str, target_id: str,
        source_type: str, target_type: str,
        relation_type: str, description: str | None = None,
    ) -> None:
        stmt = select(Relationship).where(
            Relationship.novel_id == novel_id,
            Relationship.source_id == source_id,
            Relationship.target_id == target_id,
            Relationship.relation_type == relation_type,
            Relationship.status == "canonical",
=======
    async def upsert(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        source_id: uuid.UUID,
        target_id: uuid.UUID,
        relation_type: str,
        description: str | None = None,
    ) -> EntityRelation:
        stmt = select(EntityRelation).where(
            EntityRelation.novel_id == novel_id,
            EntityRelation.source_id == source_id,
            EntityRelation.target_id == target_id,
            EntityRelation.relation_type == relation_type,
            EntityRelation.status == "canonical",
>>>>>>> origin/worktree-grill-v3
        ).limit(1)
        result = await db.execute(stmt)
        existing = result.scalar_one_or_none()
        if existing is not None:
<<<<<<< HEAD
            existing.description = description
        else:
            new_rel = Relationship(
                novel_id=novel_id, source_id=source_id, target_id=target_id,
                source_type=source_type, target_type=target_type,
                relation_type=relation_type, description=description, status="canonical",
            )
            db.add(new_rel)
        await db.flush()

    async def get_factions_for_location(
        self, db: AsyncSession, novel_id: uuid.UUID,
        location_id: str, entity_repo: "CoreEntityRepository",
    ) -> list[dict[str, Any]]:
        stmt = select(Relationship).where(
            Relationship.novel_id == novel_id,
            Relationship.target_id == location_id,
            Relationship.relation_type.in_(["controls", "stationed_at", "hidden_presence"]),
            Relationship.status == "canonical",
        )
        result = await db.execute(stmt)
        relationships = result.scalars().all()
        faction_ids = list({r.source_id for r in relationships})
        if not faction_ids:
            return []
        from shared.utils import parse_uuid
        entity_stmt = select(CoreEntity).where(
            CoreEntity.id.in_([parse_uuid(fid) for fid in faction_ids]),
            CoreEntity.status == "canonical",
        )
        entity_result = await db.execute(entity_stmt)
        entities = entity_result.scalars().all()
        entity_map = {str(e.id): e for e in entities}
        factions = []
        for r in relationships:
            entity = entity_map.get(r.source_id)
            if entity:
                factions.append({
                    "id": str(entity.id),
                    "name": entity.name,
                    "relation_type": r.relation_type,
                    "description": r.description or "",
                })
        return factions


# ============================================================
# EntityCandidateRepository (unchanged)
=======
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
>>>>>>> origin/worktree-grill-v3
# ============================================================

class CharacterRepository:
    """人物数据访问"""

    async def create(
<<<<<<< HEAD
        self, db: AsyncSession, novel_id: uuid.UUID, data: EntityCandidateCreate,
    ) -> EntityCandidate:
        candidate = EntityCandidate(
            novel_id=novel_id, name=data.name, entity_type=data.entity_type,
            summary=data.summary, source_text=data.source_text,
            source_chapter_index=data.source_chapter_index,
            importance_score=data.importance_score or 0.5,
            confidence=data.confidence or 0.5,
            candidate_reason=data.candidate_reason,
            suggested_action=data.suggested_action or "needs_user_decision",
            suggested_existing_entity_id=data.suggested_existing_entity_id,
            status=data.status or "pending",
=======
        self,
        db: AsyncSession,
        data: CharacterCreate,
    ) -> Character:
        character = Character(
            entity_id=parse_uuid(data.entity_id),
            novel_id=parse_uuid(data.novel_id),
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
>>>>>>> origin/worktree-grill-v3
        )
        db.add(character)
        await db.flush()
        return character

<<<<<<< HEAD
    async def get(self, db: AsyncSession, candidate_id: uuid.UUID) -> EntityCandidate | None:
        stmt = select(EntityCandidate).where(EntityCandidate.id == candidate_id)
=======
    async def get(
        self,
        db: AsyncSession,
        character_id: uuid.UUID,
    ) -> Character | None:
        stmt = select(Character).where(Character.entity_id == character_id)
>>>>>>> origin/worktree-grill-v3
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_novel(
<<<<<<< HEAD
        self, db: AsyncSession, novel_id: uuid.UUID, *,
        status: str | None = None, suggested_action: str | None = None,
        skip: int = 0, limit: int = DEFAULT_PAGE_SIZE,
    ) -> tuple[list[EntityCandidate], int]:
        conditions = [EntityCandidate.novel_id == novel_id]
        if status:
            conditions.append(EntityCandidate.status == status)
        if suggested_action:
            conditions.append(EntityCandidate.suggested_action == suggested_action)
        count_stmt = select(func.count(EntityCandidate.id)).where(*conditions)
        count_result = await db.execute(count_stmt)
        total = count_result.scalar() or 0
        stmt = (
            select(EntityCandidate).where(*conditions)
            .offset(skip).limit(limit)
            .order_by(EntityCandidate.importance_score.desc())
        )
        result = await db.execute(stmt)
        return list(result.scalars().all()), total

    async def get_by_status(
        self, db: AsyncSession, novel_id: uuid.UUID, status: str,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> list[EntityCandidate]:
        stmt = (
            select(EntityCandidate)
            .where(EntityCandidate.novel_id == novel_id, EntityCandidate.status == status)
            .limit(limit).order_by(EntityCandidate.importance_score.desc())
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def update(
        self, db: AsyncSession, candidate_id: uuid.UUID, data: EntityCandidateUpdate,
    ) -> EntityCandidate | None:
        candidate = await self.get(db, candidate_id)
        if candidate is None:
=======
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
>>>>>>> origin/worktree-grill-v3
            return None
        update_values: dict[str, Any] = {}
<<<<<<< HEAD
        for field in ("name", "entity_type", "summary", "source_text",
                       "source_chapter_index", "importance_score", "confidence",
                       "candidate_reason", "suggested_action",
                       "suggested_existing_entity_id", "status"):
            value = getattr(data, field, None)
            if value is not None:
                update_values[field] = value
        if update_values:
            stmt = update(EntityCandidate).where(
                EntityCandidate.id == candidate_id
            ).values(**update_values)
            await db.execute(stmt)
            await db.flush()
            candidate = await self.get(db, candidate_id)
        return candidate

    async def update_status(
        self, db: AsyncSession, candidate_id: uuid.UUID, status: str,
    ) -> None:
        stmt = update(EntityCandidate).where(
            EntityCandidate.id == candidate_id
        ).values(status=status)
        await db.execute(stmt)
        await db.flush()

    async def delete(self, db: AsyncSession, candidate_id: uuid.UUID) -> bool:
        stmt = delete(EntityCandidate).where(EntityCandidate.id == candidate_id)
=======
        for field in (
            "name", "role", "appearance", "personality", "desire", "fear",
            "secret", "weakness", "current_goal", "current_state",
            "current_emotion", "stance", "voice_style", "relationship_summary",
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

    async def delete(
        self,
        db: AsyncSession,
        character_id: uuid.UUID,
    ) -> bool:
        stmt = delete(Character).where(Character.entity_id == character_id)
>>>>>>> origin/worktree-grill-v3
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
            update(Character)
            .where(Character.entity_id == character_id)
            .values(meta=meta)
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
                items.append({
                    "id": str(c.entity_id),
                    "name": c.name,
                    "current_state": c.current_state,
                })
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
        data: CharacterKnowledgeCreate,
    ) -> CharacterKnowledge:
        knowledge = CharacterKnowledge(
            novel_id=parse_uuid(data.novel_id),
            character_id=parse_uuid(data.character_id),
            target_type=data.target_type,
            target_id=parse_uuid(data.target_id),
            knowledge_level=data.knowledge_level,
            known_content=data.known_content,
            misconception=data.misconception,
            source_chapter_index=data.source_chapter_index,
            source_memory_id=parse_uuid(data.source_memory_id) if data.source_memory_id else None,
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
            "knowledge_level", "known_content", "misconception",
            "source_chapter_index", "status",
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


# ============================================================
# 向后兼容别名（候选池/别名已废弃）
# ============================================================

WorldEntityRepository = CoreEntityRepository
RelationshipRepository = EntityRelationRepository
