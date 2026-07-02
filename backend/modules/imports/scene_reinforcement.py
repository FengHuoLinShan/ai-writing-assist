"""Phase 1a text-backed reinforcement for intermediate Scene candidates."""

from __future__ import annotations

import asyncio
import inspect
import os
from collections import defaultdict
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any

from modules.imports.deep_import_retry import run_deep_import_llm_with_retry
from modules.imports.llm_schemas import SceneCandidateOutput
from modules.imports.scene_candidates import (
    SceneCandidate,
    SceneCandidateBatch,
    SceneReinforcementResult,
)

PHASE1A_REINFORCE_CONCURRENCY = 6
PHASE1A_REINFORCE_BATCH_TIMEOUT_SECONDS = 180.0
DEEP_IMPORT_LLM_RETRY_COUNT = 1
DEEP_IMPORT_422_BLOCK_THRESHOLD = 0.40

ChapterProvider = Callable[[SceneCandidateBatch], Awaitable[Sequence[Mapping[str, Any]]]]
Phase1aLLMCallable = Callable[[dict[str, Any]], Awaitable[Any]]
BatchKey = tuple[str, str, int, tuple[int, ...]]


class Phase1aSceneReinforcer:
    """Reinforce Phase 0 batches without merging rounds or writing Scenes."""

    def __init__(
        self,
        llm: Phase1aLLMCallable | Any,
        *,
        concurrency: int | None = None,
        max_retries: int = DEEP_IMPORT_LLM_RETRY_COUNT,
    ) -> None:
        self.llm = llm
        self.concurrency = max(
            1,
            concurrency
            if concurrency is not None
            else _positive_int_env(
                "PHASE1A_REINFORCE_CONCURRENCY",
                PHASE1A_REINFORCE_CONCURRENCY,
            ),
        )
        self.batch_timeout_seconds = _positive_float_env(
            "PHASE1A_REINFORCE_BATCH_TIMEOUT_SECONDS",
            _llm_timeout_default(PHASE1A_REINFORCE_BATCH_TIMEOUT_SECONDS),
        )
        self.max_retries = max_retries

    async def run(
        self,
        *,
        phase0_candidates: Sequence[SceneCandidate],
        chapters: Sequence[Mapping[str, Any]] | None = None,
        chapter_provider: ChapterProvider | None = None,
    ) -> SceneReinforcementResult:
        """Run Phase 1a reinforcement for each Round A/B batch separately."""

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
        quality_stats = _build_quality_stats(
            candidates,
            total_batches=len(ordered_batches),
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
        return _candidate_from_batch(
            batch,
            quality=_quality_for_output(output),
            payload=output.model_dump(mode="json"),
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
    for chapter in sorted(
        chapters,
        key=lambda item: item.get("chapter_index", 10**9),
    ):
        chapter_index = chapter.get("chapter_index", "?")
        title = chapter.get("title") or f"Chapter {chapter_index}"
        content = chapter.get("content") or chapter.get("text") or ""
        parts.append(f"## Chapter {chapter_index}: {title}\n{content}")
    return "\n\n".join(parts)


def _chapter_payload(chapter: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "chapter_index": chapter.get("chapter_index"),
        "title": chapter.get("title", ""),
        "content": chapter.get("content") or chapter.get("text") or "",
    }


def _classify_references(candidates: Sequence[SceneCandidate]) -> dict[str, list[dict]]:
    strong = []
    weak = []
    failed_diagnostics = []
    for candidate in candidates:
        payload = {
            "candidate_id": candidate.candidate_id,
            "source_round": candidate.source_round,
            "source_batch_id": candidate.source_batch_id,
            "source_chapter_indices": candidate.source_chapter_indices,
            "payload": candidate.payload,
        }
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
                    "diagnostics": candidate.diagnostics,
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
            scene.get("title", "")
            for candidate in candidates
            if candidate.quality in {"high", "low"}
            for scene in candidate.payload.get("scenes", [])
            if isinstance(scene, dict)
        ],
    }


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


def _total_timeout_seconds(
    *,
    env_name: str,
    total_batches: int,
    concurrency: int,
    batch_timeout_seconds: float,
) -> float:
    env_timeout = _positive_float_env(env_name, 0.0)
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


def _build_quality_stats(
    candidates: Sequence[SceneCandidate],
    *,
    total_batches: int,
) -> dict[str, Any]:
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
