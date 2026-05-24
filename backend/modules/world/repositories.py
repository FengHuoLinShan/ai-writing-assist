"""
World 数据访问层

封装 4 张表的所有数据库操作。
只处理 ORM ↔ DB 的基本 CRUD，不含业务逻辑。
"""

from __future__ import annotations

import uuid
from typing import Any, Sequence

from sqlalchemy import Select, delete, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from modules.world.models import EntityAlias, EntityCandidate, Relationship, WorldEntity
from modules.world.schemas import (
    EntityAliasCreate,
    EntityCandidateCreate,
    EntityCandidateUpdate,
    RelationshipCreate,
    RelationshipUpdate,
    WorldEntityCreate,
    WorldEntityUpdate,
)
from shared.constants import DEFAULT_PAGE_SIZE


# ============================================================
# WorldEntityRepository
# ============================================================

class WorldEntityRepository:
    """世界对象数据访问"""

    async def create(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        data: WorldEntityCreate,
    ) -> WorldEntity:
        """创建世界对象"""
        entity = WorldEntity(
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

    async def get(
        self,
        db: AsyncSession,
        entity_id: uuid.UUID,
    ) -> WorldEntity | None:
        """根据 ID 获取世界对象"""
        stmt = select(WorldEntity).where(WorldEntity.id == entity_id)
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
    ) -> tuple[list[WorldEntity], int]:
        """获取小说的世界对象列表（分页），返回 (items, total)"""
        # 构建查询条件
        conditions = [WorldEntity.novel_id == novel_id]
        if entity_type:
            conditions.append(WorldEntity.entity_type == entity_type)
        if status:
            conditions.append(WorldEntity.status == status)

        # 计数
        count_stmt = select(WorldEntity.id).where(*conditions)
        count_result = await db.execute(count_stmt)
        total = len(count_result.all())

        # 分页查询
        stmt = (
            select(WorldEntity)
            .where(*conditions)
            .offset(skip)
            .limit(limit)
            .order_by(WorldEntity.importance.desc(), WorldEntity.name)
        )
        result = await db.execute(stmt)
        items: Sequence[WorldEntity] = result.scalars().all()
        return list(items), total

    async def get_by_ids(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        entity_ids: list[uuid.UUID],
    ) -> list[WorldEntity]:
        """批量获取指定 ID 的世界对象"""
        stmt = select(WorldEntity).where(
            WorldEntity.novel_id == novel_id,
            WorldEntity.id.in_(entity_ids),
        )
        result = await db.execute(stmt)
        items: Sequence[WorldEntity] = result.scalars().all()
        return list(items)

    async def get_by_type_and_status(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        entity_type: str | None = None,
        status: str | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> list[WorldEntity]:
        """按类型和状态查询"""
        conditions = [WorldEntity.novel_id == novel_id]
        if entity_type:
            conditions.append(WorldEntity.entity_type == entity_type)
        if status:
            conditions.append(WorldEntity.status == status)

        stmt = (
            select(WorldEntity)
            .where(*conditions)
            .limit(limit)
            .order_by(WorldEntity.importance.desc())
        )
        result = await db.execute(stmt)
        items: Sequence[WorldEntity] = result.scalars().all()
        return list(items)

    async def update(
        self,
        db: AsyncSession,
        entity_id: uuid.UUID,
        data: WorldEntityUpdate,
    ) -> WorldEntity | None:
        """更新世界对象，返回更新后的对象（不存在返回 None）"""
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
                update(WorldEntity)
                .where(WorldEntity.id == entity_id)
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
        """删除世界对象，返回是否成功删除"""
        stmt = delete(WorldEntity).where(WorldEntity.id == entity_id)
        result = await db.execute(stmt)
        await db.flush()
        return result.rowcount > 0


# ============================================================
# RelationshipRepository
# ============================================================

class RelationshipRepository:
    """关系数据访问"""

    async def create(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        data: RelationshipCreate,
    ) -> Relationship:
        """创建关系"""
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

    async def get(
        self,
        db: AsyncSession,
        rel_id: uuid.UUID,
    ) -> Relationship | None:
        """根据 ID 获取关系"""
        stmt = select(Relationship).where(Relationship.id == rel_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_novel(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        *,
        skip: int = 0,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> tuple[list[Relationship], int]:
        """获取小说的关系列表（分页）"""
        conditions = [Relationship.novel_id == novel_id]

        count_stmt = select(Relationship.id).where(*conditions)
        count_result = await db.execute(count_stmt)
        total = len(count_result.all())

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
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        source_id: str,
        *,
        relation_type: str | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> list[Relationship]:
        """获取以指定对象为源的关系"""
        conditions = [
            Relationship.novel_id == novel_id,
            Relationship.source_id == source_id,
        ]
        if relation_type:
            conditions.append(Relationship.relation_type == relation_type)

        stmt = (
            select(Relationship)
            .where(*conditions)
            .limit(limit)
            .order_by(Relationship.strength.desc())
        )
        result = await db.execute(stmt)
        items: Sequence[Relationship] = result.scalars().all()
        return list(items)

    async def get_by_target(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        target_id: str,
        *,
        relation_type: str | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> list[Relationship]:
        """获取以指定对象为目标的关系"""
        conditions = [
            Relationship.novel_id == novel_id,
            Relationship.target_id == target_id,
        ]
        if relation_type:
            conditions.append(Relationship.relation_type == relation_type)

        stmt = (
            select(Relationship)
            .where(*conditions)
            .limit(limit)
            .order_by(Relationship.strength.desc())
        )
        result = await db.execute(stmt)
        items: Sequence[Relationship] = result.scalars().all()
        return list(items)

    async def get_related_entity_ids(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        entity_id: str,
        depth: int = 1,
        limit: int = 20,
    ) -> set[str]:
        """获取与指定对象直接相关的实体 ID 集合

        一跳（depth=1）：直接连接的对象
        二跳（depth=2）：直接对象的直接连接对象（一跳扩展）
        """
        related: set[str] = set()

        # 一跳：直接 source→target 和 target→source
        source_rels = await self.get_by_source(db, novel_id, entity_id, limit=limit)
        for rel in source_rels:
            related.add(rel.target_id)

        target_rels = await self.get_by_target(db, novel_id, entity_id, limit=limit)
        for rel in target_rels:
            related.add(rel.source_id)

        if depth >= 2:
            # 二跳：对一跳结果再扩展
            for related_id in list(related):
                if len(related) >= limit:
                    break
                second_source = await self.get_by_source(
                    db, novel_id, related_id, limit=limit // 2,
                )
                for rel in second_source:
                    if len(related) >= limit:
                        break
                    related.add(rel.target_id)

                second_target = await self.get_by_target(
                    db, novel_id, related_id, limit=limit // 2,
                )
                for rel in second_target:
                    if len(related) >= limit:
                        break
                    related.add(rel.source_id)

        return related

    async def update(
        self,
        db: AsyncSession,
        rel_id: uuid.UUID,
        data: RelationshipUpdate,
    ) -> Relationship | None:
        """更新关系"""
        rel = await self.get(db, rel_id)
        if rel is None:
            return None

        update_values: dict[str, Any] = {}
        for field in (
            "source_type",
            "source_id",
            "target_type",
            "target_id",
            "relation_type",
            "description",
            "visibility",
            "strength",
            "status",
        ):
            value = getattr(data, field, None)
            if value is not None:
                update_values[field] = value

        if update_values:
            stmt = (
                update(Relationship)
                .where(Relationship.id == rel_id)
                .values(**update_values)
            )
            await db.execute(stmt)
            await db.flush()
            rel = await self.get(db, rel_id)

        return rel

    async def delete(
        self,
        db: AsyncSession,
        rel_id: uuid.UUID,
    ) -> bool:
        """删除关系"""
        stmt = delete(Relationship).where(Relationship.id == rel_id)
        result = await db.execute(stmt)
        await db.flush()
        return result.rowcount > 0


# ============================================================
# EntityAliasRepository
# ============================================================

class EntityAliasRepository:
    """别名数据访问"""

    async def create(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        data: EntityAliasCreate,
    ) -> EntityAlias:
        """创建别名"""
        alias = EntityAlias(
            novel_id=novel_id,
            entity_id=data.entity_id,
            alias=data.alias,
            alias_type=data.alias_type or "name",
            source_chapter_index=data.source_chapter_index,
            confidence=data.confidence or 0.8,
            status=data.status or "confirmed",
        )
        db.add(alias)
        await db.flush()
        return alias

    async def get(
        self,
        db: AsyncSession,
        alias_id: uuid.UUID,
    ) -> EntityAlias | None:
        """根据 ID 获取别名"""
        stmt = select(EntityAlias).where(EntityAlias.id == alias_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_novel(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        *,
        entity_id: str | None = None,
        skip: int = 0,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> tuple[list[EntityAlias], int]:
        """获取小说的别名列表（分页）"""
        conditions = [EntityAlias.novel_id == novel_id]
        if entity_id:
            conditions.append(EntityAlias.entity_id == entity_id)

        count_stmt = select(EntityAlias.id).where(*conditions)
        count_result = await db.execute(count_stmt)
        total = len(count_result.all())

        stmt = (
            select(EntityAlias)
            .where(*conditions)
            .offset(skip)
            .limit(limit)
            .order_by(EntityAlias.alias)
        )
        result = await db.execute(stmt)
        items: Sequence[EntityAlias] = result.scalars().all()
        return list(items), total

    async def get_by_entity(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        entity_id: str,
    ) -> list[EntityAlias]:
        """获取指定对象的所有别名"""
        stmt = select(EntityAlias).where(
            EntityAlias.novel_id == novel_id,
            EntityAlias.entity_id == entity_id,
        )
        result = await db.execute(stmt)
        items: Sequence[EntityAlias] = result.scalars().all()
        return list(items)

    async def find_by_alias_text(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        alias_text: str,
    ) -> list[EntityAlias]:
        """通过别名文本查找（精确匹配）"""
        stmt = select(EntityAlias).where(
            EntityAlias.novel_id == novel_id,
            EntityAlias.alias == alias_text,
        )
        result = await db.execute(stmt)
        items: Sequence[EntityAlias] = result.scalars().all()
        return list(items)

    async def delete(
        self,
        db: AsyncSession,
        alias_id: uuid.UUID,
    ) -> bool:
        """删除别名"""
        stmt = delete(EntityAlias).where(EntityAlias.id == alias_id)
        result = await db.execute(stmt)
        await db.flush()
        return result.rowcount > 0


# ============================================================
# EntityCandidateRepository
# ============================================================

class EntityCandidateRepository:
    """候选对象数据访问"""

    async def create(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        data: EntityCandidateCreate,
    ) -> EntityCandidate:
        """创建候选对象"""
        candidate = EntityCandidate(
            novel_id=novel_id,
            name=data.name,
            entity_type=data.entity_type,
            summary=data.summary,
            source_text=data.source_text,
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

    async def get(
        self,
        db: AsyncSession,
        candidate_id: uuid.UUID,
    ) -> EntityCandidate | None:
        """根据 ID 获取候选对象"""
        stmt = select(EntityCandidate).where(EntityCandidate.id == candidate_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_novel(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        *,
        status: str | None = None,
        suggested_action: str | None = None,
        skip: int = 0,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> tuple[list[EntityCandidate], int]:
        """获取小说的候选对象列表（分页）"""
        conditions = [EntityCandidate.novel_id == novel_id]
        if status:
            conditions.append(EntityCandidate.status == status)
        if suggested_action:
            conditions.append(EntityCandidate.suggested_action == suggested_action)

        count_stmt = select(EntityCandidate.id).where(*conditions)
        count_result = await db.execute(count_stmt)
        total = len(count_result.all())

        stmt = (
            select(EntityCandidate)
            .where(*conditions)
            .offset(skip)
            .limit(limit)
            .order_by(EntityCandidate.importance_score.desc())
        )
        result = await db.execute(stmt)
        items: Sequence[EntityCandidate] = result.scalars().all()
        return list(items), total

    async def get_by_status(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        status: str,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> list[EntityCandidate]:
        """按状态查询候选"""
        stmt = (
            select(EntityCandidate)
            .where(
                EntityCandidate.novel_id == novel_id,
                EntityCandidate.status == status,
            )
            .limit(limit)
            .order_by(EntityCandidate.importance_score.desc())
        )
        result = await db.execute(stmt)
        items: Sequence[EntityCandidate] = result.scalars().all()
        return list(items)

    async def update(
        self,
        db: AsyncSession,
        candidate_id: uuid.UUID,
        data: EntityCandidateUpdate,
    ) -> EntityCandidate | None:
        """更新候选对象"""
        candidate = await self.get(db, candidate_id)
        if candidate is None:
            return None

        update_values: dict[str, Any] = {}
        for field in (
            "name",
            "entity_type",
            "summary",
            "source_text",
            "source_chapter_index",
            "importance_score",
            "confidence",
            "candidate_reason",
            "suggested_action",
            "suggested_existing_entity_id",
            "status",
        ):
            value = getattr(data, field, None)
            if value is not None:
                update_values[field] = value

        if update_values:
            stmt = (
                update(EntityCandidate)
                .where(EntityCandidate.id == candidate_id)
                .values(**update_values)
            )
            await db.execute(stmt)
            await db.flush()
            candidate = await self.get(db, candidate_id)

        return candidate

    async def delete(
        self,
        db: AsyncSession,
        candidate_id: uuid.UUID,
    ) -> bool:
        """删除候选对象"""
        stmt = delete(EntityCandidate).where(EntityCandidate.id == candidate_id)
        result = await db.execute(stmt)
        await db.flush()
        return result.rowcount > 0
