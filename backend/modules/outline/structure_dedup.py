from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import get_settings
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
from modules.rag import facade as rag_facade
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
    ) -> dict[str, Any]:
        selected_types = set(asset_types or _SUPPORTED_ASSET_TYPES)
        assets = await self._load_assets(db, novel_id=novel_id, limit=limit)
        suggestions: list[dict[str, Any]] = []
        scanned_counts: dict[str, int] = {}

        for asset_type, items in assets.items():
            if asset_type not in selected_types:
                continue
            scanned_counts[asset_type] = len(items)
            pairs = self._candidate_pairs(items, max_pairs=max_suggestions * 2)
            for pair_index, (source, target, match) in enumerate(pairs):
                if len(suggestions) >= max_suggestions:
                    break
                evidence = await self._evidence(db, novel_id, source, target)
                decision = await self._decide(source, target, match, evidence)
                if decision.action == "keep_separate":
                    continue
                primary = (
                    source if decision.recommended_primary_side == "source" else target
                )
                suggestions.append(
                    {
                        "asset_type": asset_type,
                        "action": decision.action,
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
        return ordered[:max_pairs]

    async def _evidence(
        self,
        db: AsyncSession,
        novel_id: str,
        source: _StructureAsset,
        target: _StructureAsset,
    ) -> list[dict[str, Any]]:
        query = f"{source.title} {target.title} {source.summary} {target.summary}"[:500]
        try:
            bundle = await rag_facade.retrieve(db, novel_id, query, top_k=4)
        except Exception:
            return _asset_summary_evidence(source, target, "rag_error")
        if not bundle.chunks:
            return _asset_summary_evidence(source, target, "no_rag_hit")
        return [
            {
                "source_type": "rag",
                "rag_chunk_id": chunk.id,
                "chapter_index": chunk.chapter_index,
                "scene_id": chunk.scene_id,
                "snippet": _clip(chunk.text),
            }
            for chunk in bundle.chunks[:4]
        ]

    async def _decide(
        self,
        source: _StructureAsset,
        target: _StructureAsset,
        match: dict[str, Any],
        evidence: list[dict[str, Any]],
    ) -> StructureDedupDecision:
        deterministic = _deterministic_decision(source, target, match)
        if deterministic.action == "merge" and deterministic.confidence >= 0.96:
            return deterministic

        client = self._llm_client or LLMClient()
        settings = get_settings()
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
                    model=settings.llm_model,
                    messages=[
                        LLMMessage(
                            role="system",
                            content=(
                                "你判断两个长篇小说结构资产是否重复。只输出 JSON。"
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
                    max_tokens=768,
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
    if left_title and right_title and (
        left_title in right_title or right_title in left_title
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
