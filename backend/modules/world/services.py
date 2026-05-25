"""
World 业务逻辑层

组装 repository 完成业务操作。服务层可包含业务规则，但不直接操作数据库。
"""

from __future__ import annotations

import difflib
import uuid
from typing import Any

from fastapi import HTTPException
from fastapi import status as http_status
from sqlalchemy.ext.asyncio import AsyncSession

from modules.world.contracts import DuplicateSuggestion
from modules.world.models import EntityAlias, EntityCandidate, Relationship, WorldEntity
from modules.world.repositories import (
    EntityAliasRepository,
    EntityCandidateRepository,
    RelationshipRepository,
    WorldEntityRepository,
)
from modules.world.schemas import (
    DuplicateSuggestionResult,
    EntityAliasCreate,
    EntityAliasResponse,
    EntityCandidateCreate,
    EntityCandidateResponse,
    EntityCandidateUpdate,
    EntityCandidateListResponse,
    RelationshipCreate,
    RelationshipResponse,
    RelationshipUpdate,
    WorldContextBundle,
    WorldEntityContext,
    WorldEntityCreate,
    WorldEntityListResponse,
    WorldEntityResponse,
    WorldEntityUpdate,
)
from shared.constants import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    SIMILARITY_HIGH_CONFIDENCE,
    SIMILARITY_MEDIUM_CONFIDENCE,
)


# ============================================================
# WorldEntityService
# ============================================================

class WorldEntityService:
    """世界对象业务服务"""

    def __init__(self) -> None:
        self._repo = WorldEntityRepository()

    async def create(
        self,
        db: AsyncSession,
        novel_id: str,
        data: WorldEntityCreate,
    ) -> WorldEntityResponse:
        """创建世界对象"""
        nid = self._parse_uuid(novel_id, "novel_id")
        entity = await self._repo.create(db, nid, data)
        return WorldEntityResponse.model_validate(entity)

    async def get(
        self,
        db: AsyncSession,
        entity_id: str,
        novel_id: str | None = None,
    ) -> WorldEntityResponse:
        """获取世界对象详情"""
        eid = self._parse_uuid(entity_id, "entity_id")
        entity = await self._repo.get(db, eid)
        if entity is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"WorldEntity {entity_id} not found",
            )
        if novel_id and str(entity.novel_id) != novel_id:
            raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND)
        return WorldEntityResponse.model_validate(entity)

    async def list(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        entity_type: str | None = None,
        status: str | None = None,
        skip: int = 0,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> WorldEntityListResponse:
        """获取世界对象列表"""
        nid = self._parse_uuid(novel_id, "novel_id")
        limit = min(limit, MAX_PAGE_SIZE)
        items, total = await self._repo.get_by_novel(
            db, nid,
            entity_type=entity_type,
            status=status,
            skip=skip,
            limit=limit,
        )
        return WorldEntityListResponse(
            items=[WorldEntityResponse.model_validate(e) for e in items],
            total=total,
        )

    async def update(
        self,
        db: AsyncSession,
        entity_id: str,
        data: WorldEntityUpdate,
        novel_id: str | None = None,
    ) -> WorldEntityResponse:
        """更新世界对象"""
        eid = self._parse_uuid(entity_id, "entity_id")
        if novel_id:
            existing = await self._repo.get(db, eid)
            if existing is None or str(existing.novel_id) != novel_id:
                raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND)
        entity = await self._repo.update(db, eid, data)
        if entity is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"WorldEntity {entity_id} not found",
            )
        return WorldEntityResponse.model_validate(entity)

    async def delete(
        self,
        db: AsyncSession,
        entity_id: str,
        novel_id: str | None = None,
    ) -> None:
        """删除世界对象"""
        eid = self._parse_uuid(entity_id, "entity_id")
        if novel_id:
            existing = await self._repo.get(db, eid)
            if existing is None or str(existing.novel_id) != novel_id:
                raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND)
        deleted = await self._repo.delete(db, eid)
        if not deleted:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"WorldEntity {entity_id} not found",
            )

    async def get_entity_context(
        self,
        db: AsyncSession,
        novel_id: str,
        entity_ids: list[str] | None = None,
        reveal_mode: str = "author_safe",
        limit: int = 20,
    ) -> WorldContextBundle:
        """获取世界对象上下文包（供其他模块使用）"""
        nid = self._parse_uuid(novel_id, "novel_id")

        if entity_ids:
            eids = [self._parse_uuid(eid, "entity_id") for eid in entity_ids]
            entities = await self._repo.get_by_ids(db, nid, eids)
        else:
            entities, _ = await self._repo.get_by_novel(db, nid, limit=limit)

        contexts: list[WorldEntityContext] = []
        for entity in entities:
            ctx = self._entity_to_context(entity, reveal_mode)
            contexts.append(ctx)

        return WorldContextBundle(
            novel_id=novel_id,
            entities=contexts,
            total_count=len(contexts),
            reveal_mode=reveal_mode,
        )

    @staticmethod
    def _entity_to_context(
        entity: WorldEntity,
        reveal_mode: str,
    ) -> WorldEntityContext:
        """将 ORM 模型转为上下文对象，根据 reveal_mode 过滤信息"""
        hidden = None
        if reveal_mode == "author_only":
            hidden = entity.hidden_truth

        return WorldEntityContext(
            entity_id=str(entity.id),
            entity_type=entity.entity_type,
            name=entity.name,
            summary=entity.summary,
            public_info=entity.public_info,
            hidden_truth=hidden,
            importance=entity.importance,
            importance_level=entity.importance_level,
            reveal_level=entity.reveal_level,
            status=entity.status,
        )

    @staticmethod
    def _parse_uuid(value: str, field_name: str) -> uuid.UUID:
        """将字符串 ID 解析为 UUID"""
        try:
            return uuid.UUID(hex=value)
        except ValueError:
            raise HTTPException(
                status_code=http_status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"Invalid {field_name}: {value}",
            )


# ============================================================
# RelationshipService
# ============================================================

class RelationshipService:
    """关系业务服务"""

    def __init__(self) -> None:
        self._repo = RelationshipRepository()
        self._entity_repo = WorldEntityRepository()

    async def create(
        self,
        db: AsyncSession,
        novel_id: str,
        data: RelationshipCreate,
    ) -> RelationshipResponse:
        """创建关系"""
        nid = self._parse_uuid(novel_id, "novel_id")
        rel = await self._repo.create(db, nid, data)
        return RelationshipResponse.model_validate(rel)

    async def get(
        self,
        db: AsyncSession,
        rel_id: str,
        novel_id: str | None = None,
    ) -> RelationshipResponse:
        """获取关系详情"""
        rid = self._parse_uuid(rel_id, "relationship_id")
        rel = await self._repo.get(db, rid)
        if rel is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"Relationship {rel_id} not found",
            )
        if novel_id and str(rel.novel_id) != novel_id:
            raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND)
        return RelationshipResponse.model_validate(rel)

    async def list(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        skip: int = 0,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> tuple[list[RelationshipResponse], int]:
        """获取关系列表"""
        nid = self._parse_uuid(novel_id, "novel_id")
        limit = min(limit, MAX_PAGE_SIZE)
        items, total = await self._repo.get_by_novel(db, nid, skip=skip, limit=limit)
        return [RelationshipResponse.model_validate(r) for r in items], total

    async def update(
        self,
        db: AsyncSession,
        rel_id: str,
        data: RelationshipUpdate,
        novel_id: str | None = None,
    ) -> RelationshipResponse:
        """更新关系"""
        rid = self._parse_uuid(rel_id, "relationship_id")
        if novel_id:
            existing = await self._repo.get(db, rid)
            if existing is None or str(existing.novel_id) != novel_id:
                raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND)
        rel = await self._repo.update(db, rid, data)
        if rel is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"Relationship {rel_id} not found",
            )
        return RelationshipResponse.model_validate(rel)

    async def delete(
        self,
        db: AsyncSession,
        rel_id: str,
        novel_id: str | None = None,
    ) -> None:
        """删除关系"""
        rid = self._parse_uuid(rel_id, "relationship_id")
        if novel_id:
            existing = await self._repo.get(db, rid)
            if existing is None or str(existing.novel_id) != novel_id:
                raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND)
        deleted = await self._repo.delete(db, rid)
        if not deleted:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"Relationship {rel_id} not found",
            )

    async def expand_related(
        self,
        db: AsyncSession,
        novel_id: str,
        seed_entity_ids: list[str],
        depth: int = 1,
        limit: int = 20,
    ) -> list[WorldEntityContext]:
        """关系一跳/二跳扩展，返回相关对象的上下文列表"""
        nid = self._parse_uuid(novel_id, "novel_id")
        limit = min(limit, MAX_PAGE_SIZE)

        # 收集所有相关实体 ID
        related_ids: set[str] = set()
        for seed_id in seed_entity_ids:
            new_related = await self._repo.get_related_entity_ids(
                db, nid, seed_id, depth=depth, limit=limit,
            )
            related_ids.update(new_related)

        if not related_ids:
            return []

        # 按 limit 截断
        related_list = list(related_ids)[:limit]

        # 获取实体信息
        eids = [self._parse_uuid(eid, "entity_id") for eid in related_list]
        entities = await self._entity_repo.get_by_ids(db, nid, eids)

        contexts: list[WorldEntityContext] = []
        for entity in entities:
            contexts.append(WorldEntityContext(
                entity_id=str(entity.id),
                entity_type=entity.entity_type,
                name=entity.name,
                summary=entity.summary,
                public_info=entity.public_info,
                importance=entity.importance,
                importance_level=entity.importance_level,
                reveal_level=entity.reveal_level,
                status=entity.status,
                related_entity_ids=list(related_ids),
            ))

        return contexts

    @staticmethod
    def _parse_uuid(value: str, field_name: str) -> uuid.UUID:
        try:
            return uuid.UUID(hex=value)
        except ValueError:
            raise HTTPException(
                status_code=http_status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"Invalid {field_name}: {value}",
            )


# ============================================================
# EntityCandidateService
# ============================================================

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
        nid = self._parse_uuid(novel_id, "novel_id")
        candidate = await self._repo.create(db, nid, data)
        return EntityCandidateResponse.model_validate(candidate)

    async def get(
        self,
        db: AsyncSession,
        candidate_id: str,
        novel_id: str | None = None,
    ) -> EntityCandidateResponse:
        """获取候选对象详情"""
        cid = self._parse_uuid(candidate_id, "candidate_id")
        candidate = await self._repo.get(db, cid)
        if candidate is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"EntityCandidate {candidate_id} not found",
            )
        if novel_id and str(candidate.novel_id) != novel_id:
            raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND)
        return EntityCandidateResponse.model_validate(candidate)

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
        nid = self._parse_uuid(novel_id, "novel_id")
        limit = min(limit, MAX_PAGE_SIZE)
        items, total = await self._repo.get_by_novel(
            db, nid,
            status=status,
            suggested_action=suggested_action,
            skip=skip,
            limit=limit,
        )
        return EntityCandidateListResponse(
            items=[EntityCandidateResponse.model_validate(c) for c in items],
            total=total,
        )

    async def update(
        self,
        db: AsyncSession,
        candidate_id: str,
        data: EntityCandidateUpdate,
        novel_id: str | None = None,
    ) -> EntityCandidateResponse:
        """更新候选对象"""
        cid = self._parse_uuid(candidate_id, "candidate_id")
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
        return EntityCandidateResponse.model_validate(candidate)

    async def delete(
        self,
        db: AsyncSession,
        candidate_id: str,
        novel_id: str | None = None,
    ) -> None:
        """删除候选对象"""
        cid = self._parse_uuid(candidate_id, "candidate_id")
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
        nid = self._parse_uuid(novel_id, "novel_id")
        cid = self._parse_uuid(candidate_id, "candidate_id")

        candidate = await self._repo.get(db, cid)
        if candidate is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"EntityCandidate {candidate_id} not found",
            )

        action = candidate.suggested_action
        edits = user_edits or {}

        if action in ("ignore", "temporary_only"):
            # 标记为 ignored，不创建实体
            await self._repo.update_status(db, cid, "ignored")
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail=f"Candidate suggested action is '{action}', cannot promote to canonical",
            )

        if action == "alias_of_existing" and candidate.suggested_existing_entity_id:
            # 在已有实体上创建别名
            existing_eid = self._parse_uuid(
                candidate.suggested_existing_entity_id, "entity_id",
            )
            from modules.world.repositories import EntityAliasRepository
            alias_repo = EntityAliasRepository()
            from modules.world.schemas import EntityAliasCreate
            alias_data = EntityAliasCreate(
                entity_id=candidate.suggested_existing_entity_id,
                alias=candidate.name,
                alias_type="name",
                source_chapter_index=candidate.source_chapter_index,
                confidence=candidate.confidence,
            )
            await alias_repo.create(db, nid, alias_data)
            # 标记候选为 canonical（已处理）
            await self._repo.update_status(db, cid, "canonical")
            # 返回已有实体信息
            from modules.world.repositories import WorldEntityRepository
            entity_repo = WorldEntityRepository()
            entity = await entity_repo.get(db, existing_eid)
            if entity is None:
                raise HTTPException(
                    status_code=http_status.HTTP_404_NOT_FOUND,
                    detail=f"Suggested existing entity {candidate.suggested_existing_entity_id} not found",
                )
            if str(entity.novel_id) != str(nid):
                raise HTTPException(
                    status_code=http_status.HTTP_400_BAD_REQUEST,
                    detail="Suggested entity does not belong to the same novel",
                )
            return WorldEntityResponse.model_validate(entity)

        if action == "merge_with_existing" and candidate.suggested_existing_entity_id:
            # 合并到已有实体（将候选信息追加到正史对象上）
            existing_eid = self._parse_uuid(
                candidate.suggested_existing_entity_id, "entity_id",
            )
            from modules.world.repositories import WorldEntityRepository
            entity_repo = WorldEntityRepository()
            from modules.world.schemas import WorldEntityUpdate

            # 校验已有实体属于同一 novel
            entity = await entity_repo.get(db, existing_eid)
            if entity is None:
                raise HTTPException(
                    status_code=http_status.HTTP_404_NOT_FOUND,
                    detail=f"Entity to merge into {candidate.suggested_existing_entity_id} not found",
                )
            if str(entity.novel_id) != str(nid):
                raise HTTPException(
                    status_code=http_status.HTTP_400_BAD_REQUEST,
                    detail="Suggested entity does not belong to the same novel",
                )

            # 合并候选字段到已有实体（不覆盖已有非空内容）
            merge_fields: dict[str, Any] = {
                "summary": candidate.summary or None,
                "importance": candidate.importance_score,
            }
            if edits:
                merge_fields.update(edits)

            update_data = WorldEntityUpdate(**{
                k: v for k, v in merge_fields.items() if v is not None
            })
            entity = await entity_repo.update(db, existing_eid, update_data)
            if entity is None:
                raise HTTPException(
                    status_code=http_status.HTTP_404_NOT_FOUND,
                    detail=f"Entity to merge into {candidate.suggested_existing_entity_id} not found",
                )
            # 标记候选为 canonical
            await self._repo.update_status(db, cid, "canonical")
            return WorldEntityResponse.model_validate(entity)

        # create_new：创建新实体
        from modules.world.schemas import WorldEntityCreate
        create_fields: dict[str, Any] = {
            "name": edits.get("name", candidate.name),
            "entity_type": edits.get("entity_type", candidate.entity_type),
            "summary": edits.get("summary", candidate.summary or ""),
            "public_info": edits.get("public_info", ""),
            "hidden_truth": edits.get("hidden_truth", ""),
            "importance": edits.get("importance", candidate.importance_score),
            "importance_level": edits.get("importance_level", "normal"),
            "reveal_level": edits.get("reveal_level", "author_only"),
        }
        create_data = WorldEntityCreate(**create_fields)

        from modules.world.repositories import WorldEntityRepository
        entity_repo = WorldEntityRepository()
        entity = await entity_repo.create(db, nid, create_data)

        # 标记候选为 canonical
        await self._repo.update_status(db, cid, "canonical")

        return WorldEntityResponse.model_validate(entity)

    @staticmethod
    def _parse_uuid(value: str, field_name: str) -> uuid.UUID:
        try:
            return uuid.UUID(hex=value)
        except ValueError:
            raise HTTPException(
                status_code=http_status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"Invalid {field_name}: {value}",
            )


# ============================================================
# AliasService
# ============================================================

class AliasService:
    """别名业务服务"""

    def __init__(self) -> None:
        self._repo = EntityAliasRepository()

    async def create(
        self,
        db: AsyncSession,
        novel_id: str,
        data: EntityAliasCreate,
    ) -> EntityAliasResponse:
        """创建别名"""
        nid = self._parse_uuid(novel_id, "novel_id")
        alias = await self._repo.create(db, nid, data)
        return EntityAliasResponse.model_validate(alias)

    async def list(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        entity_id: str | None = None,
        skip: int = 0,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> tuple[list[EntityAliasResponse], int]:
        """获取别名列表"""
        nid = self._parse_uuid(novel_id, "novel_id")
        limit = min(limit, MAX_PAGE_SIZE)
        eid = self._parse_uuid(entity_id, "entity_id") if entity_id else None
        items, total = await self._repo.get_by_novel(
            db, nid,
            entity_id=eid,
            skip=skip,
            limit=limit,
        )
        return [EntityAliasResponse.model_validate(a) for a in items], total

    async def delete(
        self,
        db: AsyncSession,
        alias_id: str,
        novel_id: str | None = None,
    ) -> None:
        """删除别名"""
        aid = self._parse_uuid(alias_id, "alias_id")
        if novel_id:
            existing = await self._repo.get(db, aid)
            if existing is None or str(existing.novel_id) != novel_id:
                raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND)
        deleted = await self._repo.delete(db, aid)
        if not deleted:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"EntityAlias {alias_id} not found",
            )

    @staticmethod
    def _parse_uuid(value: str, field_name: str) -> uuid.UUID:
        try:
            return uuid.UUID(hex=value)
        except ValueError:
            raise HTTPException(
                status_code=http_status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"Invalid {field_name}: {value}",
            )


# ============================================================
# EntityDedupService
# ============================================================

class EntityDedupService:
    """对象去重业务服务

    提供三种去重方法：
    1. 名称精确匹配（exact_name）
    2. pg_trgm 名称相似匹配（trgm_similar）— 在生产数据库中执行
    3. pgvector 语义相似匹配（vector_similar）— 在生产数据库中执行

    MVP 阶段仅实现规则级别的名称精确匹配，
    pg_trgm 和 pgvector 相似匹配需在真实 PostgreSQL 上运行。
    """

    def __init__(self) -> None:
        self._entity_repo = WorldEntityRepository()
        self._candidate_repo = EntityCandidateRepository()
        self._alias_repo = EntityAliasRepository()

    async def find_duplicates(
        self,
        db: AsyncSession,
        novel_id: str,
        candidate_id: str,
    ) -> list[DuplicateSuggestionResult]:
        """对指定候选对象进行去重检查

        执行顺序：
        1. 名称精确匹配
        2. 别名匹配
        3. 模糊名称匹配（difflib，代码层面）
        4. trgm 相似度（PostgreSQL 环境）
        5. 向量相似度（PostgreSQL + pgvector 环境）

        返回所有匹配结果，按相似度降序排列。
        """
        nid = self._parse_uuid(novel_id, "novel_id")
        cid = self._parse_uuid(candidate_id, "candidate_id")

        candidate = await self._candidate_repo.get(db, cid)
        if candidate is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"EntityCandidate {candidate_id} not found",
            )

        suggestions: list[DuplicateSuggestionResult] = []
        seen_ids: set[str] = set()

        # 1. 名称精确匹配
        exact_matches = await self._find_exact_name_matches(
            db, nid, candidate.name, candidate.entity_type,
        )
        for match in exact_matches:
            eid_str = str(match.id)
            if eid_str not in seen_ids:
                seen_ids.add(eid_str)
                suggestions.append(DuplicateSuggestionResult(
                    candidate_id=candidate_id,
                    candidate_name=candidate.name,
                    existing_entity_id=eid_str,
                    existing_entity_name=match.name,
                    similarity_score=1.0,
                    match_method="exact_name",
                    action="alias_of_existing",
                ))

        # 2. 别名匹配
        alias_matches = await self._find_alias_matches(
            db, nid, candidate.name,
        )
        for alias_elem in alias_matches:
            if alias_elem.entity_id not in seen_ids and alias_elem.entity_id:
                seen_ids.add(alias_elem.entity_id)
                eid = self._parse_uuid(alias_elem.entity_id, "entity_id")
                entity = await self._entity_repo.get(db, eid)
                entity_name = entity.name if entity else alias_elem.alias
                suggestions.append(DuplicateSuggestionResult(
                    candidate_id=candidate_id,
                    candidate_name=candidate.name,
                    existing_entity_id=alias_elem.entity_id,
                    existing_entity_name=entity_name,
                    similarity_score=SIMILARITY_HIGH_CONFIDENCE,
                    match_method="alias_match",
                    action="alias_of_existing",
                ))

        # 3. 模糊名称匹配（difflib）
        all_entities, _ = await self._entity_repo.get_by_novel(db, nid, limit=500)
        fuzzy_matches = self._fuzzy_name_matches(
            candidate.name, candidate.entity_type, all_entities,
        )
        for fuzz in fuzzy_matches:
            eid_str = fuzz["entity_id"]
            if eid_str not in seen_ids:
                seen_ids.add(eid_str)
                suggestions.append(DuplicateSuggestionResult(
                    candidate_id=candidate_id,
                    candidate_name=candidate.name,
                    existing_entity_id=eid_str,
                    existing_entity_name=fuzz["entity_name"],
                    similarity_score=fuzz["score"],
                    match_method="fuzzy_name",
                    action=fuzz["action"],
                ))

        # 4. 按相似度降序排列
        suggestions.sort(key=lambda s: s.similarity_score, reverse=True)

        return suggestions

    async def find_similar_entities(
        self,
        db: AsyncSession,
        novel_id: str,
        name: str,
        aliases: list[str] | None = None,
        entity_type: str | None = None,
    ) -> list[DuplicateSuggestionResult]:
        """对指定名称查找相似的正史对象（供 EntityExtractionService 使用）

        执行精确匹配 + 别名匹配 + 模糊匹配，返回去重排序结果。
        """
        nid = self._parse_uuid(novel_id, "novel_id")
        suggestions: list[DuplicateSuggestionResult] = []
        seen_ids: set[str] = set()

        # 1. 精确匹配名称
        exact_matches = await self._find_exact_name_matches(db, nid, name, entity_type)
        for match in exact_matches:
            eid_str = str(match.id)
            if eid_str not in seen_ids:
                seen_ids.add(eid_str)
                suggestions.append(DuplicateSuggestionResult(
                    candidate_id="",
                    candidate_name=name,
                    existing_entity_id=eid_str,
                    existing_entity_name=match.name,
                    similarity_score=1.0,
                    match_method="exact_name",
                    action="alias_of_existing",
                ))

        # 2. 别名匹配
        alias_matches = await self._find_alias_matches(db, nid, name)
        for alias_elem in alias_matches:
            if alias_elem.entity_id not in seen_ids and alias_elem.entity_id:
                seen_ids.add(alias_elem.entity_id)
                eid = self._parse_uuid(alias_elem.entity_id, "entity_id")
                entity = await self._entity_repo.get(db, eid)
                entity_name = entity.name if entity else alias_elem.alias
                suggestions.append(DuplicateSuggestionResult(
                    candidate_id="",
                    candidate_name=name,
                    existing_entity_id=alias_elem.entity_id,
                    existing_entity_name=entity_name,
                    similarity_score=SIMILARITY_HIGH_CONFIDENCE,
                    match_method="alias_match",
                    action="alias_of_existing",
                ))

        # 3. 模糊匹配
        all_entities, _ = await self._entity_repo.get_by_novel(db, nid, limit=500)
        fuzzy_matches = self._fuzzy_name_matches(name, entity_type, all_entities)
        for fuzz in fuzzy_matches:
            eid_str = fuzz["entity_id"]
            if eid_str not in seen_ids:
                seen_ids.add(eid_str)
                suggestions.append(DuplicateSuggestionResult(
                    candidate_id="",
                    candidate_name=name,
                    existing_entity_id=eid_str,
                    existing_entity_name=fuzz["entity_name"],
                    similarity_score=fuzz["score"],
                    match_method="fuzzy_name",
                    action=fuzz["action"],
                ))

        suggestions.sort(key=lambda s: s.similarity_score, reverse=True)
        return suggestions

    async def merge_candidate_into_entity(
        self,
        db: AsyncSession,
        novel_id: str,
        candidate_id: str,
        target_entity_id: str,
    ) -> WorldEntity:
        """将候选对象合并到指定正史对象

        合并逻辑：
        1. 校验候选和实体属于同一项目
        2. 将候选名称添加为别名
        3. 合并 summary/public_info/hidden_truth（append 不覆盖）
        4. 合并 importance（取 max）
        5. 标记候选为 canonical
        6. 返回更新后的正史对象

        Args:
            db: 数据库 session
            novel_id: 项目 ID
            candidate_id: 候选对象 ID
            target_entity_id: 目标正史对象 ID

        Returns:
            更新后的 WorldEntity
        """
        nid = self._parse_uuid(novel_id, "novel_id")
        cid = self._parse_uuid(candidate_id, "candidate_id")
        teid = self._parse_uuid(target_entity_id, "target_entity_id")

        # 获取候选对象
        candidate = await self._candidate_repo.get(db, cid)
        if candidate is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"EntityCandidate {candidate_id} not found",
            )
        if candidate.novel_id != nid:
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail="Candidate does not belong to the same novel",
            )

        # 获取目标实体
        entity = await self._entity_repo.get(db, teid)
        if entity is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"WorldEntity {target_entity_id} not found",
            )
        if entity.novel_id != nid:
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail="Target entity does not belong to the same novel",
            )

        # 合并字段
        merged_fields: list[str] = []
        added_aliases: list[str] = []

        # 合并别名（候选名称作为正史对象别名写入 entity_aliases 表）
        if candidate.name != entity.name:
            from modules.world.schemas import EntityAliasCreate
            alias_data = EntityAliasCreate(
                entity_id=str(entity.id),
                alias=candidate.name,
                alias_type="name",
                source_chapter_index=candidate.source_chapter_index,
                confidence=candidate.confidence or 0.8,
            )
            from modules.world.repositories import EntityAliasRepository
            await EntityAliasRepository().create(db, nid, alias_data)
            added_aliases.append(candidate.name)
            merged_fields.append("aliases")

        # 合并 summary
        entity.summary = _merge_text_field(entity.summary, candidate.summary)
        merged_fields.append("summary")

        # 合并 public_info（候选没有 public_info，使用 source_text 作为补充）
        if candidate.source_text:
            entity.public_info = _merge_text_field(entity.public_info, candidate.source_text)
            merged_fields.append("public_info")

        # 合并 hidden_truth（候选没有 hidden_truth，使用 source_text 作为补充）
        if candidate.source_text:
            entity.hidden_truth = _merge_text_field(entity.hidden_truth, candidate.source_text)
            merged_fields.append("hidden_truth")

        # 合并 importance（取最大值）
        if candidate.importance_score is not None and candidate.importance_score > (entity.importance or 0):
            entity.importance = candidate.importance_score

        # 标记候选为 canonical
        candidate.status = "canonical"
        await db.flush()
        await db.refresh(entity)
        return entity

    def _fuzzy_name_matches(
        self,
        name: str,
        entity_type: str | None,
        entities: list[WorldEntity],
    ) -> list[dict[str, Any]]:
        """使用 difflib 进行模糊名称匹配，返回相似度 >= 0.72 的建议

        同时兼容 entity_type：同类型或一方为 other 时视为可合并。
        """
        if not name:
            return []
        results: list[dict[str, Any]] = []
        normalized_name = _normalize_name(name)
        for entity in entities:
            if not _world_entity_types_compatible(entity_type, entity.entity_type):
                continue
            candidates = [entity.name]
            best_score = max(
                (
                    difflib.SequenceMatcher(None, normalized_name, _normalize_name(c)).ratio()
                    for c in candidates
                    if c
                ),
                default=0.0,
            )
            if 0.72 <= best_score < 1.0:
                results.append({
                    "entity_id": str(entity.id),
                    "entity_name": entity.name,
                    "score": best_score,
                    "action": "alias_of_existing",
                })
        return sorted(results, key=lambda r: r["score"], reverse=True)

    async def _find_exact_name_matches(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        name: str,
        entity_type: str | None = None,
    ) -> list[WorldEntity]:
        """查找名称精确匹配的正史对象"""
        from sqlalchemy import select

        conditions = [
            WorldEntity.novel_id == novel_id,
            WorldEntity.name == name,
        ]
        if entity_type:
            conditions.append(WorldEntity.entity_type == entity_type)

        stmt = select(WorldEntity).where(*conditions)
        result = await db.execute(stmt)
        items = result.scalars().all()
        return list(items)

    async def _find_alias_matches(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        alias_text: str,
    ) -> list[EntityAlias]:
        """查找别名精确匹配"""
        from sqlalchemy import select

        stmt = select(EntityAlias).where(
            EntityAlias.novel_id == novel_id,
            EntityAlias.alias == alias_text,
        )
        result = await db.execute(stmt)
        items = result.scalars().all()
        return list(items)

    async def find_trgm_similar(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        name: str,
        threshold: float = SIMILARITY_MEDIUM_CONFIDENCE,
    ) -> list[DuplicateSuggestionResult]:
        """使用 pg_trgm 查找名称相似的对象

        注意：此方法需要 PostgreSQL 和 pg_trgm 扩展。
        在 SQLite 环境下不会执行。
        """
        # MVP 占位：pg_trgm 需要在 PostgreSQL 上执行
        # 生产环境实现：
        # SELECT w.id, w.name, similarity(w.name, :name) as sim
        # FROM world_entities w
        # WHERE w.novel_id = :novel_id
        #   AND similarity(w.name, :name) > :threshold
        # ORDER BY sim DESC
        # LIMIT :limit
        return []

    async def find_vector_similar(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        embedding: list[float],
        threshold: float = SIMILARITY_MEDIUM_CONFIDENCE,
    ) -> list[DuplicateSuggestionResult]:
        """使用 pgvector 查找语义相似的对象

        注意：此方法需要 PostgreSQL 和 pgvector 扩展。
        在 SQLite 环境下不会执行。
        """
        # MVP 占位：pgvector 需要在 PostgreSQL 上执行
        # 生产环境实现：
        # SELECT w.id, w.name, 1 - (w.embedding <=> :embedding) as sim
        # FROM world_entities w
        # WHERE w.novel_id = :novel_id
        #   AND 1 - (w.embedding <=> :embedding) > :threshold
        # ORDER BY sim DESC
        # LIMIT :limit
        return []

    @staticmethod
    def _parse_uuid(value: str, field_name: str) -> uuid.UUID:
        try:
            return uuid.UUID(hex=value)
        except ValueError:
            raise HTTPException(
                status_code=http_status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"Invalid {field_name}: {value}",
            )


# ============================================================
# EntityExtractionService — LLM 抽取管线
# ============================================================

class EntityExtractionService:
    """从章节正文中抽取世界对象候选

    流程：
    WritingDraft chapters → batch group(5章/批) → LLM extract →
    dedup → EntityCandidate
    """

    def __init__(self) -> None:
        self._entity_repo = WorldEntityRepository()
        self._candidate_repo = EntityCandidateRepository()
        self._dedup_service = EntityDedupService()

    async def extract_entities_from_chapters(
        self,
        db: AsyncSession,
        novel_id: str,
        start_chapter: int,
        end_chapter: int,
        batch_size: int = 5,
    ) -> ExtractionResult:
        """从指定章节范围抽取世界对象候选

        Args:
            db: 数据库 session
            novel_id: 项目 ID
            start_chapter: 起始章节索引
            end_chapter: 结束章节索引
            batch_size: 每批章节数

        Returns:
            ExtractionResult — 抽取结果统计
        """
        nid = self._parse_uuid(novel_id, "novel_id")
        _start, _end = start_chapter, end_chapter

        # 1. 读取已有正史对象作为 context
        # 所有 status 为 "canonical" 或 "draft" 的实体都计入上下文
        all_entities, _ = await self._entity_repo.get_by_novel(db, nid, limit=500)
        existing_context = "\n".join(
            f"- {e.name} ({e.entity_type})"
            for e in all_entities if e.status in ("canonical", "draft")
        ) or "无已有对象"

        # 2. 分批读取 WritingDraft
        chapters = await self._load_chapters(db, novel_id, start_chapter, end_chapter)
        if not chapters:
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail=f"未找到章节 {start_chapter}-{end_chapter} 的正文",
            )

        # 3. 分批调用 LLM
        from infrastructure.llm.client import LLMClient
        from infrastructure.llm.schemas import LLMCallRequest

        llm = LLMClient()
        total_created = 0
        total_skipped = 0
        created_items: list[dict[str, Any]] = []
        batches = [chapters[i:i + batch_size] for i in range(0, len(chapters), batch_size)]

        for batch_idx, batch in enumerate(batches):
            batch_text = "\n\n".join(
                f"--- 第{c['chapter_index']}章: {c['title']} ---\n{c['content']}"
                for c in batch
            )

            system_prompt = (
                "你是一个小说世界对象抽取助手。"
                "从章节正文中抽取需要长期维护的世界对象候选。"
                f"已有对象列表：\n{existing_context}\n\n"
                "规则：不抽取路人、普通道具、临时场景元素。"
                "别名标记为 alias_of_existing，不创建新对象。"
                "输出 JSON 数组，每个对象包含：name, entity_type, summary, "
                "public_info, hidden_truth, importance, suggested_action, "
                "suggested_existing_entity_name, candidate_reason, confidence"
            )

            request = LLMCallRequest(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": batch_text},
                ],
                temperature=0.3,
                response_format={"type": "json_object"},
            )

            try:
                from pydantic import BaseModel
                class _ExtractedEntity(BaseModel):
                    name: str
                    entity_type: str
                    summary: str
                    public_info: str
                    hidden_truth: str
                    importance: float
                    suggested_action: str
                    suggested_existing_entity_name: str | None = None
                    candidate_reason: str
                    confidence: float
                    source_chapter: int | None = None  # 由 LLM 推断来源章节

                class _ExtractionOutput(BaseModel):
                    entities: list[_ExtractedEntity]

                result = await llm.generate_structured(request, _ExtractionOutput)
            except Exception as exc:
                import logging
                logging.getLogger(__name__).warning(
                    "LLM extraction failed for batch %d: %s", batch_idx, exc,
                )
                continue

            # 4. 对每个结果：去重 + 创建候选
            for extracted in result.entities:
                if not extracted.name or not extracted.name.strip():
                    total_skipped += 1
                    continue

                # 去重
                suggestions = await self._dedup_service.find_similar_entities(
                    db, novel_id, extracted.name,
                    entity_type=extracted.entity_type,
                )

                high_confidence = [s for s in suggestions if s.similarity_score >= 0.88]
                if high_confidence:
                    total_skipped += 1
                    continue

                # 来源章节：优先使用 LLM 推断值，否则用批次首章
                src_ch = extracted.source_chapter or batch[0]["chapter_index"]

                # 创建候选
                from modules.world.schemas import EntityCandidateCreate
                candidate_data = EntityCandidateCreate(
                    name=extracted.name.strip(),
                    entity_type=extracted.entity_type,
                    summary=extracted.summary[:2000] if extracted.summary else None,
                    source_text=extracted.summary[:500] or None,
                    source_chapter_index=src_ch,
                    importance_score=min(max(extracted.importance, 0.0), 1.0),
                    confidence=min(max(extracted.confidence, 0.0), 1.0),
                    candidate_reason=extracted.candidate_reason[:500] if extracted.candidate_reason else None,
                    suggested_action=extracted.suggested_action,
                    suggested_existing_entity_id=(
                        suggestions[0].existing_entity_id
                        if suggestions
                        else None
                    ),
                )
                try:
                    candidate = await self._candidate_repo.create(db, nid, candidate_data)
                    total_created += 1
                    created_items.append({
                        "candidate_id": str(candidate.id),
                        "name": candidate.name,
                        "entity_type": candidate.entity_type,
                        "suggested_action": candidate.suggested_action,
                    })
                except ValueError:
                    total_skipped += 1

        await db.flush()
        return ExtractionResult(
            total_chapters=len(chapters),
            total_created=total_created,
            total_skipped=total_skipped,
            items=created_items,
        )

    async def _load_chapters(
        self,
        db: AsyncSession,
        novel_id: str,
        start_chapter: int,
        end_chapter: int,
    ) -> list[dict[str, Any]]:
        """读取指定范围的 WritingDraft"""
        from modules.writing.facade import get_latest_draft_for_chapter

        chapters: list[dict[str, Any]] = []
        for idx in range(start_chapter, end_chapter + 1):
            draft = await get_latest_draft_for_chapter(db, novel_id, idx)
            if draft and draft.content:
                chapters.append({
                    "chapter_index": idx,
                    "title": draft.title or f"第{idx}章",
                    "content": draft.content,
                })
        return chapters

    @staticmethod
    def _parse_uuid(value: str, field_name: str) -> uuid.UUID:
        try:
            return uuid.UUID(hex=value)
        except ValueError:
            raise HTTPException(
                status_code=http_status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"Invalid {field_name}: {value}",
            )


class ExtractionResult:
    """抽取结果统计"""
    total_chapters: int
    total_created: int
    total_skipped: int
    items: list[dict[str, Any]]

    def __init__(
        self,
        *,
        total_chapters: int = 0,
        total_created: int = 0,
        total_skipped: int = 0,
        items: list[dict[str, Any]] | None = None,
    ) -> None:
        self.total_chapters = total_chapters
        self.total_created = total_created
        self.total_skipped = total_skipped
        self.items = items or []


# ============================================================
# 合并与去重辅助函数
# ============================================================

def _normalize_name(value: str) -> str:
    """标准化名称用于匹配：去除特殊字符后 casefold"""
    normalized = value.casefold()
    for token in ("·", "•", "-", "_", " ", "（", "）", "(", ")", "　"):
        normalized = normalized.replace(token, "")
    return normalized


def _merge_text_field(current: str | None, incoming: str | None) -> str:
    """合并两个文本字段：不覆盖非空已有内容，只追加"""
    current_text = (current or "").strip()
    incoming_text = (incoming or "").strip()
    if not incoming_text:
        return current_text
    if not current_text:
        return incoming_text
    if incoming_text == current_text or incoming_text in current_text:
        return current_text
    return f"{current_text}\n\n{incoming_text}"


def _merge_string_lists(*values: list[str]) -> list[str]:
    """合并多个字符串列表，去重保序"""
    merged: list[str] = []
    for group in values:
        for item in group:
            if item and item not in merged:
                merged.append(item)
    return merged


def _world_entity_types_compatible(left: str | None, right: str | None) -> bool:
    """判断两个 entity_type 是否可合并"""
    left = (left or "other").strip().casefold()
    right = (right or "other").strip().casefold()
    return "other" in {left, right} or left == right
