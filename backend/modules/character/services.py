"""
Character 业务逻辑层

调用 repository 完成业务操作。
服务层可包含业务规则，但不直接操作数据库。
"""

from __future__ import annotations

import uuid

from fastapi import HTTPException
from fastapi import status as http_status
from sqlalchemy.ext.asyncio import AsyncSession

from modules.character.repositories import (
    CharacterKnowledgeRepository,
    CharacterRepository,
)
from modules.character.schemas import (
    CharacterContextBundle,
    CharacterContextItem,
    CharacterCreate,
    CharacterKnowledgeContext,
    CharacterKnowledgeCreate,
    CharacterKnowledgeResponse,
    CharacterKnowledgeUpdate,
    CharacterResponse,
    CharacterUpdate,
)
from shared.constants import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from shared.enums import KnowledgeLevel


class CharacterService:
    """人物业务服务"""

    def __init__(self) -> None:
        self._repo = CharacterRepository()
        self._knowledge_repo = CharacterKnowledgeRepository()

    async def create_character(
        self,
        db: AsyncSession,
        data: CharacterCreate,
    ) -> CharacterResponse:
        """创建新人物"""
        character = await self._repo.create(db, data)
        return CharacterResponse.model_validate(character)

    async def get_character(
        self,
        db: AsyncSession,
        character_id: str,
    ) -> CharacterResponse:
        """获取人物详情"""
        cid = self._parse_uuid(character_id)
        character = await self._repo.get(db, cid)
        if character is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"Character {character_id} not found",
            )
        return CharacterResponse.model_validate(character)

    async def list_characters(
        self,
        db: AsyncSession,
        novel_id: str,
        skip: int = 0,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> tuple[list[CharacterResponse], int]:
        """获取人物列表"""
        nid = self._parse_uuid(novel_id)
        limit = min(limit, MAX_PAGE_SIZE)
        items, total = await self._repo.get_by_novel(
            db, nid, skip=skip, limit=limit,
        )
        return [CharacterResponse.model_validate(c) for c in items], total

    async def update_character(
        self,
        db: AsyncSession,
        character_id: str,
        data: CharacterUpdate,
    ) -> CharacterResponse:
        """更新人物"""
        cid = self._parse_uuid(character_id)
        character = await self._repo.update(db, cid, data)
        if character is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"Character {character_id} not found",
            )
        return CharacterResponse.model_validate(character)

    async def delete_character(
        self,
        db: AsyncSession,
        character_id: str,
    ) -> None:
        """删除人物"""
        cid = self._parse_uuid(character_id)
        deleted = await self._repo.delete(db, cid)
        if not deleted:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"Character {character_id} not found",
            )

    async def update_character_state(
        self,
        db: AsyncSession,
        character_id: str,
        current_state: str | None = None,
        current_emotion: str | None = None,
        current_goal: str | None = None,
    ) -> CharacterResponse:
        """更新人物当前状态（状态变化时的便捷方法）"""
        cid = self._parse_uuid(character_id)
        update_data = CharacterUpdate(
            current_state=current_state,
            current_emotion=current_emotion,
            current_goal=current_goal,
        )
        character = await self._repo.update(db, cid, update_data)
        if character is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"Character {character_id} not found",
            )
        return CharacterResponse.model_validate(character)

    # ============================================================
    # CharacterKnowledge
    # ============================================================

    async def create_knowledge(
        self,
        db: AsyncSession,
        data: CharacterKnowledgeCreate,
    ) -> CharacterKnowledgeResponse:
        """创建人物知识记录"""
        knowledge = await self._knowledge_repo.create(db, data)
        return CharacterKnowledgeResponse.model_validate(knowledge)

    async def get_knowledge(
        self,
        db: AsyncSession,
        knowledge_id: str,
    ) -> CharacterKnowledgeResponse:
        """获取单条知识记录"""
        kid = self._parse_uuid(knowledge_id)
        knowledge = await self._knowledge_repo.get(db, kid)
        if knowledge is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"Knowledge record {knowledge_id} not found",
            )
        return CharacterKnowledgeResponse.model_validate(knowledge)

    async def list_knowledge(
        self,
        db: AsyncSession,
        novel_id: str,
        character_id: str,
        skip: int = 0,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> tuple[list[CharacterKnowledgeResponse], int]:
        """获取人物知识列表"""
        nid = self._parse_uuid(novel_id)
        cid = self._parse_uuid(character_id)
        limit = min(limit, MAX_PAGE_SIZE)
        items, total = await self._knowledge_repo.get_by_character(
            db, nid, cid, skip=skip, limit=limit,
        )
        return [
            CharacterKnowledgeResponse.model_validate(k) for k in items
        ], total

    async def update_knowledge(
        self,
        db: AsyncSession,
        knowledge_id: str,
        data: CharacterKnowledgeUpdate,
    ) -> CharacterKnowledgeResponse:
        """更新知识记录"""
        kid = self._parse_uuid(knowledge_id)
        knowledge = await self._knowledge_repo.update(db, kid, data)
        if knowledge is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"Knowledge record {knowledge_id} not found",
            )
        return CharacterKnowledgeResponse.model_validate(knowledge)

    async def delete_knowledge(
        self,
        db: AsyncSession,
        knowledge_id: str,
    ) -> None:
        """删除知识记录"""
        kid = self._parse_uuid(knowledge_id)
        deleted = await self._knowledge_repo.delete(db, kid)
        if not deleted:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"Knowledge record {knowledge_id} not found",
            )

    # ============================================================
    # 人物上下文（供其他模块使用）
    # ============================================================

    async def get_characters_context(
        self,
        db: AsyncSession,
        novel_id: str,
        character_ids: list[str],
        reveal_mode: str = "author_safe",
    ) -> CharacterContextBundle:
        """获取人物上下文包

        根据 character_ids 获取人物信息，供 Context Compiler 等模块使用。
        reveal_mode 控制哪些字段返回（author_safe 不返回 secret）。
        """
        nid = self._parse_uuid(novel_id)
        cids = [self._parse_uuid(cid) for cid in character_ids]
        characters = await self._repo.get_by_ids(db, nid, cids)

        items = []
        for char in characters:
            item = CharacterContextItem(
                character_id=str(char.id),
                name=char.name,
                role=char.role,
                appearance=char.appearance,
                personality=char.personality,
                desire=char.desire,
                fear=char.fear,
                weakness=char.weakness,
                current_goal=char.current_goal,
                current_state=char.current_state,
                current_emotion=char.current_emotion,
                stance=char.stance,
                voice_style=char.voice_style,
                behavior_rules=char.behavior_rules or [],
                relationship_summary=char.relationship_summary,
            )
            # reveal_mode 控制：非 author_only 模式不返回 secret
            if reveal_mode == "author_only":
                item.secret = char.secret
            items.append(item)

        return CharacterContextBundle(
            characters=items,
            total=len(items),
            reveal_mode=reveal_mode,
        )

    async def get_character_knowledge_context(
        self,
        db: AsyncSession,
        novel_id: str,
        character_id: str,
        target_ids: list[str] | None = None,
    ) -> list[CharacterKnowledgeContext]:
        """获取人物知识上下文

        返回角色对所有指定目标的知识情况。
        """
        nid = self._parse_uuid(novel_id)
        cid = self._parse_uuid(character_id)
        tids = (
            [self._parse_uuid(tid) for tid in target_ids]
            if target_ids
            else None
        )
        knowledge_list = await self._knowledge_repo.get_by_target(
            db, nid, cid, tids,
        )

        return [
            CharacterKnowledgeContext(
                target_type=k.target_type,
                target_id=str(k.target_id),
                knowledge_level=k.knowledge_level,
                known_content=k.known_content,
                misconception=k.misconception,
            )
            for k in knowledge_list
        ]

    async def filter_context_by_character_knowledge(
        self,
        db: AsyncSession,
        novel_id: str,
        character_id: str,
        context_items: list[dict],
    ) -> tuple[list[dict], int, int]:
        """按人物知识过滤上下文项

        这是 Character 模块的核心功能：
        - 如果 knowledge_level=unknown → 移除该项
        - 如果 knowledge_level=false_belief → 用角色的误解内容替换
        - 其他（rumor/partial/full）→ 保留该项的 known_content

        Args:
            db: 数据库 session
            novel_id: 小说 ID
            character_id: 人物 ID
            context_items: 待过滤的上下文项列表。
                            每项应包含 target_type 和 target_id 字段用于匹配知识记录。

        Returns:
            (filtered_items, removed_count, replaced_count)
        """
        cid = self._parse_uuid(character_id)
        nid = self._parse_uuid(novel_id)

        # 收集所有目标的 ID
        target_ids_map: dict[str, set[str]] = {}
        for item in context_items:
            t_type = item.get("target_type", "")
            t_id = item.get("target_id", "")
            if t_type and t_id:
                if t_type not in target_ids_map:
                    target_ids_map[t_type] = set()
                target_ids_map[t_type].add(t_id)

        # 按 target_type 分批查询知识记录
        knowledge_map: dict[str, dict] = {}  # key: "type:id" -> knowledge
        for t_type, t_ids in target_ids_map.items():
            tid_uuids = [self._parse_uuid(tid) for tid in t_ids]
            records = await self._knowledge_repo.get_by_target(
                db, nid, cid, tid_uuids,
            )
            for rec in records:
                key = f"{rec.target_type}:{rec.target_id}"
                knowledge_map[key] = {
                    "knowledge_level": rec.knowledge_level,
                    "known_content": rec.known_content,
                    "misconception": rec.misconception,
                }

        filtered_items: list[dict] = []
        removed_count = 0
        replaced_count = 0

        for item in context_items:
            key = f"{item.get('target_type', '')}:{item.get('target_id', '')}"
            knowledge = knowledge_map.get(key)

            if knowledge is None:
                # 没有知识记录 = 角色不知道 → 移除
                removed_count += 1
                continue

            level = knowledge["knowledge_level"]

            if level == KnowledgeLevel.unknown:
                # 不知道 → 移除
                removed_count += 1
            elif level == KnowledgeLevel.false_belief:
                # 误解 → 用 misconception 替换 original_content
                filtered_item = dict(item)  # copy
                filtered_item["original_content"] = filtered_item.get(
                    "content", ""
                )
                filtered_item["content"] = (
                    knowledge["misconception"]
                    or knowledge["known_content"]
                    or ""
                )
                filtered_item["knowledge_level"] = "false_belief"
                filtered_item["is_misconception"] = True
                filtered_items.append(filtered_item)
                replaced_count += 1
            else:
                # rumor/partial/full → 保留，附上 knowledge_level
                filtered_item = dict(item)
                filtered_item["knowledge_level"] = level
                if knowledge["known_content"]:
                    filtered_item["character_known_content"] = (
                        knowledge["known_content"]
                    )
                filtered_items.append(filtered_item)

        return filtered_items, removed_count, replaced_count

    # ============================================================
    # 内部工具
    # ============================================================

    @staticmethod
    def _parse_uuid(id_str: str) -> uuid.UUID:
        """将字符串 ID 解析为 UUID，格式错误时抛出 422"""
        try:
            return uuid.UUID(hex=id_str)
        except ValueError:
            raise HTTPException(
                status_code=http_status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"Invalid UUID: {id_str}",
            )
