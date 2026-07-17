from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.llm.agent_step_harness import run_managed_structured
from infrastructure.llm.client import LLMClient
from infrastructure.llm.schemas import LLMCallRequest, LLMMessage
from modules.outline.foreshadowing_repository import ForeshadowingPlanRepository
from modules.outline.models import (
    ForeshadowingPlan,
    OutlineArc,
    PlotThread,
    RevealPlan,
    Scene,
)
from modules.outline.repositories import (
    OutlineArcRepository,
    PlotThreadRepository,
    SceneRepository,
)
from modules.outline.reveal_repository import RevealPlanRepository
from modules.outline.scene_workbench import SceneWorkbenchService
from modules.outline.schemas import (
    ForeshadowingPlanUpdate,
    OutlineArcUpdate,
    PlotThreadUpdate,
    RevealPlanUpdate,
    SceneMergeRequest,
)
from shared.utils import parse_uuid

logger = logging.getLogger(__name__)

DedupAction = Literal["merge", "deprecate_duplicate", "keep_separate", "needs_review"]


class StructureDedupDecision(BaseModel):
    action: DedupAction = "needs_review"
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    reason: str = ""
    recommended_primary_side: Literal["source", "target"] = "target"


@dataclass(frozen=True)
class _StructureAsset:
    asset_type: str
    asset_id: str
    title: str
    status: str
    chapter_start: int | None
    chapter_end: int | None
    summary: str
    raw: Any


class OutlineStructureDedupService:
    """Suggest and apply dedupe operations for outline-owned structure assets."""

    def __init__(self, *, llm_client: LLMClient | None = None) -> None:
        self._llm_client = llm_client

    async def suggest(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        asset_types: list[str] | None = None,
        limit: int = 1000,
        max_suggestions: int = 80,
        progress_callback: Any | None = None,
        exclusions: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        if self._llm_client is None:
            from modules.project.facade import open_project_llm_client

            async with open_project_llm_client(db, novel_id) as client:
                return await OutlineStructureDedupService(
                    llm_client=client,
                ).suggest(
                    db,
                    novel_id=novel_id,
                    asset_types=asset_types,
                    limit=limit,
                    max_suggestions=max_suggestions,
                    progress_callback=progress_callback,
                    exclusions=exclusions,
                )
        selected_types = set(asset_types or _SUPPORTED_ASSET_TYPES)
        assets = await self._load_assets(db, novel_id=novel_id, limit=limit)
        managed_scene_pairs = (
            await SceneWorkbenchService().get_current_fusion_decision_pairs(
                db,
                novel_id,
            )
            if "scene" in selected_types
            else set()
        )
        suggestions: list[dict[str, Any]] = []
        scanned_counts: dict[str, int] = {}
        active_exclusions = {
            (
                str(item.get("left_asset_id")),
                str(item.get("right_asset_id")),
                str(item.get("left_semantic_fingerprint")),
                str(item.get("right_semantic_fingerprint")),
            )
            for item in exclusions or []
        }

        for asset_type, items in assets.items():
            if asset_type not in selected_types:
                continue
            scanned_counts[asset_type] = len(items)
            pairs = self._candidate_pairs(
                items,
                max_pairs=max_suggestions * 2,
                excluded_pairs=(managed_scene_pairs if asset_type == "scene" else None),
            )
            for pair_index, (source, target, match) in enumerate(pairs):
                if len(suggestions) >= max_suggestions:
                    break
                source_fp = _asset_fingerprints(source)
                target_fp = _asset_fingerprints(target)
                left, right = sorted((source.asset_id, target.asset_id))
                left_fp, right_fp = (
                    (source_fp, target_fp)
                    if left == source.asset_id
                    else (target_fp, source_fp)
                )
                if (
                    left,
                    right,
                    left_fp["semantic_fingerprint"],
                    right_fp["semantic_fingerprint"],
                ) in active_exclusions:
                    continue
                evidence = await self._evidence(db, novel_id, source, target)
                decision = await self._decide(source, target, match, evidence)
                if decision.action == "keep_separate":
                    continue
                primary = (
                    source if decision.recommended_primary_side == "source" else target
                )
                suggested_action = decision.action
                if asset_type == "scene" and suggested_action in {
                    "merge",
                    "deprecate_duplicate",
                }:
                    suggested_action = "ai_fusion"
                suggestions.append(
                    {
                        "asset_type": asset_type,
                        "action": suggested_action,
                        "resolution_mode": (
                            "ai_fusion_review"
                            if asset_type == "scene" and suggested_action == "ai_fusion"
                            else "direct_dedup"
                        ),
                        "source_asset_id": source.asset_id,
                        "source_title": source.title,
                        "source_status": source.status,
                        "target_asset_id": target.asset_id,
                        "target_title": target.title,
                        "target_status": target.status,
                        "recommended_primary_asset_id": primary.asset_id,
                        "recommended_primary_title": primary.title,
                        "source_workflow_id": _workflow_id_for_asset(source),
                        "target_workflow_id": _workflow_id_for_asset(target),
                        "source_snapshot": _asset_snapshot(source),
                        "target_snapshot": _asset_snapshot(target),
                        "source_semantic_fingerprint": source_fp["semantic_fingerprint"],
                        "target_semantic_fingerprint": target_fp["semantic_fingerprint"],
                        "source_execution_fingerprint": source_fp[
                            "execution_fingerprint"
                        ],
                        "target_execution_fingerprint": target_fp[
                            "execution_fingerprint"
                        ],
                        "confidence": round(decision.confidence, 3),
                        "reason": decision.reason[:500],
                        "match_method": match.get("match_method"),
                        "evidence_anchors": evidence,
                        "requires_confirmation": True,
                    }
                )
                if progress_callback is not None and pairs:
                    progress_callback(min(0.95, (pair_index + 1) / len(pairs)))
            if len(suggestions) >= max_suggestions:
                break

        total_assets = sum(scanned_counts.values())
        return {
            "task_type": "outline_structure_dedup_suggestions",
            "novel_id": novel_id,
            "asset_types_scanned": sorted(selected_types),
            "scanned_counts": scanned_counts,
            "total_assets_scanned": total_assets,
            "suggestion_count": len(suggestions),
            "suggestions": suggestions,
            "summary": f"生成 {len(suggestions)} 条结构资产去重建议",
        }

    async def apply_group(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        primary_asset_id: str,
        asset_type: str,
        operations: list[dict[str, Any]],
        validate_only: bool = False,
        execution_fingerprints_prevalidated: bool = False,
    ) -> list[dict[str, Any]]:
        """Strict outline group apply; failures propagate to caller savepoint."""
        if validate_only and execution_fingerprints_prevalidated:
            raise ValueError("invalid_group")
        nid = parse_uuid(novel_id, "novel_id")
        if validate_only:
            model = _ASSET_MODEL_BY_TYPE.get(asset_type)
            if model is None:
                raise ValueError("invalid_group")
            asset_ids = {
                parse_uuid(primary_asset_id, "primary_asset_id"),
                *(
                    parse_uuid(str(item.get("source_asset_id")), "source_asset_id")
                    for item in operations
                ),
            }
            await db.execute(
                select(model)
                .where(model.novel_id == nid, model.id.in_(asset_ids))
                .with_for_update(read=True)
            )
        assets = await self._load_assets(db, novel_id=novel_id, limit=5000)
        by_id = {item.asset_id: item for item in assets.get(asset_type, [])}
        target = by_id.get(primary_asset_id)
        if target is None:
            raise ValueError("invalid_group")
        if len({str(item.get("source_asset_id")) for item in operations}) != len(
            operations
        ):
            raise ValueError("invalid_group")
        prepared: list[tuple[dict[str, Any], _StructureAsset]] = []
        for operation in operations:
            source = by_id.get(str(operation.get("source_asset_id")))
            if source is None or source.asset_id == target.asset_id:
                raise ValueError("invalid_group")
            expected_actions = (
                {"ai_fusion", "merge", "keep_separate"}
                if asset_type == "scene"
                else {"deprecate_duplicate", "keep_separate"}
            )
            if operation.get("action") not in expected_actions:
                raise ValueError("invalid_group")
            if (
                asset_type == "scene"
                and operation.get("action") == "merge"
                and not operation.get("scene_preview_confirmed")
            ):
                raise ValueError("confirmation_required")
            source_fp = _asset_fingerprints(source)
            target_fp = _asset_fingerprints(target)
            if not execution_fingerprints_prevalidated and (
                source_fp["execution_fingerprint"]
                != operation.get("expected_source_execution_fingerprint")
                or target_fp["execution_fingerprint"]
                != operation.get("expected_target_execution_fingerprint")
            ):
                raise ValueError("stale_suggestion")
            prepared.append((operation, source))
        if validate_only:
            return []
        results: list[dict[str, Any]] = []
        for operation, source in prepared:
            if operation["action"] == "keep_separate":
                continue
            if asset_type == "scene" and operation["action"] == "ai_fusion":
                suggestion_ids = await SceneWorkbenchService().persist_fusion_suggestions(
                    db,
                    novel_id=novel_id,
                    source_workflow_id="smart-dedup",
                    suggestions=[
                        {
                            "suggestion_kind": "smart_dedup",
                            "proposed_action": "merge",
                            "source_scene_ids": [target.asset_id, source.asset_id],
                            "chapter_span": sorted(
                                {
                                    value
                                    for value in (
                                        target.chapter_start,
                                        target.chapter_end,
                                        source.chapter_start,
                                        source.chapter_end,
                                    )
                                    if value is not None
                                }
                            ),
                            "confidence": operation.get("confidence"),
                            "reason": operation.get("reason")
                            or (
                                "智能去重发现潜在同一叙事单元，转入作者可编辑的 "
                                "AI 融合流程。"
                            ),
                            "proposed_scene": {
                                "primary_scene_id": target.asset_id,
                                "resolution_mode": "ai_fusion_review",
                            },
                            "decision_origin": "smart_dedup",
                        }
                    ],
                )
                results.append(
                    {
                        "asset_type": "scene",
                        "action": "ai_fusion_suggestion",
                        "source_asset_id": source.asset_id,
                        "target_asset_id": target.asset_id,
                        "suggestion_id": suggestion_ids[0] if suggestion_ids else None,
                    }
                )
                continue
            results.append(
                await self._apply_one(
                    db,
                    novel_id=novel_id,
                    novel_uuid=nid,
                    asset_type=asset_type,
                    source_id=source.asset_id,
                    target_id=target.asset_id,
                    action=str(operation["action"]),
                )
            )
        await db.flush()
        keep_sources = {
            source.asset_id
            for operation, source in prepared
            if operation["action"] == "keep_separate"
        }
        if keep_sources:
            refreshed_assets = await self._load_assets(
                db,
                novel_id=novel_id,
                limit=5000,
            )
            refreshed_by_id = {
                item.asset_id: item for item in refreshed_assets.get(asset_type, [])
            }
            refreshed_target = refreshed_by_id.get(primary_asset_id)
            if refreshed_target is None:
                raise ValueError("stale_suggestion")
            for source_id in sorted(keep_sources):
                refreshed_source = refreshed_by_id.get(source_id)
                if refreshed_source is None:
                    raise ValueError("stale_suggestion")
                source_fp = _asset_fingerprints(refreshed_source)
                target_fp = _asset_fingerprints(refreshed_target)
                left, right = sorted((source_id, primary_asset_id))
                left_fp, right_fp = (
                    (source_fp, target_fp)
                    if left == source_id
                    else (target_fp, source_fp)
                )
                results.append(
                    {
                        "action": "keep_separate",
                        "left_asset_id": left,
                        "right_asset_id": right,
                        "left_semantic_fingerprint": left_fp[
                            "semantic_fingerprint"
                        ],
                        "right_semantic_fingerprint": right_fp[
                            "semantic_fingerprint"
                        ],
                    }
                )
        return results

    async def apply(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        confirmed: bool,
        suggestions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if not confirmed:
            raise ValueError("confirmed=true is required")

        applied = 0
        skipped = 0
        results: list[dict[str, Any]] = []
        warnings: list[str] = []
        nid = parse_uuid(novel_id, "novel_id")

        for item in suggestions:
            action = str(item.get("action") or "")
            asset_type = str(item.get("asset_type") or "")
            source_id = str(item.get("source_asset_id") or "")
            target_id = str(item.get("target_asset_id") or "")
            if action not in {"merge", "deprecate_duplicate"}:
                skipped += 1
                warnings.append(f"跳过不可应用建议：{asset_type}")
                continue
            if not source_id or not target_id or source_id == target_id:
                skipped += 1
                warnings.append(f"跳过无效建议：{asset_type}")
                continue
            try:
                result = await self._apply_one(
                    db,
                    novel_id=novel_id,
                    novel_uuid=nid,
                    asset_type=asset_type,
                    source_id=source_id,
                    target_id=target_id,
                    action=action,
                )
            except Exception as exc:
                skipped += 1
                warnings.append(str(exc))
                continue
            applied += 1
            results.append(result)

        await db.flush()
        return {
            "applied": applied,
            "skipped": skipped,
            "results": results,
            "warnings": warnings,
        }

    async def _load_assets(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        limit: int,
    ) -> dict[str, list[_StructureAsset]]:
        nid = parse_uuid(novel_id, "novel_id")
        threads, _ = await PlotThreadRepository().get_by_novel(db, nid, limit=limit)
        arcs, _ = await OutlineArcRepository().get_by_novel(db, nid, limit=limit)
        scenes = await SceneRepository().get_by_novel_ordered(db, nid)
        foreshadowing, _ = await ForeshadowingPlanRepository().get_by_novel(
            db,
            nid,
            limit=limit,
        )
        reveals, _ = await RevealPlanRepository().get_by_novel(db, nid, limit=limit)
        return {
            "plot_thread": [
                _asset_from_thread(item)
                for item in threads
                if item.status in _ACTIVE_STRUCTURE_STATUSES
            ],
            "outline_arc": [
                _asset_from_arc(item)
                for item in arcs
                if item.status in _ACTIVE_STRUCTURE_STATUSES
            ],
            "scene": [
                _asset_from_scene(item)
                for item in scenes
                if item.status in _ACTIVE_STRUCTURE_STATUSES
            ],
            "foreshadowing_plan": [
                _asset_from_foreshadowing(item)
                for item in foreshadowing
                if item.status in _ACTIVE_STRUCTURE_STATUSES
            ],
            "reveal_plan": [
                _asset_from_reveal(item)
                for item in reveals
                if item.status in _ACTIVE_STRUCTURE_STATUSES
            ],
        }

    def _candidate_pairs(
        self,
        items: list[_StructureAsset],
        *,
        max_pairs: int,
        excluded_pairs: set[frozenset[str]] | None = None,
    ) -> list[tuple[_StructureAsset, _StructureAsset, dict[str, Any]]]:
        pairs: dict[
            tuple[str, str],
            tuple[_StructureAsset, _StructureAsset, dict[str, Any]],
        ] = {}
        for left_index, left in enumerate(items):
            for right in items[left_index + 1 :]:
                score, method = _asset_similarity(left, right)
                if score < 0.74:
                    continue
                source, target = _source_target(left, right)
                pairs[(source.asset_id, target.asset_id)] = (
                    source,
                    target,
                    {"similarity_score": score, "match_method": method},
                )
        ordered = sorted(
            pairs.values(),
            key=lambda item: item[2].get("similarity_score", 0),
            reverse=True,
        )
        excluded = excluded_pairs or set()
        return [
            item
            for item in ordered
            if frozenset((item[0].asset_id, item[1].asset_id)) not in excluded
        ][:max_pairs]

    async def _evidence(
        self,
        db: AsyncSession,
        novel_id: str,
        source: _StructureAsset,
        target: _StructureAsset,
    ) -> list[dict[str, Any]]:
        from modules.context.contracts import VisibilityContextContract
        from modules.context.facade import search_novel_evidence

        query = f"{source.title} {target.title} {source.summary} {target.summary}"[:500]
        try:
            result = await search_novel_evidence(
                db,
                novel_id=novel_id,
                query=query,
                content_mode="canonical",
                visibility=VisibilityContextContract(mode="author"),
                scopes=["manuscript"],
                top_k=4,
            )
        except Exception:
            return _asset_summary_evidence(source, target, "rag_error")
        hits = list(result.get("hits") or [])
        if not hits:
            return _asset_summary_evidence(source, target, "no_rag_hit")
        return [
            {
                "source_type": "manuscript_evidence",
                "source_ref": hit.get("source_ref"),
                "chapter_index": hit.get("chapter_index"),
                "scene_refs": hit.get("scene_refs") or [],
                "snippet": _clip(str(hit.get("snippet") or "")),
            }
            for hit in hits[:4]
        ]

    async def _decide(
        self,
        source: _StructureAsset,
        target: _StructureAsset,
        match: dict[str, Any],
        evidence: list[dict[str, Any]],
    ) -> StructureDedupDecision:
        deterministic = _deterministic_decision(source, target, match)
        if (
            source.asset_type != "scene"
            and deterministic.action == "merge"
            and deterministic.confidence >= 0.96
        ):
            return deterministic

        client = self._llm_client
        if client is None:  # pragma: no cover - suggest() always manages the client.
            raise RuntimeError("project LLM client is required")
        payload = {
            "source": _asset_payload(source),
            "target": _asset_payload(target),
            "match": match,
            "evidence": evidence[:4],
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
                                "你判断两个长篇小说结构资产是否重复。Scene 必须按叙事与"
                                "因果身份判断：标题相同、人物相同或主题相似都不足以证明"
                                "是同一 Scene；只有它们实际描述同一可独立规划、修订、续写"
                                "和检查的因果叙事单元时才选择 merge。部分重叠、相邻延续或"
                                "证据冲突时选择 needs_review。只输出 JSON。"
                                "action 为 merge、deprecate_duplicate、keep_separate "
                                "或 needs_review。recommended_primary_side 必须是 source "
                                "或 target，表示建议保留/关联到哪个主体；不确定时选 "
                                "target。不要创造新资产。"
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
                StructureDedupDecision,
                step_name="outline.structure_dedup.decision.structured",
                max_fix_attempts=1,
            )
        except Exception as exc:
            logger.warning("Outline structure dedupe LLM failed: %s", exc)
            return deterministic

    async def _apply_one(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        novel_uuid: Any,
        asset_type: str,
        source_id: str,
        target_id: str,
        action: str,
    ) -> dict[str, Any]:
        if asset_type == "scene":
            merged = await SceneWorkbenchService().merge(
                db,
                novel_id,
                SceneMergeRequest(
                    target_scene_id=target_id,
                    source_scene_ids=[source_id],
                    confirmed=True,
                ),
            )
            return {
                "asset_type": asset_type,
                "action": "merge",
                "source_asset_id": source_id,
                "target_asset_id": target_id,
                "target_title": merged.scene.title,
            }
        if asset_type == "plot_thread":
            return await self._deprecate_thread(db, novel_uuid, source_id, target_id)
        if asset_type == "outline_arc":
            return await self._deprecate_arc(db, novel_uuid, source_id, target_id)
        if asset_type == "foreshadowing_plan":
            return await self._deprecate_foreshadowing(
                db,
                novel_uuid,
                source_id,
                target_id,
            )
        if asset_type == "reveal_plan":
            return await self._deprecate_reveal(db, novel_uuid, source_id, target_id)
        raise ValueError(f"unsupported asset_type: {asset_type}")

    async def _deprecate_thread(
        self,
        db: AsyncSession,
        novel_id: Any,
        source_id: str,
        target_id: str,
    ) -> dict[str, Any]:
        repo = PlotThreadRepository()
        source = await repo.get(db, parse_uuid(source_id, "source_asset_id"))
        target = await repo.get(db, parse_uuid(target_id, "target_asset_id"))
        _assert_same_novel(source, target, novel_id)
        meta = _merged_meta(source.provenance_meta, target_id)
        updated = await repo.update(
            db,
            source.id,
            PlotThreadUpdate(status="deprecated", provenance_meta=meta),
        )
        return _apply_result("plot_thread", updated, target_id)

    async def _deprecate_arc(
        self,
        db: AsyncSession,
        novel_id: Any,
        source_id: str,
        target_id: str,
    ) -> dict[str, Any]:
        repo = OutlineArcRepository()
        source = await repo.get(db, parse_uuid(source_id, "source_asset_id"))
        target = await repo.get(db, parse_uuid(target_id, "target_asset_id"))
        _assert_same_novel(source, target, novel_id)
        meta = _merged_meta(source.provenance_meta, target_id)
        updated = await repo.update(
            db,
            source.id,
            OutlineArcUpdate(status="deprecated", provenance_meta=meta),
        )
        return _apply_result("outline_arc", updated, target_id)

    async def _deprecate_foreshadowing(
        self,
        db: AsyncSession,
        novel_id: Any,
        source_id: str,
        target_id: str,
    ) -> dict[str, Any]:
        repo = ForeshadowingPlanRepository()
        source = await repo.get(db, parse_uuid(source_id, "source_asset_id"))
        target = await repo.get(db, parse_uuid(target_id, "target_asset_id"))
        _assert_same_novel(source, target, novel_id)
        meta = _merged_meta(source.provenance_meta, target_id)
        updated = await repo.update(
            db,
            source.id,
            ForeshadowingPlanUpdate(
                status="deprecated",
                provenance_meta=meta,
            ).model_dump(exclude_none=True),
        )
        return _apply_result("foreshadowing_plan", updated, target_id)

    async def _deprecate_reveal(
        self,
        db: AsyncSession,
        novel_id: Any,
        source_id: str,
        target_id: str,
    ) -> dict[str, Any]:
        repo = RevealPlanRepository()
        source = await repo.get(db, parse_uuid(source_id, "source_asset_id"))
        target = await repo.get(db, parse_uuid(target_id, "target_asset_id"))
        _assert_same_novel(source, target, novel_id)
        meta = _merged_meta(source.provenance_meta, target_id)
        updated = await repo.update(
            db,
            source.id,
            RevealPlanUpdate(
                status="deprecated",
                provenance_meta=meta,
            ).model_dump(exclude_none=True),
        )
        return _apply_result("reveal_plan", updated, target_id)


_SUPPORTED_ASSET_TYPES = [
    "plot_thread",
    "outline_arc",
    "scene",
    "foreshadowing_plan",
    "reveal_plan",
]
_ASSET_MODEL_BY_TYPE = {
    "plot_thread": PlotThread,
    "outline_arc": OutlineArc,
    "scene": Scene,
    "foreshadowing_plan": ForeshadowingPlan,
    "reveal_plan": RevealPlan,
}
_ACTIVE_STRUCTURE_STATUSES = {"candidate", "draft", "canonical"}
_STATUS_RANK = {"canonical": 0, "draft": 1, "candidate": 2}
_PUNCT_RE = re.compile(r"[\s　，。！？、；：,.!?;:《》“”\"'（）()【】\[\]—_-]+")


def _asset_from_thread(item: PlotThread) -> _StructureAsset:
    return _StructureAsset(
        asset_type="plot_thread",
        asset_id=str(item.id),
        title=item.name,
        status=item.status,
        chapter_start=item.start_chapter,
        chapter_end=item.planned_payoff_chapter,
        summary=_join_text(item.summary, item.visible_goal, item.hidden_truth),
        raw=item,
    )


def _asset_from_arc(item: OutlineArc) -> _StructureAsset:
    return _StructureAsset(
        asset_type="outline_arc",
        asset_id=str(item.id),
        title=item.title,
        status=item.status,
        chapter_start=item.start_chapter,
        chapter_end=item.end_chapter,
        summary=_join_text(item.arc_goal, item.core_conflict, item.climax, item.result),
        raw=item,
    )


def _asset_from_scene(item: Scene) -> _StructureAsset:
    chapters = _chapter_indices_from_scene(item)
    return _StructureAsset(
        asset_type="scene",
        asset_id=str(item.id),
        title=item.title or f"Scene {item.scene_index}",
        status=item.status,
        chapter_start=min(chapters) if chapters else None,
        chapter_end=max(chapters) if chapters else None,
        summary=_join_text(item.goal, item.core_conflict, item.must_happen),
        raw=item,
    )


def _asset_from_foreshadowing(item: ForeshadowingPlan) -> _StructureAsset:
    return _StructureAsset(
        asset_type="foreshadowing_plan",
        asset_id=str(item.id),
        title=item.name,
        status=item.status,
        chapter_start=item.planned_seed_chapter,
        chapter_end=item.planned_payoff_chapter,
        summary=_join_text(item.summary, item.surface_meaning, item.hidden_meaning),
        raw=item,
    )


def _asset_from_reveal(item: RevealPlan) -> _StructureAsset:
    stages = item.reveal_stages or []
    chapters = [
        int(stage.get("chapter_index"))
        for stage in stages
        if isinstance(stage, dict) and stage.get("chapter_index")
    ]
    return _StructureAsset(
        asset_type="reveal_plan",
        asset_id=str(item.id),
        title=item.secret_summary[:80],
        status=item.status,
        chapter_start=min(chapters) if chapters else None,
        chapter_end=max(chapters) if chapters else None,
        summary=_join_text(item.target_type, item.secret_summary),
        raw=item,
    )


def _workflow_id_for_asset(asset: _StructureAsset) -> str | None:
    raw = asset.raw
    meta = getattr(raw, "structure_meta", None)
    if not isinstance(meta, dict):
        meta = getattr(raw, "provenance_meta", None)
    if not isinstance(meta, dict):
        return None
    workflow_id = meta.get("workflow_id") or meta.get("deep_import_workflow_id")
    return str(workflow_id) if workflow_id else None


def _chapter_indices_from_scene(item: Scene) -> list[int]:
    result: list[int] = []
    for chunk in item.scene_chunks or []:
        if isinstance(chunk, dict) and chunk.get("chapter_index") is not None:
            try:
                result.append(int(chunk["chapter_index"]))
            except (TypeError, ValueError):
                pass
    return result


def _join_text(*parts: object) -> str:
    return " ".join(str(part).strip() for part in parts if str(part or "").strip())


def _normalize(value: str | None) -> str:
    return _PUNCT_RE.sub("", (value or "").lower())


def _char_jaccard(left: str, right: str) -> float:
    left_set = set(left)
    right_set = set(right)
    if not left_set or not right_set:
        return 0.0
    return len(left_set & right_set) / len(left_set | right_set)


def _asset_similarity(left: _StructureAsset, right: _StructureAsset) -> tuple[float, str]:
    left_title = _normalize(left.title)
    right_title = _normalize(right.title)
    if left_title and left_title == right_title:
        return 1.0, "normalized_exact_title"
    if (
        left_title
        and right_title
        and (left_title in right_title or right_title in left_title)
    ):
        return 0.9, "substring_title"
    title_score = _char_jaccard(left_title, right_title)
    summary_score = _char_jaccard(_normalize(left.summary), _normalize(right.summary))
    overlap_bonus = 0.05 if _range_overlaps(left, right) else 0.0
    score = max(title_score, summary_score * 0.92) + overlap_bonus
    if score >= 0.82:
        return min(score, 0.95), "title_or_summary_overlap"
    return score, "weak_overlap"


def _range_overlaps(left: _StructureAsset, right: _StructureAsset) -> bool:
    if left.chapter_start is None or right.chapter_start is None:
        return False
    left_end = left.chapter_end or left.chapter_start
    right_end = right.chapter_end or right.chapter_start
    return left.chapter_start <= right_end and right.chapter_start <= left_end


def _source_target(
    left: _StructureAsset,
    right: _StructureAsset,
) -> tuple[_StructureAsset, _StructureAsset]:
    left_key = (
        _STATUS_RANK.get(left.status, 9),
        left.chapter_start or 999999,
        left.asset_id,
    )
    right_key = (
        _STATUS_RANK.get(right.status, 9),
        right.chapter_start or 999999,
        right.asset_id,
    )
    target, source = (left, right) if left_key <= right_key else (right, left)
    return source, target


def _deterministic_decision(
    source: _StructureAsset,
    target: _StructureAsset,
    match: dict[str, Any],
) -> StructureDedupDecision:
    score = float(match.get("similarity_score") or 0.0)
    method = str(match.get("match_method") or "")
    if source.asset_type == "scene" and score >= 0.74:
        return StructureDedupDecision(
            action="needs_review",
            confidence=min(score, 0.95),
            reason=(
                "Scene 文本存在相似线索，但需按因果叙事身份判断，"
                "不能仅凭标题自动融合。"
            ),
        )
    if method == "normalized_exact_title" or score >= 0.96:
        return StructureDedupDecision(
            action="merge",
            confidence=max(score, 0.96),
            reason="标题或摘要高度一致，建议合并重复结构资产。",
        )
    if score >= 0.84:
        return StructureDedupDecision(
            action="deprecate_duplicate",
            confidence=score,
            reason="结构目标和文本描述高度相似，建议废弃重复项并保留目标项。",
        )
    if score >= 0.74:
        return StructureDedupDecision(
            action="needs_review",
            confidence=score,
            reason="存在相似结构线索，但需要人工复核。",
        )
    return StructureDedupDecision(action="keep_separate", confidence=1 - score)


def _asset_payload(item: _StructureAsset) -> dict[str, Any]:
    return {
        "asset_type": item.asset_type,
        "id": item.asset_id,
        "title": item.title,
        "status": item.status,
        "chapter_span": [item.chapter_start, item.chapter_end],
        "summary": _clip(item.summary, 800),
    }


def _asset_snapshot(item: _StructureAsset) -> dict[str, Any]:
    details = {
        column.name: getattr(item.raw, column.name, None)
        for column in item.raw.__table__.columns
        if column.name
        not in {
            "id",
            "novel_id",
            "embedding",
            "created_at",
            "updated_at",
        }
    }
    return {
        "asset_id": item.asset_id,
        "title": item.title,
        "asset_type": item.asset_type,
        "status": item.status,
        "summary": item.summary,
        "chapter_span": [item.chapter_start, item.chapter_end],
        "source": getattr(item.raw, "source", None),
        "workflow_id": _workflow_id_for_asset(item),
        "details": json.loads(json.dumps(details, ensure_ascii=False, default=str)),
        "updated_at": (
            item.raw.updated_at.isoformat()
            if getattr(item.raw, "updated_at", None)
            else None
        ),
    }


def _asset_fingerprints(item: _StructureAsset) -> dict[str, str]:
    semantic = {
        column.name: getattr(item.raw, column.name, None)
        for column in item.raw.__table__.columns
        if column.name
        not in {
            "id",
            "novel_id",
            "embedding",
            "created_at",
            "updated_at",
        }
    }
    execution = {
        column.name: getattr(item.raw, column.name, None)
        for column in item.raw.__table__.columns
        if column.name not in {"embedding"}
    }
    return {
        "semantic_fingerprint": _hash_payload(semantic),
        "execution_fingerprint": _hash_payload(execution),
    }


def _hash_payload(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _asset_summary_evidence(
    source: _StructureAsset,
    target: _StructureAsset,
    reason: str,
) -> list[dict[str, Any]]:
    return [
        {
            "source_type": "asset_summary",
            "degraded": True,
            "reason": reason,
            "source_asset_id": source.asset_id,
            "target_asset_id": target.asset_id,
            "snippet": _clip(f"{source.summary}\n{target.summary}"),
        }
    ]


def _clip(value: str | None, limit: int = 600) -> str:
    return (value or "").strip()[:limit]


def _merged_meta(meta: dict[str, Any] | None, target_id: str) -> dict[str, Any]:
    return {
        **(meta or {}),
        "merged_into_asset_id": target_id,
        "dedup_status": "deprecated_duplicate",
        "dedup_source": "smart_dedup",
        "needs_review": True,
    }


def _assert_same_novel(source: Any, target: Any, novel_id: Any) -> None:
    if source is None or target is None:
        raise ValueError("asset not found")
    if source.novel_id != novel_id or target.novel_id != novel_id:
        raise ValueError("asset does not belong to this novel")
    if source.id == target.id:
        raise ValueError("source and target are the same asset")


def _apply_result(asset_type: str, source: Any, target_id: str) -> dict[str, Any]:
    return {
        "asset_type": asset_type,
        "action": "deprecate_duplicate",
        "source_asset_id": str(source.id),
        "target_asset_id": target_id,
        "source_status": source.status,
    }
