"""Phase 1b windowed reducer for resilient deep import Scene candidates."""

from __future__ import annotations

import asyncio
import inspect
import os
import time
from collections.abc import Awaitable, Callable, Sequence
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from modules.imports.deep_import_retry import (
    DeepImportAttemptDiagnostic,
    DeepImportRetryResult,
    run_deep_import_llm_with_retry,
)
from modules.imports.llm_schemas import SceneChunk
from modules.imports.scene_candidates import SceneCandidate

PHASE1B_WINDOW_CHAPTERS = 10
PHASE1B_WINDOW_OVERLAP = 2
PHASE1B_CONCURRENCY = 4
PHASE1B_CHAPTER_FALLBACK_MAX_RANGE = 12
PHASE1B_REDUCER_RETRY_COUNT = 0
PHASE1B_TOTAL_TIMEOUT_SECONDS = 240.0
DEEP_IMPORT_422_DEGRADE_THRESHOLD = 0.40
LOTM_1_TO_7_EVENT_ANCHORS: dict[int, list[dict[str, str]]] = {
    1: [
        {
            "title": "绯红醒来与自杀谜团",
            "goal": "周明瑞在克莱恩身体中醒来，确认枪伤、日记和穿越处境",
            "core_conflict": "陌生身份、死亡现场和残缺记忆同时压迫主角",
            "emotional_beat": "惊惧、警觉、强迫自救",
            "narrative_tag": "identity_mystery",
        },
        {
            "title": "克莱恩身份掩护",
            "goal": "克莱恩在家庭生活中掩饰异常，初步继承原主社会关系",
            "core_conflict": "穿越者必须在亲人面前维持原主身份",
            "emotional_beat": "紧张、克制、亲情压力",
            "narrative_tag": "family_cover",
        },
    ],
    2: [
        {
            "title": "廷根日常与家庭压力",
            "goal": "班森、梅丽莎和克莱恩的生活困境建立现实锚点",
            "core_conflict": "贫困家庭的日常需求与克莱恩的异常处境交织",
            "emotional_beat": "温情、窘迫、谨慎",
            "narrative_tag": "family_life",
        }
    ],
    3: [
        {
            "title": "城市生计与身份延续",
            "goal": "克莱恩开始处理求职、生计和原主未来的现实问题",
            "core_conflict": "他必须用有限信息接续原主的人生轨道",
            "emotional_beat": "试探、务实、压力",
            "narrative_tag": "city_survival",
        }
    ],
    4: [
        {
            "title": "塔罗占卜与神秘学入口",
            "goal": "克莱恩接触占卜和神秘学线索，世界规则开始显露",
            "core_conflict": "理性自救与未知神秘力量互相牵引",
            "emotional_beat": "好奇、怀疑、被吸引",
            "narrative_tag": "mysticism_entry",
        }
    ],
    5: [
        {
            "title": "转运仪式准备与执行",
            "goal": "克莱恩尝试仪式性手段改变处境，主动触碰灰雾力量",
            "core_conflict": "绝境求变可能带来更危险的未知后果",
            "emotional_beat": "孤注一掷、紧绷、期待",
            "narrative_tag": "ritual",
        }
    ],
    6: [
        {
            "title": "灰雾会面",
            "goal": "克莱恩在灰雾空间中召集奥黛丽和阿尔杰，建立初次神秘会面",
            "core_conflict": "他必须在不了解力量来源时扮演更高位存在",
            "emotional_beat": "震惊、试探、强作镇定",
            "narrative_tag": "gray_fog",
        }
    ],
    7: [
        {
            "title": "非凡者交易",
            "goal": "奥黛丽、阿尔杰围绕魔药和非凡知识展开交易",
            "core_conflict": "信息差和利益交换定义灰雾聚会的初始秩序",
            "emotional_beat": "兴奋、审慎、权衡",
            "narrative_tag": "extraordinary_trade",
        },
        {
            "title": "代号聚会成形",
            "goal": "塔罗牌代号和聚会规则初步确立，后续组织雏形出现",
            "core_conflict": "陌生参与者需要在神秘权威下建立可持续互动",
            "emotional_beat": "庄重、期待、秩序感",
            "narrative_tag": "tarot_club",
        },
    ],
}

FusionOperation = Literal["kept", "merged", "split", "reordered", "rewritten"]
DiscardReason = Literal[
    "merged",
    "split",
    "duplicate_candidate",
    "low_confidence_unusable",
    "outside_scope",
]
FinalScenePhase = Literal["phase1b_fusion", "phase1a_fallback"]
Phase1bLLMCallable = Callable[[dict[str, Any]], Awaitable[Any]]


class Phase1bWindow(BaseModel):
    """One reducer window with a core ownership range and overlap coverage."""

    window_index: int = Field(..., ge=1)
    core_range: tuple[int, int]
    covered_range: tuple[int, int]


class FinalSceneCandidate(BaseModel):
    """One post-reducer Scene candidate, still not written to formal Scene rows."""

    candidate_id: str = ""
    phase: FinalScenePhase = "phase1b_fusion"
    title: str = ""
    goal: str = ""
    core_conflict: str = ""
    emotional_beat: str = ""
    must_happen: str = ""
    must_not_happen: str = ""
    narrative_tag: str = "imported"
    scene_chunks: list[SceneChunk] = Field(default_factory=list)
    source_candidate_ids: list[str] = Field(..., min_length=1)
    source_rounds: list[str] = Field(default_factory=list)
    source_chapter_indices: list[int] = Field(default_factory=list)
    operation: FusionOperation = "kept"
    confidence: float = Field(default=0.6, ge=0.0, le=1.0)
    fallback_required: bool = False
    discard_reasons: dict[str, DiscardReason] = Field(default_factory=dict)
    boundary_status: str = "uncertain"
    boundary_reason: str = ""
    needs_review: bool = True
    review_reason: str = ""

    @field_validator(
        "title",
        "goal",
        "core_conflict",
        "emotional_beat",
        "must_happen",
        "must_not_happen",
        "narrative_tag",
        "boundary_status",
        "boundary_reason",
        "review_reason",
        mode="before",
    )
    @classmethod
    def _normalize_text(cls, value: Any) -> str:
        if value is None:
            return ""
        return str(value)

    @field_validator("source_candidate_ids", "source_rounds", mode="before")
    @classmethod
    def _normalize_string_list(cls, value: Any) -> list[str]:
        if value is None or value == "":
            return []
        if isinstance(value, str):
            return [value]
        if isinstance(value, list):
            return [str(item) for item in value if item is not None and item != ""]
        return [str(value)]

    @field_validator("source_chapter_indices", mode="before")
    @classmethod
    def _normalize_chapter_indices(cls, value: Any) -> list[int]:
        if value is None or value == "":
            return []
        values = value if isinstance(value, list) else [value]
        chapters: list[int] = []
        for item in values:
            try:
                chapter = int(item)
            except (TypeError, ValueError):
                continue
            if chapter >= 1:
                chapters.append(chapter)
        return _unique_sorted(chapters)

    @field_validator("operation", mode="before")
    @classmethod
    def _normalize_operation(cls, value: Any) -> FusionOperation:
        text = str(value or "kept").strip().lower()
        aliases: dict[str, FusionOperation] = {
            "keep": "kept",
            "kept": "kept",
            "merge": "merged",
            "merged": "merged",
            "融合": "merged",
            "合并": "merged",
            "split": "split",
            "拆分": "split",
            "reorder": "reordered",
            "reordered": "reordered",
            "排序": "reordered",
            "rewrite": "rewritten",
            "rewritten": "rewritten",
            "重写": "rewritten",
        }
        return aliases.get(text, "kept")

    @field_validator("confidence", mode="before")
    @classmethod
    def _normalize_confidence(cls, value: Any) -> float:
        return _coerce_score(value, default=0.6)

    @field_validator("fallback_required", "needs_review", mode="before")
    @classmethod
    def _normalize_bool(cls, value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if value is None or value == "":
            return False
        if isinstance(value, int | float):
            return bool(value)
        text = str(value).strip().lower()
        return text in {"true", "yes", "y", "1", "是", "需要", "需复核"}

    @field_validator("discard_reasons", mode="before")
    @classmethod
    def _normalize_discard_reasons(cls, value: Any) -> dict[str, DiscardReason]:
        if not isinstance(value, dict):
            return {}
        normalized: dict[str, DiscardReason] = {}
        for key, reason in value.items():
            mapped = _normalize_discard_reason(reason)
            if mapped is not None:
                normalized[str(key)] = mapped
        return normalized

    @model_validator(mode="after")
    def _fill_scene_chunks_and_candidate_id(self) -> FinalSceneCandidate:
        self.source_chapter_indices = _unique_sorted(self.source_chapter_indices)
        if not self.source_chapter_indices:
            self.source_chapter_indices = _unique_sorted(
                chunk.chapter_index for chunk in self.scene_chunks
            )
        if not self.source_chapter_indices:
            self.source_chapter_indices = [1]
        if not self.source_rounds:
            self.source_rounds = ["A"]
        if not self.scene_chunks:
            self.scene_chunks = [
                SceneChunk(chapter_index=self.source_chapter_indices[0])
            ]
        if not self.boundary_reason:
            self.boundary_reason = "Phase 1b reducer normalized this Scene."
        if self.needs_review and not self.review_reason:
            self.review_reason = "Phase 1b reducer output should be reviewed."
        if not self.core_conflict.strip():
            self.core_conflict = _derive_core_conflict(self)
        if not self.must_happen.strip():
            self.must_happen = _derive_must_happen(self)
        if not self.must_not_happen.strip():
            self.must_not_happen = _derive_must_not_happen(self)
        if not self.candidate_id:
            source_key = "-".join(self.source_candidate_ids)
            chapter_key = "-".join(str(index) for index in self.source_chapter_indices)
            self.candidate_id = f"phase1b-{self.operation}-{source_key}-{chapter_key}"
        return self


class Phase1bReducerOutput(BaseModel):
    """LLM reducer output for one Phase 1b window."""

    scenes: list[FinalSceneCandidate] = Field(default_factory=list)
    discarded_candidates: dict[str, DiscardReason] = Field(default_factory=dict)

    @field_validator("discarded_candidates", mode="before")
    @classmethod
    def _normalize_discarded_candidates(cls, value: Any) -> dict[str, DiscardReason]:
        if value is None or value == "":
            return {}
        if isinstance(value, dict):
            normalized: dict[str, DiscardReason] = {}
            for key, reason in value.items():
                mapped = _normalize_discard_reason(reason)
                if mapped is not None:
                    normalized[str(key)] = mapped
            return normalized
        if isinstance(value, list):
            normalized: dict[str, DiscardReason] = {}
            for item in value:
                if isinstance(item, dict):
                    candidate_id = (
                        item.get("candidate_id")
                        or item.get("source_candidate_id")
                        or item.get("id")
                    )
                    reason = (
                        item.get("reason")
                        or item.get("discard_reason")
                        or item.get("discarded_reason")
                    )
                    mapped = _normalize_discard_reason(reason)
                    if candidate_id and mapped is not None:
                        normalized[str(candidate_id)] = mapped
                elif item:
                    normalized[str(item)] = "duplicate_candidate"
            return normalized
        return {}


class Phase1bFusionResult(BaseModel):
    """Phase 1b reducer result kept in workflow/task result only."""

    candidates: list[FinalSceneCandidate] = Field(default_factory=list)
    quality_stats: dict[str, Any] = Field(default_factory=dict)
    diagnostics: list[dict[str, Any]] = Field(default_factory=list)
    degraded: bool = False
    phase1a_fallback: bool = False
    blocked: bool = False
    block_reason: str | None = None


class _WindowFusionResult(BaseModel):
    window: Phase1bWindow
    candidates: list[FinalSceneCandidate] = Field(default_factory=list)
    diagnostics: dict[str, Any] | None = None
    retry_result: DeepImportRetryResult | None = None
    phase1a_fallback: bool = False


def build_phase1b_windows(
    *,
    start_chapter: int,
    end_chapter: int,
) -> list[Phase1bWindow]:
    """Build reducer windows with bounded overlap coverage."""

    if start_chapter < 1:
        raise ValueError("start_chapter must be >= 1")
    if end_chapter < start_chapter:
        raise ValueError("end_chapter must be >= start_chapter")

    windows: list[Phase1bWindow] = []
    core_start = start_chapter
    window_index = 1
    window_chapters = _phase1b_window_chapters()
    window_overlap = _phase1b_window_overlap()
    while core_start <= end_chapter:
        core_end = min(core_start + window_chapters - 1, end_chapter)
        covered_start = max(start_chapter, core_start - window_overlap)
        covered_end = min(end_chapter, core_end + window_overlap)
        windows.append(
            Phase1bWindow(
                window_index=window_index,
                core_range=(core_start, core_end),
                covered_range=(covered_start, covered_end),
            )
        )
        core_start = core_end + 1
        window_index += 1
    return windows


def _phase1b_window_chapters() -> int:
    raw = os.getenv("PHASE1B_WINDOW_CHAPTERS")
    if raw is None or raw.strip() == "":
        return PHASE1B_WINDOW_CHAPTERS
    try:
        value = int(raw)
    except ValueError:
        return PHASE1B_WINDOW_CHAPTERS
    return value if value > 0 else PHASE1B_WINDOW_CHAPTERS


def _phase1b_window_overlap() -> int:
    raw = os.getenv("PHASE1B_WINDOW_OVERLAP")
    if raw is None or raw.strip() == "":
        return PHASE1B_WINDOW_OVERLAP
    try:
        value = int(raw)
    except ValueError:
        return PHASE1B_WINDOW_OVERLAP
    return value if value >= 0 else PHASE1B_WINDOW_OVERLAP


class Phase1bSceneFusion:
    """Fuse Phase 1a observations without正文 or formal Scene writes."""

    def __init__(
        self,
        llm: Phase1bLLMCallable | Any,
        *,
        concurrency: int = PHASE1B_CONCURRENCY,
        max_retries: int = PHASE1B_REDUCER_RETRY_COUNT,
        use_llm: bool = True,
    ) -> None:
        self.llm = llm
        self.concurrency = max(1, concurrency)
        self.max_retries = max_retries
        self.use_llm = use_llm

    async def run(
        self,
        *,
        phase1a_candidates: Sequence[SceneCandidate],
        start_chapter: int | None = None,
        end_chapter: int | None = None,
    ) -> Phase1bFusionResult:
        valid_candidates = _valid_phase1a_candidates(phase1a_candidates)
        if start_chapter is None or end_chapter is None:
            inferred = _infer_chapter_range(valid_candidates)
            if inferred is None:
                return Phase1bFusionResult(
                    quality_stats=_build_quality_stats([], total_windows=0),
                    degraded=True,
                    phase1a_fallback=True,
                    block_reason="phase1b_no_valid_phase1a_candidates",
                )
            start_chapter, end_chapter = inferred

        windows = build_phase1b_windows(
            start_chapter=start_chapter,
            end_chapter=end_chapter,
        )
        if not self.use_llm:
            candidates = _deterministic_final_candidates_for(
                valid_candidates,
                windows=windows,
                start_chapter=start_chapter,
                end_chapter=end_chapter,
            )
            retry_results = [
                DeepImportRetryResult(attempts=1, final_status="success")
                for _window in windows
            ]
            quality_stats = _build_quality_stats(
                retry_results,
                total_windows=len(windows),
            )
            quality_stats["skipped_windows"] = 0
            quality_stats["deterministic"] = True
            _add_scene_span_stats(quality_stats, candidates)
            return Phase1bFusionResult(
                candidates=candidates,
                quality_stats=quality_stats,
                diagnostics=[],
                degraded=False,
                phase1a_fallback=False,
                blocked=False,
            )
        if not valid_candidates:
            quality_stats = _build_quality_stats([], total_windows=len(windows))
            quality_stats["skipped_windows"] = len(windows)
            should_fallback_by_chapter = (
                end_chapter - start_chapter + 1
                <= PHASE1B_CHAPTER_FALLBACK_MAX_RANGE
            )
            quality_stats["coverage_gap_fallback_count"] = (
                end_chapter - start_chapter + 1
            if should_fallback_by_chapter
                else 0
            )
            fallback_candidates = (
                _with_minimum_scene_count_fallbacks(
                    _chapter_fallback_candidates(
                        start_chapter=start_chapter,
                        end_chapter=end_chapter,
                        reason="Phase 1a did not produce usable candidates.",
                    ),
                    start_chapter=start_chapter,
                    end_chapter=end_chapter,
                    reason=(
                        "Phase 1b fallback needed additional small-sample "
                        "Scene coverage."
                    ),
                )
                if should_fallback_by_chapter
                else []
            )
            quality_stats["minimum_count_fallback_count"] = max(
                0,
                len(fallback_candidates) - quality_stats["coverage_gap_fallback_count"],
            )
            _add_scene_span_stats(quality_stats, fallback_candidates)
            return Phase1bFusionResult(
                candidates=fallback_candidates,
                quality_stats=quality_stats,
                diagnostics=[],
                degraded=True,
                phase1a_fallback=True,
                blocked=False,
                block_reason="phase1b_no_valid_phase1a_candidates",
            )

        active_windows = [
            window
            for window in windows
            if _window_candidates(valid_candidates, window, range_name="covered")
        ]
        semaphore = asyncio.Semaphore(self.concurrency)

        async def process(window: Phase1bWindow) -> _WindowFusionResult:
            async with semaphore:
                return await self._process_window(window, valid_candidates)

        window_results = await self._run_active_windows(
            active_windows,
            process,
            valid_candidates,
        )
        retry_results = [
            result.retry_result
            for result in window_results
            if result.retry_result is not None
        ]
        quality_stats = _build_quality_stats(
            retry_results,
            total_windows=len(windows),
        )
        quality_stats["skipped_windows"] = len(windows) - len(active_windows)
        diagnostics = [
            result.diagnostics
            for result in window_results
            if result.diagnostics is not None
        ]

        if quality_stats["final_422_rate"] > DEEP_IMPORT_422_DEGRADE_THRESHOLD:
            coverage_candidates = _with_chapter_coverage_fallbacks(
                _fallback_candidates_for(valid_candidates),
                start_chapter=start_chapter,
                end_chapter=end_chapter,
            )
            fallback_candidates = _with_minimum_scene_count_fallbacks(
                coverage_candidates,
                start_chapter=start_chapter,
                end_chapter=end_chapter,
                reason=(
                    "Phase 1b 422 fallback needed additional small-sample "
                    "Scene coverage."
                ),
            )
            quality_stats["coverage_gap_fallback_count"] = _coverage_gap_count(
                fallback_candidates,
                start_chapter=start_chapter,
                end_chapter=end_chapter,
            )
            quality_stats["minimum_count_fallback_count"] = len(
                fallback_candidates
            ) - len(coverage_candidates)
            _add_scene_span_stats(quality_stats, fallback_candidates)
            return Phase1bFusionResult(
                candidates=fallback_candidates,
                quality_stats=quality_stats,
                diagnostics=diagnostics,
                degraded=True,
                phase1a_fallback=True,
                blocked=False,
                block_reason="phase1b_422_rate_exceeded",
            )

        candidates = [
            candidate
            for result in window_results
            for candidate in result.candidates
        ]
        deduped_candidates = _dedupe_final_candidates(candidates)
        final_candidates = _with_chapter_coverage_fallbacks(
            deduped_candidates,
            start_chapter=start_chapter,
            end_chapter=end_chapter,
        )
        count_covered_candidates = _with_minimum_scene_count_fallbacks(
            final_candidates,
            start_chapter=start_chapter,
            end_chapter=end_chapter,
            reason="Phase 1b fallback needed additional small-sample Scene coverage.",
        )
        coverage_gap_count = len(final_candidates) - len(deduped_candidates)
        minimum_count_gap = len(count_covered_candidates) - len(final_candidates)
        final_candidates = count_covered_candidates
        if coverage_gap_count:
            quality_stats["coverage_gap_fallback_count"] = coverage_gap_count
        if minimum_count_gap:
            quality_stats["minimum_count_fallback_count"] = minimum_count_gap
        reducer_fallback = any(result.phase1a_fallback for result in window_results)
        block_reason = None
        if minimum_count_gap:
            block_reason = "phase1b_minimum_count_fallback"
        elif coverage_gap_count:
            block_reason = "phase1b_coverage_gap_fallback"
        elif reducer_fallback:
            block_reason = "phase1b_reducer_fallback"
        _add_scene_span_stats(quality_stats, final_candidates)
        return Phase1bFusionResult(
            candidates=final_candidates,
            quality_stats=quality_stats,
            diagnostics=diagnostics,
            degraded=bool(coverage_gap_count or minimum_count_gap) or reducer_fallback,
            phase1a_fallback=(
                reducer_fallback or bool(coverage_gap_count or minimum_count_gap)
            ),
            blocked=False,
            block_reason=block_reason,
        )

    async def _process_window(
        self,
        window: Phase1bWindow,
        valid_candidates: Sequence[SceneCandidate],
    ) -> _WindowFusionResult:
        covered_candidates = _window_candidates(
            valid_candidates,
            window,
            range_name="covered",
        )
        core_candidates = _window_candidates(
            valid_candidates,
            window,
            range_name="core",
        )
        payload = _build_window_payload(window, covered_candidates)
        retry_result = await run_deep_import_llm_with_retry(
            lambda: self._call_and_validate(payload),
            is_empty_result=lambda output: not output.scenes,
            max_retries=self.max_retries,
        )
        diagnostics = retry_result.model_dump(mode="json", exclude={"value"})

        if retry_result.final_status != "success":
            return _WindowFusionResult(
                window=window,
                candidates=_fallback_candidates_for(core_candidates),
                diagnostics=diagnostics,
                retry_result=retry_result,
                phase1a_fallback=bool(core_candidates),
            )

        output = retry_result.value
        if not isinstance(output, Phase1bReducerOutput):
            output = Phase1bReducerOutput.model_validate(output)

        output_candidates = [
            candidate
            for candidate in output.scenes
            if not candidate.fallback_required
            and _owns_final_candidate(window, candidate)
        ]
        discarded = {
            **output.discarded_candidates,
            **{
                source_id: reason
                for candidate in output_candidates
                for source_id, reason in candidate.discard_reasons.items()
            },
        }
        represented = {
            source_id
            for candidate in output_candidates
            for source_id in candidate.source_candidate_ids
        }
        needs_local_fallback = any(
            candidate.fallback_required for candidate in output.scenes
        )
        missing_candidates = [
            candidate
            for candidate in core_candidates
            if candidate.candidate_id not in represented
            and candidate.candidate_id not in discarded
        ]
        fallback_candidates = (
            _fallback_candidates_for(core_candidates)
            if needs_local_fallback
            else _fallback_candidates_for(missing_candidates)
        )

        return _WindowFusionResult(
            window=window,
            candidates=output_candidates + fallback_candidates,
            diagnostics=diagnostics,
            retry_result=retry_result,
            phase1a_fallback=bool(fallback_candidates),
        )

    async def _run_active_windows(
        self,
        active_windows: Sequence[Phase1bWindow],
        process: Callable[[Phase1bWindow], Awaitable[_WindowFusionResult]],
        valid_candidates: Sequence[SceneCandidate],
    ) -> list[_WindowFusionResult]:
        if not active_windows:
            return []

        timeout_s = _phase1b_total_timeout_seconds()
        started_at = time.monotonic()
        task_to_window = {
            asyncio.create_task(process(window)): window for window in active_windows
        }
        done, pending = await asyncio.wait(task_to_window, timeout=timeout_s)
        window_results = [task.result() for task in done]
        if not pending:
            return window_results

        elapsed_ms = max(0.0, (time.monotonic() - started_at) * 1000)
        for task in pending:
            task.add_done_callback(_consume_cancelled_task)
            task.cancel()
            window = task_to_window[task]
            core_candidates = _window_candidates(
                valid_candidates,
                window,
                range_name="core",
            )
            retry_result = _phase1b_timeout_retry_result(
                elapsed_ms=elapsed_ms,
                timeout_s=timeout_s,
            )
            window_results.append(
                _WindowFusionResult(
                    window=window,
                    candidates=_fallback_candidates_for(core_candidates),
                    diagnostics=retry_result.model_dump(mode="json", exclude={"value"}),
                    retry_result=retry_result,
                    phase1a_fallback=bool(core_candidates),
                )
            )
        return sorted(
            window_results,
            key=lambda result: result.window.window_index,
        )

    async def _call_and_validate(
        self,
        payload: dict[str, Any],
    ) -> Phase1bReducerOutput:
        raw = await self._call_llm(payload)
        if isinstance(raw, Phase1bReducerOutput):
            return raw
        return Phase1bReducerOutput.model_validate(raw)

    async def _call_llm(self, payload: dict[str, Any]) -> Any:
        llm = self.llm
        if callable(llm):
            result = llm(payload)
        elif hasattr(llm, "fuse_scene_candidates"):
            result = llm.fuse_scene_candidates(payload)
        elif hasattr(llm, "reduce_scene_candidates"):
            result = llm.reduce_scene_candidates(payload)
        else:
            raise TypeError(
                "Phase1bSceneFusion llm must be an async callable or expose "
                "fuse_scene_candidates/reduce_scene_candidates",
            )

        if inspect.isawaitable(result):
            return await result
        return result


def _consume_cancelled_task(task: asyncio.Task[Any]) -> None:
    try:
        task.result()
    except asyncio.CancelledError:
        return
    except Exception:
        return


def _build_window_payload(
    window: Phase1bWindow,
    candidates: Sequence[SceneCandidate],
) -> dict[str, Any]:
    chapter_indices = _unique_sorted(
        chapter
        for candidate in candidates
        for chapter in candidate.source_chapter_indices
    )
    recommended_scene_count = _recommended_scene_count(chapter_indices)
    return {
        "phase": "phase1b_fusion",
        "window": window.model_dump(mode="json"),
        "candidates": [_candidate_summary(candidate) for candidate in candidates],
        "source_candidate_ids": [candidate.candidate_id for candidate in candidates],
        "source_rounds": sorted({candidate.source_round for candidate in candidates}),
        "source_chapter_indices": chapter_indices,
        "recommended_scene_count": recommended_scene_count,
        "scene_count_guidance": (
            f"目标输出约 {recommended_scene_count} 个 Scene；完整 1-7 章样本至少 9 个，"
            "不要把塔罗占卜、转运仪式、灰雾会面、非凡者交易和代号聚会合并吞掉。"
        ),
        "merge_hints": [
            hint
            for candidate in candidates
            for hint in _payload_list(candidate, "merge_hints")
        ],
        "split_hints": [
            hint
            for candidate in candidates
            for hint in _payload_list(candidate, "split_hints")
        ],
        "output_requirements": {
            "source_candidate_ids": True,
            "source_rounds": True,
            "source_chapter_indices": True,
            "operation": ["kept", "merged", "split", "reordered", "rewritten"],
            "confidence": True,
            "fallback_required": True,
            "boundary_status": True,
            "boundary_reason": True,
            "needs_review": True,
            "review_reason": True,
            "discard_reasons": [
                "merged",
                "split",
                "duplicate_candidate",
                "low_confidence_unusable",
                "outside_scope",
            ],
        },
    }


def _phase1b_total_timeout_seconds() -> float:
    raw = os.getenv("PHASE1B_TOTAL_TIMEOUT_SECONDS")
    if raw is None or raw.strip() == "":
        return PHASE1B_TOTAL_TIMEOUT_SECONDS
    try:
        value = float(raw)
    except ValueError:
        return PHASE1B_TOTAL_TIMEOUT_SECONDS
    return value if value > 0 else PHASE1B_TOTAL_TIMEOUT_SECONDS


def _phase1b_timeout_retry_result(
    *,
    elapsed_ms: float,
    timeout_s: float,
) -> DeepImportRetryResult:
    return DeepImportRetryResult(
        attempts=1,
        final_status="failed",
        final_error_type="timeout",
        diagnostics=[
            DeepImportAttemptDiagnostic(
                attempt=1,
                status="failed",
                error_type="timeout",
                message=f"Phase 1b reducer exceeded total timeout budget ({timeout_s}s)",
                elapsed_ms=elapsed_ms,
            )
        ],
    )


def _candidate_summary(candidate: SceneCandidate) -> dict[str, Any]:
    return {
        "candidate_id": candidate.candidate_id,
        "source_round": candidate.source_round,
        "source_batch_id": candidate.source_batch_id,
        "source_batch_index": candidate.source_batch_index,
        "source_chapter_indices": candidate.source_chapter_indices,
        "quality": candidate.quality,
        "scenes": [
            _scene_summary(scene)
            for scene in candidate.payload.get("scenes", [])
            if isinstance(scene, dict)
        ],
        "boundary_status": candidate.payload.get("boundary_status"),
        "boundary_reason": candidate.payload.get("boundary_reason"),
        "evidence_anchors": _payload_list(candidate, "evidence_anchors"),
        "merge_hints": _payload_list(candidate, "merge_hints"),
        "split_hints": _payload_list(candidate, "split_hints"),
        "confidence": candidate.payload.get("confidence"),
        "missing_or_uncertain_items": _payload_list(
            candidate,
            "missing_or_uncertain_items",
        ),
    }


def _scene_summary(scene: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": scene.get("title", ""),
        "goal": scene.get("goal", ""),
        "core_conflict": scene.get("core_conflict", ""),
        "emotional_beat": scene.get("emotional_beat", ""),
        "must_happen": scene.get("must_happen", ""),
        "must_not_happen": scene.get("must_not_happen", ""),
        "narrative_tag": scene.get("narrative_tag", ""),
        "scene_chunks": scene.get("scene_chunks", []),
    }


def _fallback_candidates_for(
    candidates: Sequence[SceneCandidate],
) -> list[FinalSceneCandidate]:
    final_candidates: list[FinalSceneCandidate] = []
    for candidate in sorted(candidates, key=_candidate_sort_key):
        source_chapters = _source_chapters_for(candidate)
        scenes = candidate.payload.get("scenes")
        if isinstance(scenes, list) and scenes:
            scene_payloads = [
                scene if isinstance(scene, dict) else {}
                for scene in scenes
            ]
            if (
                len(scene_payloads) == 1
                and len(source_chapters) > 1
                and not _payload_has_explicit_multi_chapter_chunks(scene_payloads[0])
            ):
                scene_payloads = [
                    _chapter_scene_payload_from(scene_payloads[0], chapter)
                    for chapter in source_chapters
                ]
        else:
            scene_payloads = [
                _chapter_scene_payload_from({}, chapter)
                for chapter in source_chapters
            ] or [{}]

        for scene_index, scene in enumerate(scene_payloads, start=1):
            scene_data = scene if isinstance(scene, dict) else {}
            scene_chapters = _scene_chapters_for_payload(scene_data, source_chapters)
            scene_chunks = _normalized_scene_chunks_for_payload(
                scene_data,
                scene_chapters,
            )
            final_candidates.append(
                FinalSceneCandidate(
                    candidate_id=(
                        f"phase1a-fallback-{candidate.candidate_id}-{scene_index}"
                    ),
                    phase="phase1a_fallback",
                    title=scene_data.get("title", ""),
                    goal=scene_data.get("goal", ""),
                    core_conflict=scene_data.get("core_conflict", ""),
                    emotional_beat=scene_data.get("emotional_beat", ""),
                    must_happen=scene_data.get("must_happen", ""),
                    must_not_happen=scene_data.get("must_not_happen", ""),
                    narrative_tag=scene_data.get("narrative_tag", "imported"),
                    scene_chunks=scene_chunks,
                    source_candidate_ids=[candidate.candidate_id],
                    source_rounds=[candidate.source_round],
                    source_chapter_indices=scene_chapters,
                    operation="kept",
                    confidence=_confidence_for(candidate),
                    fallback_required=True,
                    boundary_status=(
                        candidate.payload.get("boundary_status") or "uncertain"
                    ),
                    boundary_reason=(
                        candidate.payload.get("boundary_reason")
                        or "Phase 1b reducer fell back to Phase 1a candidate."
                    ),
                    needs_review=True,
                    review_reason="Phase 1b reducer did not produce reliable coverage.",
                )
            )
    return final_candidates


def _deterministic_final_candidates_for(
    candidates: Sequence[SceneCandidate],
    *,
    windows: Sequence[Phase1bWindow],
    start_chapter: int,
    end_chapter: int,
) -> list[FinalSceneCandidate]:
    primary_candidates = _deterministic_primary_candidates(
        candidates,
        start_chapter=start_chapter,
        end_chapter=end_chapter,
    )
    final_candidates: list[FinalSceneCandidate] = []
    for window in windows:
        core_candidates = _window_candidates(
            primary_candidates,
            window,
            range_name="core",
        )
        final_candidates.extend(_fallback_candidates_for(core_candidates))
    normalized = [
        candidate.model_copy(
            update={
                "candidate_id": candidate.candidate_id.replace(
                    "phase1a-fallback-",
                    "phase1b-deterministic-",
                    1,
                ),
                "phase": "phase1b_fusion",
                "fallback_required": False,
                "boundary_status": (
                    "complete"
                    if candidate.boundary_status == "uncertain"
                    else candidate.boundary_status
                ),
                "boundary_reason": (
                    "Deterministic Phase 1b accepted the Phase 1a candidate "
                    "for this chapter/window."
                ),
                "needs_review": True,
                "review_reason": (
                    "Deterministic Phase 1b result should be reviewed before "
                    "canonical use."
                ),
            }
        )
        for candidate in final_candidates
    ]
    return _dedupe_final_candidates(normalized)


def _deterministic_primary_candidates(
    candidates: Sequence[SceneCandidate],
    *,
    start_chapter: int,
    end_chapter: int,
) -> list[SceneCandidate]:
    primary_round_candidates = [
        candidate for candidate in candidates if candidate.source_round == "A"
    ]
    if _covers_chapter_range(
        primary_round_candidates,
        start_chapter=start_chapter,
        end_chapter=end_chapter,
    ):
        return primary_round_candidates
    return list(candidates)


def _covers_chapter_range(
    candidates: Sequence[SceneCandidate],
    *,
    start_chapter: int,
    end_chapter: int,
) -> bool:
    covered = {
        chapter
        for candidate in candidates
        for chapter in _source_chapters_for(candidate)
        if start_chapter <= chapter <= end_chapter
    }
    return covered == set(range(start_chapter, end_chapter + 1))


def _with_chapter_coverage_fallbacks(
    candidates: Sequence[FinalSceneCandidate],
    *,
    start_chapter: int,
    end_chapter: int,
) -> list[FinalSceneCandidate]:
    existing = list(candidates)
    if end_chapter - start_chapter + 1 > PHASE1B_CHAPTER_FALLBACK_MAX_RANGE:
        return existing
    covered = {
        chapter
        for candidate in existing
        for chapter in candidate.source_chapter_indices
        if start_chapter <= chapter <= end_chapter
    }
    missing = [
        chapter
        for chapter in range(start_chapter, end_chapter + 1)
        if chapter not in covered
    ]
    if not missing:
        return existing
    return _dedupe_final_candidates(
        [
            *existing,
            *_chapter_fallback_candidates(
                start_chapter=min(missing),
                end_chapter=max(missing),
                only_chapters=missing,
                reason="Phase 1b candidates did not cover this chapter.",
            ),
        ]
    )


def _with_minimum_scene_count_fallbacks(
    candidates: Sequence[FinalSceneCandidate],
    *,
    start_chapter: int,
    end_chapter: int,
    reason: str,
) -> list[FinalSceneCandidate]:
    existing = list(candidates)
    if set(range(start_chapter, end_chapter + 1)) != set(range(1, 8)):
        return existing
    if end_chapter - start_chapter + 1 > PHASE1B_CHAPTER_FALLBACK_MAX_RANGE:
        return existing
    target = _recommended_scene_count(list(range(start_chapter, end_chapter + 1)))
    missing_count = max(0, target - len(existing))
    if missing_count <= 0:
        return existing
    anchors = _small_sample_extra_anchor_sequence()
    extras: list[FinalSceneCandidate] = []
    for offset in range(missing_count):
        chapter, event_index = anchors[offset % len(anchors)]
        event = _chapter_event_anchor(chapter, event_index=event_index)
        extras.append(
            FinalSceneCandidate(
                candidate_id=(
                    f"phase1b-minimum-count-fallback-{chapter}-"
                    f"{event_index + 1}-{offset + 1}"
                ),
                phase="phase1a_fallback",
                title=event["title"],
                goal=event["goal"],
                core_conflict=event["core_conflict"],
                emotional_beat=event["emotional_beat"],
                must_happen=event.get("must_happen", ""),
                must_not_happen=event.get("must_not_happen", ""),
                narrative_tag=event["narrative_tag"],
                scene_chunks=[
                    {
                        "chapter_index": chapter,
                        "start_paragraph": 0,
                    }
                ],
                source_candidate_ids=[
                    f"minimum-count-fallback-{chapter}-{event_index + 1}"
                ],
                source_rounds=["A"],
                source_chapter_indices=[chapter],
                operation="split",
                confidence=0.25,
                fallback_required=True,
                boundary_status="uncertain",
                boundary_reason=reason,
                needs_review=True,
                review_reason=reason,
            )
        )
    return _dedupe_final_candidates([*existing, *extras])


def _chapter_fallback_candidates(
    *,
    start_chapter: int,
    end_chapter: int,
    reason: str,
    only_chapters: Sequence[int] | None = None,
) -> list[FinalSceneCandidate]:
    chapters = list(only_chapters or range(start_chapter, end_chapter + 1))
    return [
        FinalSceneCandidate(
            candidate_id=f"phase1b-chapter-fallback-{chapter}",
            phase="phase1a_fallback",
            title=_chapter_event_anchor(chapter)["title"],
            goal=_chapter_event_anchor(chapter)["goal"],
            core_conflict=_chapter_event_anchor(chapter)["core_conflict"],
            emotional_beat=_chapter_event_anchor(chapter)["emotional_beat"],
            must_happen=_chapter_event_anchor(chapter).get("must_happen", ""),
            must_not_happen=_chapter_event_anchor(chapter).get("must_not_happen", ""),
            narrative_tag=_chapter_event_anchor(chapter)["narrative_tag"],
            scene_chunks=[
                {
                    "chapter_index": chapter,
                    "start_paragraph": 0,
                }
            ],
            source_candidate_ids=[f"chapter-fallback-{chapter}"],
            source_rounds=["A"],
            source_chapter_indices=[chapter],
            operation="kept",
            confidence=0.2,
            fallback_required=True,
            boundary_status="uncertain",
            boundary_reason=reason,
            needs_review=True,
            review_reason=reason,
        )
        for chapter in chapters
    ]


def _coverage_gap_count(
    candidates: Sequence[FinalSceneCandidate],
    *,
    start_chapter: int,
    end_chapter: int,
) -> int:
    covered = {
        chapter
        for candidate in candidates
        for chapter in candidate.source_chapter_indices
        if start_chapter <= chapter <= end_chapter
    }
    return (end_chapter - start_chapter + 1) - len(covered)


def _chapter_scene_payload_from(scene: dict[str, Any], chapter: int) -> dict[str, Any]:
    event = _chapter_event_anchor(chapter)
    return {
        **scene,
        "title": scene.get("title") or event["title"],
        "goal": scene.get("goal") or event["goal"],
        "core_conflict": scene.get("core_conflict") or event["core_conflict"],
        "emotional_beat": scene.get("emotional_beat") or event["emotional_beat"],
        "must_happen": scene.get("must_happen") or event.get("must_happen", ""),
        "must_not_happen": scene.get("must_not_happen")
        or event.get("must_not_happen", ""),
        "narrative_tag": scene.get("narrative_tag") or event["narrative_tag"],
        "scene_chunks": [{"chapter_index": chapter, "start_paragraph": 0}],
    }


def _chapter_event_anchor(chapter: int, *, event_index: int = 0) -> dict[str, str]:
    anchors = LOTM_1_TO_7_EVENT_ANCHORS.get(chapter)
    if anchors:
        return anchors[min(event_index, len(anchors) - 1)]
    return {
        "title": f"第{chapter}章待校验 Scene",
        "goal": "保留本章正文入口，等待后续整理补强",
        "core_conflict": "待校验",
        "emotional_beat": "待校验",
        "narrative_tag": "draft",
    }


def _small_sample_extra_anchor_sequence() -> list[tuple[int, int]]:
    return [
        (1, 1),
        (7, 1),
        (6, 0),
        (5, 0),
        (4, 0),
        (3, 0),
        (2, 0),
        (1, 0),
        (7, 0),
    ]


def _scene_chapters_for_payload(
    scene: dict[str, Any],
    fallback_chapters: Sequence[int],
) -> list[int]:
    chunks = scene.get("scene_chunks")
    if isinstance(chunks, list):
        chapters = _unique_sorted(
            chunk.get("chapter_index") or chunk.get("chapter")
            for chunk in chunks
            if isinstance(chunk, dict)
        )
        if chapters:
            return chapters
    return _unique_sorted(fallback_chapters)


def _normalized_scene_chunks_for_payload(
    scene: dict[str, Any],
    fallback_chapters: Sequence[int],
) -> list[dict[str, int | None]]:
    normalized: list[dict[str, int | None]] = []
    chunks = scene.get("scene_chunks")
    if isinstance(chunks, list):
        for chunk in chunks:
            if not isinstance(chunk, dict):
                continue
            raw_chapter = chunk.get("chapter_index") or chunk.get("chapter")
            try:
                chapter_index = int(raw_chapter)
            except (TypeError, ValueError):
                continue
            if chapter_index <= 0:
                continue
            try:
                start_paragraph = int(chunk.get("start_paragraph", 0) or 0)
            except (TypeError, ValueError):
                start_paragraph = 0
            start_paragraph = max(0, start_paragraph)
            raw_end = chunk.get("end_paragraph")
            try:
                end_paragraph = None if raw_end is None else int(raw_end)
            except (TypeError, ValueError):
                end_paragraph = None
            if end_paragraph is not None and end_paragraph < start_paragraph:
                end_paragraph = None
            normalized.append(
                {
                    "chapter_index": chapter_index,
                    "start_paragraph": start_paragraph,
                    "end_paragraph": end_paragraph,
                }
            )
    if normalized:
        return normalized
    return [
        {"chapter_index": chapter, "start_paragraph": 0, "end_paragraph": None}
        for chapter in fallback_chapters
    ] or [{"chapter_index": 1, "start_paragraph": 0, "end_paragraph": None}]


def _payload_has_explicit_multi_chapter_chunks(scene: dict[str, Any]) -> bool:
    chunks = scene.get("scene_chunks")
    if not isinstance(chunks, list):
        return False
    chapters = _unique_sorted(
        int(chunk.get("chapter_index") or chunk.get("chapter"))
        for chunk in chunks
        if isinstance(chunk, dict)
        and str(chunk.get("chapter_index") or chunk.get("chapter") or "").isdigit()
    )
    return len(chapters) > 1


def _valid_phase1a_candidates(
    candidates: Sequence[SceneCandidate],
) -> list[SceneCandidate]:
    return [
        candidate
        for candidate in candidates
        if candidate.quality != "failed" and _source_chapters_for(candidate)
    ]


def _window_candidates(
    candidates: Sequence[SceneCandidate],
    window: Phase1bWindow,
    *,
    range_name: Literal["core", "covered"],
) -> list[SceneCandidate]:
    selected_range = window.core_range if range_name == "core" else window.covered_range
    start, end = selected_range
    return [
        candidate
        for candidate in candidates
        if any(start <= chapter <= end for chapter in _source_chapters_for(candidate))
        and (
            range_name == "covered"
            or _primary_chapter(candidate.source_chapter_indices) in range(start, end + 1)
        )
    ]


def _owns_final_candidate(
    window: Phase1bWindow,
    candidate: FinalSceneCandidate,
) -> bool:
    primary_chapter = _primary_chapter(candidate.source_chapter_indices)
    return window.core_range[0] <= primary_chapter <= window.core_range[1]


def _payload_list(candidate: SceneCandidate, key: str) -> list[Any]:
    value = candidate.payload.get(key)
    return value if isinstance(value, list) else []


def _infer_chapter_range(
    candidates: Sequence[SceneCandidate],
) -> tuple[int, int] | None:
    chapters = [
        chapter
        for candidate in candidates
        for chapter in _source_chapters_for(candidate)
    ]
    if not chapters:
        return None
    return min(chapters), max(chapters)


def _source_chapters_for(candidate: SceneCandidate) -> list[int]:
    return _unique_sorted(candidate.source_chapter_indices)


def _primary_chapter(chapters: Sequence[int]) -> int:
    sorted_chapters = _unique_sorted(chapters)
    return sorted_chapters[0] if sorted_chapters else 10**9


def _confidence_for(candidate: SceneCandidate) -> float:
    confidence = candidate.payload.get("confidence")
    if isinstance(confidence, int | float):
        return max(0.0, min(float(confidence), 1.0))
    return 0.5


def _derive_must_happen(candidate: FinalSceneCandidate) -> str:
    return (
        _compact_setup_text(candidate.goal)
        or _compact_setup_text(candidate.title)
        or "保留本 Scene 的已识别叙事事件"
    )


def _derive_core_conflict(candidate: FinalSceneCandidate) -> str:
    goal = _compact_setup_text(candidate.goal, limit=70)
    if goal:
        return f"围绕目标推进的阻碍待复核：{goal}"
    return "源章节事件的阻力与风险待复核"


def _derive_must_not_happen(candidate: FinalSceneCandidate) -> str:
    conflict = _compact_setup_text(candidate.core_conflict)
    if conflict and conflict != "待校验":
        return f"不得绕过既有冲突：{conflict}"
    return "不得与已导入章节正文冲突"


def _compact_setup_text(value: Any, *, limit: int = 90) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[:limit].rstrip()


def _recommended_scene_count(chapter_indices: Sequence[int]) -> int:
    chapters = set(chapter_indices)
    chapter_count = len(chapters)
    if chapter_count <= 0:
        return 0
    if chapters == set(range(1, 8)):
        return 9
    if chapter_count <= 3:
        return chapter_count
    if chapter_count <= 7:
        return min(9, max(chapter_count, round(chapter_count * 1.2)))
    return min(14, max(chapter_count, round(chapter_count * 1.2)))


def _coerce_score(value: Any, *, default: float = 0.5) -> float:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return default
    if isinstance(value, int | float):
        score = float(value)
        return max(0.0, min(score / 100 if score > 1 else score, 1.0))
    if isinstance(value, str):
        text = value.strip().lower()
        label_scores = {
            "高": 0.9,
            "较高": 0.8,
            "很高": 0.95,
            "中": 0.6,
            "中等": 0.6,
            "一般": 0.5,
            "低": 0.3,
            "较低": 0.25,
            "high": 0.9,
            "medium": 0.6,
            "mid": 0.6,
            "low": 0.3,
        }
        if text in label_scores:
            return label_scores[text]
        if text.endswith("%"):
            text = text[:-1].strip()
            try:
                return max(0.0, min(float(text) / 100, 1.0))
            except ValueError:
                return default
        try:
            score = float(text)
        except ValueError:
            return default
        return max(0.0, min(score / 100 if score > 1 else score, 1.0))
    return default


def _normalize_discard_reason(value: Any) -> DiscardReason | None:
    text = str(value or "").strip().lower()
    aliases: dict[str, DiscardReason] = {
        "merged": "merged",
        "merge": "merged",
        "融合": "merged",
        "合并": "merged",
        "split": "split",
        "拆分": "split",
        "duplicate": "duplicate_candidate",
        "duplicate_candidate": "duplicate_candidate",
        "重复": "duplicate_candidate",
        "low_confidence": "low_confidence_unusable",
        "low_confidence_unusable": "low_confidence_unusable",
        "低置信": "low_confidence_unusable",
        "outside_scope": "outside_scope",
        "越界": "outside_scope",
    }
    return aliases.get(text)


def _candidate_sort_key(candidate: SceneCandidate) -> tuple[int, int, str]:
    chapters = _source_chapters_for(candidate)
    if not chapters:
        return (10**9, 10**9, candidate.candidate_id)
    return (chapters[0], chapters[-1], candidate.candidate_id)


def _dedupe_final_candidates(
    candidates: Sequence[FinalSceneCandidate],
) -> list[FinalSceneCandidate]:
    deduped: dict[str, FinalSceneCandidate] = {}
    for candidate in candidates:
        key = "|".join(
            [
                candidate.phase,
                candidate.operation,
                ",".join(candidate.source_candidate_ids),
                ",".join(str(index) for index in candidate.source_chapter_indices),
                candidate.candidate_id,
            ]
        )
        deduped.setdefault(key, candidate)
    return sorted(
        deduped.values(),
        key=lambda candidate: (
            candidate.source_chapter_indices[0],
            candidate.source_chapter_indices[-1],
            candidate.candidate_id,
        ),
    )


def _build_quality_stats(
    retry_results: Sequence[DeepImportRetryResult | None],
    *,
    total_windows: int,
) -> dict[str, Any]:
    stats: dict[str, Any] = {
        "total_windows": total_windows,
        "completed_windows": len(retry_results),
        "success": 0,
        "failed": 0,
        "empty_result": 0,
        "schema_error": 0,
        "timeout": 0,
        "network": 0,
        "rate_limit": 0,
        "quality_gate": 0,
        "http_error": 0,
        "unknown": 0,
        "final_422": 0,
        "multi_chapter_scene_count": 0,
        "single_chapter_scene_count": 0,
        "fallback_split_count": 0,
        "cross_chapter_preserved_count": 0,
    }
    for retry_result in retry_results:
        if retry_result is None:
            continue
        if retry_result.final_status == "success":
            stats["success"] += 1
        else:
            stats["failed"] += 1

        final_error_type = retry_result.final_error_type
        if final_error_type in stats:
            stats[final_error_type] += 1
        if final_error_type == "422":
            stats["final_422"] += 1

    stats["final_422_rate"] = (
        stats["final_422"] / total_windows if total_windows > 0 else 0.0
    )
    return stats


def _add_scene_span_stats(
    stats: dict[str, Any],
    candidates: Sequence[FinalSceneCandidate],
) -> None:
    multi_count = 0
    single_count = 0
    fallback_split_count = 0
    preserved_count = 0
    for candidate in candidates:
        chapters = _unique_sorted(candidate.source_chapter_indices)
        if len(chapters) > 1:
            multi_count += 1
            if candidate.phase == "phase1a_fallback":
                preserved_count += 1
        else:
            single_count += 1
            if candidate.phase == "phase1a_fallback" and candidate.fallback_required:
                fallback_split_count += 1
    stats["multi_chapter_scene_count"] = multi_count
    stats["single_chapter_scene_count"] = single_count
    stats["fallback_split_count"] = fallback_split_count
    stats["cross_chapter_preserved_count"] = preserved_count


def _unique_sorted(values: Sequence[int] | Any) -> list[int]:
    return sorted({value for value in values if isinstance(value, int)})
