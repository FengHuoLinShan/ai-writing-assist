"""
World 数据访问层

封装 core_entities、relationships、entity_candidates 三张表的数据库操作。
别名已整合为 core_entities.aliases JSONB，不再使用独立的 entity_aliases 表。
"""

from __future__ import annotations

import uuid
from typing import Any, Sequence

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import JSON

from modules.world.models import CoreEntity, EntityCandidate, Relationship
from modules.world.schemas import (
    CoreEntityCreate,
    CoreEntityUpdate,
    EntityCandidateCreate,
    EntityCandidateUpdate,
    RelationshipCreate,
    RelationshipUpdate,
)
from shared.constants import DEFAULT_PAGE_SIZE


# ============================================================
# CoreEntityRepository
# ============================================================

class CoreEntityRepository:
    """核心实体数据访问 — 取代原 WorldEntityRepository + EntityAliasRepository"""

    async def create(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        data: CoreEntityCreate,
    ) -> CoreEntity:
        """创建核心实体"""
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

    async def get(
        self,
        db: AsyncSession,
        entity_id: uuid.UUID,
    ) -> CoreEntity | None:
        """根据 ID 获取核心实体"""
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
        """获取小说的核心实体列表（分页）"""
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
        """批量获取指定 ID 的核心实体"""
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
        """按类型和状态查询"""
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
        """更新核心实体"""
        entity = await self.get(db, entity_id)
        if entity is None:
            return None

        update_values: dict[str, Any] = {}
        for field in (
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
            entity = await self.get(db, entity_id)

        return entity

    async def delete(
        self,
        db: AsyncSession,
        entity_id: uuid.UUID,
    ) -> bool:
        """删除核心实体（ON DELETE CASCADE 自动清理扩展表）"""
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

        # Search aliases in Python so the lookup works on both PostgreSQL and
        # SQLite tests, and so alias text never gets interpolated into SQL.
        # LIMIT caps memory usage for novels with many entities.
        alias_conditions = [
            CoreEntity.novel_id == novel_id,
            CoreEntity.status == "canonical",
        ]
        if entity_type:
            alias_conditions.append(CoreEntity.entity_type == entity_type)
        alias_stmt = select(CoreEntity).where(*alias_conditions).limit(500)
        alias_result = await db.execute(alias_stmt)
        for entity in alias_result.scalars().all():
            for alias_entry in entity.aliases or []:
                if isinstance(alias_entry, dict) and alias_entry.get("alias") == name:
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
# ============================================================

class RelationshipRepository:
    """关系数据访问"""

    async def create(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        data: RelationshipCreate,
    ) -> Relationship:
        rel = Relationship(
            novel_id=novel_id,
            source_type=data.source_type,
            source_id=data.source_id,
            target_type=data.target_type,
            target_id=data.target_id,
            relation_type=data.relation_type,
            description=data.description,
            visibility=data.visibility or "author_only",
            strength=data.strength or 0.5,
            status=data.status or "canonical",
        )
        db.add(rel)
        await db.flush()
        return rel

    async def get(self, db: AsyncSession, rel_id: uuid.UUID) -> Relationship | None:
        stmt = select(Relationship).where(Relationship.id == rel_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_novel(
        self, db: AsyncSession, novel_id: uuid.UUID, *,
        skip: int = 0, limit: int = DEFAULT_PAGE_SIZE,
    ) -> tuple[list[Relationship], int]:
        conditions = [Relationship.novel_id == novel_id]
        count_stmt = select(func.count(Relationship.id)).where(*conditions)
        count_result = await db.execute(count_stmt)
        total = count_result.scalar() or 0

        stmt = (
            select(Relationship)
            .where(*conditions)
            .offset(skip)
            .limit(limit)
            .order_by(Relationship.created_at.desc())
        )
        result = await db.execute(stmt)
        items: Sequence[Relationship] = result.scalars().all()
        return list(items), total

    async def get_by_source(
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
        if depth >= 2:
            for hop_id in list(one_hop_ids):
                if len(related) >= limit:
                    break
                second_hop = await self._get_one_hop_ids(db, novel_id, hop_id)
                related.update(second_hop)
                if len(related) >= limit:
                    break
        return related

    async def _get_one_hop_ids(
        self, db: AsyncSession, novel_id: uuid.UUID, entity_id: str,
    ) -> set[str]:
        from sqlalchemy import union_all
        src_stmt = select(Relationship.target_id.label("related_id")).where(
            Relationship.novel_id == novel_id, Relationship.source_id == entity_id,
        )
        tgt_stmt = select(Relationship.source_id.label("related_id")).where(
            Relationship.novel_id == novel_id, Relationship.target_id == entity_id,
        )
        combined = union_all(src_stmt, tgt_stmt)
        result = await db.execute(combined)
        return {row[0] for row in result.all()}

    async def update(
        self, db: AsyncSession, rel_id: uuid.UUID, data: RelationshipUpdate,
    ) -> Relationship | None:
        rel = await self.get(db, rel_id)
        if rel is None:
            return None
        update_values: dict[str, Any] = {}
        for field in ("source_type", "source_id", "target_type", "target_id",
                       "relation_type", "description", "visibility", "strength", "status"):
            value = getattr(data, field, None)
            if value is not None:
                update_values[field] = value
        if update_values:
            stmt = update(Relationship).where(Relationship.id == rel_id).values(**update_values)
            await db.execute(stmt)
            await db.flush()
            rel = await self.get(db, rel_id)
        return rel

    async def delete(self, db: AsyncSession, rel_id: uuid.UUID) -> bool:
        stmt = delete(Relationship).where(Relationship.id == rel_id)
        result = await db.execute(stmt)
        await db.flush()
        return result.rowcount > 0

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
        ).limit(1)
        result = await db.execute(stmt)
        existing = result.scalar_one_or_none()
        if existing is not None:
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
# ============================================================

class EntityCandidateRepository:
    """候选对象数据访问"""

    async def create(
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
        )
        db.add(candidate)
        await db.flush()
        return candidate

    async def get(self, db: AsyncSession, candidate_id: uuid.UUID) -> EntityCandidate | None:
        stmt = select(EntityCandidate).where(EntityCandidate.id == candidate_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_novel(
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
            return None
        update_values: dict[str, Any] = {}
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
        result = await db.execute(stmt)
        await db.flush()
        return result.rowcount > 0
