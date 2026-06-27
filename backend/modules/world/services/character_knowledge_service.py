"""CharacterKnowledgeService — 人物知识边界 CRUD。继承 BaseCRUDService (ADR-0002)。

跨表 novel_id 校验 (knowledge.character_id 必须属于该 novel) 走私有 helper,
不上 port (per ADR-0002 B2 拒绝项)。
"""

from __future__ import annotations

from fastapi import HTTPException
from fastapi import status as http_status
from sqlalchemy.ext.asyncio import AsyncSession

from modules.world.models import CharacterKnowledge
from modules.world.repositories import (
    CharacterKnowledgeRepository,
    CharacterRepository,
)
from modules.world.schemas import (
    CharacterKnowledgeCreate,
    CharacterKnowledgeListResponse,
    CharacterKnowledgeResponse,
    CharacterKnowledgeUpdate,
)
from modules.world.services.base import CrudService
from modules.world.services.helpers import parse_uuid
from shared.constants import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE


def _require_misconception_for_false_level(
    level: str,
    misconception: str | None,
) -> None:
    """false_belief / misunderstood 必须提供 misconception。"""
    if level in {"false_belief", "misunderstood"} and not misconception:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="false_belief/misunderstood knowledge must provide misconception",
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
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail="Character not found in this novel",
            )
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
        """update 时校验 false_belief/misunderstood 必须提供 misconception。"""
        # Schema 已校验；服务层保留 defense-in-depth 二次校验，统一返回 HTTP 422。
        if data.knowledge_level in {"false_belief", "misunderstood"}:
            rid = parse_uuid(id, self.id_param)
            existing = await self.repo.get(db, rid)
            misconception = data.misconception
            if existing is not None and misconception is None:
                misconception = existing.misconception
            _require_misconception_for_false_level(
                data.knowledge_level,
                misconception,
            )
        return await super().update(db, id, data, novel_id=novel_id)

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
