"""
Character 数据访问层

Character 以 entity_id 为 PK+FK（→ core_entities.id），仅存储扩展字段。
公共字段（name, aliases, status）在 core_entities 中。
"""

from __future__ import annotations

import uuid
from typing import Sequence

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from modules.character.models import Character, CharacterKnowledge
from modules.character.schemas import (
    CharacterCreate,
    CharacterKnowledgeCreate,
    CharacterKnowledgeUpdate,
    CharacterUpdate,
)
from shared.constants import DEFAULT_PAGE_SIZE


class CharacterRepository:
    """人物扩展表数据访问 — PK 为 entity_id"""

    async def create(
        self,
        db: AsyncSession,
        data: CharacterCreate,
    ) -> Character:
        """创建人物扩展记录"""
        character = Character(
            entity_id=uuid.UUID(hex=data.entity_id),
            novel_id=uuid.UUID(hex=data.novel_id),
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
        )
        db.add(character)
        await db.flush()
        return character

    async def get(
        self,
        db: AsyncSession,
        entity_id: uuid.UUID,
    ) -> Character | None:
        """根据 entity_id 获取人物扩展"""
        stmt = select(Character).where(Character.entity_id == entity_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_novel(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        skip: int = 0,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> tuple[list[Character], int]:
        """根据小说 ID 获取人物扩展列表（分页）"""
        count_stmt = (
            select(func.count(Character.entity_id))
            .where(Character.novel_id == novel_id)
        )
        count_result = await db.execute(count_stmt)
        total = count_result.scalar() or 0

        stmt = (
            select(Character)
            .where(Character.novel_id == novel_id)
            .offset(skip)
            .limit(limit)
            .order_by(Character.entity_id.asc())
        )
        result = await db.execute(stmt)
        items: Sequence[Character] = result.scalars().all()
        return list(items), total

    async def get_by_ids(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        entity_ids: list[uuid.UUID],
    ) -> list[Character]:
        """根据 entity_id 列表批量获取人物扩展"""
        if not entity_ids:
            return []
        stmt = (
            select(Character)
            .where(Character.novel_id == novel_id)
            .where(Character.entity_id.in_(entity_ids))
            .order_by(Character.entity_id.asc())
        )
        result = await db.execute(stmt)
        items: Sequence[Character] = result.scalars().all()
        return list(items)

    async def update(
        self,
        db: AsyncSession,
        entity_id: uuid.UUID,
        data: CharacterUpdate,
    ) -> Character | None:
        """更新人物扩展字段"""
        character = await self.get(db, entity_id)
        if character is None:
            return None

        update_values: dict[str, object] = {}
        field_map = {
            "role": "role",
            "appearance": "appearance",
            "personality": "personality",
            "desire": "desire",
            "fear": "fear",
            "secret": "secret",
            "weakness": "weakness",
            "current_goal": "current_goal",
            "current_state": "current_state",
            "current_emotion": "current_emotion",
            "stance": "stance",
            "voice_style": "voice_style",
            "behavior_rules": "behavior_rules",
            "relationship_summary": "relationship_summary",
            "meta": "meta",
        }

        for schema_field, model_field in field_map.items():
            value = getattr(data, schema_field, None)
            if value is not None:
                update_values[model_field] = value

        if update_values:
            stmt = (
                update(Character)
                .where(Character.entity_id == entity_id)
                .values(**update_values)
            )
            await db.execute(stmt)
            await db.flush()
            character = await self.get(db, entity_id)

        return character

    async def delete(
        self,
        db: AsyncSession,
        entity_id: uuid.UUID,
    ) -> bool:
        """删除人物扩展记录"""
        stmt = delete(Character).where(Character.entity_id == entity_id)
        result = await db.execute(stmt)
        await db.flush()
        return result.rowcount > 0

    async def update_character_meta_location(
        self,
        db: AsyncSession,
        entity_id: uuid.UUID,
        location_id: str,
        text_state: str,
        chapter_index: int,
    ) -> None:
        """更新人物当前位置元数据"""
        stmt = select(Character).where(Character.entity_id == entity_id)
        result = await db.execute(stmt)
        char = result.scalar_one_or_none()
        if char is None:
            return
        meta = dict(char.meta or {})
        meta["current_location_id"] = location_id
        meta["last_updated_chapter"] = chapter_index
        char.meta = meta
        char.current_state = text_state
        await db.flush()

    async def find_characters_by_location(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        location_id: str,
    ) -> list[dict]:
        """获取当前在指定地点的人物列表（返回 entity_id）"""
        stmt = select(Character).where(
            Character.novel_id == novel_id,
        )
        result = await db.execute(stmt)
        all_chars = result.scalars().all()
        characters = []
        for char in all_chars:
            meta = char.meta or {}
            if meta.get("current_location_id") == location_id:
                characters.append({
                    "id": str(char.entity_id),
                    "current_state": char.current_state or "",
                })
        return characters

    async def get_character_location_id(
        self,
        db: AsyncSession,
        entity_id: uuid.UUID,
    ) -> str | None:
        """获取人物当前位置 ID"""
        stmt = select(Character).where(Character.entity_id == entity_id)
        result = await db.execute(stmt)
        char = result.scalar_one_or_none()
        if char is None:
            return None
        meta = char.meta or {}
        return meta.get("current_location_id")


class CharacterKnowledgeRepository:
    """人物知识数据访问 — character_id 现在引用 core_entities.id"""

    async def create(
        self,
        db: AsyncSession,
        data: CharacterKnowledgeCreate,
    ) -> CharacterKnowledge:
        """创建新知识记录"""
        knowledge = CharacterKnowledge(
            novel_id=uuid.UUID(hex=data.novel_id),
            character_id=uuid.UUID(hex=data.character_id),
            target_type=data.target_type,
            target_id=uuid.UUID(hex=data.target_id),
            knowledge_level=data.knowledge_level,
            known_content=data.known_content,
            misconception=data.misconception,
            source_chapter_index=data.source_chapter_index,
            source_memory_id=(
                uuid.UUID(hex=data.source_memory_id)
                if data.source_memory_id
                else None
            ),
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
        """根据 ID 获取知识记录"""
        stmt = select(CharacterKnowledge).where(CharacterKnowledge.id == knowledge_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_character(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        character_id: uuid.UUID,
        skip: int = 0,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> tuple[list[CharacterKnowledge], int]:
        """获取人物知识列表（分页）"""
        count_stmt = (
            select(func.count(CharacterKnowledge.id))
            .where(CharacterKnowledge.novel_id == novel_id)
            .where(CharacterKnowledge.character_id == character_id)
        )
        count_result = await db.execute(count_stmt)
        total = count_result.scalar() or 0

        stmt = (
            select(CharacterKnowledge)
            .where(CharacterKnowledge.novel_id == novel_id)
            .where(CharacterKnowledge.character_id == character_id)
            .offset(skip)
            .limit(limit)
            .order_by(CharacterKnowledge.created_at.desc())
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
        target_type: str | None = None,
    ) -> list[CharacterKnowledge]:
        """获取人物对特定目标的知识记录"""
        if target_ids is not None and len(target_ids) == 0:
            return []

        stmt = (
            select(CharacterKnowledge)
            .where(CharacterKnowledge.novel_id == novel_id)
            .where(CharacterKnowledge.character_id == character_id)
        )
        if target_ids:
            stmt = stmt.where(CharacterKnowledge.target_id.in_(target_ids))
        if target_type is not None:
            stmt = stmt.where(CharacterKnowledge.target_type == target_type)
        result = await db.execute(stmt)
        items: Sequence[CharacterKnowledge] = result.scalars().all()
        return list(items)

    async def update(
        self,
        db: AsyncSession,
        knowledge_id: uuid.UUID,
        data: CharacterKnowledgeUpdate,
    ) -> CharacterKnowledge | None:
        """更新知识记录"""
        knowledge = await self.get(db, knowledge_id)
        if knowledge is None:
            return None

        update_values: dict[str, object] = {}
        for field in (
            "knowledge_level", "known_content", "misconception",
            "source_chapter_index", "source_memory_id", "status",
        ):
            value = getattr(data, field, None)
            if value is not None:
                if field == "source_memory_id" and isinstance(value, str):
                    update_values[field] = uuid.UUID(hex=value)
                else:
                    update_values[field] = value

        if update_values:
            stmt = (
                update(CharacterKnowledge)
                .where(CharacterKnowledge.id == knowledge_id)
                .values(**update_values)
            )
            await db.execute(stmt)
            await db.flush()
            knowledge = await self.get(db, knowledge_id)

        return knowledge

    async def get_unknown_target_ids(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        character_id: uuid.UUID,
    ) -> dict[str, list[str]]:
        """获取角色标记为 unknown/false_belief 的所有目标 ID

        供 RAG 检索进行硬过滤，防止角色视角越权。
        """
        stmt = select(CharacterKnowledge).where(
            CharacterKnowledge.novel_id == novel_id,
            CharacterKnowledge.character_id == character_id,
            CharacterKnowledge.knowledge_level.in_(["unknown", "false_belief"]),
        )
        result = await db.execute(stmt)
        rows: Sequence[CharacterKnowledge] = result.scalars().all()

        entity_ids: list[str] = []
        char_ids: list[str] = []
        for row in rows:
            tid = str(row.target_id)
            if row.target_type == "entity":
                entity_ids.append(tid)
            elif row.target_type == "character":
                char_ids.append(tid)
        return {"entity_ids": entity_ids, "character_ids": char_ids}

    async def delete(
        self,
        db: AsyncSession,
        knowledge_id: uuid.UUID,
    ) -> bool:
        """删除知识记录"""
        stmt = delete(CharacterKnowledge).where(CharacterKnowledge.id == knowledge_id)
        result = await db.execute(stmt)
        await db.flush()
        return result.rowcount > 0
