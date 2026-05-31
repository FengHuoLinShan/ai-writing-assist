"""EntityDedupService — 候选实体去重与模糊匹配"""

from __future__ import annotations

import difflib
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from modules.world.repositories import CoreEntityRepository
from modules.world.schemas import (
    CoreEntityUpdate,
    DuplicateSuggestionResult,
)
from modules.world.services.helpers import parse_uuid
from shared.constants import SIMILARITY_HIGH_CONFIDENCE, SIMILARITY_MEDIUM_CONFIDENCE

# difflib 阈值 — 低于此值不返回建议
_MIN_SIMILARITY = 0.58


class EntityDedupService:
    """去重服务 — 基于名称模糊匹配 + 别名精确匹配"""

    def __init__(self) -> None:
        self._entity_repo = CoreEntityRepository()

    async def find_duplicates(
        self,
        db: AsyncSession,
        novel_id: str,
        candidate_id: str,
    ) -> list[DuplicateSuggestionResult]:
        """查找与指定候选重名的已有实体"""
        cid = parse_uuid(candidate_id, "candidate_id")
        candidate = await self._entity_repo.get(db, cid)
        if candidate is None:
            return []

        return await self.find_similar_entities(
            db, novel_id, candidate.name,
            entity_type=candidate.entity_type,
        )

    async def find_similar_entities(
        self,
        db: AsyncSession,
        novel_id: str,
        name: str,
        aliases: list[str] | None = None,
        entity_type: str | None = None,
    ) -> list[DuplicateSuggestionResult]:
        """查找与给定名称相似的已有实体（difflib 模糊匹配 + 别名精确匹配）"""
        nid = parse_uuid(novel_id, "novel_id")
        existing, _ = await self._entity_repo.get_by_novel(
            db, nid, limit=500,
        )

        name_lower = name.strip().lower()
        results: list[DuplicateSuggestionResult] = []

        for entity in existing:
            # 跳过候选状态的实体（不与自己匹配）
            if entity.status not in ("canonical", "draft"):
                continue
            # 类型过滤
            if entity_type and entity.entity_type != entity_type:
                continue

            entity_name = entity.name.strip().lower()
            similarity = 0.0
            match_method = ""

            # 1. 精确名称匹配
            if name_lower == entity_name:
                similarity = 1.0
                match_method = "exact_name"

            # 2. 别名精确匹配
            elif aliases:
                entity_aliases = self._get_aliases(entity)
                for alias in aliases:
                    alias_lower = alias.strip().lower()
                    if alias_lower == entity_name or alias_lower in entity_aliases:
                        similarity = 1.0
                        match_method = "exact_alias"
                        break

            # 3. difflib 模糊匹配
            if similarity == 0.0:
                ratio = difflib.SequenceMatcher(None, name_lower, entity_name).ratio()
                if ratio >= _MIN_SIMILARITY:
                    similarity = ratio
                    match_method = "fuzzy"

                # 也对别名做模糊匹配
                if similarity < _MIN_SIMILARITY:
                    entity_aliases = self._get_aliases(entity)
                    for ea in entity_aliases:
                        ratio = difflib.SequenceMatcher(None, name_lower, ea).ratio()
                        if ratio >= _MIN_SIMILARITY and ratio > similarity:
                            similarity = ratio
                            match_method = "fuzzy_alias"

            if similarity >= _MIN_SIMILARITY:
                action = "needs_user_decision"
                if similarity >= SIMILARITY_HIGH_CONFIDENCE:
                    action = "merge_with_existing"
                elif similarity >= SIMILARITY_MEDIUM_CONFIDENCE:
                    action = "needs_user_decision"

                results.append(DuplicateSuggestionResult(
                    candidate_name=name,
                    existing_entity_id=str(entity.id),
                    existing_entity_name=entity.name,
                    similarity_score=round(similarity, 4),
                    match_method=match_method,
                    action=action,
                ))

        # 按相似度降序排列
        results.sort(key=lambda r: r.similarity_score, reverse=True)
        return results

    @staticmethod
    def _get_aliases(entity) -> list[str]:
        """从 entity.content_json 提取别名列表"""
        content = entity.content_json or {}
        aliases = content.get("aliases", [])
        if not aliases:
            return []
        result: list[str] = []
        for a in aliases:
            if isinstance(a, str):
                result.append(a.lower())
            elif isinstance(a, dict):
                alias_val = a.get("alias", "")
                if alias_val:
                    result.append(str(alias_val).lower())
        return result

    async def merge_candidate_into_entity(
        self,
        db: AsyncSession,
        novel_id: str,
        candidate_id: str,
        target_entity_id: str,
    ) -> Any:
        """合并候选到正史对象（直接更新 entity status）"""
        cid = parse_uuid(candidate_id, "candidate_id")
        teid = parse_uuid(target_entity_id, "target_entity_id")

        entity = await self._entity_repo.get(db, cid)
        if entity is None:
            from fastapi import HTTPException
            from fastapi import status as http_status
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"Entity {candidate_id} not found",
            )

        update_data = CoreEntityUpdate(status="canonical")
        entity = await self._entity_repo.update(db, teid, update_data)
        return entity
