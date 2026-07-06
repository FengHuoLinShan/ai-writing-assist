"""Deprecated Phase 1a reinforcement for intermediate Scene candidates.

This module is retained for explicit legacy repair and historical artifact
acceptance. Formal Scene slicing now runs through ``scene_slicing.py`` and uses
Phase 0 window token budgets instead of a fixed Phase 1a max-token setting.
"""

from __future__ import annotations

import asyncio
import inspect
import os
from collections import defaultdict
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any

from modules.imports.deep_import_retry import run_deep_import_llm_with_retry
from modules.imports.env_helpers import positive_float_env, positive_int_env
from modules.imports.legacy_scene_pipeline import (
    require_legacy_scene_pipeline_enabled,
)
from modules.imports.llm_schemas import SceneCandidateOutput
from modules.imports.scene_candidates import (
    SceneCandidate,
    SceneCandidateBatch,
    SceneReinforcementResult,
    build_scene_candidate_quality_stats,
)

PHASE1A_REINFORCE_CONCURRENCY = 6
PHASE1A_REINFORCE_BATCH_TIMEOUT_SECONDS = 180.0
DEEP_IMPORT_LLM_RETRY_COUNT = 1
DEEP_IMPORT_422_BLOCK_THRESHOLD = 0.40
PHASE1A_REFERENCE_SCENE_LIMIT = 12
PHASE1A_SCENE_TITLE_LIMIT = 40
PHASE1A_SCENE_GOAL_LIMIT = 140
PHASE1A_BOUNDARY_REASON_LIMIT = 160
PHASE1A_CHAPTER_TEXT_CHAR_LIMIT = 1000
PHASE1A_RETRYABLE_ERROR_TYPES = frozenset(
    {"network", "rate_limit", "empty_result"}
)

ChapterProvider = Callable[[SceneCandidateBatch], Awaitable[Sequence[Mapping[str, Any]]]]
Phase1aLLMCallable = Callable[[dict[str, Any]], Awaitable[Any]]
BatchKey = tuple[str, str, int, tuple[int, ...]]


class Phase1aSceneReinforcer:
    """Deprecated legacy reinforcement for Phase 0 batches."""

    def __init__(
        self,
        llm: Phase1aLLMCallable | Any,
        *,
        concurrency: int | None = None,
        max_retries: int = DEEP_IMPORT_LLM_RETRY_COUNT,
        retryable_error_types: set[str] | frozenset[str] | None = None,
    ) -> None:
        self.llm = llm
        self.concurrency = max(
            1,
            concurrency
            if concurrency is not None
            else positive_int_env(
                "PHASE1A_REINFORCE_CONCURRENCY",
                PHASE1A_REINFORCE_CONCURRENCY,
            ),
        )
        self.batch_timeout_seconds = positive_float_env(
            "PHASE1A_REINFORCE_BATCH_TIMEOUT_SECONDS",
            _llm_timeout_default(PHASE1A_REINFORCE_BATCH_TIMEOUT_SECONDS),
        )
        self.max_retries = max_retries
        self.retryable_error_types = retryable_error_types or _retryable_error_types_env()

    async def run(
        self,
        *,
        phase0_candidates: Sequence[SceneCandidate],
        chapters: Sequence[Mapping[str, Any]] | None = None,
        chapter_provider: ChapterProvider | None = None,
    ) -> SceneReinforcementResult:
        """Run Phase 1a reinforcement for each Round A/B batch separately."""

        require_legacy_scene_pipeline_enabled("Phase1aSceneReinforcer")
        if chapters is None and chapter_provider is None:
            raise ValueError("chapters or chapter_provider is required")

        batch_groups, batches_by_key = _group_candidates_by_batch(phase0_candidates)
        ordered_batches = sorted(
            batches_by_key.values(),
            key=lambda batch: (batch.round_name, _chapter_sort_key(batch)),
        )
        round_batches = _batches_by_round(ordered_batches)
        chapters_by_index = _chapters_by_index(chapters or [])
        semaphore = asyncio.Semaphore(self.concurrency)

        async def process(batch: SceneCandidateBatch) -> SceneCandidate:
            async with semaphore:
                return await self._process_batch(
                    batch,
                    batch_candidates=batch_groups[_batch_key(batch)],
                    previous_batch=_adjacent_batch(
                        round_batches[batch.round_name],
                        batch,
                        offset=-1,
                    ),
                    next_batch=_adjacent_batch(
                        round_batches[batch.round_name],
                        batch,
                        offset=1,
                    ),
                    batch_groups=batch_groups,
                    chapters_by_index=chapters_by_index,
                    chapter_provider=chapter_provider,
                )

        candidates = await _run_batches_with_total_timeout(
            ordered_batches,
            process,
            timeout_seconds=_total_timeout_seconds(
                env_name="PHASE1A_REINFORCE_TOTAL_TIMEOUT_SECONDS",
                total_batches=len(ordered_batches),
                concurrency=self.concurrency,
                batch_timeout_seconds=self.batch_timeout_seconds,
            ),
        )
        diagnostics = [
            candidate.diagnostics
            for candidate in candidates
            if candidate.diagnostics
        ]
        quality_stats = build_scene_candidate_quality_stats(
            candidates,
            total_batches=len(ordered_batches),
            include_degraded_fallback=True,
        )
        blocked = quality_stats["final_422_rate"] > DEEP_IMPORT_422_BLOCK_THRESHOLD
        return SceneReinforcementResult(
            candidates=candidates,
            quality_stats=quality_stats,
            diagnostics=diagnostics,
            blocked=blocked,
            block_reason="phase1a_422_rate_exceeded" if blocked else None,
            did_merge_rounds=False,
        )

    async def _process_batch(
        self,
        batch: SceneCandidateBatch,
        *,
        batch_candidates: Sequence[SceneCandidate],
        previous_batch: SceneCandidateBatch | None,
        next_batch: SceneCandidateBatch | None,
        batch_groups: Mapping[BatchKey, Sequence[SceneCandidate]],
        chapters_by_index: Mapping[int, Mapping[str, Any]],
        chapter_provider: ChapterProvider | None,
    ) -> SceneCandidate:
        payload = await self._build_payload(
            batch,
            batch_candidates=batch_candidates,
            previous_batch=previous_batch,
            next_batch=next_batch,
            batch_groups=batch_groups,
            chapters_by_index=chapters_by_index,
            chapter_provider=chapter_provider,
        )
        retry_result = await run_deep_import_llm_with_retry(
            lambda: asyncio.wait_for(
                self._call_and_validate(payload),
                timeout=self.batch_timeout_seconds,
            ),
            is_empty_result=lambda output: not output.scenes,
            max_retries=self.max_retries,
            retryable_error_types=set(self.retryable_error_types),
        )
        diagnostics = retry_result.model_dump(mode="json", exclude={"value"})

        if retry_result.final_status != "success":
            if retry_result.final_error_type == "422":
                return _candidate_from_batch(
                    batch,
                    quality="failed",
                    diagnostics=diagnostics,
                )
            return _candidate_from_batch(
                batch,
                quality="low",
                payload=_fallback_phase1a_payload(
                    batch,
                    batch_candidates=batch_candidates,
                    diagnostics=diagnostics,
                ),
                diagnostics=_fallback_diagnostics(diagnostics),
            )

        output = retry_result.value
        if not isinstance(output, SceneCandidateOutput):
            output = SceneCandidateOutput.model_validate(output)
        return _candidate_from_batch(
            batch,
            quality=_quality_for_output(output),
            payload=_normalize_phase1a_output_payload(
                output.model_dump(mode="json")
            ),
            diagnostics=diagnostics,
        )

    async def _build_payload(
        self,
        batch: SceneCandidateBatch,
        *,
        batch_candidates: Sequence[SceneCandidate],
        previous_batch: SceneCandidateBatch | None,
        next_batch: SceneCandidateBatch | None,
        batch_groups: Mapping[BatchKey, Sequence[SceneCandidate]],
        chapters_by_index: Mapping[int, Mapping[str, Any]],
        chapter_provider: ChapterProvider | None,
    ) -> dict[str, Any]:
        chapters = (
            await chapter_provider(batch)
            if chapter_provider is not None
            else [
                chapters_by_index[index]
                for index in batch.chapter_indices
                if index in chapters_by_index
            ]
        )

        return {
            "phase": "phase1a_scene_reinforcement",
            "round": batch.round_name,
            "batch": batch.model_dump(mode="json"),
            "chapter_text": _build_chapter_text(chapters),
            "chapter_text_budget": {
                "chars_per_chapter": _phase1a_chapter_text_char_limit(),
                "strategy": "bounded_head_middle_tail",
            },
            "chapters": [_chapter_payload(chapter) for chapter in chapters],
            "phase0_references": _classify_references(batch_candidates),
            "previous_batch_summary": _batch_summary(
                previous_batch,
                batch_groups.get(_batch_key(previous_batch), [])
                if previous_batch
                else [],
            ),
            "next_batch_summary": _batch_summary(
                next_batch,
                batch_groups.get(_batch_key(next_batch), [])
                if next_batch
                else [],
            ),
            "output_requirements": {
                "boundary_status": True,
                "evidence_anchors": True,
                "merge_hints": True,
                "split_hints": True,
                "confidence": True,
                "missing_or_uncertain_items": True,
                "preserve_source_fields": [
                    "source_round",
                    "source_batch_id",
                    "source_chapter_indices",
                ],
            },
        }

    async def _call_and_validate(
        self,
        payload: dict[str, Any],
    ) -> SceneCandidateOutput:
        raw = await self._call_llm(payload)
        if isinstance(raw, SceneCandidateOutput):
            return raw
        return SceneCandidateOutput.model_validate(raw)

    async def _call_llm(self, payload: dict[str, Any]) -> Any:
        llm = self.llm
        if callable(llm):
            result = llm(payload)
        elif hasattr(llm, "reinforce_scene_candidates"):
            result = llm.reinforce_scene_candidates(payload)
        elif hasattr(llm, "generate_scene_candidates"):
            result = llm.generate_scene_candidates(payload)
        else:
            raise TypeError(
                "Phase1aSceneReinforcer llm must be an async callable or expose "
                "reinforce_scene_candidates/generate_scene_candidates",
            )

        if inspect.isawaitable(result):
            return await result
        return result


def _group_candidates_by_batch(
    candidates: Sequence[SceneCandidate],
) -> tuple[dict[BatchKey, list[SceneCandidate]], dict[BatchKey, SceneCandidateBatch]]:
    groups: dict[BatchKey, list[SceneCandidate]] = {}
    batches: dict[BatchKey, SceneCandidateBatch] = {}
    for candidate in candidates:
        batch = SceneCandidateBatch(
            batch_id=candidate.source_batch_id,
            round_name=candidate.source_round,
            batch_index=candidate.source_batch_index,
            chapter_indices=candidate.source_chapter_indices,
        )
        key = _batch_key(batch)
        batches.setdefault(key, batch)
        groups.setdefault(key, []).append(candidate)
    return groups, batches


def _batch_key(batch: SceneCandidateBatch) -> BatchKey:
    return (
        batch.round_name,
        batch.batch_id,
        batch.batch_index,
        tuple(batch.chapter_indices),
    )


def _batches_by_round(
    batches: Sequence[SceneCandidateBatch],
) -> dict[str, list[SceneCandidateBatch]]:
    grouped: dict[str, list[SceneCandidateBatch]] = defaultdict(list)
    for batch in batches:
        grouped[batch.round_name].append(batch)
    for round_batches in grouped.values():
        round_batches.sort(key=_chapter_sort_key)
    return dict(grouped)


def _adjacent_batch(
    batches: Sequence[SceneCandidateBatch],
    batch: SceneCandidateBatch,
    *,
    offset: int,
) -> SceneCandidateBatch | None:
    index = batches.index(batch)
    adjacent_index = index + offset
    if adjacent_index < 0 or adjacent_index >= len(batches):
        return None
    return batches[adjacent_index]


def _chapter_sort_key(batch: SceneCandidateBatch) -> tuple[int, int, int]:
    if not batch.chapter_indices:
        return (10**9, 10**9, batch.batch_index)
    return (min(batch.chapter_indices), max(batch.chapter_indices), batch.batch_index)


def _chapters_by_index(
    chapters: Sequence[Mapping[str, Any]],
) -> dict[int, Mapping[str, Any]]:
    mapped: dict[int, Mapping[str, Any]] = {}
    for chapter in chapters:
        chapter_index = chapter.get("chapter_index")
        if isinstance(chapter_index, int):
            mapped[chapter_index] = chapter
    return mapped


def _build_chapter_text(chapters: Sequence[Mapping[str, Any]]) -> str:
    parts = []
    char_limit = _phase1a_chapter_text_char_limit()
    for chapter in sorted(
        chapters,
        key=lambda item: item.get("chapter_index", 10**9),
    ):
        chapter_index = chapter.get("chapter_index", "?")
        title = chapter.get("title") or f"Chapter {chapter_index}"
        content = chapter.get("content") or chapter.get("text") or ""
        parts.append(
            f"## Chapter {chapter_index}: {title}\n"
            f"{_bounded_chapter_text(content, limit=char_limit)}"
        )
    return "\n\n".join(parts)


def _chapter_payload(chapter: Mapping[str, Any]) -> dict[str, Any]:
    content = chapter.get("content") or chapter.get("text") or ""
    char_limit = _phase1a_chapter_text_char_limit()
    return {
        "chapter_index": chapter.get("chapter_index"),
        "title": chapter.get("title", ""),
        "content_chars": len(str(content)),
        "content_truncated": len(str(content)) > char_limit,
    }

def _classify_references(candidates: Sequence[SceneCandidate]) -> dict[str, list[dict]]:
    strong = []
    weak = []
    failed_diagnostics = []
    for candidate in candidates:
        payload = _compact_phase0_reference(candidate)
        if candidate.quality == "high":
            strong.append(payload)
        elif candidate.quality == "low":
            weak.append(payload)
        else:
            failed_diagnostics.append(
                {
                    "candidate_id": candidate.candidate_id,
                    "source_round": candidate.source_round,
                    "source_batch_id": candidate.source_batch_id,
                    "source_chapter_indices": candidate.source_chapter_indices,
                    "quality": candidate.quality,
                    "diagnostics": _compact_diagnostics(candidate.diagnostics),
                    "gap": "phase0 candidate was unavailable or unusable",
                }
            )
    return {
        "strong": strong,
        "weak": weak,
        "failed_diagnostics": failed_diagnostics,
    }


def _batch_summary(
    batch: SceneCandidateBatch | None,
    candidates: Sequence[SceneCandidate],
) -> dict[str, Any] | None:
    if batch is None:
        return None
    references = _classify_references(candidates)
    return {
        "batch_id": batch.batch_id,
        "round": batch.round_name,
        "batch_index": batch.batch_index,
        "chapter_indices": batch.chapter_indices,
        "strong_reference_count": len(references["strong"]),
        "weak_reference_count": len(references["weak"]),
        "failed_reference_count": len(references["failed_diagnostics"]),
        "scene_titles": [
            _compact_text(scene.get("title"), limit=PHASE1A_SCENE_TITLE_LIMIT)
            for candidate in candidates
            if candidate.quality in {"high", "low"}
            for scene in candidate.payload.get("scenes", [])
            if isinstance(scene, dict)
        ][:PHASE1A_REFERENCE_SCENE_LIMIT],
    }


def _compact_phase0_reference(candidate: SceneCandidate) -> dict[str, Any]:
    payload = candidate.payload if isinstance(candidate.payload, dict) else {}
    return {
        "candidate_id": candidate.candidate_id,
        "source_round": candidate.source_round,
        "source_batch_id": candidate.source_batch_id,
        "source_chapter_indices": candidate.source_chapter_indices,
        "quality": candidate.quality,
        "boundary_status": payload.get("boundary_status"),
        "confidence": payload.get("confidence"),
        "scenes": [
            _compact_phase1a_scene(scene)
            for scene in payload.get("scenes", [])[:PHASE1A_REFERENCE_SCENE_LIMIT]
            if isinstance(scene, dict)
        ],
    }


def _compact_diagnostics(diagnostics: Mapping[str, Any] | None) -> dict[str, Any]:
    diagnostics = diagnostics or {}
    return {
        "final_status": diagnostics.get("final_status"),
        "final_error_type": diagnostics.get("final_error_type"),
    }


def _normalize_phase1a_output_payload(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(payload)
    normalized["scenes"] = [
        _compact_phase1a_scene(scene)
        for scene in normalized.get("scenes", [])
        if isinstance(scene, dict)
    ]
    return normalized


def _fallback_phase1a_payload(
    batch: SceneCandidateBatch,
    *,
    batch_candidates: Sequence[SceneCandidate],
    diagnostics: Mapping[str, Any],
) -> dict[str, Any]:
    references = _classify_references(batch_candidates)
    fallback_reason = str(
        diagnostics.get("final_error_type") or "degraded_fallback"
    )
    phase0_titles = [
        scene.get("title")
        for group_name in ("strong", "weak")
        for reference in references.get(group_name, [])
        for scene in reference.get("scenes", [])
        if isinstance(scene, dict) and scene.get("title")
    ]
    title_seed = _compact_text(
        phase0_titles[0] if phase0_titles else "Phase0 anchor",
        limit=PHASE1A_SCENE_TITLE_LIMIT,
    )
    return {
        "scenes": [
            {
                "title": f"{title_seed} #{chapter_index}",
                "goal": "LLM 补强失败时保留章节锚点，供 Phase1b 继续融合。",
                "scene_chunks": [{"chapter_index": chapter_index}],
                "boundary_reason": f"degraded fallback after {fallback_reason}",
            }
            for chapter_index in batch.chapter_indices
        ],
        "degraded": True,
        "fallback_reason": fallback_reason,
        "fallback_source": "phase0_anchor",
        "phase0_reference_counts": {
            "strong": len(references.get("strong", [])),
            "weak": len(references.get("weak", [])),
            "failed": len(references.get("failed_diagnostics", [])),
        },
    }


def _fallback_diagnostics(diagnostics: Mapping[str, Any]) -> dict[str, Any]:
    original_error_type = diagnostics.get("final_error_type")
    return {
        "attempts": diagnostics.get("attempts", 1),
        "final_status": "success",
        "final_error_type": None,
        "degraded": True,
        "degraded_reason": "phase1a_llm_failed_fallback",
        "original_error_type": original_error_type,
        "diagnostics": diagnostics.get("diagnostics", []),
    }


def _compact_phase1a_scene(scene: Mapping[str, Any]) -> dict[str, Any]:
    compact: dict[str, Any] = {
        "title": _compact_text(scene.get("title"), limit=PHASE1A_SCENE_TITLE_LIMIT),
        "goal": _compact_text(scene.get("goal"), limit=PHASE1A_SCENE_GOAL_LIMIT),
        "scene_chunks": [
            _compact_scene_chunk(chunk)
            for chunk in scene.get("scene_chunks", [])
            if isinstance(chunk, dict)
        ],
    }
    boundary_reason = _compact_text(
        scene.get("boundary_reason"),
        limit=PHASE1A_BOUNDARY_REASON_LIMIT,
    )
    if boundary_reason:
        compact["boundary_reason"] = boundary_reason
    return compact


def _compact_scene_chunk(chunk: Mapping[str, Any]) -> dict[str, Any]:
    compact = {"chapter_index": chunk.get("chapter_index")}
    if chunk.get("start_paragraph") is not None:
        compact["start_paragraph"] = chunk.get("start_paragraph")
    if chunk.get("end_paragraph") is not None:
        compact["end_paragraph"] = chunk.get("end_paragraph")
    return compact


def _compact_text(value: Any, *, limit: int) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip()


def _bounded_chapter_text(value: Any, *, limit: int) -> str:
    text = str(value or "").strip()
    if limit <= 0 or len(text) <= limit:
        return text
    head_limit = max(1, limit // 3)
    middle_limit = max(1, limit // 3)
    tail_limit = max(1, limit - head_limit - middle_limit)
    middle_start = max(0, (len(text) - middle_limit) // 2)
    middle_end = middle_start + middle_limit
    return (
        text[:head_limit].rstrip()
        + "\n[...phase1a text budget omitted middle gap...]\n"
        + text[middle_start:middle_end].strip()
        + "\n[...phase1a text budget omitted tail gap...]\n"
        + text[-tail_limit:].lstrip()
    )


def _phase1a_chapter_text_char_limit() -> int:
    return positive_int_env(
        "PHASE1A_CHAPTER_TEXT_CHAR_LIMIT",
        PHASE1A_CHAPTER_TEXT_CHAR_LIMIT,
    )


def _retryable_error_types_env() -> frozenset[str]:
    raw = os.getenv("PHASE1A_RETRYABLE_ERROR_TYPES")
    if raw is None or raw.strip() == "":
        return PHASE1A_RETRYABLE_ERROR_TYPES
    allowed = {
        "422",
        "network",
        "timeout",
        "rate_limit",
        "empty_result",
        "schema_error",
        "quality_gate",
        "http_error",
        "unknown",
    }
    values = {
        item.strip()
        for item in raw.split(",")
        if item.strip() and item.strip() in allowed
    }
    return frozenset(values) if values else PHASE1A_RETRYABLE_ERROR_TYPES


def _candidate_from_batch(
    batch: SceneCandidateBatch,
    *,
    quality: str,
    payload: dict | None = None,
    diagnostics: dict | None = None,
) -> SceneCandidate:
    candidate_payload = dict(payload or {})
    if candidate_payload:
        candidate_payload["source_round"] = batch.round_name
        candidate_payload["source_batch_id"] = batch.batch_id
        candidate_payload["source_chapter_indices"] = batch.chapter_indices

    return SceneCandidate(
        candidate_id=f"phase1a-{batch.batch_id}",
        source_round=batch.round_name,
        source_batch_id=batch.batch_id,
        source_batch_index=batch.batch_index,
        source_chapter_indices=batch.chapter_indices,
        quality=quality,
        payload=candidate_payload,
        diagnostics=diagnostics or {},
    )


def _quality_for_output(output: SceneCandidateOutput) -> str:
    if output.confidence is not None and output.confidence < 0.5:
        return "low"
    if output.boundary_status in {"truncated", "uncertain", "incomplete"}:
        return "low"
    return "high"


def _llm_timeout_default(default: float) -> float:
    return positive_float_env("LLM_TIMEOUT", default)


def _total_timeout_seconds(
    *,
    env_name: str,
    total_batches: int,
    concurrency: int,
    batch_timeout_seconds: float,
) -> float:
    env_timeout = positive_float_env(env_name, 0.0)
    if env_timeout > 0:
        return env_timeout
    waves = max(
        1,
        (max(total_batches, 1) + max(concurrency, 1) - 1) // max(concurrency, 1),
    )
    return waves * batch_timeout_seconds + 60.0


async def _run_batches_with_total_timeout(
    batches: Sequence[SceneCandidateBatch],
    process: Callable[[SceneCandidateBatch], Awaitable[SceneCandidate]],
    *,
    timeout_seconds: float,
) -> list[SceneCandidate]:
    tasks = [(batch, asyncio.create_task(process(batch))) for batch in batches]
    done, pending = await asyncio.wait(
        [task for _batch, task in tasks],
        timeout=timeout_seconds,
    )
    if pending:
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)

    candidates: list[SceneCandidate] = []
    for batch, task in tasks:
        if task in done:
            try:
                candidates.append(task.result())
            except Exception as exc:
                candidates.append(
                    _candidate_from_batch(
                        batch,
                        quality="failed",
                        diagnostics=_timeout_diagnostics(
                            message=f"Phase1a batch task failed: {exc}"
                        ),
                    )
                )
            continue
        candidates.append(
            _candidate_from_batch(
                batch,
                quality="failed",
                diagnostics=_timeout_diagnostics(
                    message=(
                        "Phase1a total timeout exceeded "
                        f"({timeout_seconds:.2f}s)"
                    )
                ),
            )
        )
    return candidates


def _timeout_diagnostics(*, message: str) -> dict[str, Any]:
    return {
        "attempts": 1,
        "final_status": "failed",
        "final_error_type": "timeout",
        "diagnostics": [
            {
                "attempt": 1,
                "status": "failed",
                "error_type": "timeout",
                "message": message[:300],
                "elapsed_ms": 0.0,
                "retry_scheduled": False,
            }
        ],
    }
