from __future__ import annotations

import json
import logging
from collections import defaultdict
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import DomainError, ValidationError
from infrastructure.llm.agent_step_harness import run_managed_structured
from infrastructure.llm.client import LLMClient
from infrastructure.llm.schemas import LLMCallRequest, LLMMessage
from modules.world.models import CoreEntity
from modules.world.repositories import CoreEntityRepository
from modules.world.schemas import EntityFusionApplyItem
from modules.world.services.common import normalize_name, parse_uuid
from modules.world.services.core.dedup_service import EntityDedupService
from modules.world.services.core.entity_alias_service import EntityAliasService

logger = logging.getLogger(__name__)


def _service_error_detail(exc: Exception) -> str | None:
    if isinstance(exc, DomainError):
        return exc.message
    if exc.__class__.__module__.startswith("fastapi") and hasattr(exc, "detail"):
        return str(exc.detail)
    return None


class EntityFusionDecision(BaseModel):
    action: Literal["merge", "alias_only", "keep_separate", "needs_review"] = (
        "needs_review"
    )
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    reason: str = ""
    alias: str | None = None
    recommended_primary_side: Literal["source", "target"] = "target"


class WorldEntityFusionService:
    """Generate and apply user-confirmed world entity fusion suggestions."""

    def __init__(
        self,
        *,
        entity_repo: CoreEntityRepository | None = None,
        dedup_service: EntityDedupService | None = None,
        alias_service: EntityAliasService | None = None,
        llm_client: LLMClient | None = None,
    ) -> None:
        self._entity_repo = entity_repo or CoreEntityRepository()
        self._dedup = dedup_service or EntityDedupService()
        self._alias_service = alias_service or EntityAliasService(self._entity_repo)
        self._llm_client = llm_client

    async def suggest(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        entity_type: str | None = None,
        status: str | None = None,
        limit: int = 200,
        max_suggestions: int = 50,
        progress_callback: Any | None = None,
    ) -> dict[str, Any]:
        if self._llm_client is None:
            from modules.project.facade import open_project_llm_client

            async with open_project_llm_client(db, novel_id) as client:
                return await WorldEntityFusionService(
                    entity_repo=self._entity_repo,
                    dedup_service=self._dedup,
                    alias_service=self._alias_service,
                    llm_client=client,
                ).suggest(
                    db,
                    novel_id=novel_id,
                    entity_type=entity_type,
                    status=status,
                    limit=limit,
                    max_suggestions=max_suggestions,
                    progress_callback=progress_callback,
                )
        nid = parse_uuid(novel_id, "novel_id")
        statuses = [status] if status else ["candidate", "draft", "canonical"]
        entities = await self._entity_repo.get_by_type_and_status(
            db,
            nid,
            entity_type=entity_type,
            statuses=statuses,
            limit=limit,
        )
        pairs = await self._candidate_pairs(
            db,
            novel_id=novel_id,
            entities=entities,
            max_pairs=max_suggestions * 3,
        )
        suggestions: list[dict[str, Any]] = []
        for index, (source, target, match) in enumerate(pairs):
            if len(suggestions) >= max_suggestions:
                break
            evidence = (
                _entity_summary_evidence(source, target)
                if match.get("match_method") == "summary_overlap"
                else await self._evidence(db, novel_id, source, target)
            )
            decision = await self._decide(source, target, match, evidence)
            if decision.action in {"keep_separate"}:
                continue
            primary = source if decision.recommended_primary_side == "source" else target
            suggestions.append(
                {
                    "action": decision.action,
                    "source_entity_id": str(source.id),
                    "source_entity_name": source.name,
                    "source_status": source.status,
                    "target_entity_id": str(target.id),
                    "target_entity_name": target.name,
                    "target_status": target.status,
                    "recommended_primary_entity_id": str(primary.id),
                    "recommended_primary_entity_name": primary.name,
                    "entity_type": source.entity_type,
                    "confidence": round(decision.confidence, 3),
                    "reason": decision.reason[:500],
                    "alias": decision.alias or source.name,
                    "match_method": match.get("match_method"),
                    "evidence_anchors": evidence,
                    "requires_canonical_confirmation": (
                        source.status == "canonical" and target.status == "canonical"
                    ),
                }
            )
            if progress_callback is not None and pairs:
                progress_callback(min(0.95, (index + 1) / len(pairs)))
        return {
            "task_type": "world_entity_fusion_suggestions",
            "novel_id": novel_id,
            "total_entities_scanned": len(entities),
            "candidate_pair_count": len(pairs),
            "suggestion_count": len(suggestions),
            "suggestions": suggestions,
            "summary": f"生成 {len(suggestions)} 条世界对象合并建议",
        }

    async def apply(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        confirmed: bool,
        suggestions: list[EntityFusionApplyItem],
    ) -> dict[str, Any]:
        if not confirmed:
            raise ValidationError("confirmed=true is required")

        applied = 0
        skipped = 0
        results: list[dict[str, Any]] = []
        warnings: list[str] = []
        nid = parse_uuid(novel_id, "novel_id")
        entity_ids = list(
            dict.fromkeys(
                [
                    parse_uuid(item.source_entity_id, "source_entity_id")
                    for item in suggestions
                ]
                + [
                    parse_uuid(item.target_entity_id, "target_entity_id")
                    for item in suggestions
                ]
            )
        )
        entities_by_id = {
            entity.id: entity
            for entity in await self._entity_repo.get_by_ids(db, nid, entity_ids)
        }

        for item in suggestions:
            source = entities_by_id.get(
                parse_uuid(item.source_entity_id, "source_entity_id")
            )
            target = entities_by_id.get(
                parse_uuid(item.target_entity_id, "target_entity_id")
            )
            if (
                source is None
                or target is None
                or source.novel_id != nid
                or target.novel_id != nid
            ):
                skipped += 1
                warnings.append("跳过不存在或跨项目的对象建议")
                continue
            if source.id == target.id:
                skipped += 1
                warnings.append(f"跳过自合并：{source.name}")
                continue

            if item.action == "alias_only":
                alias = (item.alias or source.name).strip()
                if not alias:
                    skipped += 1
                    warnings.append(f"跳过空别名：{source.name}")
                    continue
                try:
                    if source.status == "canonical":
                        if not item.allow_canonical_alias:
                            skipped += 1
                            warnings.append(
                                f"需要二次确认才能将已采用对象设为别名：{source.name}"
                            )
                            continue
                        result = await self._alias_service.resolve_candidate_as_alias(
                            db,
                            novel_id,
                            str(source.id),
                            target_entity_id=str(target.id),
                            alias=alias,
                            allow_canonical_source=True,
                        )
                    else:
                        result = await self._alias_service.create_alias(
                            db,
                            novel_id,
                            str(target.id),
                            alias,
                            "alias",
                        )
                    applied += 1
                    results.append({"action": "alias_only", **result})
                except Exception as exc:
                    detail = _service_error_detail(exc)
                    if detail is None:
                        raise
                    skipped += 1
                    warnings.append(detail)
                continue

            if source.status == "canonical" and target.status == "canonical":
                if not item.allow_canonical_merge:
                    skipped += 1
                    warnings.append(f"需要二次确认才能合并已采用对象：{source.name}")
                    continue
                allow_canonical = True
            else:
                allow_canonical = item.allow_canonical_merge

            try:
                result = await self._dedup.merge_candidate_into_entity(
                    db,
                    novel_id,
                    str(source.id),
                    str(target.id),
                    allow_canonical_source=allow_canonical,
                )
            except Exception as exc:
                detail = _service_error_detail(exc)
                if detail is None:
                    raise
                skipped += 1
                warnings.append(detail)
                continue
            applied += 1
            results.append(
                {
                    "action": "merge",
                    "source_entity_id": result.candidate_entity_id,
                    "target_entity_id": result.target_entity_id,
                    "aliases_inherited": result.aliases_inherited,
                    "relations_migrated": result.relations_migrated,
                    "relations_deduplicated": result.relations_deduplicated,
                }
            )

        await db.flush()
        return {
            "applied": applied,
            "skipped": skipped,
            "results": results,
            "warnings": warnings,
        }

    async def _candidate_pairs(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        entities: list[CoreEntity],
        max_pairs: int,
    ) -> list[tuple[CoreEntity, CoreEntity, dict[str, Any]]]:
        by_id = {str(entity.id): entity for entity in entities}
        pairs: dict[tuple[str, str], dict[str, Any]] = {}
        paired_sources: set[str] = set()

        exact_groups: dict[tuple[str, str], list[CoreEntity]] = defaultdict(list)
        for entity in entities:
            normalized = normalize_name(entity.name)
            if normalized:
                exact_groups[(entity.entity_type, normalized)].append(entity)

        for group in exact_groups.values():
            if len(group) < 2:
                continue
            target = min(
                group,
                key=lambda item: (
                    _STATUS_RANK.get(item.status, 9),
                    item.name,
                    str(item.id),
                ),
            )
            for source in group:
                if source.id == target.id:
                    continue
                pairs[(str(source.id), str(target.id))] = {
                    "similarity_score": 1.0,
                    "match_method": "normalized_exact_name",
                }
                paired_sources.add(str(source.id))
                if len(pairs) >= max_pairs:
                    break
            if len(pairs) >= max_pairs:
                break

        for source in entities:
            if str(source.id) in paired_sources:
                continue
            aliases = _aliases(source)
            for target in entities:
                if source.id == target.id:
                    continue
                if source.entity_type != target.entity_type:
                    continue
                score, method = _pair_similarity(source, target)
                if score >= 0.84:
                    merge_source, merge_target = _source_target(source, target)
                    pairs[(str(merge_source.id), str(merge_target.id))] = {
                        "similarity_score": score,
                        "match_method": method,
                    }
            for suggestion in await self._dedup.find_similar_entities(
                db,
                novel_id,
                source.name,
                aliases=aliases,
                entity_type=source.entity_type,
            ):
                target = by_id.get(suggestion.existing_entity_id)
                if target is None or target.id == source.id:
                    continue
                merge_source, merge_target = _source_target(source, target)
                pairs[(str(merge_source.id), str(merge_target.id))] = {
                    "similarity_score": suggestion.similarity_score,
                    "match_method": suggestion.match_method,
                }
            if len(pairs) >= max_pairs:
                break

        ordered = sorted(
            pairs.items(),
            key=lambda item: item[1].get("similarity_score", 0),
            reverse=True,
        )
        return [
            (by_id[source_id], by_id[target_id], match)
            for (source_id, target_id), match in ordered[:max_pairs]
            if source_id in by_id and target_id in by_id
        ]

    async def _evidence(
        self,
        db: AsyncSession,
        novel_id: str,
        source: CoreEntity,
        target: CoreEntity,
    ) -> list[dict[str, Any]]:
        from modules.context.facade import retrieve_planned_context_evidence

        query = (
            f"{source.name} {target.name} {source.summary or ''} {target.summary or ''}"
        )
        try:
            bundle = await retrieve_planned_context_evidence(
                db,
                novel_id=novel_id,
                task=query[:500],
                retrieval_purpose="world_fusion",
                consumer_action="world.entity_fusion",
                content_mode="canonical",
                entity_ids=[str(source.id), str(target.id)],
                top_k=5,
            )
        except Exception:
            return [
                {
                    "source_type": "entity_summary",
                    "source_entity_id": str(source.id),
                    "target_entity_id": str(target.id),
                    "snippet": _clip(f"{source.summary or ''}\n{target.summary or ''}"),
                }
            ]
        hits = list(bundle.rag_chunks or [])
        if not hits:
            return [
                {
                    "source_type": "entity_summary",
                    "source_entity_id": str(source.id),
                    "target_entity_id": str(target.id),
                    "snippet": _clip(f"{source.summary or ''}\n{target.summary or ''}"),
                }
            ]
        return [
            {
                "source_type": "manuscript_evidence",
                "source_ref": hit.get("source_ref"),
                "chapter_index": hit.get("chapter_index"),
                "scene_refs": hit.get("scene_refs") or [],
                "snippet": _clip(str(hit.get("text") or "")),
            }
            for hit in hits[:5]
        ]

    async def _decide(
        self,
        source: CoreEntity,
        target: CoreEntity,
        match: dict[str, Any],
        evidence: list[dict[str, Any]],
    ) -> EntityFusionDecision:
        deterministic = _deterministic_decision(source, target, match)
        if deterministic.action == "merge" and deterministic.confidence >= 0.98:
            return deterministic
        if deterministic.action in {"keep_separate", "needs_review", "alias_only"}:
            return deterministic

        client = self._llm_client
        if client is None:  # pragma: no cover - suggest() always manages the client.
            raise RuntimeError("project LLM client is required")
        payload = {
            "source": _entity_payload(source),
            "target": _entity_payload(target),
            "match": match,
            "evidence": evidence[:5],
        }
        try:
            return await run_managed_structured(
                client,
                LLMCallRequest(
                    model=client.model_name,
                    messages=[
                        LLMMessage(
                            role="system",
                            content=(
                                "你判断两个长篇小说世界对象是否应合并。只输出 JSON，"
                                "action 为 merge、alias_only、keep_separate 或 "
                                "needs_review。recommended_primary_side 必须是 source "
                                "或 target，表示建议保留/登记别名到哪个主体；不确定时选 "
                                "target。不要创造新对象。"
                            ),
                        ),
                        LLMMessage(
                            role="user",
                            content=json.dumps(payload, ensure_ascii=False),
                        ),
                    ],
                    temperature=0.1,
                    response_format={"type": "json_object"},
                ),
                EntityFusionDecision,
                step_name="world.entity_fusion.decision.structured",
                max_fix_attempts=1,
            )
        except Exception as exc:
            logger.warning("World entity fusion LLM failed: %s", exc)
            return deterministic


def _aliases(entity: CoreEntity) -> list[str]:
    result: list[str] = []
    for item in (entity.content_json or {}).get("aliases", []):
        if isinstance(item, str):
            result.append(item)
        elif isinstance(item, dict) and item.get("alias"):
            result.append(str(item["alias"]))
    return result


def _lexical_similarity(left: CoreEntity, right: CoreEntity) -> tuple[float, str]:
    left_name = normalize_name(left.name)
    right_name = normalize_name(right.name)
    if left_name == right_name:
        return 1.0, "normalized_exact_name"
    left_aliases = {normalize_name(alias) for alias in _aliases(left)}
    right_aliases = {normalize_name(alias) for alias in _aliases(right)}
    if left_name in right_aliases or right_name in left_aliases:
        return 0.99, "alias_name_match"
    if left_name and right_name and (left_name in right_name or right_name in left_name):
        return 0.88, "substring_name"
    return 0.0, "none"


def _pair_similarity(left: CoreEntity, right: CoreEntity) -> tuple[float, str]:
    lexical_score, lexical_method = _lexical_similarity(left, right)
    if lexical_method in {"normalized_exact_name", "alias_name_match"}:
        return lexical_score, lexical_method
    summary_score = _summary_similarity(left.summary, right.summary)
    if summary_score > lexical_score:
        return summary_score, "summary_overlap"
    return lexical_score, lexical_method


def _summary_similarity(left: str | None, right: str | None) -> float:
    left_text = _normalize_summary_text(left)
    right_text = _normalize_summary_text(right)
    if len(left_text) < 24 or len(right_text) < 24:
        return 0.0
    left_grams = _char_ngrams(left_text, 2)
    right_grams = _char_ngrams(right_text, 2)
    if not left_grams or not right_grams:
        return 0.0
    intersection = len(left_grams & right_grams)
    containment = intersection / min(len(left_grams), len(right_grams))
    jaccard = intersection / len(left_grams | right_grams)
    if containment >= 0.92 and jaccard >= 0.7:
        return 0.92
    if containment >= 0.84 and jaccard >= 0.62:
        return 0.84
    return 0.0


def _normalize_summary_text(value: str | None) -> str:
    return "".join(
        char
        for char in (value or "").strip().lower()
        if char.isalnum() or "\u4e00" <= char <= "\u9fff"
    )


def _char_ngrams(value: str, size: int) -> set[str]:
    if len(value) < size:
        return set()
    return {value[index : index + size] for index in range(len(value) - size + 1)}


def _deterministic_decision(
    source: CoreEntity,
    target: CoreEntity,
    match: dict[str, Any],
) -> EntityFusionDecision:
    score = float(match.get("similarity_score") or 0.0)
    method = str(match.get("match_method") or "")
    if method in {"normalized_exact_name", "exact_name"} or score >= 0.98:
        if "alias" in method:
            if source.status in {"candidate", "draft"}:
                return EntityFusionDecision(
                    action="merge",
                    confidence=max(score, 0.98),
                    reason="别名命中且来源仍待处理，建议合并到更稳定对象。",
                    alias=source.name,
                )
            return EntityFusionDecision(
                action="needs_review",
                confidence=max(score, 0.9),
                reason="已采用对象存在别名命中，需要人工确认是否合并或仅保留别名。",
                alias=source.name,
            )
        return EntityFusionDecision(
            action="merge",
            confidence=max(score, 0.98),
            reason="名称或别名高度一致。",
            alias=source.name,
        )
    if "alias" in method or score >= 0.9:
        return EntityFusionDecision(
            action="alias_only",
            confidence=max(score, 0.9),
            reason="更像别名关系，建议先登记别名。",
            alias=source.name,
        )
    if score >= 0.84:
        return EntityFusionDecision(
            action="needs_review",
            confidence=score,
            reason="名称相似但证据不足，需要人工复核。",
            alias=source.name,
        )
    return EntityFusionDecision(
        action="keep_separate",
        confidence=1.0 - score,
        reason="名称和证据不足以支持合并。",
    )


_STATUS_RANK = {"canonical": 0, "draft": 1, "candidate": 2}


def _source_target(left: CoreEntity, right: CoreEntity) -> tuple[CoreEntity, CoreEntity]:
    left_key = (_STATUS_RANK.get(left.status, 9), left.name, str(left.id))
    right_key = (_STATUS_RANK.get(right.status, 9), right.name, str(right.id))
    target, source = (left, right) if left_key <= right_key else (right, left)
    return source, target


def _entity_payload(entity: CoreEntity) -> dict[str, Any]:
    return {
        "id": str(entity.id),
        "name": entity.name,
        "entity_type": entity.entity_type,
        "status": entity.status,
        "summary": entity.summary,
        "aliases": _aliases(entity),
    }


def _entity_summary_evidence(
    source: CoreEntity,
    target: CoreEntity,
) -> list[dict[str, Any]]:
    return [
        {
            "source_type": "entity_summary",
            "source_entity_id": str(source.id),
            "target_entity_id": str(target.id),
            "snippet": _clip(f"{source.summary or ''}\n{target.summary or ''}"),
        }
    ]


def _clip(value: str | None, limit: int = 600) -> str:
    return (value or "").strip()[:limit]
