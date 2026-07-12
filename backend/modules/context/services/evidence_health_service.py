"""Combine module-owned evidence health summaries."""

from __future__ import annotations

from dataclasses import asdict

from sqlalchemy.ext.asyncio import AsyncSession

from modules.context.contracts import EvidenceHealthContract
from modules.context.services.retrieval_trace_service import RetrievalTraceService


class EvidenceHealthService:
    def __init__(self, trace_service: RetrievalTraceService | None = None) -> None:
        self._traces = trace_service or RetrievalTraceService()

    async def get_health(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        content_mode: str,
        window_hours: int,
    ) -> EvidenceHealthContract:
        from modules.outline.facade import get_scene_span_coverage
        from modules.rag.facade import get_scene_mapping_coverage

        scene = await get_scene_span_coverage(
            db,
            novel_id,
            content_mode=content_mode,
        )
        rag = await get_scene_mapping_coverage(
            db,
            novel_id,
            content_mode=content_mode,
        )
        retrieval = await self._traces.summarize(
            db,
            novel_id=novel_id,
            content_mode=content_mode,
            window_hours=window_hours,
        )
        reasons: list[str] = []
        if rag.dangling_mapping_count:
            reasons.append("dangling_scene_span_mapping")
        if rag.wrong_source_mapping_count:
            reasons.append("wrong_source_scene_span_mapping")
        if rag.eligible_mapping_rate is not None and rag.eligible_mapping_rate < 0.98:
            reasons.append("eligible_mapping_below_target")
        if retrieval["unclassified_empty_count"]:
            reasons.append("unclassified_empty_context")
        if reasons:
            state = "degraded"
        elif retrieval["query_count"] == 0:
            state = "insufficient_data"
        else:
            state = "healthy"

        scene_dict = asdict(scene)
        scene_dict.pop("precise_spans", None)
        return EvidenceHealthContract(
            novel_id=novel_id,
            content_mode=content_mode,
            window_hours=window_hours,
            health_state=state,
            health_reasons=reasons,
            scene_span_coverage=scene_dict,
            rag_mapping_coverage=asdict(rag),
            retrieval_summary=retrieval,
        )
