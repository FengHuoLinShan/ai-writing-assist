"""
Character 数据访问层

封装 characters 表和 character_knowledge 表的所有数据库操作。
只处理 ORM ↔ DB 的基本 CRUD，不含业务逻辑。
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

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
    """人物数据访问"""

    async def create(
        self,
        db: AsyncSession,
        data: CharacterCreate,
    ) -> Character:
        """创建新人物"""
        character = Character(
            novel_id=uuid.UUID(hex=data.novel_id),
            world_entity_id=(
                uuid.UUID(hex=data.world_entity_id) if data.world_entity_id else None
            ),
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
        """根据 ID 获取人物"""
        stmt = select(Character).where(Character.id == character_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_novel(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        skip: int = 0,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> tuple[list[Character], int]:
        """根据小说 ID 获取人物列表（分页），返回 (items, total)"""
        # 获取总数
        count_stmt = select(func.count(Character.id)).where(
            Character.novel_id == novel_id
        )
        count_result = await db.execute(count_stmt)
        total = count_result.scalar() or 0

        # 获取分页数据
        stmt = (
            select(Character)
            .where(Character.novel_id == novel_id)
            .offset(skip)
            .limit(limit)
            .order_by(Character.created_at.desc())
        )
        result = await db.execute(stmt)
        items: Sequence[Character] = result.scalars().all()
        return list(items), total

    async def get_by_world_entity(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        world_entity_id: uuid.UUID,
    ) -> Character | None:
        """根据 world_entity_id 获取人物"""
        stmt = (
            select(Character)
            .where(Character.novel_id == novel_id)
            .where(Character.world_entity_id == world_entity_id)
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_ids(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        character_ids: list[uuid.UUID],
    ) -> list[Character]:
        """根据 ID 列表批量获取人物"""
        if not character_ids:
            return []
        stmt = (
            select(Character)
            .where(Character.novel_id == novel_id)
            .where(Character.id.in_(character_ids))
            .order_by(Character.id.asc())
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
        """更新人物，返回更新后的对象（不存在返回 None）"""
        character = await self.get(db, character_id)
        if character is None:
            return None

        update_values: dict[str, object] = {}
        field_map = {
            "world_entity_id": "world_entity_id",
            "name": "name",
            "aliases": "aliases",
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
            "status": "status",
        }

        for schema_field, model_field in field_map.items():
            value = getattr(data, schema_field, None)
            if value is not None:
                # Handle UUID conversion
                if schema_field == "world_entity_id" and isinstance(value, str):
                    update_values[model_field] = uuid.UUID(hex=value)
                else:
                    update_values[model_field] = value

        if update_values:
            stmt = (
                update(Character)
                .where(Character.id == character_id)
                .values(**update_values)
            )
            await db.execute(stmt)
            await db.flush()
            character = await self.get(db, character_id)

        return character

    async def delete(
        self,
        db: AsyncSession,
        character_id: uuid.UUID,
    ) -> bool:
        """删除人物，返回是否成功删除"""
        stmt = delete(Character).where(Character.id == character_id)
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
            select(Character.id)
            .where(
                Character.novel_id == novel_id,
                Character.name == name,
                Character.status == "canonical",
            )
            .limit(1)
        )
        result = await db.execute(stmt)
        row = result.scalar_one_or_none()
        if row is not None:
            return str(row)

        alias_stmt = select(Character).where(
            Character.novel_id == novel_id,
            Character.status == "canonical",
        )
        alias_result = await db.execute(alias_stmt)
        chars = alias_result.scalars().all()
        for char in chars:
            for alias_entry in char.aliases or []:
                if isinstance(alias_entry, dict) and alias_entry.get("alias") == name:
                    return str(char.id)

        return None

    async def update_character_meta_location(
        self,
        db: AsyncSession,
        character_id: uuid.UUID,
        location_id: str,
        text_state: str,
        chapter_index: int,
    ) -> None:
        stmt = select(Character).where(Character.id == character_id)
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
        stmt = select(Character).where(
            Character.novel_id == novel_id,
            Character.status == "canonical",
        )
        result = await db.execute(stmt)
        all_chars = result.scalars().all()
        characters = []
        for char in all_chars:
            meta = char.meta or {}
            if meta.get("current_location_id") == location_id:
                characters.append(
                    {
                        "id": str(char.id),
                        "name": char.name,
                        "current_state": char.current_state or "",
                    }
                )
        return characters

    async def get_character_location_id(
        self,
        db: AsyncSession,
        character_id: uuid.UUID,
    ) -> str | None:
        stmt = select(Character).where(Character.id == character_id)
        result = await db.execute(stmt)
        char = result.scalar_one_or_none()
        if char is None:
            return None
        meta = char.meta or {}
        return meta.get("current_location_id")


class CharacterKnowledgeRepository:
    """人物知识数据访问"""

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
                uuid.UUID(hex=data.source_memory_id) if data.source_memory_id else None
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
        """获取人物对特定目标的知识记录

        Args:
            db: 数据库 session
            novel_id: 小说 ID
            character_id: 人物 ID
            target_ids: 目标 ID 列表（可选，不传则返回所有目标的知识）
                          传入空列表 [] 时返回空（区别于 None）
            target_type: 目标类型过滤（可选）
        """
        # 空列表：明确要求查询 0 个目标，直接返回空
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
            "knowledge_level",
            "known_content",
            "misconception",
            "source_chapter_index",
            "source_memory_id",
            "status",
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
