"""EntityDedupService — 候选实体去重与模糊匹配"""

from __future__ import annotations

import json
import logging
import os
import pickle
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from fastapi import status as http_status
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
from modules.world.services.dedup_scorer import DedupScorer
from modules.world.services.helpers import merge_text_field, parse_uuid
from shared.constants import (
    DEDUP_AUTO_MERGE_THRESHOLD,
    DEDUP_CONFLICT_FIELDS,
    DEDUP_DISCARD_THRESHOLD,
    DEDUP_FUSION_TOP_K,
    DEDUP_REVIEW_THRESHOLD,
)
from shared.enums import CandidateAction

logger = logging.getLogger(__name__)

DEDUP_MODEL_ACTIVE = os.environ.get("DEDUP_MODEL_ACTIVE", "false").lower() == "true"


class DedupModelProxy:
    """去重 LR 模型单例代理。

    负责从 pickle 加载预训练模型，并在加载失败/版本不匹配/维度不匹配时
    自动回退到 None，由调用方切回 _cascade_score。
    """

    _instance: DedupModelProxy | None = None

    def __new__(cls) -> DedupModelProxy:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._load()
        return cls._instance

    def _load(self) -> None:
        self._pipeline: Any | None = None
        self._metadata: dict[str, Any] = {}
        self._feature_dim = 7
        self._model_version = "unknown"
        if not DEDUP_MODEL_ACTIVE:
            return
        try:
            base = Path(__file__).resolve().parents[3] / "data" / "dedup_training"
            meta_path = base / "dedup_model_metadata.json"
            model_path = base / "dedup_fusion_model.pkl"
            with open(meta_path, encoding="utf-8") as fh:
                self._metadata = json.load(fh)
            with open(model_path, "rb") as fh:
                self._pipeline = pickle.load(fh)

            import sklearn

            meta_sklearn = self._metadata.get("sklearn_version")
            if meta_sklearn and meta_sklearn != sklearn.__version__:
                logger.warning(
                    "sklearn version mismatch (metadata=%s, runtime=%s), "
                    "falling back to cascade",
                    meta_sklearn,
                    sklearn.__version__,
                )
                self._pipeline = None

            meta_dim = self._metadata.get("feature_dim")
            if meta_dim is not None and meta_dim != self._feature_dim:
                logger.warning(
                    "feature dimension mismatch (metadata=%s, expected=%s), "
                    "falling back to cascade",
                    meta_dim,
                    self._feature_dim,
                )
                self._pipeline = None

            self._model_version = self._metadata.get("model_version", "unknown")
        except FileNotFoundError:
            logger.warning("Dedup model files not found, falling back to cascade")
            self._pipeline = None
        except Exception as exc:
            logger.warning("Dedup model load failed: %s", exc)
            self._pipeline = None

    @property
    def calibrated_thresholds(self) -> dict[str, float]:
        """返回模型标定阈值，带默认值保底。"""
        import copy

        thresholds = copy.copy(self._metadata.get("thresholds", {}))
        if "theta_merge" not in thresholds:
            thresholds["theta_merge"] = DEDUP_AUTO_MERGE_THRESHOLD
        if "theta_review" not in thresholds:
            thresholds["theta_review"] = DEDUP_REVIEW_THRESHOLD
        if "theta_discard" not in thresholds:
            thresholds["theta_discard"] = DEDUP_DISCARD_THRESHOLD
        return thresholds

    @property
    def model_version(self) -> str:
        """返回模型版本字符串。"""
        return self._model_version

    def predict(self, vector: list[float]) -> tuple[float, str]:
        if self._pipeline is None:
            raise RuntimeError("model not loaded")
        if len(vector) != self._feature_dim:
            raise ValueError(f"expected {self._feature_dim} features, got {len(vector)}")
        proba = float(self._pipeline.predict_proba([vector])[0][1])
        return proba, self._model_version


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
        nid = parse_uuid(novel_id, "novel_id")
        cid = parse_uuid(candidate_id, "candidate_id")
        candidate = await self._entity_repo.get(db, cid)
        if candidate is None or candidate.novel_id != nid:
            return []

        return await self.find_similar_entities(
            db,
            novel_id,
            candidate.name,
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
        """查找与给定名称相似的已有实体

        pg_trgm DB 初筛 + 异质信号级联评分 + 可选语义检索。
        """
        nid = parse_uuid(novel_id, "novel_id")
        name_lower = name.strip().lower()

        # 阶段一：词法初筛（search_text 虚拟列同时覆盖 name + aliases）
        lexical_candidates = await self._entity_repo.find_similar_by_search_text(
            db,
            nid,
            name_lower,
            entity_type=entity_type,
            status_filter=["canonical", "draft"],
            top_k=DEDUP_FUSION_TOP_K,
        )

        # 阶段二：语义搜索（不再全局短路，让 DB 层自然跳过无向量记录）
        semantic_candidates: list[tuple[Any, float]] = []
        if query_embedding is not None:
            semantic_candidates = await self._entity_repo.find_similar_by_embedding(
                db,
                nid,
                query_embedding,
                entity_type=entity_type,
                status_filter=["canonical", "draft"],
                top_k=DEDUP_FUSION_TOP_K,
            )

        # 构建语义候选映射：entity_id -> cosine_score
        semantic_map: dict[str, float] = {
            str(e.id): score for e, score in semantic_candidates
        }

        # 合并候选集合（词法召回 + 语义召回的并集）
        seen_ids: set[str] = set()
        all_candidates: list[tuple[Any, float | None, float | None]] = []
        # (entity, lexical_score, semantic_score)
        for entity, lex_score in lexical_candidates:
            eid = str(entity.id)
            seen_ids.add(eid)
            sem_score = semantic_map.get(eid)
            all_candidates.append((entity, lex_score, sem_score))

        for entity, sem_score in semantic_candidates:
            eid = str(entity.id)
            if eid not in seen_ids:
                all_candidates.append((entity, None, sem_score))

        results: list[DuplicateSuggestionResult] = []
        scorer = DedupScorer()

        for entity, _lex_score, sem_score in all_candidates:
            # 跳过候选状态的实体（不与自己匹配）
            if entity.status not in ("canonical", "draft"):
                continue
            # 类型过滤
            if entity_type and entity.entity_type != entity_type:
                continue

            entity_name = entity.name.strip().lower()
            entity_aliases = self._get_aliases(entity)

            # 1. 精确名称匹配
            if name_lower == entity_name:
                similarity = 1.0
                match_method = "exact_name"
                action = CandidateAction.merge_with_existing
                results.append(
                    DuplicateSuggestionResult(
                        candidate_name=name,
                        existing_entity_id=str(entity.id),
                        existing_entity_name=entity.name,
                        similarity_score=round(similarity, 4),
                        match_method=match_method,
                        action=action,
                    )
                )
                continue

            # 2. 别名精确匹配
            if aliases:
                alias_matched = False
                for alias in aliases:
                    alias_lower = alias.strip().lower()
                    if alias_lower == entity_name or alias_lower in entity_aliases:
                        similarity = 1.0
                        match_method = "exact_alias"
                        action = CandidateAction.merge_with_existing
                        results.append(
                            DuplicateSuggestionResult(
                                candidate_name=name,
                                existing_entity_id=str(entity.id),
                                existing_entity_name=entity.name,
                                similarity_score=round(similarity, 4),
                                match_method=match_method,
                                action=action,
                            )
                        )
                        alias_matched = True
                        break
                if alias_matched:
                    continue

            # 3. 计算异质信号
            signals = scorer.compute_signals(
                name_lower,
                entity_name,
                candidate_aliases=entity_aliases,
                semantic_cosine=sem_score,
            )

            # 4. 级联评分（模型优先，失败回退）
            similarity, match_method, action = self._resolve_score(signals)

            if similarity >= DEDUP_DISCARD_THRESHOLD:
                results.append(
                    DuplicateSuggestionResult(
                        candidate_name=name,
                        existing_entity_id=str(entity.id),
                        existing_entity_name=entity.name,
                        similarity_score=round(similarity, 4),
                        match_method=match_method,
                        action=action,
                    )
                )

        # 按相似度降序排列
        results.sort(key=lambda r: r.similarity_score, reverse=True)
        return results

    @staticmethod
    def _model_score(signals) -> tuple[float, str, CandidateAction]:
        """LR 模型评分：predict_proba → 基于校准阈值的 action。"""
        proxy = DedupModelProxy()
        proba, _ = proxy.predict(signals.to_vector())
        thresholds = proxy.calibrated_thresholds
        theta_merge = thresholds.get("theta_merge", DEDUP_AUTO_MERGE_THRESHOLD)
        theta_review = thresholds.get("theta_review", DEDUP_REVIEW_THRESHOLD)
        theta_discard = thresholds.get("theta_discard", DEDUP_DISCARD_THRESHOLD)

        sim = round(proba, 4)
        if sim >= theta_merge:
            return (sim, "lr_model", CandidateAction.merge_with_existing)
        if sim >= theta_review:
            return (sim, "lr_model", CandidateAction.needs_user_decision)
        if sim >= theta_discard:
            return (sim, "lr_model", CandidateAction.needs_user_decision)
        return (sim, "lr_model", CandidateAction.ignore)

    def _resolve_score(self, signals) -> tuple[float, str, CandidateAction]:
        """影子模式入口：关闭时直接走级联；开启时优先模型，异常回退。"""
        cascade_result = self._cascade_score(signals)
        if not DEDUP_MODEL_ACTIVE:
            return cascade_result
        # 无语义向量时回退级联 — 模型在语义缺失下不可靠
        if signals.semantic_cosine is None:
            return cascade_result
        try:
            return self._model_score(signals)
        except Exception as exc:
            logger.warning("Model inference failed: %s", exc)
            return cascade_result

    @staticmethod
    def _cascade_score(signals) -> tuple[float, str, CandidateAction]:
        """级联评分：按信号强度分层决策。

        Returns:
            (similarity, match_method, action)
        """
        # 路径2：强子串包含（简称⊂全称）
        if signals.substring_match >= 0.85:
            return (0.95, "substring", CandidateAction.merge_with_existing)

        # 路径3：高形相似 + 高音似（排除近形笔误）
        if signals.rapidfuzz_ratio >= 0.92 and signals.pinyin_jaro >= 0.90:
            return (0.90, "fuzzy_pinyin", CandidateAction.merge_with_existing)

        # 路径4：有语义向量 — 语义主导
        if signals.semantic_cosine is not None and signals.semantic_cosine >= 0.75:
            # 语义 >= 0.85：极高置信，直接合并
            if signals.semantic_cosine >= 0.85:
                return (0.90, "semantic", CandidateAction.merge_with_existing)
            sim = round(0.50 + signals.semantic_cosine * 0.35, 4)
            if sim >= DEDUP_AUTO_MERGE_THRESHOLD:
                return (sim, "semantic", CandidateAction.merge_with_existing)
            if sim >= DEDUP_REVIEW_THRESHOLD:
                return (sim, "semantic", CandidateAction.needs_user_decision)
            # 语义中低但其他信号强，继续路径5

        # 路径5：无语义或语义不强 — 纯词法融合
        # 加权：形相似 50% + 音似 20% + 字序 20% + 子串 10%
        lexical = (
            0.50 * signals.rapidfuzz_ratio
            + 0.20 * signals.pinyin_jaro
            + 0.20 * signals.rapidfuzz_token_sort
            + 0.10 * signals.substring_match
        )

        # 行政区划前缀冲突：直接降权到 discard 区间
        if signals.prefix_conflict:
            lexical = min(lexical, DEDUP_DISCARD_THRESHOLD - 0.01)

        sim = round(lexical, 4)

        if sim >= DEDUP_AUTO_MERGE_THRESHOLD:
            return (sim, "lexical_fusion", CandidateAction.merge_with_existing)
        if sim >= DEDUP_REVIEW_THRESHOLD:
            return (sim, "lexical_fusion", CandidateAction.needs_user_decision)
        if sim >= DEDUP_DISCARD_THRESHOLD:
            return (sim, "lexical_fusion", CandidateAction.needs_user_decision)

        return (sim, "lexical_fusion", CandidateAction.ignore)

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
        *,
        allow_canonical_source: bool = False,
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
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"Target entity {target_entity_id} not found",
            )

        # 1. 加载 Candidate（FOR UPDATE 防并发重复合并）
        if cid == tid:
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail="Cannot merge an entity into itself",
            )
        stmt = select(CoreEntity).where(CoreEntity.id == cid).with_for_update()
        result = await db.execute(stmt)
        candidate = result.scalar_one_or_none()
        if candidate is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"Candidate entity {candidate_id} not found",
            )

        # 校验同 novel_id
        if str(candidate.novel_id) != str(target.novel_id):
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail="Cannot merge entities across novels",
            )

        # 校验 candidate 必须是 draft/candidate
        # target 非 canonical 时由后置逻辑自动提升，不再前置拦截
        allowed_source_statuses = ("draft", "candidate", "canonical") if (
            allow_canonical_source
        ) else ("draft", "candidate")
        if candidate.status not in allowed_source_statuses:
            raise HTTPException(
                status_code=http_status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=(
                    "Merge candidate must be draft or candidate"
                    f"{' or canonical' if allow_canonical_source else ''}, "
                    f"got {candidate.status}"
                ),
            )

        # 2. 别名继承
        aliases_inherited = await self._inherit_aliases(db, candidate, target)

        # 3. 关系迁移
        migration_result = await self._migrate_relations(
            db,
            novel_id,
            candidate_id,
            target_entity_id,
        )
        relations_migrated = migration_result["migrated"]
        relations_deduplicated = migration_result["deduplicated"]

        # 4. 自环清理：只删迁移产生的自环，不碰 target 原有合法自环
        created_self_loop_ids = migration_result.get("created_self_loop_ids", [])
        self_loops_cleaned = 0
        for sl_id in created_self_loop_ids:
            import uuid as _uuid2

            await self._relation_repo.update(
                db,
                _uuid2.UUID(sl_id),
                EntityRelationUpdate(status="deprecated"),
            )
            self_loops_cleaned += 1

        # 5. Character 同步
        character_synced = await self._sync_character_on_merge(
            db,
            novel_id,
            candidate_id,
            target_entity_id,
        )

        # 6. 文本字段合并
        await self._merge_text_fields(db, candidate, target)

        # 6.5 冲突归档
        conflicts_archived = await self._archive_conflicts(db, candidate, target)

        # 7. 标记 candidate 为 merged
        merged_content = dict(candidate.content_json or {})
        merged_content["merged_into"] = str(tid)
        merged_content["merged_at"] = datetime.now(UTC).isoformat()
        await self._entity_repo.update(
            db,
            cid,
            CoreEntityUpdate(
                status="merged",
                content_json=merged_content,
            ),
        )

        # 8. 确保 target 为 canonical
        if target.status != "canonical":
            await self._entity_repo.update(db, tid, CoreEntityUpdate(status="canonical"))

        for changed_id, reason in (
            (str(cid), "candidate_merged"),
            (str(tid), "entity_merged"),
        ):
            try:
                from modules.context.facade import mark_asset_context_changed

                await mark_asset_context_changed(
                    db,
                    novel_id=novel_id,
                    asset_type="world_entity",
                    asset_id=changed_id,
                    reason=reason,
                )
            except Exception:
                logger.warning(
                    "实体 %s 合并后标记上下文确认失效失败",
                    changed_id,
                    exc_info=True,
                )

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
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"Candidate entity {candidate_id} not found",
            )

        suggestions = await self.find_similar_entities(
            db,
            novel_id,
            candidate.name,
            entity_type=candidate.entity_type,
            query_embedding=query_embedding,
        )

        # 过滤掉候选实体自身
        suggestions = [s for s in suggestions if s.existing_entity_id != str(cid)]

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
        if best.similarity_score >= DEDUP_AUTO_MERGE_THRESHOLD:
            merge_result = await self.merge_candidate_into_entity(
                db,
                novel_id,
                candidate_id,
                best.existing_entity_id,
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
                alias_entry
                if isinstance(alias_entry, dict)
                else {"alias": alias_text, "type": "inherited"}
            )
            existing_texts.add(alias_text.lower())
            added += 1

        if added > 0:
            target_content["aliases"] = target_aliases
            await self._entity_repo.update(
                db,
                target.id,
                CoreEntityUpdate(
                    content_json=target_content,
                ),
            )

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
                    db,
                    rel.id,
                    EntityRelationUpdate(status="deprecated"),
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
                db,
                nid,
                new_source,
                new_target,
                rel.relation_type,
            )
            if existing is not None and str(existing.id) != str(rel.id):
                # 合并描述到已有边，标记当前边为 deprecated
                merged_desc = merge_text_field(existing.description, rel.description)
                if merged_desc != (existing.description or ""):
                    await self._relation_repo.update(
                        db,
                        existing.id,
                        EntityRelationUpdate(description=merged_desc),
                    )
                await self._relation_repo.update(
                    db,
                    rel.id,
                    EntityRelationUpdate(status="deprecated"),
                )
                deduplicated += 1
            else:
                # 重定向
                await self._relation_repo.update_endpoint(
                    db,
                    rel.id,
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
            # candidate 有 Character 而 target 没有：直接迁移 Character 行
            migrated = await char_repo.migrate_entity_id(db, cid, tid)
            return migrated

        # 合并别名
        target_aliases: list[dict] = list(target_char.aliases or [])
        existing_alias_texts: set[str] = {
            a.get("alias", "").strip() if isinstance(a, dict) else str(a).strip()
            for a in target_aliases
        }
        for alias in candidate_char.aliases or []:
            if isinstance(alias, dict):
                text = alias.get("alias", "").strip()
            else:
                text = str(alias).strip()
            if text and text not in existing_alias_texts:
                target_aliases.append(alias)
                existing_alias_texts.add(text)

        await char_repo.update(
            db,
            tid,
            CharacterUpdate(
                aliases=target_aliases,
                appearance=merge_text_field(
                    target_char.appearance,
                    candidate_char.appearance,
                ),
                personality=merge_text_field(
                    target_char.personality,
                    candidate_char.personality,
                ),
                desire=merge_text_field(
                    target_char.desire,
                    candidate_char.desire,
                ),
                fear=merge_text_field(
                    target_char.fear,
                    candidate_char.fear,
                ),
                secret=merge_text_field(
                    target_char.secret,
                    candidate_char.secret,
                ),
                weakness=merge_text_field(
                    target_char.weakness,
                    candidate_char.weakness,
                ),
                current_goal=merge_text_field(
                    target_char.current_goal,
                    candidate_char.current_goal,
                ),
                relationship_summary=merge_text_field(
                    target_char.relationship_summary,
                    candidate_char.relationship_summary,
                ),
                meta={**candidate_char.meta, **target_char.meta},
            ),
        )

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
            conflicts.append(
                {
                    "field": field,
                    "canonical_value": canonical_val,
                    "candidate_value": candidate_val,
                    "candidate_id": str(candidate.id),
                    "resolved_at": datetime.now(UTC).isoformat(),
                }
            )

        if not conflicts:
            return 0

        target_meta = dict(target_json.get("meta", {}))
        existing_notes = list(target_meta.get("conflict_notes", []))
        existing_notes.extend(conflicts)
        target_meta["conflict_notes"] = existing_notes

        merged_json = dict(target_json)
        merged_json["meta"] = target_meta
        await self._entity_repo.update(
            db,
            target.id,
            CoreEntityUpdate(
                content_json=merged_json,
            ),
        )
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
