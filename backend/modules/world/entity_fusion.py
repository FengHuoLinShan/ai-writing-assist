from __future__ import annotations

import hashlib
import json
import logging
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import DomainError, ValidationError
from infrastructure.llm.agent_step_harness import run_managed_structured
from infrastructure.llm.client import LLMClient
from infrastructure.llm.schemas import LLMCallRequest, LLMMessage
from modules.world.models import Character, CoreEntity, EntityRelation, Event
from modules.world.repositories import CoreEntityRepository
from modules.world.schemas import EntityFusionApplyItem
from modules.world.services.common import normalize_name, parse_uuid
from modules.world.services.core.dedup_service import EntityDedupService
from modules.world.services.core.entity_alias_service import EntityAliasService

logger = logging.getLogger(__name__)

_TASK_REVALIDATION_BATCH_SIZE = 12


@dataclass(frozen=True)
class _FusionEntityDTO:
    """Detached entity fields used after the task releases its read transaction."""

    id: str
    name: str
    entity_type: str
    status: str
    summary: str | None
    aliases: tuple[str, ...]


@dataclass(frozen=True)
class _PreparedFusionPair:
    """Plain, fingerprinted inputs for one transaction-free decision."""

    source: _FusionEntityDTO
    target: _FusionEntityDTO
    similarity_score: float
    match_method: str
    evidence: tuple[dict[str, Any], ...]
    source_snapshot: dict[str, Any]
    target_snapshot: dict[str, Any]
    source_semantic_fingerprint: str
    target_semantic_fingerprint: str
    source_execution_fingerprint: str
    target_execution_fingerprint: str
    pair_fingerprint: str
    disposition_fingerprint: str

    @property
    def match(self) -> dict[str, Any]:
        return {
            "similarity_score": self.similarity_score,
            "match_method": self.match_method,
        }


@dataclass(frozen=True)
class _FusionTaskPlan:
    novel_id: str
    total_entities_scanned: int
    candidate_pair_count: int
    max_suggestions: int
    pairs: tuple[_PreparedFusionPair, ...]


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
        exclusions: list[dict[str, Any]] | None = None,
        progress_callback: Any | None = None,
        group_before_budget: bool = False,
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
                    exclusions=exclusions,
                    progress_callback=progress_callback,
                    group_before_budget=group_before_budget,
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
            max_pairs=None if group_before_budget else max_suggestions * 3,
        )
        fingerprint_inputs = await self._load_fingerprint_inputs(db, nid, entities)
        fingerprint_cache: dict[str, dict[str, Any]] = {}

        async def fingerprints(entity: CoreEntity) -> dict[str, Any]:
            key = str(entity.id)
            if key not in fingerprint_cache:
                fingerprint_cache[key] = await self._entity_fingerprints(
                    db,
                    nid,
                    entity,
                    prefetched=fingerprint_inputs,
                )
            return fingerprint_cache[key]

        active_exclusions = {
            (
                str(item.get("left_asset_id")),
                str(item.get("right_asset_id")),
                str(item.get("left_semantic_fingerprint")),
                str(item.get("right_semantic_fingerprint")),
            )
            for item in exclusions or []
        }
        suggestions: list[dict[str, Any]] = []
        for index, (source, target, match) in enumerate(pairs):
            if not group_before_budget and len(suggestions) >= max_suggestions:
                break
            source_fp = await fingerprints(source)
            target_fp = await fingerprints(target)
            left, right = sorted((str(source.id), str(target.id)))
            left_fp, right_fp = (
                (source_fp, target_fp)
                if left == str(source.id)
                else (target_fp, source_fp)
            )
            exclusion_key = (
                left,
                right,
                left_fp["semantic_fingerprint"],
                right_fp["semantic_fingerprint"],
            )
            if exclusion_key in active_exclusions:
                continue
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
                    "source_snapshot": _entity_snapshot(source, source_fp),
                    "target_snapshot": _entity_snapshot(target, target_fp),
                    "source_semantic_fingerprint": source_fp["semantic_fingerprint"],
                    "target_semantic_fingerprint": target_fp["semantic_fingerprint"],
                    "source_execution_fingerprint": source_fp["execution_fingerprint"],
                    "target_execution_fingerprint": target_fp["execution_fingerprint"],
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

    async def suggest_for_task(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        entity_type: str | None = None,
        status: str | None = None,
        limit: int = 200,
        max_suggestions: int = 50,
        checkpoint_callback: Callable[[dict[str, Any], float], None],
        llm_execution_snapshot: dict[str, Any] | None = None,
        snapshot_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        """Generate suggestions without holding a transaction during LLM calls.

        This commit-owning entry point is intentionally limited to a fenced
        TaskWorker handler session.  The normal ``suggest`` method keeps caller
        transaction ownership and remains suitable for ordinary services.
        """
        from infrastructure.tasks.facade import require_task_checkpoint_session
        from modules.project.facade import (
            build_project_llm_execution_snapshot,
            create_project_snapshot_llm_client,
            require_active_project,
            restore_project_llm_execution_settings,
        )

        require_task_checkpoint_session(db)
        await require_active_project(db, novel_id)
        snapshot = llm_execution_snapshot
        if self._llm_client is None and not snapshot:
            if snapshot_callback is None:
                raise RuntimeError(
                    "task LLM snapshot callback is required before external I/O"
                )
            snapshot = await build_project_llm_execution_snapshot(db, novel_id)
            snapshot_callback(snapshot)
        plan = await self._prepare_task_scan(
            db,
            novel_id=novel_id,
            entity_type=entity_type,
            status=status,
            limit=limit,
            max_suggestions=max_suggestions,
        )

        if self._llm_client is not None:
            return await self._decide_task_plan(
                db,
                plan,
                checkpoint_callback=checkpoint_callback,
            )

        if not snapshot:
            raise RuntimeError("project LLM execution snapshot is required")
        # Restore and validate the persisted, secret-free profile while the
        # project guard is still held.  The resulting client is DB-independent.
        project_settings = await restore_project_llm_execution_settings(
            db,
            novel_id,
            snapshot,
        )
        client = create_project_snapshot_llm_client(
            project_settings,
            novel_id=novel_id,
        )
        try:
            runner = WorldEntityFusionService(
                entity_repo=self._entity_repo,
                dedup_service=self._dedup,
                alias_service=self._alias_service,
                llm_client=client,
            )
            return await runner._decide_task_plan(
                db,
                plan,
                checkpoint_callback=checkpoint_callback,
            )
        finally:
            await client.close()

    async def _prepare_task_scan(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        entity_type: str | None,
        status: str | None,
        limit: int,
        max_suggestions: int,
    ) -> _FusionTaskPlan:
        """Copy every post-checkpoint input into detached, JSON-safe values."""
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
        fingerprint_inputs = await self._load_fingerprint_inputs(db, nid, entities)
        fingerprint_cache: dict[str, dict[str, Any]] = {}

        async def fingerprints(entity: CoreEntity) -> dict[str, Any]:
            key = str(entity.id)
            if key not in fingerprint_cache:
                fingerprint_cache[key] = await self._entity_fingerprints(
                    db,
                    nid,
                    entity,
                    prefetched=fingerprint_inputs,
                )
            return fingerprint_cache[key]

        prepared: list[_PreparedFusionPair] = []
        for source, target, raw_match in pairs:
            source_fp = await fingerprints(source)
            target_fp = await fingerprints(target)
            # The task-only seam must reach its first lease-fenced commit before
            # any provider call.  Context evidence retrieval can invoke both the
            # embedding provider and the optional LLM reranker, so freeze the
            # entity-owned evidence here.  Ordinary suggest() keeps the richer
            # caller-owned RAG evidence path.
            evidence = _entity_summary_evidence(source, target)
            match = _normalized_match(raw_match)
            source_dto = _detached_entity(source)
            target_dto = _detached_entity(target)
            prepared.append(
                _PreparedFusionPair(
                    source=source_dto,
                    target=target_dto,
                    similarity_score=match["similarity_score"],
                    match_method=match["match_method"],
                    evidence=tuple(_json_copy(evidence)),
                    source_snapshot=_json_copy(_entity_snapshot(source, source_fp)),
                    target_snapshot=_json_copy(_entity_snapshot(target, target_fp)),
                    source_semantic_fingerprint=source_fp["semantic_fingerprint"],
                    target_semantic_fingerprint=target_fp["semantic_fingerprint"],
                    source_execution_fingerprint=source_fp["execution_fingerprint"],
                    target_execution_fingerprint=target_fp["execution_fingerprint"],
                    pair_fingerprint=_pair_fingerprint(
                        source_dto,
                        target_dto,
                        match,
                    ),
                    disposition_fingerprint=_disposition_fingerprint(
                        source_dto,
                        target_dto,
                    ),
                )
            )

        return _FusionTaskPlan(
            novel_id=novel_id,
            total_entities_scanned=len(entities),
            candidate_pair_count=len(pairs),
            max_suggestions=max_suggestions,
            pairs=tuple(prepared),
        )

    async def _decide_task_plan(
        self,
        db: AsyncSession,
        plan: _FusionTaskPlan,
        *,
        checkpoint_callback: Callable[[dict[str, Any], float], None],
    ) -> dict[str, Any]:
        from modules.project.facade import require_active_project

        suggestions: list[dict[str, Any]] = []
        stale_pairs: list[dict[str, str]] = []
        processed = 0
        initial = self._task_result(
            plan,
            suggestions=suggestions,
            processed_pair_count=processed,
            stale_pairs=stale_pairs,
        )
        checkpoint_callback(initial, 0.15)
        # This is the key lease/project-fenced boundary before external I/O.
        await db.commit()

        for offset in range(0, len(plan.pairs), _TASK_REVALIDATION_BATCH_SIZE):
            if len(suggestions) >= plan.max_suggestions:
                break
            batch = plan.pairs[offset : offset + _TASK_REVALIDATION_BATCH_SIZE]
            decisions: list[tuple[_PreparedFusionPair, EntityFusionDecision]] = []
            for pair in batch:
                if db.in_transaction():
                    raise RuntimeError(
                        "world fusion task cannot call the LLM inside a transaction"
                    )
                decision = await self._decide(
                    pair.source,
                    pair.target,
                    pair.match,
                    list(pair.evidence),
                )
                decisions.append((pair, decision))
                processed += 1

            # Every persistence batch starts in deletion-safe lock order.
            await require_active_project(db, plan.novel_id)
            fresh, stale = await self._revalidate_task_batch(
                db,
                novel_id=plan.novel_id,
                decisions=decisions,
            )
            stale_pairs.extend(stale)
            remaining = plan.max_suggestions - len(suggestions)
            suggestions.extend(fresh[:remaining])
            result = self._task_result(
                plan,
                suggestions=suggestions,
                processed_pair_count=processed,
                stale_pairs=stale_pairs,
            )
            progress = 0.15 + 0.85 * min(1.0, processed / len(plan.pairs))
            checkpoint_callback(result, progress)
            # Revalidation and the detached task result become durable under the
            # same lease fence, then all world/project locks are released.
            await db.commit()

        result = self._task_result(
            plan,
            suggestions=suggestions,
            processed_pair_count=processed,
            stale_pairs=stale_pairs,
        )
        checkpoint_callback(result, 1.0)
        return result

    async def _revalidate_task_batch(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        decisions: list[tuple[_PreparedFusionPair, EntityFusionDecision]],
    ) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
        """Return only decisions whose pair, assets, and disposition stayed fresh."""
        candidate_decisions = [
            (pair, decision)
            for pair, decision in decisions
            if decision.action != "keep_separate"
        ]
        if not candidate_decisions:
            return [], []

        nid = parse_uuid(novel_id, "novel_id")
        entity_ids = list(
            dict.fromkeys(
                parse_uuid(entity_id, "entity_id")
                for pair, _decision in candidate_decisions
                for entity_id in (pair.source.id, pair.target.id)
            )
        )
        stmt = (
            select(CoreEntity)
            .where(
                CoreEntity.novel_id == nid,
                CoreEntity.id.in_(entity_ids),
            )
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
        current_entities = list((await db.execute(stmt)).scalars().all())
        current_by_id = {str(entity.id): entity for entity in current_entities}
        fingerprint_inputs = await self._load_fingerprint_inputs(
            db,
            nid,
            current_entities,
            refresh=True,
            lock=True,
        )
        fingerprints = {
            str(entity.id): await self._entity_fingerprints(
                db,
                nid,
                entity,
                prefetched=fingerprint_inputs,
            )
            for entity in current_entities
        }

        fresh: list[dict[str, Any]] = []
        stale: list[dict[str, str]] = []
        for pair, decision in candidate_decisions:
            source = current_by_id.get(pair.source.id)
            target = current_by_id.get(pair.target.id)
            reason: str | None = None
            if source is None or target is None:
                reason = "asset_missing"
            else:
                source_fp = fingerprints[pair.source.id]
                target_fp = fingerprints[pair.target.id]
                if (
                    source_fp["semantic_fingerprint"] != pair.source_semantic_fingerprint
                    or source_fp["execution_fingerprint"]
                    != pair.source_execution_fingerprint
                    or target_fp["semantic_fingerprint"]
                    != pair.target_semantic_fingerprint
                    or target_fp["execution_fingerprint"]
                    != pair.target_execution_fingerprint
                ):
                    reason = "asset_changed"
                elif (
                    _disposition_fingerprint(source, target)
                    != pair.disposition_fingerprint
                ):
                    reason = "disposition_changed"
                else:
                    current_match = await self._current_pair_match(
                        db,
                        novel_id=novel_id,
                        source=source,
                        target=target,
                    )
                    if (
                        current_match is None
                        or _pair_fingerprint(
                            source,
                            target,
                            current_match,
                        )
                        != pair.pair_fingerprint
                    ):
                        reason = "pair_changed"

            if reason is not None:
                stale.append(
                    {
                        "source_entity_id": pair.source.id,
                        "target_entity_id": pair.target.id,
                        "reason": reason,
                    }
                )
                continue
            fresh.append(_task_suggestion(pair, decision))
        return fresh, stale

    async def _current_pair_match(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        source: CoreEntity,
        target: CoreEntity,
    ) -> dict[str, Any] | None:
        if source.entity_type != target.entity_type:
            return None
        current_source, current_target = _source_target(source, target)
        if current_source.id != source.id or current_target.id != target.id:
            return None

        score, method = _pair_similarity(source, target)
        if score >= 0.84:
            return _normalized_match({"similarity_score": score, "match_method": method})

        for query, expected_id in ((source, target.id), (target, source.id)):
            matches = await self._dedup.find_similar_entities(
                db,
                novel_id,
                query.name,
                aliases=_aliases(query),
                entity_type=query.entity_type,
            )
            match = next(
                (
                    item
                    for item in matches
                    if str(item.existing_entity_id) == str(expected_id)
                ),
                None,
            )
            if match is not None:
                return _normalized_match(
                    {
                        "similarity_score": match.similarity_score,
                        "match_method": match.match_method,
                    }
                )
        return None

    @staticmethod
    def _task_result(
        plan: _FusionTaskPlan,
        *,
        suggestions: list[dict[str, Any]],
        processed_pair_count: int,
        stale_pairs: list[dict[str, str]],
    ) -> dict[str, Any]:
        warnings = []
        if stale_pairs:
            warnings.append(f"{len(stale_pairs)} 组对象在扫描期间发生变化，已跳过")
        return {
            "task_type": "world_entity_fusion_suggestions",
            "novel_id": plan.novel_id,
            "total_entities_scanned": plan.total_entities_scanned,
            "candidate_pair_count": plan.candidate_pair_count,
            "processed_pair_count": processed_pair_count,
            "suggestion_count": len(suggestions),
            "skipped_stale_count": len(stale_pairs),
            "stale_pairs": list(stale_pairs),
            "suggestions": list(suggestions),
            "warnings": warnings,
            "summary": f"生成 {len(suggestions)} 条世界对象合并建议",
        }

    async def apply_group(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        primary_entity_id: str,
        operations: list[dict[str, Any]],
        validate_only: bool = False,
        execution_fingerprints_prevalidated: bool = False,
    ) -> list[dict[str, Any]]:
        """Strict group apply. Any error is raised for the caller savepoint."""
        if validate_only and execution_fingerprints_prevalidated:
            raise ValidationError("Invalid group validation mode")
        nid = parse_uuid(novel_id, "novel_id")
        ids = [parse_uuid(primary_entity_id, "primary_entity_id")]
        ids.extend(
            parse_uuid(item["source_entity_id"], "source_entity_id")
            for item in operations
        )
        unique_ids = list(dict.fromkeys(ids))
        if validate_only:
            entity_stmt = (
                select(CoreEntity)
                .where(
                    CoreEntity.novel_id == nid,
                    CoreEntity.id.in_(unique_ids),
                )
                .with_for_update(read=True)
            )
            entities = list((await db.execute(entity_stmt)).scalars().all())
        else:
            entities = await self._entity_repo.get_by_ids(db, nid, unique_ids)
        by_id = {str(item.id): item for item in entities}
        target = by_id.get(primary_entity_id)
        if target is None:
            raise ValidationError("Primary entity not found")
        if len({item["source_entity_id"] for item in operations}) != len(operations):
            raise ValidationError("Duplicate source entity in group")

        fingerprint_inputs = await self._load_fingerprint_inputs(
            db,
            nid,
            entities,
            lock=validate_only,
        )
        fingerprints_by_id = {
            entity.id: await self._entity_fingerprints(
                db,
                nid,
                entity,
                prefetched=fingerprint_inputs,
            )
            for entity in entities
        }

        prepared: list[tuple[dict[str, Any], CoreEntity]] = []
        for item in operations:
            source = by_id.get(str(item["source_entity_id"]))
            if source is None or source.id == target.id:
                raise ValidationError("Invalid source entity")
            if source.entity_type != target.entity_type:
                raise ValidationError("Entity fusion group must use one entity type")
            source_fp = fingerprints_by_id[source.id]
            target_fp = fingerprints_by_id[target.id]
            if not execution_fingerprints_prevalidated and (
                source_fp["execution_fingerprint"]
                != item.get("expected_source_execution_fingerprint")
                or target_fp["execution_fingerprint"]
                != item.get("expected_target_execution_fingerprint")
            ):
                raise ValidationError("stale_suggestion")
            action = str(item.get("action") or "")
            if action not in {"merge", "alias_only", "keep_separate"}:
                raise ValidationError("Unsupported world group action")
            if (
                action == "merge"
                and source.status == "canonical"
                and not item.get("allow_canonical_merge")
            ):
                raise ValidationError("confirmation_required")
            if (
                action == "alias_only"
                and source.status == "canonical"
                and not item.get("allow_canonical_alias")
            ):
                raise ValidationError("confirmation_required")
            prepared.append((item, source))

        if validate_only:
            return []

        results: list[dict[str, Any]] = []
        for item, source in prepared:
            if item["action"] == "keep_separate":
                continue
            if item["action"] == "alias_only":
                result = await self._alias_service.resolve_candidate_as_alias(
                    db,
                    novel_id,
                    str(source.id),
                    target_entity_id=str(target.id),
                    alias=str(item.get("alias") or source.name),
                    allow_canonical_source=source.status == "canonical",
                )
                results.append({"action": "alias_only", **result})
                continue
            result = await self._dedup.merge_candidate_into_entity(
                db,
                novel_id,
                str(source.id),
                str(target.id),
                allow_canonical_source=source.status == "canonical",
            )
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
        keep_sources = [
            source for item, source in prepared if item["action"] == "keep_separate"
        ]
        if keep_sources:
            await db.refresh(target)
            refreshed_inputs = await self._load_fingerprint_inputs(
                db,
                nid,
                [target, *keep_sources],
            )
            target_fp = await self._entity_fingerprints(
                db,
                nid,
                target,
                prefetched=refreshed_inputs,
            )
            for source in keep_sources:
                await db.refresh(source)
                source_fp = await self._entity_fingerprints(
                    db, nid, source, prefetched=refreshed_inputs
                )
                left, right = sorted((str(source.id), str(target.id)))
                left_fp, right_fp = (
                    (source_fp, target_fp)
                    if left == str(source.id)
                    else (target_fp, source_fp)
                )
                results.append(
                    {
                        "action": "keep_separate",
                        "left_asset_id": left,
                        "right_asset_id": right,
                        "left_semantic_fingerprint": left_fp["semantic_fingerprint"],
                        "right_semantic_fingerprint": right_fp["semantic_fingerprint"],
                    }
                )
        return results

    async def _entity_fingerprints(
        self,
        db: AsyncSession,
        novel_id: Any,
        entity: CoreEntity,
        *,
        prefetched: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        relations = (
            prefetched["relations_by_entity"].get(entity.id, [])
            if prefetched is not None
            else await self._dedup._relation_repo.get_all_for_entity(
                db, novel_id, entity.id
            )
        )
        extension: dict[str, Any] = {}
        if entity.entity_type == "character":
            character = (
                prefetched["characters_by_id"].get(entity.id)
                if prefetched is not None
                else (
                    await db.execute(
                        select(Character).where(
                            Character.entity_id == entity.id,
                            Character.novel_id == novel_id,
                        )
                    )
                ).scalar_one_or_none()
            )
            if character is not None:
                extension["character"] = _mapped_payload(character)
        if entity.entity_type == "event":
            event = (
                prefetched["events_by_id"].get(entity.id)
                if prefetched is not None
                else (
                    await db.execute(
                        select(Event).where(
                            Event.entity_id == entity.id,
                            Event.novel_id == novel_id,
                        )
                    )
                ).scalar_one_or_none()
            )
            if event is not None:
                extension["event"] = _mapped_payload(event)
        semantic = {
            "name": entity.name,
            "entity_type": entity.entity_type,
            "status": entity.status,
            "summary": entity.summary,
            "public_info": entity.public_info,
            "hidden_truth": entity.hidden_truth,
            "content": {
                key: value
                for key, value in (entity.content_json or {}).items()
                if key != "_meta"
            },
            "aliases": sorted(_aliases(entity)),
            "importance": entity.importance,
            "importance_level": entity.importance_level,
            "reveal_level": entity.reveal_level,
            "extension": extension,
        }
        execution = {
            **semantic,
            "public_info": entity.public_info,
            "hidden_truth": entity.hidden_truth,
            "content_json": entity.content_json or {},
            "importance": entity.importance,
            "importance_level": entity.importance_level,
            "reveal_level": entity.reveal_level,
            "relations": sorted(
                (
                    str(item.id),
                    str(item.source_id),
                    str(item.target_id),
                    item.relation_type,
                    item.status,
                    str(item.updated_at or ""),
                )
                for item in relations
            ),
        }
        return {
            "semantic_fingerprint": _hash_payload(semantic),
            "execution_fingerprint": _hash_payload(execution),
            "relation_count": len(relations),
            "extension": extension,
        }

    async def _load_fingerprint_inputs(
        self,
        db: AsyncSession,
        novel_id: Any,
        entities: list[CoreEntity],
        *,
        refresh: bool = False,
        lock: bool = False,
    ) -> dict[str, Any]:
        entity_ids = list(dict.fromkeys(entity.id for entity in entities))
        if refresh or lock:
            relation_stmt = select(EntityRelation).where(
                EntityRelation.novel_id == novel_id,
                or_(
                    EntityRelation.source_id.in_(entity_ids),
                    EntityRelation.target_id.in_(entity_ids),
                ),
            )
            if lock:
                relation_stmt = relation_stmt.with_for_update(read=True)
            if refresh:
                relation_stmt = relation_stmt.execution_options(populate_existing=True)
            relations = list((await db.execute(relation_stmt)).scalars().all())
        else:
            relations = await self._dedup._relation_repo.get_all_for_entities(
                db,
                novel_id,
                entity_ids,
            )
        relations_by_entity: dict[Any, list[Any]] = defaultdict(list)
        requested = set(entity_ids)
        for relation in relations:
            if relation.source_id in requested:
                relations_by_entity[relation.source_id].append(relation)
            if (
                relation.target_id in requested
                and relation.target_id != relation.source_id
            ):
                relations_by_entity[relation.target_id].append(relation)

        character_ids = [
            entity.id for entity in entities if entity.entity_type == "character"
        ]
        event_ids = [entity.id for entity in entities if entity.entity_type == "event"]
        character_stmt = select(Character).where(
            Character.novel_id == novel_id,
            Character.entity_id.in_(character_ids),
        )
        event_stmt = select(Event).where(
            Event.novel_id == novel_id,
            Event.entity_id.in_(event_ids),
        )
        if lock:
            character_stmt = character_stmt.with_for_update(read=True)
            event_stmt = event_stmt.with_for_update(read=True)
        if refresh:
            character_stmt = character_stmt.execution_options(populate_existing=True)
            event_stmt = event_stmt.execution_options(populate_existing=True)
        characters = (
            list((await db.execute(character_stmt)).scalars().all())
            if character_ids
            else []
        )
        events = list((await db.execute(event_stmt)).scalars().all()) if event_ids else []
        return {
            "relations_by_entity": relations_by_entity,
            "characters_by_id": {item.entity_id: item for item in characters},
            "events_by_id": {item.entity_id: item for item in events},
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
        max_pairs: int | None,
    ) -> list[tuple[CoreEntity, CoreEntity, dict[str, Any]]]:
        by_id = {str(entity.id): entity for entity in entities}
        pairs: dict[tuple[str, str], dict[str, Any]] = {}
        paired_sources: set[str] = set()

        def record_pair(
            source: CoreEntity,
            target: CoreEntity,
            match: dict[str, Any],
        ) -> None:
            key = (str(source.id), str(target.id))
            existing = pairs.get(key)
            if existing is None or float(match.get("similarity_score") or 0.0) > float(
                existing.get("similarity_score") or 0.0
            ):
                pairs[key] = match

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
                record_pair(
                    source,
                    target,
                    {
                        "similarity_score": 1.0,
                        "match_method": "normalized_exact_name",
                    },
                )
                paired_sources.add(str(source.id))
                if max_pairs is not None and len(pairs) >= max_pairs:
                    break
            if max_pairs is not None and len(pairs) >= max_pairs:
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
                    record_pair(
                        merge_source,
                        merge_target,
                        {
                            "similarity_score": score,
                            "match_method": method,
                        },
                    )
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
                record_pair(
                    merge_source,
                    merge_target,
                    {
                        "similarity_score": suggestion.similarity_score,
                        "match_method": suggestion.match_method,
                    },
                )
            if max_pairs is not None and len(pairs) >= max_pairs:
                break

        ordered = sorted(
            pairs.items(),
            key=lambda item: item[1].get("similarity_score", 0),
            reverse=True,
        )
        return [
            (by_id[source_id], by_id[target_id], match)
            for (source_id, target_id), match in (
                ordered if max_pairs is None else ordered[:max_pairs]
            )
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
        except SQLAlchemyError:
            # A retrieval database failure is not equivalent to "no evidence";
            # propagating it prevents low-information suggestions from being
            # generated while the persistence layer is unhealthy.
            raise
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
        source: CoreEntity | _FusionEntityDTO,
        target: CoreEntity | _FusionEntityDTO,
        match: dict[str, Any],
        evidence: list[dict[str, Any]],
    ) -> EntityFusionDecision:
        deterministic = _deterministic_decision(source, target, match)
        if deterministic.action == "merge" and deterministic.confidence >= 0.98:
            return deterministic
        if deterministic.action == "keep_separate":
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
            # Provider errors can contain request details.  Keep task/API logs
            # secret-free and let the deterministic result provide degradation.
            logger.warning(
                "World entity fusion LLM failed: %s",
                type(exc).__name__,
            )
            return deterministic


def _detached_entity(entity: CoreEntity) -> _FusionEntityDTO:
    return _FusionEntityDTO(
        id=str(entity.id),
        name=entity.name,
        entity_type=entity.entity_type,
        status=entity.status,
        summary=entity.summary,
        aliases=tuple(_aliases(entity)),
    )


def _json_copy(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def _normalized_match(match: dict[str, Any]) -> dict[str, Any]:
    return {
        "similarity_score": round(float(match.get("similarity_score") or 0.0), 6),
        "match_method": str(match.get("match_method") or ""),
    }


def _pair_fingerprint(
    source: CoreEntity | _FusionEntityDTO,
    target: CoreEntity | _FusionEntityDTO,
    match: dict[str, Any],
) -> str:
    return _hash_payload(
        {
            "asset_ids": sorted((str(source.id), str(target.id))),
            "match": _normalized_match(match),
        }
    )


def _disposition_fingerprint(
    source: CoreEntity | _FusionEntityDTO,
    target: CoreEntity | _FusionEntityDTO,
) -> str:
    current_source, current_target = _source_target(source, target)
    return _hash_payload(
        {
            "source_entity_id": str(current_source.id),
            "source_status": current_source.status,
            "target_entity_id": str(current_target.id),
            "target_status": current_target.status,
            "entity_type": current_source.entity_type,
            "requires_canonical_confirmation": (
                current_source.status == "canonical"
                and current_target.status == "canonical"
            ),
        }
    )


def _task_suggestion(
    pair: _PreparedFusionPair,
    decision: EntityFusionDecision,
) -> dict[str, Any]:
    primary = (
        pair.source if decision.recommended_primary_side == "source" else pair.target
    )
    return {
        "action": decision.action,
        "source_entity_id": pair.source.id,
        "source_entity_name": pair.source.name,
        "source_status": pair.source.status,
        "target_entity_id": pair.target.id,
        "target_entity_name": pair.target.name,
        "target_status": pair.target.status,
        "recommended_primary_entity_id": primary.id,
        "recommended_primary_entity_name": primary.name,
        "entity_type": pair.source.entity_type,
        "source_snapshot": _json_copy(pair.source_snapshot),
        "target_snapshot": _json_copy(pair.target_snapshot),
        "source_semantic_fingerprint": pair.source_semantic_fingerprint,
        "target_semantic_fingerprint": pair.target_semantic_fingerprint,
        "source_execution_fingerprint": pair.source_execution_fingerprint,
        "target_execution_fingerprint": pair.target_execution_fingerprint,
        "confidence": round(decision.confidence, 3),
        "reason": decision.reason[:500],
        "alias": decision.alias or pair.source.name,
        "match_method": pair.match_method,
        "evidence_anchors": _json_copy(list(pair.evidence)),
        "requires_canonical_confirmation": (
            pair.source.status == "canonical" and pair.target.status == "canonical"
        ),
    }


def _aliases(entity: CoreEntity | _FusionEntityDTO) -> list[str]:
    if isinstance(entity, _FusionEntityDTO):
        return list(entity.aliases)
    result: list[str] = []
    for item in (entity.content_json or {}).get("aliases", []):
        if isinstance(item, str):
            result.append(item)
        elif isinstance(item, dict) and item.get("alias"):
            result.append(str(item["alias"]))
    return result


def _lexical_similarity(
    left: CoreEntity | _FusionEntityDTO,
    right: CoreEntity | _FusionEntityDTO,
) -> tuple[float, str]:
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


def _pair_similarity(
    left: CoreEntity | _FusionEntityDTO,
    right: CoreEntity | _FusionEntityDTO,
) -> tuple[float, str]:
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
    source: CoreEntity | _FusionEntityDTO,
    target: CoreEntity | _FusionEntityDTO,
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


def _source_target(
    left: CoreEntity | _FusionEntityDTO,
    right: CoreEntity | _FusionEntityDTO,
) -> tuple[CoreEntity | _FusionEntityDTO, CoreEntity | _FusionEntityDTO]:
    left_key = (_STATUS_RANK.get(left.status, 9), left.name, str(left.id))
    right_key = (_STATUS_RANK.get(right.status, 9), right.name, str(right.id))
    target, source = (left, right) if left_key <= right_key else (right, left)
    return source, target


def _entity_payload(entity: CoreEntity | _FusionEntityDTO) -> dict[str, Any]:
    return {
        "id": str(entity.id),
        "name": entity.name,
        "entity_type": entity.entity_type,
        "status": entity.status,
        "summary": entity.summary,
        "aliases": _aliases(entity),
    }


def _entity_snapshot(entity: CoreEntity, fingerprints: dict[str, Any]) -> dict[str, Any]:
    meta = dict((entity.content_json or {}).get("_meta") or {})
    return {
        "asset_id": str(entity.id),
        "title": entity.name,
        "entity_type": entity.entity_type,
        "status": entity.status,
        "summary": entity.summary or "",
        "public_info": entity.public_info or "",
        "hidden_truth": entity.hidden_truth or "",
        "aliases": _aliases(entity),
        "importance": entity.importance,
        "importance_level": entity.importance_level,
        "reveal_level": entity.reveal_level,
        "source": meta.get("source") or entity.created_by,
        "workflow_id": meta.get("workflow_id"),
        "updated_at": entity.updated_at.isoformat() if entity.updated_at else None,
        "relation_count": fingerprints.get("relation_count", 0),
        "details": fingerprints.get("extension") or {},
    }


def _hash_payload(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _mapped_payload(row: Any) -> dict[str, Any]:
    payload = {
        column.name: getattr(row, column.name, None)
        for column in row.__table__.columns
        if column.name not in {"embedding"}
    }
    return json.loads(json.dumps(payload, ensure_ascii=False, default=str))


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
