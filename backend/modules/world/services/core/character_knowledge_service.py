"""CharacterKnowledgeService — 人物知识边界 CRUD。继承 BaseCRUDService (ADR-0002)。

跨表 novel_id 校验 (knowledge.character_id 必须属于该 novel) 走私有 helper,
不上 port (per ADR-0002 B2 拒绝项)。
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from core.crud import CrudService
from core.errors import NotFoundError, ValidationError
from modules.world.models import CharacterKnowledge
from modules.world.repositories import (
    CharacterKnowledgeRepository,
    CharacterRepository,
    CoreEntityRepository,
)
from modules.world.schemas import (
    CharacterKnowledgeCreate,
    CharacterKnowledgeListResponse,
    CharacterKnowledgeResponse,
    CharacterKnowledgeUpdate,
)
from modules.world.services.common import parse_uuid
from shared.constants import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE


def _require_misconception_for_false_level(
    level: str,
    misconception: str | None,
) -> None:
    """false_belief / misunderstood 必须提供 misconception。"""
    if level in {"false_belief", "misunderstood"} and not misconception:
        raise ValidationError(
            "false_belief/misunderstood knowledge must provide misconception",
            status_code=422,
        )


class CharacterKnowledgeService(
    CrudService[
        CharacterKnowledge,
        CharacterKnowledgeCreate,
        CharacterKnowledgeUpdate,
        CharacterKnowledgeResponse,
    ],
):
    """人物知识 CRUD。

    跨表 novel_id 校验: create 前确认 character 属于该 novel。
    """

    repo = CharacterKnowledgeRepository()
    response = CharacterKnowledgeResponse
    label = "Knowledge"
    id_param = "knowledge_id"

    # 跨表校验需要 CharacterRepository — 显式注入
    def __init__(self) -> None:
        self._character_repo = CharacterRepository()
        self._entity_repo = CoreEntityRepository()

    async def create(  # type: ignore[override]
        self,
        db: AsyncSession,
        novel_id: str,
        data: CharacterKnowledgeCreate,
    ) -> CharacterKnowledgeResponse:
        """create 前确认 character 属于该 novel (跨表 novel_id 隔离)。"""
        nid = parse_uuid(novel_id, "novel_id")
        cid = parse_uuid(data.character_id, "character_id")
        char = await self._character_repo.get(db, cid)
        if char is None or char.novel_id != nid:
            raise NotFoundError("Character not found in this novel")
        await self._assert_character_in_novel(db, nid, cid)
        await self._assert_target_in_novel(db, nid, data.target_type, data.target_id)
        # Schema 已做基础校验；服务层再次检查作为 defense-in-depth，
        # 确保任何绕过 schema 的情况都能返回受控的 HTTP 422 错误信息。
        _require_misconception_for_false_level(
            data.knowledge_level,
            data.misconception,
        )
        return await super().create(db, novel_id, data)

    async def update(  # type: ignore[override]
        self,
        db: AsyncSession,
        id: str,
        data: CharacterKnowledgeUpdate,
        *,
        novel_id: str,
    ) -> CharacterKnowledgeResponse:
        """update 时确保人物/目标仍已采用，并校验误解字段。"""
        rid = parse_uuid(id, self.id_param)
        nid = parse_uuid(novel_id, "novel_id")
        existing = await self.repo.get(db, rid)
        self._assert_found_in_novel(existing, id, nid)
        await self._assert_character_in_novel(db, nid, existing.character_id)
        await self._assert_target_in_novel(
            db,
            nid,
            existing.target_type,
            str(existing.target_id),
        )
        # Schema 已校验；服务层保留 defense-in-depth 二次校验，统一返回 HTTP 422。
        if data.knowledge_level in {"false_belief", "misunderstood"}:
            misconception = data.misconception
            if misconception is None:
                misconception = existing.misconception
            _require_misconception_for_false_level(
                data.knowledge_level,
                misconception,
            )
        updated = await self.repo.update(db, rid, data)
        self._assert_found_in_novel(updated, id, nid)
        return self._to_response(updated)

    async def _assert_character_in_novel(
        self,
        db: AsyncSession,
        novel_id,
        character_id,
    ) -> None:
        entity = await self._entity_repo.get(db, character_id)
        if (
            entity is None
            or entity.novel_id != novel_id
            or entity.status != "canonical"
        ):
            raise NotFoundError("Character not found in this novel")
        if entity.entity_type != "character":
            raise ValidationError(
                "Character must reference a character CoreEntity",
                status_code=422,
            )

    async def _assert_target_in_novel(
        self,
        db: AsyncSession,
        novel_id,
        target_type: str,
        target_id: str,
    ) -> None:
        generic_target_types = {
            "entity",
            "world_entity",
            "object",
        }
        typed_target_types = {
            "character",
            "event",
            "location",
            "item",
            "faction",
        }
        if target_type not in generic_target_types | typed_target_types:
            return
        tid = parse_uuid(target_id, "target_id")
        target = await self._entity_repo.get(db, tid)
        if (
            target is None
            or target.novel_id != novel_id
            or target.status != "canonical"
        ):
            raise NotFoundError("Knowledge target not found in this novel")
        if target_type in typed_target_types and target.entity_type != target_type:
            raise ValidationError(
                f"Knowledge target type {target_type} does not match "
                f"CoreEntity type {target.entity_type}",
                status_code=422,
            )

    # ============================================================
    # list 加按 character_id 过滤 (base 的 list 是按 novel_id 列表)
    # ============================================================

    async def list(  # type: ignore[override]
        self,
        db: AsyncSession,
        novel_id: str,
        character_id: str | None = None,
        *,
        skip: int = 0,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> CharacterKnowledgeListResponse:
        """按 novel_id 列表；可选按 character_id 过滤, 返 ListResponse 包装。"""
        nid = parse_uuid(novel_id, "novel_id")
        limit = min(limit, MAX_PAGE_SIZE)
        if character_id is not None:
            cid = parse_uuid(character_id, "character_id")
            items, total = await self.repo.get_by_character(
                db,
                nid,
                cid,
                skip=skip,
                limit=limit,
            )
        else:
            items, total = await self.repo.get_by_novel(
                db,
                nid,
                skip=skip,
                limit=limit,
            )
        return CharacterKnowledgeListResponse(
            items=[CharacterKnowledgeResponse.model_validate(k) for k in items],
            total=total,
        )
