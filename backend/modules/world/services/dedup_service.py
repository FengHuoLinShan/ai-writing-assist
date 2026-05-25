"""EntityDedupService — 对象去重与合并"""

from __future__ import annotations

import difflib
import uuid
from typing import Any

from fastapi import HTTPException
from fastapi import status as http_status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.world.contracts import DuplicateSuggestion
from modules.world.models import EntityAlias, WorldEntity
from modules.world.repositories import (
    EntityAliasRepository,
    EntityCandidateRepository,
    WorldEntityRepository,
)
from modules.world.schemas import DuplicateSuggestionResult, EntityAliasCreate
from modules.world.services.helpers import (
    merge_text_field,
    normalize_name,
    parse_uuid,
    world_entity_types_compatible,
)
from shared.constants import SIMILARITY_HIGH_CONFIDENCE, SIMILARITY_MEDIUM_CONFIDENCE


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
        """对指定候选对象进行去重检查"""
        nid = parse_uuid(novel_id, "novel_id")
        cid = parse_uuid(candidate_id, "candidate_id")

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
        alias_matches = await self._find_alias_matches(db, nid, candidate.name)
        for alias_elem in alias_matches:
            if alias_elem.entity_id not in seen_ids and alias_elem.entity_id:
                seen_ids.add(alias_elem.entity_id)
                eid = parse_uuid(alias_elem.entity_id, "entity_id")
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
        """对指定名称查找相似的正史对象（供 EntityExtractionService 使用）"""
        nid = parse_uuid(novel_id, "novel_id")
        suggestions: list[DuplicateSuggestionResult] = []
        seen_ids: set[str] = set()

        # 1. 精确匹配
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
                eid = parse_uuid(alias_elem.entity_id, "entity_id")
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
        """将候选对象合并到指定正史对象"""
        nid = parse_uuid(novel_id, "novel_id")
        cid = parse_uuid(candidate_id, "candidate_id")
        teid = parse_uuid(target_entity_id, "target_entity_id")

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

        merged_fields: list[str] = []
        added_aliases: list[str] = []

        # 合并别名
        if candidate.name != entity.name:
            alias_data = EntityAliasCreate(
                entity_id=str(entity.id),
                alias=candidate.name,
                alias_type="name",
                source_chapter_index=candidate.source_chapter_index,
                confidence=candidate.confidence or 0.8,
            )
            await EntityAliasRepository().create(db, nid, alias_data)
            added_aliases.append(candidate.name)
            merged_fields.append("aliases")

        # 合并 summary
        entity.summary = merge_text_field(entity.summary, candidate.summary)
        merged_fields.append("summary")

        # 合并 public_info
        if candidate.source_text:
            entity.public_info = merge_text_field(entity.public_info, candidate.source_text)
            merged_fields.append("public_info")

        # 合并 hidden_truth
        if candidate.source_text:
            entity.hidden_truth = merge_text_field(entity.hidden_truth, candidate.source_text)
            merged_fields.append("hidden_truth")

        # 合并 importance
        if candidate.importance_score is not None and candidate.importance_score > (entity.importance or 0):
            entity.importance = candidate.importance_score

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
        """使用 difflib 进行模糊名称匹配"""
        if not name:
            return []
        results: list[dict[str, Any]] = []
        normalized_name = normalize_name(name)
        for entity in entities:
            if not world_entity_types_compatible(entity_type, entity.entity_type):
                continue
            candidates = [entity.name]
            best_score = max(
                (
                    difflib.SequenceMatcher(None, normalized_name, normalize_name(c)).ratio()
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
        """使用 pg_trgm 查找名称相似的对象（MVP 占位）"""
        return []

    async def find_vector_similar(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        embedding: list[float],
        threshold: float = SIMILARITY_MEDIUM_CONFIDENCE,
    ) -> list[DuplicateSuggestionResult]:
        """使用 pgvector 查找语义相似的对象（MVP 占位）"""
        return []
