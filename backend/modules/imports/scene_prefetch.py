"""Phase 0 two-round scene candidate prefetch."""

from __future__ import annotations

import asyncio
import inspect
import os
from collections.abc import Awaitable, Callable
from typing import Any

from modules.imports.deep_import_retry import run_deep_import_llm_with_retry
from modules.imports.llm_schemas import SceneCandidateOutput
from modules.imports.scene_candidates import (
    SceneCandidate,
    SceneCandidateBatch,
    ScenePrefetchResult,
)

PHASE0_PREFETCH_CONCURRENCY = 6
PHASE0_PREFETCH_BATCH_TIMEOUT_SECONDS = 180.0
PHASE0_PREFETCH_RETRY_COUNT = 0
DEEP_IMPORT_422_BLOCK_THRESHOLD = 0.40
ROUND_B_CHAPTER_OFFSET = 2

Phase0LLMCallable = Callable[[SceneCandidateBatch], Awaitable[Any]]


def build_phase0_prefetch_batches(
    start_chapter: int,
    end_chapter: int,
    window: int = 5,
) -> list[SceneCandidateBatch]:
    """Build Round A and offset Round B batches for Phase 0 prefetch."""

    if start_chapter < 1:
        raise ValueError("start_chapter must be >= 1")
    if end_chapter < start_chapter:
        raise ValueError("end_chapter must be >= start_chapter")
    if window < 1:
        raise ValueError("window must be >= 1")

    batches: list[SceneCandidateBatch] = []
    batches.extend(
        _build_round_batches(
            round_name="A",
            first_chapter=start_chapter,
            end_chapter=end_chapter,
            window=window,
        )
    )
    batches.extend(
        _build_round_batches(
            round_name="B",
            first_chapter=start_chapter + ROUND_B_CHAPTER_OFFSET,
            end_chapter=end_chapter,
            window=window,
        )
    )
    return batches


class Phase0ScenePrefetcher:
    """Collect Phase 0 candidate observations without formal Scene writes."""

    def __init__(
        self,
        llm: Phase0LLMCallable | Any,
        *,
        concurrency: int | None = None,
        max_retries: int = PHASE0_PREFETCH_RETRY_COUNT,
    ) -> None:
        self.llm = llm
        self.concurrency = max(
            1,
            concurrency
            if concurrency is not None
            else _positive_int_env(
                "PHASE0_PREFETCH_CONCURRENCY",
                PHASE0_PREFETCH_CONCURRENCY,
            ),
        )
        self.batch_timeout_seconds = _positive_float_env(
            "PHASE0_PREFETCH_BATCH_TIMEOUT_SECONDS",
            _llm_timeout_default(PHASE0_PREFETCH_BATCH_TIMEOUT_SECONDS),
        )
        self.max_retries = max_retries

    async def run(
        self,
        db: Any | None = None,
        *,
        novel_id: str | None = None,
        start_chapter: int,
        end_chapter: int,
        window: int = 5,
    ) -> ScenePrefetchResult:
        """Run Phase 0 prefetch for all planned batches.

        ``db`` and ``novel_id`` are accepted for future workflow integration but
        are intentionally unused here; Phase 0 must not write formal Scene rows.
        """

        del db, novel_id
        batches = build_phase0_prefetch_batches(
            start_chapter=start_chapter,
            end_chapter=end_chapter,
            window=window,
        )
        semaphore = asyncio.Semaphore(self.concurrency)

        async def process(batch: SceneCandidateBatch) -> SceneCandidate:
            async with semaphore:
                return await self._process_batch(batch)

        candidates = await asyncio.gather(*(process(batch) for batch in batches))
        diagnostics = [
            candidate.diagnostics
            for candidate in candidates
            if candidate.diagnostics
        ]
        quality_stats = _build_quality_stats(candidates, total_batches=len(batches))
        blocked = quality_stats["final_422_rate"] > DEEP_IMPORT_422_BLOCK_THRESHOLD
        return ScenePrefetchResult(
            candidates=candidates,
            quality_stats=quality_stats,
            diagnostics=diagnostics,
            blocked=blocked,
            block_reason="phase0_422_rate_exceeded" if blocked else None,
        )

    async def _process_batch(self, batch: SceneCandidateBatch) -> SceneCandidate:
        retry_result = await run_deep_import_llm_with_retry(
            lambda: asyncio.wait_for(
                self._call_and_validate(batch),
                timeout=self.batch_timeout_seconds,
            ),
            is_empty_result=lambda output: not output.scenes,
            max_retries=self.max_retries,
        )
        diagnostics = retry_result.model_dump(mode="json", exclude={"value"})

        if retry_result.final_status != "success":
            return _candidate_from_batch(
                batch,
                quality="failed",
                diagnostics=diagnostics,
            )

        output = retry_result.value
        if not isinstance(output, SceneCandidateOutput):
            output = SceneCandidateOutput.model_validate(output)
        payload = output.model_dump(mode="json")
        return _candidate_from_batch(
            batch,
            quality=_quality_for_output(output),
            payload=payload,
            diagnostics=diagnostics,
        )

    async def _call_and_validate(
        self,
        batch: SceneCandidateBatch,
    ) -> SceneCandidateOutput:
        raw = await self._call_llm(batch)
        if isinstance(raw, SceneCandidateOutput):
            return raw
        return SceneCandidateOutput.model_validate(raw)

    async def _call_llm(self, batch: SceneCandidateBatch) -> Any:
        llm = self.llm
        if callable(llm):
            result = llm(batch)
        elif hasattr(llm, "prefetch_scene_candidates"):
            result = llm.prefetch_scene_candidates(batch)
        elif hasattr(llm, "generate_scene_candidates"):
            result = llm.generate_scene_candidates(batch)
        else:
            raise TypeError(
                "Phase0ScenePrefetcher llm must be an async callable or expose "
                "prefetch_scene_candidates/generate_scene_candidates",
            )

        if inspect.isawaitable(result):
            return await result
        return result


def _build_round_batches(
    *,
    round_name: str,
    first_chapter: int,
    end_chapter: int,
    window: int,
) -> list[SceneCandidateBatch]:
    batches: list[SceneCandidateBatch] = []
    current = first_chapter
    batch_index = 1
    while current <= end_chapter:
        last = min(current + window - 1, end_chapter)
        chapter_indices = list(range(current, last + 1))
        batches.append(
            SceneCandidateBatch(
                batch_id=_batch_id(round_name, batch_index, chapter_indices),
                round_name=round_name,
                batch_index=batch_index,
                chapter_indices=chapter_indices,
            )
        )
        current += window
        batch_index += 1
    return batches


def _positive_int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _positive_float_env(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _llm_timeout_default(default: float) -> float:
    return _positive_float_env("LLM_TIMEOUT", default)


def _candidate_from_batch(
    batch: SceneCandidateBatch,
    *,
    quality: str,
    payload: dict | None = None,
    diagnostics: dict | None = None,
) -> SceneCandidate:
    return SceneCandidate(
        candidate_id=f"phase0-{batch.batch_id}",
        source_round=batch.round_name,
        source_batch_id=batch.batch_id,
        source_batch_index=batch.batch_index,
        source_chapter_indices=batch.chapter_indices,
        quality=quality,
        payload=payload or {},
        diagnostics=diagnostics or {},
    )


def _quality_for_output(output: SceneCandidateOutput) -> str:
    if output.confidence is not None and output.confidence < 0.7:
        return "low"
    if output.boundary_status in {"truncated", "uncertain", "incomplete"}:
        return "low"
    return "high"


def _build_quality_stats(
    candidates: list[SceneCandidate],
    *,
    total_batches: int,
) -> dict:
    stats = {
        "total_batches": total_batches,
        "completed_batches": len(candidates),
        "success": 0,
        "failed": 0,
        "high_quality": 0,
        "low_quality": 0,
        "empty_result": 0,
        "schema_error": 0,
        "timeout": 0,
        "network": 0,
        "rate_limit": 0,
        "quality_gate": 0,
        "http_error": 0,
        "unknown": 0,
        "final_422": 0,
    }
    for candidate in candidates:
        if candidate.quality == "failed":
            stats["failed"] += 1
        else:
            stats["success"] += 1
        if candidate.quality == "high":
            stats["high_quality"] += 1
        if candidate.quality == "low":
            stats["low_quality"] += 1

        final_error_type = candidate.diagnostics.get("final_error_type")
        if final_error_type in stats:
            stats[final_error_type] += 1
        if final_error_type == "422":
            stats["final_422"] += 1

    stats["final_422_rate"] = (
        stats["final_422"] / total_batches if total_batches > 0 else 0.0
    )
    return stats


def _batch_id(round_name: str, batch_index: int, chapter_indices: list[int]) -> str:
    first = chapter_indices[0]
    last = chapter_indices[-1]
    return f"{round_name}-{batch_index:04d}-{first}-{last}"
