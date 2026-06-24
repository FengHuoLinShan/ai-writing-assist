"""CharacterService — 人物业务。继承 BaseCRUDService (ADR-0002)。

知识边界 (CharacterKnowledge) 的 CRUD 移到 CharacterKnowledgeService (独立子类)。
本 service 只保留:
- 5 verb 继承自 base
- 8 个特例方法 (人物上下文 / 知识过滤 / facade 跨模块 leak)
"""

from __future__ import annotations

from fastapi import HTTPException
from fastapi import status as http_status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from modules.world.models import Character
from modules.world.repositories import (
    CharacterKnowledgeRepository,
    CharacterRepository,
    CoreEntityRepository,
)
from modules.world.schemas import (
    CharacterContextBundle,
    CharacterContextItem,
    CharacterCreate,
    CharacterResponse,
    CharacterUpdate,
)
from modules.world.services.base import CrudService
from modules.world.services.helpers import parse_uuid
from shared.constants import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE


class CharacterService(
    CrudService[Character, CharacterCreate, CharacterUpdate, CharacterResponse],
):
    """人物业务服务。

    5 verb 继承自 base; 知识 CRUD 在独立 CharacterKnowledgeService。
    """

    repo = CharacterRepository()
    response = CharacterResponse
    label = "Character"
    id_param = "character_id"  # Character PK 是 entity_id, parse_uuid 报错字段名

    # knowledge 业务方法不属 base 5 verb, 显式注入第二个 repo
    def __init__(self) -> None:
        self._knowledge_repo = CharacterKnowledgeRepository()

    # ============================================================
    # 5 verb 继承自 base
    # (list 加 clamp, create 校验 entity_id, 其它 3 verb 透传)
    # ============================================================

    async def create(
        self,
        db: AsyncSession,
        novel_id: str,
        data: CharacterCreate,
    ) -> CharacterResponse:
        """创建人物前校验关联 CoreEntity 存在且属于当前项目。"""
        nid = parse_uuid(novel_id, "novel_id")
        eid = parse_uuid(data.entity_id, "entity_id")
        entity_repo = CoreEntityRepository()
        entity = await entity_repo.get(db, eid)
        if entity is None or entity.novel_id != nid:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"CoreEntity {data.entity_id} not found",
            )
        try:
            obj = await self.repo.create(db, nid, data)
        except IntegrityError as exc:
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail=f"CoreEntity {data.entity_id} not found or conflict",
            ) from exc
        return self._to_response(obj)

    async def list(  # type: ignore[override]
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        skip: int = 0,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> tuple[list[CharacterResponse], int]:
        """返 (items, total) tuple (非 ListResponse 包装, 与 WorldEntityService 不同)。"""
        nid = parse_uuid(novel_id, "novel_id")
        limit = min(limit, MAX_PAGE_SIZE)
        items, total = await self.repo.get_by_novel(
            db,
            nid,
            skip=skip,
            limit=limit,
        )
        return [CharacterResponse.model_validate(c) for c in items], total

    # ============================================================
    # CharacterState 更新 (跨多字段, 非 5 verb 标准 update)
    # ============================================================

    async def update_character_state(
        self,
        db: AsyncSession,
        character_id: str,
        *,
        current_state: str | None = None,
        current_emotion: str | None = None,
        current_goal: str | None = None,
        novel_id: str,
    ) -> CharacterResponse:
        cid = parse_uuid(character_id, "character_id")
        nid = parse_uuid(novel_id, "novel_id")
        existing = await self.repo.get(db, cid)
        if existing is None or existing.novel_id != nid:
            self._raise_404(character_id)
        update_data = CharacterUpdate(
            current_state=current_state,
            current_emotion=current_emotion,
            current_goal=current_goal,
        )
        character = await self.repo.update(db, cid, update_data)
        if character is None:
            self._raise_404(character_id)
        return CharacterResponse.model_validate(character)

    # ============================================================
    # 人物上下文 (供 context module 用)
    # ============================================================

    async def get_characters_context(
        self,
        db: AsyncSession,
        novel_id: str,
        character_ids: list[str],
        reveal_mode: str = "author_safe",
    ) -> CharacterContextBundle:
        nid = parse_uuid(novel_id, "novel_id")
        cids = [parse_uuid(cid, "character_id") for cid in character_ids]
        characters = await self.repo.get_by_ids(db, nid, cids)

        items = []
        for char in characters:
            item = CharacterContextItem(
                character_id=str(char.entity_id),
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
    ) -> list:
        """返回 knowledge 上下文, 留为返回 dict (避免循环 import schema)。"""
        from modules.world.schemas import CharacterKnowledgeContext

        nid = parse_uuid(novel_id, "novel_id")
        cid = parse_uuid(character_id, "character_id")
        tids = [parse_uuid(tid) for tid in target_ids] if target_ids else None
        knowledge_list = await self._knowledge_repo.get_by_target(
            db,
            nid,
            cid,
            tids,
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
        cid = parse_uuid(character_id, "character_id")
        nid = parse_uuid(novel_id, "novel_id")

        target_ids_map: dict[str, set[str]] = {}
        for item in context_items:
            t_type = item.get("target_type", "")
            t_id = item.get("target_id", "")
            if t_type and t_id:
                target_ids_map.setdefault(t_type, set()).add(t_id)

        knowledge_map: dict[str, dict] = {}
        for t_type, t_ids in target_ids_map.items():
            tid_uuids = [parse_uuid(tid) for tid in t_ids]
            records = await self._knowledge_repo.get_by_target(
                db,
                nid,
                cid,
                tid_uuids,
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

            # 设计选择：在 character reveal 模式下，调用方（characters_loader）
            # 只在 reveal_mode == "character" 时才会进入本方法。因此此处缺失
            # knowledge 记录代表该视角人物对这个实体没有任何认知边界信息，
            # 按“未知”处理并 intentional 地从该人物的 compiled context 中移除。
            if knowledge is None:
                removed_count += 1
                continue

            level = knowledge["knowledge_level"]

            if level == "unknown":
                removed_count += 1
            elif level in {"false_belief", "misunderstood"}:
                filtered_item = dict(item)
                filtered_item.pop("hidden_truth", None)
                filtered_item["original_content"] = filtered_item.get("content", "")
                filtered_item["content"] = (
                    knowledge["misconception"] or knowledge["known_content"] or ""
                )
                filtered_item["knowledge_level"] = level
                filtered_item["is_misconception"] = True
                filtered_items.append(filtered_item)
                replaced_count += 1
            elif level == "restricted":
                filtered_item = dict(item)
                filtered_item.pop("hidden_truth", None)
                filtered_item["knowledge_level"] = level
                if knowledge["known_content"]:
                    filtered_item["content"] = knowledge["known_content"]
                    filtered_item["summary"] = knowledge["known_content"]
                filtered_items.append(filtered_item)
            elif level in {"partial", "rumor"}:
                filtered_item = dict(item)
                filtered_item["knowledge_level"] = level
                if knowledge["known_content"]:
                    filtered_item["character_known_content"] = knowledge["known_content"]
                filtered_items.append(filtered_item)
            else:
                # full 等明确等级：按原样保留（包括 hidden_truth）
                filtered_item = dict(item)
                filtered_item["knowledge_level"] = level
                filtered_items.append(filtered_item)

        return filtered_items, removed_count, replaced_count

    # ============================================================
    # 跨模块 facade leak (PR 2)
    # ============================================================

    async def get_id_by_world_entity(
        self,
        db: AsyncSession,
        novel_id: str,
        world_entity_id: str,
    ) -> str | None:
        """按核心实体 ID 查 character entity_id。返 str 或 None。

        注: novel_id 接收但不传给 repo — character PK 是 entity_id,
        repo.get 不需 novel_id 过滤。novel_id 参数保留是为了 facade 跨模块契约稳定。
        """
        weid = parse_uuid(world_entity_id, "entity_id")
        char = await self.repo.get(db, weid)
        if char is None:
            return None
        return str(char.entity_id)

    async def find_by_name(
        self,
        db: AsyncSession,
        novel_id: str,
        name: str,
    ) -> str | None:
        """按 character name 查正史 character 的 entity_id。"""
        nid = parse_uuid(novel_id, "novel_id")
        return await self.repo.find_character_by_name(db, nid, name)

    async def update_location(
        self,
        db: AsyncSession,
        novel_id: str,
        character_id: str,
        location_id: str,
        text_state: str,
        chapter_index: int,
    ) -> None:
        """更新 character 的位置元数据。"""
        cid = parse_uuid(character_id, "character_id")
        loc_id = parse_uuid(location_id, "location_id")
        await self.repo.update_character_meta_location(
            db,
            cid,
            loc_id,
            text_state,
            chapter_index,
        )

    async def get_characters_at_location(
        self,
        db: AsyncSession,
        novel_id: str,
        location_id: str,
    ) -> list[dict]:
        """查某 location 下的所有正史 character。"""
        nid = parse_uuid(novel_id, "novel_id")
        loc_id = parse_uuid(location_id, "location_id")
        return await self.repo.find_characters_by_location(db, nid, loc_id)

    async def get_location_id(
        self,
        db: AsyncSession,
        novel_id: str,
        character_id: str,
    ) -> str | None:
        """查 character 的 location_id, 返 str 或 None。"""
        cid = parse_uuid(character_id, "character_id")
        return await self.repo.get_character_location_id(db, cid)
