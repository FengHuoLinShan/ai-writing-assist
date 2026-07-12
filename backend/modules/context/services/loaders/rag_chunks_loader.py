"""RAG 检索片段加载器"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from collections import Counter
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field
from typing import Any

from sqlalchemy.exc import IntegrityError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from modules.context.contracts import (
    CONTEXT_BUDGET,
    CompileOptions,
    RetrievalQueryPlan,
    StructureContextBundle,
    VisibilityContextContract,
)
from modules.context.services.protocol import Loader
from modules.context.services.retrieval_query_planner import RetrievalQueryPlanner

logger = logging.getLogger(__name__)

_RetrieveFn = Callable[..., Awaitable[Any]]
_TraceRecorder = Callable[..., Awaitable[Any]]


@dataclass
class _PlanExecution:
    chunks: list = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    warning_codes: list[str] = field(default_factory=list)
    activations: dict[str, dict] = field(default_factory=dict)
    candidate_count: int = 0
    unique_count: int = 0
    duplicate_count: int = 0
    degraded: bool = False


async def _default_retrieve(*args: Any, **kwargs: Any) -> Any:
    from modules.rag.facade import retrieve

    return await retrieve(*args, **kwargs)


async def _default_record_trace(
    db: AsyncSession,
    *,
    novel_id: str,
    payload: dict,
) -> Any:
    from modules.context.services.retrieval_trace_service import RetrievalTraceService

    service = RetrievalTraceService()
    bind = db.get_bind()
    if bind.dialect.name == "postgresql":
        from core.database import get_manager

        async with get_manager().session_factory() as trace_db:
            record = await service.record(
                trace_db,
                novel_id=novel_id,
                payload=payload,
            )
            await trace_db.commit()
            return record
    return await service.record(db, novel_id=novel_id, payload=payload)


class RagChunksLoader(Loader):
    """加载 RAG 检索片段"""

    def __init__(
        self,
        retrieve_fn: _RetrieveFn = _default_retrieve,
        trace_recorder: _TraceRecorder = _default_record_trace,
        planner: RetrievalQueryPlanner | None = None,
    ) -> None:
        self._retrieve = retrieve_fn
        self._record = trace_recorder
        self._planner = planner or RetrievalQueryPlanner()

    @property
    def name(self) -> str:
        return "rag_chunks"

    async def load(
        self,
        db: AsyncSession,
        options: CompileOptions,
        bundle: StructureContextBundle,
    ) -> None:
        started = time.monotonic()
        rag_limit = options.top_k or CONTEXT_BUDGET.get("rag_chunks", 8)

        rag_visibility: str | None = None
        if options.reveal_mode == "reader":
            rag_visibility = "reader_known"

        plan = self._planner.plan(options)
        strict_scene_filter = (
            options.reveal_mode == "character" and options.scene_id is not None
        )
        visible_until_chapter = plan.visible_until_chapter
        trace = {
            "content_mode": options.content_mode,
            "consumer_action": options.consumer_action or "generic",
            "retrieval_purpose": plan.purpose,
            "reveal_mode": _normalized_reveal_mode(options.reveal_mode),
            "scene_id": options.scene_id,
            "chapter_index": options.chapter_index,
            "plan_version": plan.version,
            "plan_hash": plan.plan_hash,
            "clause_summaries": [_clause_summary(clause) for clause in plan.clauses],
            "candidate_count": 0,
            "unique_count": 0,
            "hydrated_count": 0,
            "drop_counts": {},
            "safe_empty_reason": None,
            "degraded": False,
            "warning_codes": [],
            "latency_metadata": {},
        }
        retrieve_started = time.monotonic()
        execution = await self._execute_plan(
            db,
            options,
            plan,
            rag_visibility=rag_visibility,
        )
        trace["latency_metadata"]["retrieve_ms"] = (
            time.monotonic() - retrieve_started
        ) * 1000
        trace["candidate_count"] = execution.candidate_count
        trace["unique_count"] = execution.unique_count
        trace["degraded"] = execution.degraded
        trace["warning_codes"] = execution.warning_codes
        initial_drops = Counter()
        if execution.duplicate_count:
            initial_drops["duplicate_candidate"] = execution.duplicate_count
        if execution.unique_count > rag_limit:
            initial_drops["rank_budget"] = execution.unique_count - rag_limit
        if strict_scene_filter:
            warning = (
                "RAG 已按当前 Scene 严格过滤；无 Scene 标注或其它 Scene 的片段"
                "不会进入角色视角上下文"
            )
            if warning not in bundle.warnings:
                bundle.warnings.append(warning)
        for warning in execution.warnings:
            if warning not in bundle.warnings:
                bundle.warnings.append(warning)
        if execution.degraded and "RAG 检索降级" not in bundle.warnings:
            bundle.warnings.append("RAG 检索降级")
        if execution.chunks:
            rehydrate_started = time.monotonic()
            bundle.rag_chunks, drop_counts = await self._rehydrate_chunks(
                db,
                options,
                execution.chunks[:rag_limit],
                bundle,
                visible_until_chapter=visible_until_chapter,
                activations=execution.activations,
            )
            trace["latency_metadata"]["rehydrate_ms"] = (
                time.monotonic() - rehydrate_started
            ) * 1000
            initial_drops.update(drop_counts)
        trace["drop_counts"] = dict(sorted(initial_drops.items()))

        bundle.budget_used["rag_chunks"] = len(bundle.rag_chunks)
        trace["hydrated_count"] = len(bundle.rag_chunks)
        trace["safe_empty_reason"] = _safe_empty_reason(
            trace,
            strict_scene_filter=strict_scene_filter,
        )
        trace["latency_metadata"]["total_ms"] = (time.monotonic() - started) * 1000
        bundle.retrieval_trace = dict(trace)
        await self._record_trace(db, options, bundle, trace)

    async def _execute_plan(
        self,
        db: AsyncSession,
        options: CompileOptions,
        plan: RetrievalQueryPlan,
        *,
        rag_visibility: str | None,
    ) -> _PlanExecution:
        scores: dict[str, float] = {}
        chunks_by_id: dict[str, Any] = {}
        activations: dict[str, dict] = {}
        warnings: list[str] = []
        warning_codes: list[str] = []
        candidate_count = 0
        degraded = False
        for clause in plan.clauses:
            try:
                result = await self._retrieve(
                    db,
                    options.novel_id,
                    query=clause.query_text,
                    content_mode=options.content_mode,
                    entity_ids=clause.entity_ids,
                    character_ids=clause.character_ids,
                    thread_ids=clause.thread_ids,
                    chapter_index=clause.chapter_index,
                    scene_id=clause.scene_id,
                    strict_scene_filter=clause.strict_scene_filter,
                    visibility=rag_visibility,
                    mode=clause.mode,
                    top_k=clause.top_k,
                    reference_chapter_index=options.chapter_index,
                    visible_until_chapter=plan.visible_until_chapter,
                )
            except Exception:
                degraded = True
                warning_codes.append("clause_retrieval_failed")
                warnings.append("RAG 子查询失败，已使用其它检索结果")
                continue
            result_chunks = list(getattr(result, "chunks", []) or [])
            candidate_count += len(result_chunks)
            degraded = degraded or bool(getattr(result, "degraded", False))
            if getattr(result, "degraded", False):
                warning_codes.append("retrieval_degraded")
            warnings.extend(getattr(result, "warnings", []) or [])
            for rank, chunk in enumerate(result_chunks, start=1):
                chunk_id = str(chunk.id)
                chunks_by_id.setdefault(chunk_id, chunk)
                scores[chunk_id] = scores.get(chunk_id, 0.0) + (
                    clause.priority / (60 + rank)
                )
                activation = activations.setdefault(
                    chunk_id,
                    {"clause_ids": [], "reason_codes": []},
                )
                activation["clause_ids"].append(clause.clause_id)
                activation["reason_codes"].append(clause.reason_code)

        ordered_ids = sorted(
            chunks_by_id,
            key=lambda chunk_id: (
                -scores[chunk_id],
                getattr(chunks_by_id[chunk_id], "chapter_index", 0) or 0,
                getattr(chunks_by_id[chunk_id], "chunk_index", 0) or 0,
                chunk_id,
            ),
        )
        return _PlanExecution(
            chunks=[chunks_by_id[chunk_id] for chunk_id in ordered_ids],
            warnings=list(dict.fromkeys(warnings)),
            warning_codes=list(dict.fromkeys(warning_codes)),
            activations=activations,
            candidate_count=candidate_count,
            unique_count=len(chunks_by_id),
            duplicate_count=max(0, candidate_count - len(chunks_by_id)),
            degraded=degraded,
        )

    async def _rehydrate_chunks(
        self,
        db: AsyncSession,
        options: CompileOptions,
        chunks: list,
        bundle: StructureContextBundle,
        *,
        visible_until_chapter: int | None,
        activations: dict[str, dict],
    ) -> tuple[list[dict], dict[str, int]]:
        from modules.context.novel_evidence import NovelEvidenceService
        from modules.writing.facade import (
            build_manuscript_range_ref,
            list_manuscript_sources,
        )

        chapters = sorted(
            {
                int(chunk.chapter_index)
                for chunk in chunks
                if getattr(chunk, "chapter_index", None) is not None
            }
        )
        current_sources = await list_manuscript_sources(
            db,
            options.novel_id,
            chapters,
            content_mode=options.content_mode,
        )
        current_by_chapter = {source.chapter_index: source for source in current_sources}
        visibility = VisibilityContextContract(
            mode=(
                options.reveal_mode
                if options.reveal_mode in {"reader", "character"}
                else "author"
            ),
            cutoff_chapter=visible_until_chapter,
            cutoff_scene_id=options.visible_until_scene_id,
            cutoff_offset=options.visible_until_offset,
            character_id=options.viewpoint_character_id,
        )
        evidence = NovelEvidenceService()
        visibility, cursor_warnings = await evidence.resolve_visibility_cursor(
            db,
            novel_id=options.novel_id,
            content_mode=options.content_mode,
            visibility=visibility,
        )
        for warning in cursor_warnings:
            if warning not in bundle.warnings:
                bundle.warnings.append(warning)
        hydrated: list[dict] = []
        drops: Counter[str] = Counter()
        for chunk in chunks:
            source = current_by_chapter.get(getattr(chunk, "chapter_index", None))
            drop_reason = _source_drop_reason(chunk, source)
            if drop_reason is not None:
                drops[drop_reason] += 1
                warning = "RAG 候选未匹配当前正文版本，已剔除"
                if warning not in bundle.warnings:
                    bundle.warnings.append(warning)
                continue
            try:
                source_ref = await build_manuscript_range_ref(
                    db,
                    options.novel_id,
                    draft_id=chunk.source_id,
                    start_offset=chunk.start_offset,
                    end_offset=chunk.end_offset,
                    content_mode=options.content_mode,
                )
                read = await evidence.read(
                    db,
                    novel_id=options.novel_id,
                    source_ref=source_ref,
                    visibility=visibility,
                    before=0,
                    after=0,
                )
            except Exception as exc:
                reason = (
                    "visibility_denied"
                    if "可见截止" in str(exc) or "超出当前可见" in str(exc)
                    else "read_failed"
                )
                drops[reason] += 1
                warning = "RAG 候选原文引用已失效，已剔除"
                if warning not in bundle.warnings:
                    bundle.warnings.append(warning)
                continue
            raw = chunk.model_dump() if hasattr(chunk, "model_dump") else asdict(chunk)
            raw["text"] = read["text"]
            raw["summary"] = None
            raw["source_ref"] = read["source_ref"]
            raw["scene_refs"] = read["scene_refs"]
            raw["object_refs"] = read["object_refs"]
            activation = activations.get(str(chunk.id), {})
            raw["retrieval_clause_ids"] = list(activation.get("clause_ids") or [])
            raw["activation_reasons"] = list(activation.get("reason_codes") or [])
            hydrated.append(raw)
        return hydrated, dict(sorted(drops.items()))

    async def _record_trace(
        self,
        db: AsyncSession,
        options: CompileOptions,
        bundle: StructureContextBundle,
        trace: dict,
    ) -> None:
        try:
            await self._record(
                db,
                novel_id=options.novel_id,
                payload=trace,
            )
        except (ValueError, IntegrityError, ProgrammingError):
            raise
        except Exception:
            logger.warning("Context retrieval trace write failed", exc_info=True)
            warning = "RAG 检索诊断记录失败"
            if warning not in bundle.warnings:
                bundle.warnings.append(warning)


def _source_drop_reason(chunk: Any, source: Any) -> str | None:
    if getattr(chunk, "source_type", None) != "chapter_text" or source is None:
        return "source_missing"
    if not getattr(chunk, "source_id", None) or source.id != chunk.source_id:
        return "source_id_mismatch"
    if (
        not getattr(chunk, "source_content_hash", None)
        or source.content_hash != chunk.source_content_hash
    ):
        return "source_hash_mismatch"
    start = getattr(chunk, "start_offset", None)
    end = getattr(chunk, "end_offset", None)
    if start is None or end is None or int(start) < 0 or int(end) <= int(start):
        return "invalid_range"
    return None


def _safe_empty_reason(trace: dict, *, strict_scene_filter: bool) -> str | None:
    if int(trace.get("hydrated_count") or 0) > 0:
        return None
    drops = dict(trace.get("drop_counts") or {})
    if not trace.get("clause_summaries"):
        return "no_query_clause"
    if strict_scene_filter and int(trace.get("candidate_count") or 0) == 0:
        return "strict_scene_unmapped"
    if trace.get("degraded") and int(trace.get("candidate_count") or 0) == 0:
        return "retrieval_degraded_empty"
    if int(trace.get("candidate_count") or 0) == 0:
        return "no_retrieval_match"
    if drops and sum(drops.values()) == int(trace.get("candidate_count") or 0):
        source_invalid_reasons = {
            "source_missing",
            "source_id_mismatch",
            "source_hash_mismatch",
            "invalid_range",
            "read_failed",
        }
        if set(drops) <= source_invalid_reasons:
            return "all_source_invalid"
        if set(drops) == {"visibility_denied"}:
            return "all_visibility_filtered"
    return "mixed_filtered_empty"


def _clause_summary(clause) -> dict:
    return {
        "clause_id": clause.clause_id,
        "reason_code": clause.reason_code,
        "query_hash": _hash_text(clause.query_text),
        "query_length": len(clause.query_text),
        "mode": clause.mode,
        "top_k": clause.top_k,
        "has_scene_filter": bool(clause.scene_id),
        "strict_scene_filter": clause.strict_scene_filter,
        "has_entity_filter": bool(clause.entity_ids),
        "has_character_filter": bool(clause.character_ids),
        "has_thread_filter": bool(clause.thread_ids),
    }


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _hash_payload(payload: dict) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return _hash_text(raw)


def _normalized_reveal_mode(value: str) -> str:
    if value in {"reader", "character"}:
        return value
    return "author"
