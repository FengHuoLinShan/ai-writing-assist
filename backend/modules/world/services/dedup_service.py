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
from modules.world.models import CoreEntity
from modules.world.repositories import (
    CoreEntityRepository,
    EntityCandidateRepository,
)
from modules.world.schemas import DuplicateSuggestionResult
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
    2. 别名匹配（alias_match）— 搜索 core_entities.aliases JSONB
    3. 模糊名称匹配（fuzzy_name）— difflib
    """

    def __init__(self) -> None:
        self._entity_repo = CoreEntityRepository()
        self._candidate_repo = EntityCandidateRepository()

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

        # 2. 别名匹配（搜索 core_entities.aliases JSONB）
        alias_matches = await self._find_alias_matches_in_jsonb(db, nid, candidate.name)
        for match in alias_matches:
            eid_str = str(match["entity_id"])
            if eid_str not in seen_ids:
                seen_ids.add(eid_str)
                suggestions.append(DuplicateSuggestionResult(
                    candidate_id=candidate_id,
                    candidate_name=candidate.name,
                    existing_entity_id=eid_str,
                    existing_entity_name=match["entity_name"],
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
                    candidate_id="", candidate_name=name,
                    existing_entity_id=eid_str, existing_entity_name=match.name,
                    similarity_score=1.0, match_method="exact_name", action="alias_of_existing",
                ))

        # 2. 别名匹配
        alias_matches = await self._find_alias_matches_in_jsonb(db, nid, name)
        for match in alias_matches:
            eid_str = str(match["entity_id"])
            if eid_str not in seen_ids:
                seen_ids.add(eid_str)
                suggestions.append(DuplicateSuggestionResult(
                    candidate_id="", candidate_name=name,
                    existing_entity_id=eid_str, existing_entity_name=match["entity_name"],
                    similarity_score=SIMILARITY_HIGH_CONFIDENCE,
                    match_method="alias_match", action="alias_of_existing",
                ))

        # 3. 模糊匹配
        all_entities, _ = await self._entity_repo.get_by_novel(db, nid, limit=500)
        fuzzy_matches = self._fuzzy_name_matches(name, entity_type, all_entities)
        for fuzz in fuzzy_matches:
            eid_str = fuzz["entity_id"]
            if eid_str not in seen_ids:
                seen_ids.add(eid_str)
                suggestions.append(DuplicateSuggestionResult(
                    candidate_id="", candidate_name=name,
                    existing_entity_id=eid_str, existing_entity_name=fuzz["entity_name"],
                    similarity_score=fuzz["score"], match_method="fuzzy_name", action=fuzz["action"],
                ))

        suggestions.sort(key=lambda s: s.similarity_score, reverse=True)
        return suggestions

    async def merge_candidate_into_entity(
        self,
        db: AsyncSession,
        novel_id: str,
        candidate_id: str,
        target_entity_id: str,
    ) -> CoreEntity:
        """将候选对象合并到指定 CoreEntity"""
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
            raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST,
                               detail="Candidate does not belong to the same novel")

        entity = await self._entity_repo.get(db, teid)
        if entity is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"CoreEntity {target_entity_id} not found",
            )
        if entity.novel_id != nid:
            raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST,
                               detail="Target entity does not belong to the same novel")

        # 合并别名：添加到 core_entities.aliases JSONB（去重）
        if candidate.name != entity.name:
            current_aliases: list[dict] = list(entity.aliases or [])
            existing_alias_texts = {a.get("alias") for a in current_aliases if isinstance(a, dict)}
            if candidate.name not in existing_alias_texts:
                current_aliases.append({
                    "alias": candidate.name,
                    "type": "name",
                    "source_chapter": candidate.source_chapter_index,
                })
                entity.aliases = current_aliases

        # 合并文本字段
        entity.summary = merge_text_field(entity.summary, candidate.summary)
        if candidate.source_text:
            entity.public_info = merge_text_field(entity.public_info, candidate.source_text)
            entity.hidden_truth = merge_text_field(entity.hidden_truth, candidate.source_text)

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
        entities: list[CoreEntity],
    ) -> list[dict[str, Any]]:
        """使用 difflib 进行模糊名称匹配"""
        if not name:
            return []
        results: list[dict[str, Any]] = []
        normalized_name = normalize_name(name)
        for entity in entities:
            if not world_entity_types_compatible(entity_type, entity.entity_type):
                continue
            best_score = max(
                (difflib.SequenceMatcher(None, normalized_name, normalize_name(entity.name)).ratio(),),
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
    ) -> list[CoreEntity]:
        """查找名称精确匹配的 CoreEntity"""
        conditions = [CoreEntity.novel_id == novel_id, CoreEntity.name == name]
        if entity_type:
            conditions.append(CoreEntity.entity_type == entity_type)
        stmt = select(CoreEntity).where(*conditions)
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def _find_alias_matches_in_jsonb(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        alias_text: str,
    ) -> list[dict[str, Any]]:
        """搜索 core_entities.aliases JSONB 中的别名匹配"""
        stmt = (
            select(CoreEntity)
            .where(
                CoreEntity.novel_id == novel_id,
                CoreEntity.status.in_(["canonical", "draft"]),
            )
        )
        result = await db.execute(stmt)
        matches: list[dict[str, Any]] = []
        for entity in result.scalars().all():
            for alias_entry in entity.aliases or []:
                if isinstance(alias_entry, dict) and alias_entry.get("alias") == alias_text:
                    matches.append({"entity_id": str(entity.id), "entity_name": entity.name})
                    break
        return matches

    async def find_trgm_similar(
        self, db: AsyncSession, novel_id: uuid.UUID,
        name: str, threshold: float = SIMILARITY_MEDIUM_CONFIDENCE,
    ) -> list[DuplicateSuggestionResult]:
        return []

    async def find_vector_similar(
        self, db: AsyncSession, novel_id: uuid.UUID,
        embedding: list[float], threshold: float = SIMILARITY_MEDIUM_CONFIDENCE,
    ) -> list[DuplicateSuggestionResult]:
        return []
