"""EntityDedupService — 候选实体去重与模糊匹配"""

from __future__ import annotations

import difflib
import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.world.models import CoreEntity
from modules.world.repositories import (
    CharacterRepository,
    CoreEntityRepository,
    EntityRelationRepository,
)
from modules.world.schemas import (
    CoreEntityUpdate,
    DuplicateSuggestionResult,
    EntityRelationUpdate,
)
from modules.world.services.helpers import merge_text_field, parse_uuid
from shared.constants import (
    DEDUP_CONFLICT_FIELDS,
    DEDUP_FUSION_TOP_K,
    DEDUP_RRF_K,
    SIMILARITY_HIGH_CONFIDENCE,
    SIMILARITY_MEDIUM_CONFIDENCE,
)
from shared.enums import CandidateAction

# difflib 阈值 — 低于此值不返回建议
_MIN_SIMILARITY = 0.58

logger = logging.getLogger(__name__)


class EntityDedupService:
    """去重服务 — pg_trgm 初筛 + RRF 混合检索 + 深度合并"""

    def __init__(self) -> None:
        self._entity_repo = CoreEntityRepository()
        self._relation_repo = EntityRelationRepository()

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
        query_embedding: list[float] | None = None,
    ) -> list[DuplicateSuggestionResult]:
        """查找与给定名称相似的已有实体（pg_trgm DB 初筛 + difflib 精排 + 可选语义检索）"""
        nid = parse_uuid(novel_id, "novel_id")
        name_lower = name.strip().lower()

        # 阶段一：词法初筛（search_text 虚拟列同时覆盖 name + aliases）
        lexical_candidates = await self._entity_repo.find_similar_by_search_text(
            db, nid, name_lower,
            entity_type=entity_type,
            status_filter=["canonical", "draft"],
            top_k=DEDUP_FUSION_TOP_K,
        )

        # 阶段二：语义搜索（可选，仅在有 embedding 时启用）
        candidates: list[tuple[Any, float, str]]  # [(entity, final_score, match_method)]
        if query_embedding is not None:
            has_emb = await self._entity_repo.has_embeddings(db, nid)
            if has_emb:
                semantic_candidates = await self._entity_repo.find_similar_by_embedding(
                    db, nid, query_embedding,
                    entity_type=entity_type,
                    status_filter=["canonical", "draft"],
                    top_k=DEDUP_FUSION_TOP_K,
                )
                if semantic_candidates:
                    candidates = self._rrf_fusion(
                        lexical_candidates, semantic_candidates, k=DEDUP_RRF_K,
                    )
                else:
                    candidates = [(e, s, "lexical") for e, s in lexical_candidates]
            else:
                candidates = [(e, s, "lexical") for e, s in lexical_candidates]
                logger.info(
                    "Semantic dedup path not active for novel %s — "
                    "no stored embeddings found. Run backfill_entity_embeddings().",
                    novel_id,
                )
        else:
            candidates = [(e, s, "lexical") for e, s in lexical_candidates]

        results: list[DuplicateSuggestionResult] = []

        for entity, rrf_score, rrf_method in candidates:
            # 跳过候选状态的实体（不与自己匹配）
            if entity.status not in ("canonical", "draft"):
                continue
            # 类型过滤
            if entity_type and entity.entity_type != entity_type:
                continue

            entity_name = entity.name.strip().lower()
            difflib_similarity = 0.0
            difflib_method = ""

            # 1. 精确名称匹配
            if name_lower == entity_name:
                difflib_similarity = 1.0
                difflib_method = "exact_name"

            # 2. 别名精确匹配
            elif aliases:
                entity_aliases = self._get_aliases(entity)
                for alias in aliases:
                    alias_lower = alias.strip().lower()
                    if alias_lower == entity_name or alias_lower in entity_aliases:
                        difflib_similarity = 1.0
                        difflib_method = "exact_alias"
                        break

            # 3. difflib 模糊匹配
            if difflib_similarity == 0.0:
                ratio = difflib.SequenceMatcher(None, name_lower, entity_name).ratio()
                if ratio >= _MIN_SIMILARITY:
                    difflib_similarity = ratio
                    difflib_method = "fuzzy"

                # 也对别名做模糊匹配
                if difflib_similarity < _MIN_SIMILARITY:
                    entity_aliases = self._get_aliases(entity)
                    for ea in entity_aliases:
                        ratio = difflib.SequenceMatcher(None, name_lower, ea).ratio()
                        if ratio >= _MIN_SIMILARITY and ratio > difflib_similarity:
                            difflib_similarity = ratio
                            difflib_method = "fuzzy_alias"

            # 综合评分：词法 + 语义融合，纯语义匹配有独立通道
            if difflib_similarity >= 1.0:
                # 精确名称/别名匹配不受语义分干扰
                similarity = difflib_similarity
            elif difflib_similarity > 0:
                # 有词法命中：0.65 词法 + 0.35 语义
                similarity = 0.65 * difflib_similarity + 0.35 * rrf_score
            elif rrf_method in ("semantic", "hybrid") and rrf_score >= 0.4:
                # 纯语义命中（如"面具人"→"李四"字面无关联）：
                # rrf 0.45→0.58, rrf 0.5→0.625, 让高置信语义匹配独立通过
                similarity = 0.50 + rrf_score * 0.25
                difflib_method = rrf_method
            else:
                similarity = difflib_similarity

            # match_method 优先用精确/别名匹配，其次用 RRF 标签
            match_method = difflib_method or rrf_method

            if similarity >= _MIN_SIMILARITY:
                action = CandidateAction.needs_user_decision
                if similarity >= SIMILARITY_HIGH_CONFIDENCE:
                    action = CandidateAction.merge_with_existing
                elif similarity >= SIMILARITY_MEDIUM_CONFIDENCE:
                    action = CandidateAction.needs_user_decision

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
    def _rrf_fusion(
        lexical_ranked: list[tuple[Any, float]],
        semantic_ranked: list[tuple[Any, float]],
        k: int = 60,
    ) -> list[tuple[Any, float, str]]:
        """对两个排序列表做 RRF (Reciprocal Rank Fusion)。

        score = 1/(k + rank_lexical) + 1/(k + rank_semantic)
        只出现在一个列表的实体，缺失列表的 rank 贡献为 0（标准 RRF）。
        返回归一化到 [0,1] 的 (entity, score, method) 列表，按分降序。
        """
        scores: dict[str, float] = {}
        methods: dict[str, str] = {}
        entities: dict[str, Any] = {}

        for rank, (entity, _) in enumerate(lexical_ranked, start=1):
            eid = str(entity.id)
            entities[eid] = entity
            scores[eid] = 1.0 / (k + rank)
            methods[eid] = "lexical"

        for rank, (entity, _) in enumerate(semantic_ranked, start=1):
            eid = str(entity.id)
            entities[eid] = entity
            rrf = 1.0 / (k + rank)
            if eid in scores:
                scores[eid] += rrf
                methods[eid] = "hybrid"
            else:
                scores[eid] = rrf
                methods[eid] = "semantic"

        # 归一化到 [0, 1]：理论最大值为两个第 1 名的加和
        max_possible = 2.0 / (k + 1)
        norm_factor = max_possible if max_possible > 0 else 1.0

        merged: list[tuple[Any, float, str]] = []
        seen: set[str] = set()
        for eid, score in sorted(scores.items(), key=lambda x: x[1], reverse=True):
            if eid not in seen:
                seen.add(eid)
                merged.append((
                    entities[eid],
                    min(1.0, score / norm_factor),
                    methods[eid],
                ))
        return merged

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

    # ============================================================
    # 深度合并（排他锁 + 自环清理 + 跨表事务）
    # ============================================================

    async def merge_candidate_into_entity(
        self,
        db: AsyncSession,
        novel_id: str,
        candidate_id: str,
        target_entity_id: str,
    ) -> Any:  # MergeResult
        """合并候选实体到目标正史实体（事务性跨表深度合并）。

        9 步事务：排他锁 → 别名继承 → 关系迁移 → 自环清理 → Character 同步
        → 文本合并 → 标记 candidate → 确保 target canonical → 返回统计。
        调用方负责事务的 commit/rollback。
        """
        from modules.world.contracts import MergeResult

        cid = parse_uuid(candidate_id, "candidate_id")
        tid = parse_uuid(target_entity_id, "target_entity_id")

        # 0. 加载 Target（排他锁防并发写偏斜）
        stmt = select(CoreEntity).where(CoreEntity.id == tid).with_for_update()
        result = await db.execute(stmt)
        target = result.scalar_one_or_none()

        if target is None:
            from fastapi import HTTPException
            from fastapi import status as http_status
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"Target entity {target_entity_id} not found",
            )

        # 1. 加载 Candidate（FOR UPDATE 防并发重复合并）
        if cid == tid:
            from fastapi import HTTPException
            from fastapi import status as http_status
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail="Cannot merge an entity into itself",
            )
        stmt = select(CoreEntity).where(CoreEntity.id == cid).with_for_update()
        result = await db.execute(stmt)
        candidate = result.scalar_one_or_none()
        if candidate is None:
            from fastapi import HTTPException
            from fastapi import status as http_status
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"Candidate entity {candidate_id} not found",
            )

        # 校验同 novel_id
        if str(candidate.novel_id) != str(target.novel_id):
            from fastapi import HTTPException
            from fastapi import status as http_status
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail="Cannot merge entities across novels",
            )

        # 2. 别名继承
        aliases_inherited = await self._inherit_aliases(db, candidate, target)

        # 3. 关系迁移
        migration_result = await self._migrate_relations(
            db, novel_id, candidate_id, target_entity_id,
        )
        relations_migrated = migration_result["migrated"]
        relations_deduplicated = migration_result["deduplicated"]

        # 4. 自环清理：只删迁移产生的自环，不碰 target 原有合法自环
        created_self_loop_ids = migration_result.get("created_self_loop_ids", [])
        self_loops_cleaned = 0
        for sl_id in created_self_loop_ids:
            import uuid as _uuid2
            await self._relation_repo.update(
                db, _uuid2.UUID(sl_id),
                EntityRelationUpdate(status="deprecated"),
            )
            self_loops_cleaned += 1

        # 5. Character 同步
        character_synced = await self._sync_character_on_merge(
            db, novel_id, candidate_id, target_entity_id,
        )

        # 6. 文本字段合并
        await self._merge_text_fields(db, candidate, target)

        # 6.5 冲突归档
        conflicts_archived = await self._archive_conflicts(db, candidate, target)

        # 7. 标记 candidate 为 merged
        merged_content = dict(candidate.content_json or {})
        merged_content["merged_into"] = str(tid)
        merged_content["merged_at"] = datetime.now(UTC).isoformat()
        await self._entity_repo.update(db, cid, CoreEntityUpdate(
            status="merged",
            content_json=merged_content,
        ))

        # 8. 确保 target 为 canonical
        if target.status != "canonical":
            await self._entity_repo.update(db, tid, CoreEntityUpdate(status="canonical"))

        await db.flush()

        return MergeResult(
            target_entity_id=str(tid),
            candidate_entity_id=str(cid),
            aliases_inherited=aliases_inherited,
            relations_migrated=relations_migrated,
            relations_deduplicated=relations_deduplicated,
            self_loops_cleaned=self_loops_cleaned,
            character_synced=character_synced,
            conflicts_archived=conflicts_archived,
        )

    async def resolve_candidate(
        self,
        db: AsyncSession,
        novel_id: str,
        candidate_id: str,
        *,
        query_embedding: list[float] | None = None,
    ) -> Any:  # ResolveResult
        """自动决议候选实体：高置信→合并，无匹配→提升，中间→需人工。"""
        from modules.world.contracts import ResolveResult

        cid = parse_uuid(candidate_id, "candidate_id")
        candidate = await self._entity_repo.get(db, cid)
        if candidate is None:
            from fastapi import HTTPException
            from fastapi import status as http_status
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"Candidate entity {candidate_id} not found",
            )

        suggestions = await self.find_similar_entities(
            db, novel_id, candidate.name,
            entity_type=candidate.entity_type,
            query_embedding=query_embedding,
        )

        # 过滤掉候选实体自身
        suggestions = [
            s for s in suggestions
            if s.existing_entity_id != str(cid)
        ]

        # 无匹配 → 直接提升为 canonical
        if not suggestions:
            await self._entity_repo.update(db, cid, CoreEntityUpdate(status="canonical"))
            await db.flush()
            return ResolveResult(
                action="promoted",
                promoted_entity_id=str(cid),
            )

        best = suggestions[0]

        # 高置信度 → 自动合并
        if best.similarity_score >= SIMILARITY_HIGH_CONFIDENCE:
            merge_result = await self.merge_candidate_into_entity(
                db, novel_id, candidate_id, best.existing_entity_id,
            )
            return ResolveResult(
                action="merged",
                merge_result=merge_result,
            )

        # 中间态 → 返回建议列表等待人工决定
        return ResolveResult(
            action="needs_user_decision",
            suggestions=suggestions,
        )

    # ----------------------------------------------------------
    # 私有合并辅助方法
    # ----------------------------------------------------------

    async def _inherit_aliases(
        self,
        db: AsyncSession,
        candidate: CoreEntity,
        target: CoreEntity,
    ) -> int:
        """将 candidate 的别名合并到 target 的 content_json.aliases，去重返回新增数。"""
        candidate_aliases_raw = self._get_aliases_raw(candidate)
        target_content = dict(target.content_json or {})
        target_aliases: list[dict] = list(target_content.get("aliases", []))

        # 构建已存在别名的文本集合（大小写不敏感）
        existing_texts: set[str] = set()
        for a in target_aliases:
            text = a.get("alias", "") if isinstance(a, dict) else str(a)
            if text.strip():
                existing_texts.add(text.strip().lower())

        added = 0
        for alias_entry in candidate_aliases_raw:
            alias_text = (
                alias_entry.get("alias", "").strip()
                if isinstance(alias_entry, dict)
                else str(alias_entry).strip()
            )
            if not alias_text or alias_text.lower() in existing_texts:
                continue
            target_aliases.append(
                alias_entry if isinstance(alias_entry, dict)
                else {"alias": alias_text, "type": "inherited"}
            )
            existing_texts.add(alias_text.lower())
            added += 1

        if added > 0:
            target_content["aliases"] = target_aliases
            await self._entity_repo.update(db, target.id, CoreEntityUpdate(
                content_json=target_content,
            ))

        return added

    async def _migrate_relations(
        self,
        db: AsyncSession,
        novel_id: str,
        candidate_id: str,
        target_id: str,
    ) -> dict:
        """将 candidate 的 EntityRelation 边重定向到 target，处理重复。

        Returns:
            {"migrated": int, "deduplicated": int, "created_self_loop_ids": list}
            created_self_loop_ids 是迁移产生的自环 ID 列表，由调用方负责清理。
        """
        import uuid as _uuid

        nid = _uuid.UUID(novel_id)
        cid = _uuid.UUID(candidate_id)
        tid = _uuid.UUID(target_id)
        all_rels = await self._relation_repo.get_all_for_entity(db, nid, cid)
        migrated = 0
        deduplicated = 0
        created_self_loop_ids: list[str] = []

        for rel in all_rels:
            is_source = rel.source_id == cid
            is_target = rel.target_id == cid

            # 候选自环：标记 deprecated，不做迁移
            if is_source and is_target:
                await self._relation_repo.update(
                    db, rel.id, EntityRelationUpdate(status="deprecated"),
                )
                deduplicated += 1
                continue

            if is_source:
                new_source = tid
                new_target = rel.target_id
            elif is_target:
                new_source = rel.source_id
                new_target = tid
            else:
                continue

            # 记录迁移产生的自环
            if new_source == tid and new_target == tid:
                created_self_loop_ids.append(str(rel.id))

            # 检查是否已有同类型同方向边
            existing = await self._relation_repo.find_duplicate_relation(
                db, nid, new_source, new_target, rel.relation_type,
            )
            if existing is not None and str(existing.id) != str(rel.id):
                # 合并描述到已有边，标记当前边为 deprecated
                merged_desc = merge_text_field(existing.description, rel.description)
                if merged_desc != (existing.description or ""):
                    await self._relation_repo.update(
                        db, existing.id,
                        EntityRelationUpdate(description=merged_desc),
                    )
                await self._relation_repo.update(
                    db, rel.id,
                    EntityRelationUpdate(status="deprecated"),
                )
                deduplicated += 1
            else:
                # 重定向
                await self._relation_repo.update_endpoint(
                    db, rel.id,
                    source_id=new_source if is_source else None,
                    target_id=new_target if is_target else None,
                )
                migrated += 1

        return {
            "migrated": migrated,
            "deduplicated": deduplicated,
            "created_self_loop_ids": created_self_loop_ids,
        }

    async def _sync_character_on_merge(
        self,
        db: AsyncSession,
        novel_id: str,
        candidate_id: str,
        target_id: str,
    ) -> bool:
        """若 candidate 有 Character 扩展行，将其数据合并到 target 的 Character。"""
        import uuid as _uuid

        from modules.world.schemas import CharacterUpdate

        cid = _uuid.UUID(candidate_id)
        tid = _uuid.UUID(target_id)

        char_repo = CharacterRepository()
        candidate_char = await char_repo.get(db, cid)
        if candidate_char is None:
            return False

        target_char = await char_repo.get(db, tid)
        if target_char is None:
            return False

        # 合并别名
        target_aliases: list[dict] = list(target_char.aliases or [])
        existing_alias_texts: set[str] = {
            a.get("alias", "").strip() if isinstance(a, dict) else str(a).strip()
            for a in target_aliases
        }
        for alias in (candidate_char.aliases or []):
            text = alias.get("alias", "").strip() if isinstance(alias, dict) else str(alias).strip()
            if text and text not in existing_alias_texts:
                target_aliases.append(alias)
                existing_alias_texts.add(text)

        await char_repo.update(db, tid, CharacterUpdate(
            aliases=target_aliases,
            appearance=merge_text_field(target_char.appearance, candidate_char.appearance),
            personality=merge_text_field(target_char.personality, candidate_char.personality),
            desire=merge_text_field(target_char.desire, candidate_char.desire),
            fear=merge_text_field(target_char.fear, candidate_char.fear),
            secret=merge_text_field(target_char.secret, candidate_char.secret),
            weakness=merge_text_field(target_char.weakness, candidate_char.weakness),
            current_goal=merge_text_field(target_char.current_goal, candidate_char.current_goal),
            relationship_summary=merge_text_field(
                target_char.relationship_summary, candidate_char.relationship_summary,
            ),
            meta={**candidate_char.meta, **target_char.meta},
        ))

        return True

    async def _merge_text_fields(
        self,
        db: AsyncSession,
        candidate: CoreEntity,
        target: CoreEntity,
    ) -> None:
        """合并 summary / public_info / hidden_truth。"""
        updates: dict[str, str] = {}
        merged_summary = merge_text_field(target.summary, candidate.summary)
        if merged_summary != (target.summary or ""):
            updates["summary"] = merged_summary
        merged_public = merge_text_field(target.public_info, candidate.public_info)
        if merged_public != (target.public_info or ""):
            updates["public_info"] = merged_public
        merged_hidden = merge_text_field(target.hidden_truth, candidate.hidden_truth)
        if merged_hidden != (target.hidden_truth or ""):
            updates["hidden_truth"] = merged_hidden

        if updates:
            await self._entity_repo.update(db, target.id, CoreEntityUpdate(**updates))

    async def _archive_conflicts(
        self,
        db: AsyncSession,
        candidate: CoreEntity,
        target: CoreEntity,
    ) -> int:
        """对比 content_json 冲突字段，记录到 target.content_json.meta.conflict_notes。

        只对比 DEDUP_CONFLICT_FIELDS 中列出的关键字段。
        正史值保留不动，候选值写入 conflict_notes 备忘。
        返回记录的冲突数。
        """
        candidate_json = candidate.content_json or {}
        target_json = target.content_json or {}

        conflicts: list[dict] = []
        for field in DEDUP_CONFLICT_FIELDS:
            canonical_val = target_json.get(field)
            candidate_val = candidate_json.get(field)
            if canonical_val is None or candidate_val is None:
                continue
            if str(canonical_val).strip() == str(candidate_val).strip():
                continue
            conflicts.append({
                "field": field,
                "canonical_value": canonical_val,
                "candidate_value": candidate_val,
                "candidate_id": str(candidate.id),
                "resolved_at": datetime.now(UTC).isoformat(),
            })

        if not conflicts:
            return 0

        target_meta = dict(target_json.get("meta", {}))
        existing_notes = list(target_meta.get("conflict_notes", []))
        existing_notes.extend(conflicts)
        target_meta["conflict_notes"] = existing_notes

        merged_json = dict(target_json)
        merged_json["meta"] = target_meta
        await self._entity_repo.update(db, target.id, CoreEntityUpdate(
            content_json=merged_json,
        ))
        return len(conflicts)

    def _get_aliases_raw(self, entity: CoreEntity) -> list[dict]:
        """提取原始别名列表（保留原始格式，不转小写）。"""
        content = entity.content_json or {}
        aliases = content.get("aliases", [])
        if not aliases:
            return []
        result: list[dict] = []
        for a in aliases:
            if isinstance(a, dict):
                result.append(a)
            elif isinstance(a, str):
                result.append({"alias": a, "type": "unknown"})
        return result
