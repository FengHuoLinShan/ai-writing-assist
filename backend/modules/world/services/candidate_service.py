"""EntityCandidateService — 候选对象池 CRUD + 晋升/合并"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from fastapi import status as http_status
from sqlalchemy.ext.asyncio import AsyncSession

from modules.world.repositories import (
    EntityAliasRepository,
    EntityCandidateRepository,
    WorldEntityRepository,
)
from modules.world.schemas import (
    EntityAliasCreate,
    EntityCandidateCreate,
    EntityCandidateListResponse,
    EntityCandidateResponse,
    EntityCandidateUpdate,
    WorldEntityCreate,
    WorldEntityResponse,
    WorldEntityUpdate,
)
from modules.world.services.helpers import parse_uuid
from shared.constants import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE


class EntityCandidateService:
    """候选对象池业务服务"""

    def __init__(self) -> None:
        self._repo = EntityCandidateRepository()

    async def create(
        self,
        db: AsyncSession,
        novel_id: str,
        data: EntityCandidateCreate,
    ) -> EntityCandidateResponse:
        """创建候选对象"""
        nid = parse_uuid(novel_id, "novel_id")
        candidate = await self._repo.create(db, nid, data)
        response = EntityCandidateResponse.model_validate(candidate)
        await self._attach_existing_entity_names(db, nid, [response])
        return response

    async def get(
        self,
        db: AsyncSession,
        candidate_id: str,
        novel_id: str | None = None,
    ) -> EntityCandidateResponse:
        """获取候选对象详情"""
        cid = parse_uuid(candidate_id, "candidate_id")
        candidate = await self._repo.get(db, cid)
        if candidate is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"EntityCandidate {candidate_id} not found",
            )
        if novel_id and str(candidate.novel_id) != novel_id:
            raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND)
        response = EntityCandidateResponse.model_validate(candidate)
        if candidate.novel_id:
            await self._attach_existing_entity_names(db, candidate.novel_id, [response])
        return response

    async def list(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        status: str | None = None,
        suggested_action: str | None = None,
        skip: int = 0,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> EntityCandidateListResponse:
        """获取候选对象列表"""
        nid = parse_uuid(novel_id, "novel_id")
        limit = min(limit, MAX_PAGE_SIZE)
        items, total = await self._repo.get_by_novel(
            db,
            nid,
            status=status,
            suggested_action=suggested_action,
            skip=skip,
            limit=limit,
        )
        responses = [EntityCandidateResponse.model_validate(c) for c in items]
        await self._attach_existing_entity_names(db, nid, responses)
        return EntityCandidateListResponse(items=responses, total=total)

    async def update(
        self,
        db: AsyncSession,
        candidate_id: str,
        data: EntityCandidateUpdate,
        novel_id: str | None = None,
    ) -> EntityCandidateResponse:
        """更新候选对象"""
        cid = parse_uuid(candidate_id, "candidate_id")
        if novel_id:
            existing = await self._repo.get(db, cid)
            if existing is None or str(existing.novel_id) != novel_id:
                raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND)
        candidate = await self._repo.update(db, cid, data)
        if candidate is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"EntityCandidate {candidate_id} not found",
            )
        response = EntityCandidateResponse.model_validate(candidate)
        if candidate.novel_id:
            await self._attach_existing_entity_names(db, candidate.novel_id, [response])
        return response

    async def delete(
        self,
        db: AsyncSession,
        candidate_id: str,
        novel_id: str | None = None,
    ) -> None:
        """删除候选对象"""
        cid = parse_uuid(candidate_id, "candidate_id")
        if novel_id:
            existing = await self._repo.get(db, cid)
            if existing is None or str(existing.novel_id) != novel_id:
                raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND)
        deleted = await self._repo.delete(db, cid)
        if not deleted:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"EntityCandidate {candidate_id} not found",
            )

    async def accept_candidate(
        self,
        db: AsyncSession,
        novel_id: str,
        candidate_id: str,
        *,
        user_edits: dict[str, Any] | None = None,
    ) -> WorldEntityResponse:
        """将候选对象晋升为正史世界对象

        1. 获取候选对象
        2. 根据候选数据 + 用户编辑创建 WorldEntity
        3. 根据 suggested_action 处理：
           - create_new: 创建新实体
           - alias_of_existing: 在已有实体上创建别名
           - merge_with_existing: 将候选信息合并到已有实体
           - ignore/temporary_only: 标记候选为 ignored
        4. 更新候选状态为 canonical/ignored

        Args:
            db: 数据库 session
            novel_id: 项目 ID
            candidate_id: 候选对象 ID
            user_edits: 用户编辑的可选覆盖字段

        Returns:
            WorldEntityResponse — 创建/更新后的正史对象
        """
        nid = parse_uuid(novel_id, "novel_id")
        cid = parse_uuid(candidate_id, "candidate_id")

        candidate = await self._repo.get(db, cid)
        if candidate is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"EntityCandidate {candidate_id} not found",
            )
        if str(candidate.novel_id) != str(nid):
            raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND)

        action = candidate.suggested_action
        edits = user_edits or {}

        if action in ("ignore", "temporary_only"):
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Candidate suggested action is '{action}', "
                    "cannot promote to canonical"
                ),
            )

        if action in ("alias_of_existing", "merge_with_existing"):
            if not candidate.suggested_existing_entity_id:
                raise HTTPException(
                    status_code=http_status.HTTP_400_BAD_REQUEST,
                    detail=(
                        f"Candidate suggested action is '{action}', "
                        "but suggested_existing_entity_id is missing"
                    ),
                )

        if action == "alias_of_existing" and candidate.suggested_existing_entity_id:
            existing_eid = parse_uuid(
                candidate.suggested_existing_entity_id,
                "entity_id",
            )
            entity_repo = WorldEntityRepository()
            entity = await entity_repo.get(db, existing_eid)
            if entity is None:
                raise HTTPException(
                    status_code=http_status.HTTP_404_NOT_FOUND,
                    detail=(
                        "Suggested existing entity "
                        f"{candidate.suggested_existing_entity_id} not found"
                    ),
                )
            if str(entity.novel_id) != str(nid):
                raise HTTPException(
                    status_code=http_status.HTTP_400_BAD_REQUEST,
                    detail="Suggested entity does not belong to the same novel",
                )
            alias_repo = EntityAliasRepository()
            alias_data = EntityAliasCreate(
                entity_id=candidate.suggested_existing_entity_id,
                alias=candidate.name,
                alias_type="name",
                source_chapter_index=candidate.source_chapter_index,
                confidence=candidate.confidence,
            )
            await alias_repo.create(db, nid, alias_data)
            await self._repo.update_status(db, cid, "canonical")
            return WorldEntityResponse.model_validate(entity)

        if action == "merge_with_existing" and candidate.suggested_existing_entity_id:
            existing_eid = parse_uuid(
                candidate.suggested_existing_entity_id,
                "entity_id",
            )
            entity_repo = WorldEntityRepository()

            entity = await entity_repo.get(db, existing_eid)
            if entity is None:
                raise HTTPException(
                    status_code=http_status.HTTP_404_NOT_FOUND,
                    detail=(
                        "Entity to merge into "
                        f"{candidate.suggested_existing_entity_id} not found"
                    ),
                )
            if str(entity.novel_id) != str(nid):
                raise HTTPException(
                    status_code=http_status.HTTP_400_BAD_REQUEST,
                    detail="Suggested entity does not belong to the same novel",
                )

            merge_fields: dict[str, Any] = {
                "summary": candidate.summary or None,
                "importance": candidate.importance_score,
            }
            if edits:
                merge_fields.update(edits)

            update_data = WorldEntityUpdate(
                **{k: v for k, v in merge_fields.items() if v is not None}
            )
            entity = await entity_repo.update(db, existing_eid, update_data)
            if entity is None:
                raise HTTPException(
                    status_code=http_status.HTTP_404_NOT_FOUND,
                    detail=(
                        "Entity to merge into "
                        f"{candidate.suggested_existing_entity_id} not found"
                    ),
                )
            await self._repo.update_status(db, cid, "canonical")
            return WorldEntityResponse.model_validate(entity)

        # create_new
        # 映射中文/LLM 输出的实体类型到标准英文类型
        from modules.world.services.entity_types import map_entity_type

        raw_type = edits.get("entity_type", candidate.entity_type)
        mapped_type = map_entity_type(raw_type)
        create_fields: dict[str, Any] = {
            "name": edits.get("name", candidate.name),
            "entity_type": mapped_type,
            "summary": edits.get("summary", candidate.summary or ""),
            "public_info": edits.get("public_info", ""),
            "hidden_truth": edits.get("hidden_truth", ""),
            "importance": edits.get("importance", candidate.importance_score),
            "importance_level": edits.get("importance_level", "normal"),
            "reveal_level": edits.get("reveal_level", "author_only"),
        }
        create_data = WorldEntityCreate(**create_fields)

        entity_repo = WorldEntityRepository()
        entity = await entity_repo.create(db, nid, create_data)
        await self._repo.update_status(db, cid, "canonical")

        # 自动同步：entity_type=人物 → 创建 Character 记录
        if mapped_type == "character_ref":
            import logging

            try:
                from modules.character.facade import create_character

                await create_character(
                    db=db,
                    novel_id=novel_id,
                    name=candidate.name,
                    world_entity_id=str(entity.id),
                )
            except Exception as exc:
                logging.getLogger(__name__).warning(
                    "Failed to auto-create Character for candidate %s: %s",
                    candidate.name,
                    exc,
                )

        return WorldEntityResponse.model_validate(entity)

    async def _attach_existing_entity_names(
        self,
        db: AsyncSession,
        novel_id,
        items: list[EntityCandidateResponse],
    ) -> None:
        """Populate suggested_existing_entity_name without crossing novel boundaries."""
        ids = {
            item.suggested_existing_entity_id
            for item in items
            if item.suggested_existing_entity_id
        }
        if not ids:
            return

        entity_repo = WorldEntityRepository()
        for entity_id in ids:
            try:
                eid = parse_uuid(entity_id, "entity_id")
            except HTTPException:
                continue
            entity = await entity_repo.get(db, eid)
            if entity is None or str(entity.novel_id) != str(novel_id):
                continue
            for item in items:
                if item.suggested_existing_entity_id == entity_id:
                    item.suggested_existing_entity_name = entity.name
