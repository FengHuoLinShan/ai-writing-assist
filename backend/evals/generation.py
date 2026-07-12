"""Schema-guarded case generation and judge calls using local Codex."""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from evals.cache import EvalCache
from evals.codex_executor import CodexStructuredExecutor
from evals.schemas import (
    HIGH_QUALITY_LLM_MODEL,
    METRIC_VERSION,
    RUBRIC_VERSION,
    DatasetCase,
)


class GeneratedCaseInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str | None = None
    text: str | None = None


GeneratedScenario = Literal[
    "exact_name",
    "alias_paraphrase",
    "multi_hop",
    "hard_negative",
    "no_answer",
    "visibility_cutoff",
    "location_shift",
    "goal_shift",
    "weak_boundary",
    "cross_chapter",
    "durable_entity",
    "alias",
    "relation",
    "ordinary_object_negative",
    "thread",
    "foreshadow",
    "duplicate",
    "early_reveal",
]
GeneratedPersona = Literal[
    "author_retrieval",
    "writing_conflict",
    "evidence_fusion",
    "cross_chapter_judgment",
]
_REQUIRED_PERSONAS = {
    "author_retrieval",
    "writing_conflict",
    "evidence_fusion",
    "cross_chapter_judgment",
}


class GeneratedCaseReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str | None = None
    no_answer: bool | None = None
    boundary_offsets: list[int] | None = None
    chapter_indices: list[int] | None = None
    entity_name: str | None = None
    entity_type: str | None = None
    expected_action: str | None = None
    action: str | None = None
    source_refs_valid: bool | None = None
    rubric_score: int | None = None


class GeneratedCaseDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario: GeneratedScenario
    persona: GeneratedPersona = "author_retrieval"
    reference_id: str
    input: GeneratedCaseInput
    visible_until_chapter: int | None = Field(default=None, ge=1)
    hard_negative_chapter_indices: list[int] = Field(default_factory=list)
    risk_flags: list[str] = Field(default_factory=list)


class GeneratedCaseBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cases: list[GeneratedCaseDraft] = Field(default_factory=list)


class ReferenceSnapshotItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reference_id: str
    reference: GeneratedCaseReference
    supporting_chapter_indices: list[int] = Field(default_factory=list)
    input_seed: GeneratedCaseInput = Field(default_factory=GeneratedCaseInput)


class ReferenceSnapshotBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    references: list[ReferenceSnapshotItem] = Field(default_factory=list)


class JudgeDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    natural_query: bool
    answerable: bool
    correctly_no_answer: bool
    reference_faithful: bool
    reference_complete: bool
    hard_negative_valid: bool
    ambiguity: str | None = None
    rubric_score: int = Field(default=3, ge=1, le=5)
    risk_flags: list[str] = Field(default_factory=list)
    decision: str = Field(pattern=r"^(accept|reject|review)$")
    reason: str


class JudgeDecisionItem(JudgeDecision):
    case_id: str


class JudgeDecisionBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decisions: list[JudgeDecisionItem] = Field(default_factory=list)


class ModelReviewDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    status: Literal["accepted", "edited", "rejected", "ambiguous"]
    reason: str
    score: int = Field(ge=1, le=5)
    corrected_reference_json: str | None = None


class ModelReviewDecisionBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decisions: list[ModelReviewDecision] = Field(default_factory=list)


@dataclass(frozen=True)
class GenerationRunMeta:
    model: str
    prompt_hash: str
    profile_hash: str
    reasoning_effort: str | None = None
    seed: int = 20260711
    duration_ms: int = 0
    cost_usd: float | None = None
    cost_status: str = "unavailable_codex_cli"
    cached: bool = False


class HighQualityEvalLLM:
    """Eval-only generator and judge using an approved local Codex executor."""

    def __init__(
        self,
        executor: CodexStructuredExecutor,
        *,
        cache: EvalCache | None = None,
        cache_only: bool = False,
        allow_primary_cache_fallback: bool = True,
    ) -> None:
        self.executor = executor
        self.cache = cache
        self.cache_only = cache_only
        self.allow_primary_cache_fallback = allow_primary_cache_fallback

    def run_meta(
        self,
        prompt: str,
        *,
        duration_ms: int = 0,
        cached: bool = False,
        prompt_hash: str | None = None,
        model: str | None = None,
        profile_hash: str | None = None,
        reasoning_effort: str | None = None,
    ) -> GenerationRunMeta:
        return GenerationRunMeta(
            model=model or self._model,
            reasoning_effort=(
                reasoning_effort
                if reasoning_effort is not None
                else self.executor.meta.reasoning_effort
                if (model is None or model == self._model)
                else None
            ),
            prompt_hash=(
                prompt_hash
                if prompt_hash is not None
                else hashlib.sha256(prompt.encode("utf-8")).hexdigest()
            ),
            profile_hash=profile_hash or self.executor.meta.executor_hash,
            duration_ms=duration_ms,
            cost_status=getattr(
                self.executor,
                "cost_status",
                "unavailable_codex_cli",
            ),
            cached=cached,
        )

    async def generate_reference_snapshot(
        self,
        *,
        suite: str,
        source_excerpt: str,
        chapter_indices: list[int],
        scenarios: list[str],
        count: int,
    ) -> tuple[ReferenceSnapshotBatch, GenerationRunMeta]:
        prompt = _reference_snapshot_prompt(
            suite=suite,
            source_excerpt=source_excerpt,
            chapter_indices=chapter_indices,
            scenarios=scenarios,
            count=count,
        )
        cached_entry = self._cache_get(
            "reference-snapshot", prompt, ReferenceSnapshotBatch
        )
        if cached_entry is not None:
            (
                cached,
                effective_prompt_hash,
                cached_model,
                cached_profile_hash,
                cached_reasoning_effort,
                cached_duration_ms,
            ) = cached_entry
            return cached, self.run_meta(
                prompt,
                duration_ms=cached_duration_ms,
                cached=True,
                prompt_hash=effective_prompt_hash,
                model=cached_model,
                profile_hash=cached_profile_hash,
                reasoning_effort=cached_reasoning_effort,
            )
        self._raise_on_cache_miss("reference-snapshot")
        started = time.perf_counter()
        result = await self.executor.generate_structured(
            "你是中文长篇小说评测 reference 标注员。先固定事实和边界，"
            "不要生成问题，不调用工具，不输出推理过程。\n\n"
            f"{prompt}",
            ReferenceSnapshotBatch,
            step_name="eval.dataset.generate_reference_snapshot.structured",
        )
        duration_ms = round((time.perf_counter() - started) * 1000)
        self._cache_put(
            "reference-snapshot",
            prompt,
            result,
            duration_ms=duration_ms,
        )
        return result, self.run_meta(prompt, duration_ms=duration_ms)

    async def generate_cases(
        self,
        *,
        suite: str,
        source_excerpt: str,
        chapter_indices: list[int],
        scenarios: list[str],
        count: int,
        reference_snapshot: ReferenceSnapshotBatch,
        avoid_cases: list[str] | None = None,
    ) -> tuple[GeneratedCaseBatch, GenerationRunMeta]:
        prompt = _generation_prompt(
            suite=suite,
            source_excerpt=source_excerpt,
            chapter_indices=chapter_indices,
            scenarios=scenarios,
            count=count,
            reference_snapshot=reference_snapshot,
            avoid_cases=avoid_cases or [],
        )
        cached_entry = self._cache_get("generation", prompt, GeneratedCaseBatch)
        if cached_entry is not None:
            (
                cached,
                effective_prompt_hash,
                cached_model,
                cached_profile_hash,
                cached_reasoning_effort,
                cached_duration_ms,
            ) = cached_entry
            _validate_reference_ids(cached, reference_snapshot)
            _validate_case_distribution(cached, scenarios=scenarios, count=count)
            _validate_unique_generated_cases(cached)
            return cached, self.run_meta(
                prompt,
                duration_ms=cached_duration_ms,
                cached=True,
                prompt_hash=effective_prompt_hash,
                model=cached_model,
                profile_hash=cached_profile_hash,
                reasoning_effort=cached_reasoning_effort,
            )
        self._raise_on_cache_miss("generation")
        started = time.perf_counter()
        effective_prompt = prompt
        result: GeneratedCaseBatch | None = None
        for semantic_attempt in range(1, 3):
            result = await self.executor.generate_structured(
                "你是中文长篇小说评测数据设计者。不要调用工具，不输出推理过程。"
                "引用只能来自给定章节。\n\n"
                f"{effective_prompt}",
                GeneratedCaseBatch,
                step_name="eval.dataset.generate_cases.structured",
            )
            try:
                _validate_reference_ids(result, reference_snapshot)
                _validate_case_distribution(result, scenarios=scenarios, count=count)
                _validate_unique_generated_cases(result)
                break
            except ValueError as exc:
                if semantic_attempt >= 2:
                    raise
                effective_prompt = (
                    f"{prompt}\n\n"
                    "上一轮输出通过 JSON schema 但违反评测分布约束。"
                    "请完整重写 cases，只能使用 configured scenarios 和 frozen "
                    "reference IDs；不要沿用错误 scenario。\n"
                    f"validation_error={exc}"
                )
        if result is None:  # pragma: no cover - loop always executes
            raise RuntimeError("semantic generation produced no result")
        duration_ms = round((time.perf_counter() - started) * 1000)
        self._cache_put(
            "generation",
            prompt,
            result,
            effective_prompt=effective_prompt,
            duration_ms=duration_ms,
        )
        return result, self.run_meta(effective_prompt, duration_ms=duration_ms)

    async def judge_case(
        self,
        case: DatasetCase,
        *,
        source_excerpt: str,
        judge_round: int,
    ) -> tuple[JudgeDecision, GenerationRunMeta]:
        prompt = _judge_prompt(
            case,
            source_excerpt=source_excerpt,
            judge_round=judge_round,
        )
        cached_entry = self._cache_get(f"judge-{judge_round}", prompt, JudgeDecision)
        if cached_entry is not None:
            (
                cached,
                effective_prompt_hash,
                cached_model,
                cached_profile_hash,
                cached_reasoning_effort,
                cached_duration_ms,
            ) = cached_entry
            return cached, self.run_meta(
                prompt,
                duration_ms=cached_duration_ms,
                cached=True,
                prompt_hash=effective_prompt_hash,
                model=cached_model,
                profile_hash=cached_profile_hash,
                reasoning_effort=cached_reasoning_effort,
            )
        self._raise_on_cache_miss(f"judge-{judge_round}")
        started = time.perf_counter()
        result = await self.executor.generate_structured(
            "你是评测数据质检员。独立判断，不采信生成器自评。"
            "不要调用工具，不输出隐藏推理。\n\n"
            f"{prompt}",
            JudgeDecision,
            step_name=f"eval.dataset.judge_round_{judge_round}.structured",
        )
        duration_ms = round((time.perf_counter() - started) * 1000)
        self._cache_put(
            f"judge-{judge_round}",
            prompt,
            result,
            duration_ms=duration_ms,
        )
        return result, self.run_meta(prompt, duration_ms=duration_ms)

    async def judge_cases(
        self,
        cases: list[DatasetCase],
        *,
        source_excerpt: str,
        judge_round: int,
    ) -> tuple[dict[str, JudgeDecision], GenerationRunMeta]:
        if not cases:
            return {}, self.run_meta("")
        prompt = _judge_batch_prompt(
            cases,
            source_excerpt=source_excerpt,
            judge_round=judge_round,
        )
        namespace = f"judge-batch-{judge_round}"
        cached_entry = self._cache_get(namespace, prompt, JudgeDecisionBatch)
        if cached_entry is None:
            self._raise_on_cache_miss(namespace)
            started = time.perf_counter()
            cached = await self.executor.generate_structured(
                "你是评测数据质检员。逐条独立判断，不采信生成器自评。"
                "不要调用工具，不输出隐藏推理。\n\n"
                f"{prompt}",
                JudgeDecisionBatch,
                step_name=f"eval.dataset.judge_batch_{judge_round}.structured",
            )
            duration_ms = round((time.perf_counter() - started) * 1000)
            self._cache_put(
                namespace,
                prompt,
                cached,
                duration_ms=duration_ms,
            )
            effective_prompt_hash = hashlib.sha256(prompt.encode()).hexdigest()
            cached_reasoning_effort = self.executor.meta.reasoning_effort
            cached_duration_ms = duration_ms
            cached_model = self._model
            cached_profile_hash = self.executor.meta.executor_hash
        else:
            (
                cached,
                effective_prompt_hash,
                cached_model,
                cached_profile_hash,
                cached_reasoning_effort,
                cached_duration_ms,
            ) = cached_entry
        expected_ids = {case.case_id for case in cases}
        actual_ids = [item.case_id for item in cached.decisions]
        if set(actual_ids) != expected_ids or len(actual_ids) != len(set(actual_ids)):
            raise ValueError(
                "judge batch case IDs do not match request: "
                f"expected={sorted(expected_ids)}, actual={sorted(actual_ids)}"
            )
        return (
            {
                item.case_id: JudgeDecision.model_validate(
                    item.model_dump(exclude={"case_id"})
                )
                for item in cached.decisions
            },
            self.run_meta(
                prompt,
                duration_ms=cached_duration_ms,
                cached=cached_entry is not None,
                prompt_hash=effective_prompt_hash,
                model=cached_model,
                profile_hash=cached_profile_hash,
                reasoning_effort=cached_reasoning_effort,
            ),
        )

    async def review_cases(
        self,
        case_payloads: list[dict[str, Any]],
        *,
        reviewer_role: str,
    ) -> tuple[dict[str, ModelReviewDecision], GenerationRunMeta]:
        prompt = _model_review_prompt(case_payloads, reviewer_role=reviewer_role)
        namespace = f"model-review-{reviewer_role}"
        cached_entry = self._cache_get(namespace, prompt, ModelReviewDecisionBatch)
        if cached_entry is None:
            self._raise_on_cache_miss(namespace)
            started = time.perf_counter()
            batch = await self.executor.generate_structured(
                "你是独立的中文长篇小说评测数据审查员。"
                "只依据给定小说上下文审查，不调用工具，不输出隐藏推理。\n\n"
                f"{prompt}",
                ModelReviewDecisionBatch,
                step_name=f"eval.dataset.model_review_{reviewer_role}.structured",
            )
            duration_ms = round((time.perf_counter() - started) * 1000)
            self._cache_put(
                namespace,
                prompt,
                batch,
                duration_ms=duration_ms,
            )
            meta = self.run_meta(prompt, duration_ms=duration_ms)
        else:
            (
                batch,
                prompt_hash,
                model,
                profile_hash,
                reasoning_effort,
                duration_ms,
            ) = cached_entry
            meta = self.run_meta(
                prompt,
                duration_ms=duration_ms,
                cached=True,
                prompt_hash=prompt_hash,
                model=model,
                profile_hash=profile_hash,
                reasoning_effort=reasoning_effort,
            )
        expected_ids = {str(item["case_id"]) for item in case_payloads}
        payload_by_id = {str(item["case_id"]): item for item in case_payloads}
        actual_ids = [item.case_id for item in batch.decisions]
        if set(actual_ids) != expected_ids or len(actual_ids) != len(set(actual_ids)):
            raise ValueError(
                "model review case IDs do not match request: "
                f"expected={sorted(expected_ids)}, actual={sorted(actual_ids)}"
            )
        for decision in batch.decisions:
            if decision.status == "edited" and decision.corrected_reference_json is None:
                raise ValueError(
                    f"edited model review lacks corrected_reference: {decision.case_id}"
                )
            if (
                decision.status != "edited"
                and decision.corrected_reference_json is not None
            ):
                raise ValueError(
                    "non-edited model review must not change reference: "
                    f"{decision.case_id}"
                )
            if decision.corrected_reference_json is not None:
                corrected = json.loads(decision.corrected_reference_json)
                if not isinstance(corrected, dict):
                    raise ValueError(
                        "corrected_reference_json must encode an object: "
                        f"{decision.case_id}"
                    )
                forbidden = {
                    "reference",
                    "suite",
                    "scenario",
                    "risk_level",
                    "source_refs",
                    "hard_negative_refs",
                    "visibility",
                }
                unexpected = sorted(forbidden & set(corrected))
                if unexpected:
                    raise ValueError(
                        "corrected_reference_json contains non-reference fields: "
                        f"case={decision.case_id} fields={unexpected}"
                    )
                payload = payload_by_id[decision.case_id]
                if corrected.get("no_answer") is True and payload.get("source_refs"):
                    raise ValueError(
                        "corrected no-answer case retains positive source refs: "
                        f"{decision.case_id}"
                    )
                if (
                    payload.get("suite") == "scene"
                    and (
                        corrected.get("action") == "no_boundary"
                        or corrected.get("expected_action") == "no_boundary"
                    )
                    and corrected.get("boundary_offsets")
                ):
                    raise ValueError(
                        "corrected no-boundary Scene retains boundary offsets: "
                        f"{decision.case_id}"
                    )
        return {item.case_id: item for item in batch.decisions}, meta

    def _cache_get(
        self,
        namespace: str,
        prompt: str,
        response_model: type[BaseModel],
    ) -> tuple[Any, str, str, str, str | None, int] | None:
        if self.cache is None:
            return None
        payload = None
        models = [self._model]
        if self.allow_primary_cache_fallback and HIGH_QUALITY_LLM_MODEL not in models:
            models.append(HIGH_QUALITY_LLM_MODEL)
        for model in models:
            key = self._cache_key(namespace, prompt, response_model, model=model)
            payload = self.cache.get(namespace, key)
            if payload is not None:
                break
        if payload is None:
            return None
        return (
            response_model.model_validate(payload["result"]),
            str(
                payload.get("prompt_hash") or hashlib.sha256(prompt.encode()).hexdigest()
            ),
            str(payload["model"]),
            str(payload["executor_hash"]),
            (
                str(payload["reasoning_effort"])
                if payload.get("reasoning_effort")
                else None
            ),
            int(payload.get("duration_ms") or 0),
        )

    def _cache_put(
        self,
        namespace: str,
        prompt: str,
        result: BaseModel,
        *,
        effective_prompt: str | None = None,
        duration_ms: int = 0,
    ) -> None:
        if self.cache is None:
            return
        key = self._cache_key(namespace, prompt, type(result))
        effective = effective_prompt if effective_prompt is not None else prompt
        self.cache.put(
            namespace,
            key,
            {
                "model": self._model,
                "reasoning_effort": self.executor.meta.reasoning_effort,
                "prompt_hash": hashlib.sha256(effective.encode()).hexdigest(),
                "input_hash": hashlib.sha256(prompt.encode()).hexdigest(),
                "executor_hash": self.executor.meta.executor_hash,
                "duration_ms": duration_ms,
                "metric_version": METRIC_VERSION,
                "rubric_version": RUBRIC_VERSION,
                "temperature_profile": getattr(
                    self.executor,
                    "cache_profile",
                    "codex_cli_fixed",
                ),
                "result": result.model_dump(mode="json"),
            },
        )

    def _raise_on_cache_miss(self, namespace: str) -> None:
        if self.cache_only:
            raise RuntimeError(
                f"eval cache-only mode: cache miss in {namespace}; "
                "Codex execution was not started"
            )

    def _cache_key(
        self,
        namespace: str,
        prompt: str,
        response_model: type[BaseModel],
        *,
        model: str | None = None,
    ) -> str:
        return EvalCache.key(
            {
                "namespace": namespace,
                "model": model or self._model,
                "prompt_hash": hashlib.sha256(prompt.encode()).hexdigest(),
                "input_hash": hashlib.sha256(prompt.encode()).hexdigest(),
                "metric_version": METRIC_VERSION,
                "rubric_version": RUBRIC_VERSION,
                "temperature_profile": getattr(
                    self.executor,
                    "cache_profile",
                    "codex_cli_fixed",
                ),
                "schema": response_model.model_json_schema(),
            }
        )

    @property
    def _model(self) -> str:
        return getattr(self.executor, "model", self.executor.meta.model)


def materialize_generated_cases(
    drafts: list[GeneratedCaseDraft],
    *,
    suite: str,
    corpus: Any,
    run_meta: GenerationRunMeta,
    reference_snapshot: ReferenceSnapshotBatch,
    case_offset: int = 0,
) -> list[DatasetCase]:
    from evals.schemas import (
        EvalSuite,
        GenerationMeta,
        RiskLevel,
        VisibilitySpec,
    )

    chapters = {item.chapter_index: item for item in corpus.chapters}
    references = {item.reference_id: item for item in reference_snapshot.references}
    cases: list[DatasetCase] = []
    for index, draft in enumerate(drafts, start=case_offset + 1):
        frozen = references[draft.reference_id]
        frozen_reference = frozen.reference.model_dump(exclude_none=True)
        no_answer = bool(frozen_reference.get("no_answer"))
        positive_chapter_indices = [] if no_answer else frozen.supporting_chapter_indices
        positive_refs = [
            _chapter_ref(corpus, chapters[chapter_index])
            for chapter_index in positive_chapter_indices
            if chapter_index in chapters
        ]
        positive_index_set = {ref.chapter_index for ref in positive_refs}
        negative_refs = [
            _chapter_ref(corpus, chapters[chapter_index])
            for chapter_index in draft.hard_negative_chapter_indices
            if chapter_index in chapters and chapter_index not in positive_index_set
        ]
        source_group = (
            positive_refs[0].source_group_id
            if positive_refs
            else negative_refs[0].source_group_id
            if negative_refs
            else "unresolved"
        )
        split = _split_for_source_group(source_group)
        generated_input = draft.input.model_dump(exclude_none=True)
        case_input = frozen.input_seed.model_dump(exclude_none=True)
        if suite == "rag":
            case_input.update(generated_input)
        else:
            case_input.update(
                {
                    key: value
                    for key, value in generated_input.items()
                    if key != "text" or "text" not in case_input
                }
            )
        reference = frozen_reference
        entity_name = reference.pop("entity_name", None)
        entity_type = reference.pop("entity_type", None)
        if entity_name is not None or entity_type is not None:
            reference["entity"] = {
                "name": entity_name,
                "entity_type": entity_type,
            }
        if suite == "rag":
            reference.setdefault(
                "context_ids",
                [
                    f"{ref.source_alias}:chapter:{ref.chapter_index}"
                    for ref in positive_refs
                ],
            )
        cases.append(
            DatasetCase(
                case_id=f"{suite}-{index:06d}",
                suite=EvalSuite(suite),
                scenario=draft.scenario,
                risk_level=_risk_level_for_generated_case(
                    draft,
                    no_answer=no_answer,
                    risk_level_type=RiskLevel,
                ),
                source_group_id=source_group,
                source_refs=positive_refs,
                input=case_input,
                reference=reference,
                hard_negative_refs=negative_refs,
                visibility=VisibilitySpec(
                    visible_until_chapter=draft.visible_until_chapter,
                ),
                rubric={"persona": draft.persona},
                generation_meta=GenerationMeta(
                    model=run_meta.model,
                    reasoning_effort=run_meta.reasoning_effort,
                    profile_hash=run_meta.profile_hash,
                    prompt_hash=run_meta.prompt_hash,
                    seed=run_meta.seed,
                    source_hash=corpus.file_hash,
                    duration_ms=run_meta.duration_ms,
                    cost_usd=run_meta.cost_usd,
                    cost_status=run_meta.cost_status,
                    cached=run_meta.cached,
                ),
                split=split,
            )
        )
    return cases


def _risk_level_for_generated_case(
    draft: GeneratedCaseDraft,
    *,
    no_answer: bool,
    risk_level_type: Any,
):
    """Promote only plan-defined safety strata, not every generation caveat."""
    if no_answer:
        return risk_level_type.safety_critical
    normalized = " ".join([draft.scenario, *draft.risk_flags]).casefold()
    safety_terms = (
        "visibility",
        "cutoff",
        "future",
        "hidden",
        "cross_novel",
        "cross-novel",
        "canonical_merge",
        "auto_merge",
        "unconfirmed_asset_write",
        "未来",
        "隐藏知识",
        "跨小说",
        "自动合并",
        "未确认写入",
    )
    if any(term in normalized for term in safety_terms):
        return risk_level_type.safety_critical
    return risk_level_type.normal


def _chapter_ref(corpus: Any, chapter: Any):
    from evals.schemas import LogicalSourceRef

    return LogicalSourceRef(
        corpus_id=corpus.corpus_id,
        source_alias=corpus.source_alias,
        source_group_id=chapter.source_group_id,
        chapter_index=chapter.chapter_index,
        content_hash=chapter.content_hash,
    )


def _split_for_source_group(source_group: str):
    from evals.schemas import DatasetSplit

    bucket = int(hashlib.sha256(source_group.encode("utf-8")).hexdigest()[:8], 16) % 10
    if bucket < 6:
        return DatasetSplit.train
    if bucket < 8:
        return DatasetSplit.dev
    return DatasetSplit.test


def _generation_prompt(
    *,
    suite: str,
    source_excerpt: str,
    chapter_indices: list[int],
    scenarios: list[str],
    count: int,
    reference_snapshot: ReferenceSnapshotBatch,
    avoid_cases: list[str],
) -> str:
    suite_contracts = {
        "rag": (
            'input={"query": str}; reference={"answer": str, '
            '"no_answer": bool}. supporting chapters are positive retrieval contexts.'
        ),
        "scene": (
            'input={"text": str}; reference={"boundary_offsets": [int], '
            '"chapter_indices": [int]}. Use offsets relative to input.text.'
        ),
        "world": (
            "input.text; reference.entity_name, reference.entity_type and "
            "reference.expected_action. Negative cases may use "
            'expected_action="ignore".'
        ),
        "outline": (
            "input.text; reference.action, reference.source_refs_valid and "
            "reference.rubric_score. action must preserve "
            "preview/apply safety."
        ),
    }
    return (
        f"suite={suite}\n"
        f"目标数量={count}\n"
        f"允许章节={chapter_indices}\n"
        f"场景分层={scenarios}\n\n"
        "seed=20260711\n"
        f"suite 字段契约：{suite_contracts[suite]}\n"
        "只能从已冻结 reference snapshot 选择 reference_id；不得重写答案、"
        "supporting chapter 或结构边界。生成自然的作者输入，并可对同一 reference "
        "生成不同 persona 的问法。persona 只能是 author_retrieval、"
        "writing_conflict、evidence_fusion、cross_chapter_judgment。"
        "scenario 必须严格从场景分层列表选择，不得追加后缀或自造名称；"
        "四种 persona 都必须覆盖。每条 case 的 scenario、reference_id 与最终 input "
        "组合必须唯一；persona 标签不同不能作为重复 case 的唯一区别。RAG 复用 "
        "reference_id 时必须生成语义和措辞均不同的自然 query。"
        "目标数量不小于场景数时，每个场景至少一条。"
        "no-answer case 必须给出 hard negative。"
        "scenario=visibility_cutoff 时必须显式给出 visible_until_chapter，"
        "值为允许检索的最后一章，supporting chapter 不得超过该值。"
        "并尽量给容易混淆但不支持答案的 hard_negative_chapter_indices。"
        "不得复制长段原文，不得使用未给出的未来情节。\n\n"
        "以下是本 suite 已存在或上一轮被拒绝的语义 case，禁止生成相同的 "
        "scenario/input/reference 组合：\n"
        f"{json.dumps(avoid_cases[-120:], ensure_ascii=False)}\n\n"
        "已冻结 reference snapshot：\n"
        f"{reference_snapshot.model_dump_json()}\n\n"
        f"正文摘录：\n{source_excerpt}"
    )


def _model_review_prompt(
    case_payloads: list[dict[str, Any]],
    *,
    reviewer_role: str,
) -> str:
    normalized_role = reviewer_role.strip().lower().replace("_", "-")
    is_adjudicator = normalized_role == "adjudicator" or normalized_role.endswith(
        "-adjudicator"
    )
    role_instruction = (
        "这是分歧裁决：比较 independent_reviews 的理由和修订，但最终必须根据小说"
        "上下文独立给出可落地结论；不要简单多数投票。"
        if is_adjudicator
        else "这是独立审查：忽略其他 reviewer 结论（正常情况下不会提供）。"
    )
    return (
        f"reviewer_role={reviewer_role}\n"
        f"{role_instruction}"
        "对每个 case_id 独立给出一条 decision，不能漏项或增加 ID。"
        "审查 reference 是否被所给小说上下文直接支持、input 是否自然可判定、"
        "no-answer/hard-negative/visibility 是否正确，且不得使用未提供的未来知识。"
        "accepted=无需修改；edited=核心 case 有效但 reference 需小幅纠正，此时必须"
        "给 corrected_reference_json，其值必须是包含完整 reference 对象的 JSON 字符串；"
        "corrected_reference_json 解码后的顶层本身就是 reference 对象，严禁再包装"
        "一层 reference 键。它只能包含 reference 字段，不得嵌入 suite、scenario、"
        "risk_level、source_refs、hard_negative_refs 或 visibility。reviewer 不能修改"
        "input/scenario/source_refs：若修复依赖修改这些字段，必须 rejected。"
        "若 case 仍有正向 source_refs，不得把 corrected_reference.no_answer 改为 true；"
        "对‘无法确定/本章未说明’这类可由正向证据支持的结论，应保留 no_answer=false "
        "并把结论写入 answer。只有原 case 无正向 source_refs 时才允许 no_answer=true，"
        "此时 context_ids 必须为空。"
        "Scene corrected_reference 若 action/expected_action 为 no_boundary，"
        "boundary_offsets 必须是空数组；不得一边声明无边界一边保留边界 offset。"
        "rejected=不可修复或上下文不支持；"
        "ambiguous=上下文本身不足以唯一裁定。score 为整体质量 1-5。"
        "不要因已有自动 judge 结论而锚定；payload 不提供自动 judge 结论。\n"
        f"cases={json.dumps(case_payloads, ensure_ascii=False, sort_keys=True)}"
    )


def _reference_snapshot_prompt(
    *,
    suite: str,
    source_excerpt: str,
    chapter_indices: list[int],
    scenarios: list[str],
    count: int,
) -> str:
    return (
        f"suite={suite}\nseed=20260711\n允许章节={chapter_indices}\n"
        f"目标 reference 数量={max(1, min((count + 1) // 2, 5))}\n"
        f"场景分层={scenarios}\n"
        "先从正文标注可独立验证的 reference，此阶段禁止生成问题。"
        "reference_id 在本批唯一。supporting_chapter_indices 只能来自允许章节。"
        "RAG 可包含 answer/no_answer；Scene 要固定 input_seed.text 及其相对"
        "boundary_offsets；World/Outline 要固定 input_seed.text 与结构化期望。"
        "不得复制非验收所需的长段原文。\n\n"
        f"正文摘录：\n{source_excerpt}"
    )


def _validate_reference_ids(
    cases: GeneratedCaseBatch,
    snapshot: ReferenceSnapshotBatch,
) -> None:
    available = {item.reference_id for item in snapshot.references}
    missing = sorted({case.reference_id for case in cases.cases} - available)
    if missing:
        raise ValueError(f"generated cases reference unknown frozen IDs: {missing}")


def _validate_case_distribution(
    cases: GeneratedCaseBatch,
    *,
    scenarios: list[str],
    count: int,
) -> None:
    allowed = set(scenarios)
    actual = [case.scenario for case in cases.cases]
    unknown = sorted(set(actual) - allowed)
    if unknown:
        raise ValueError(f"generated cases use unconfigured scenarios: {unknown}")
    if count >= len(allowed):
        missing = sorted(allowed - set(actual))
        if missing:
            raise ValueError(f"generated cases miss required scenarios: {missing}")
    if count >= len(_REQUIRED_PERSONAS):
        actual_personas = {case.persona for case in cases.cases}
        missing_personas = sorted(_REQUIRED_PERSONAS - actual_personas)
        if missing_personas:
            raise ValueError(
                f"generated cases miss required personas: {missing_personas}"
            )
    missing_cutoffs = [
        case.reference_id
        for case in cases.cases
        if case.scenario == "visibility_cutoff" and case.visible_until_chapter is None
    ]
    if missing_cutoffs:
        raise ValueError(
            f"visibility_cutoff cases require visible_until_chapter: {missing_cutoffs}"
        )
    if len(cases.cases) != count:
        raise ValueError(
            f"generated case count mismatch: expected={count}, actual={len(cases.cases)}"
        )


def _validate_unique_generated_cases(cases: GeneratedCaseBatch) -> None:
    identities = [
        (
            case.scenario,
            case.reference_id,
            json.dumps(case.input.model_dump(exclude_none=True), sort_keys=True),
        )
        for case in cases.cases
    ]
    if len(identities) != len(set(identities)):
        raise ValueError(
            "generated cases contain semantic duplicates; persona alone is not unique"
        )


def _judge_rubric(judge_round: int) -> str:
    focus = (
        "优先审查引用忠实、可回答性和 hard negative。"
        if judge_round == 1
        else "优先审查歧义、自然度、未来信息和共同偏差。"
    )
    return (
        f"{focus} rubric_score 必须按同一质量方向评分：5=忠实完整自然且无边界问题；"
        "4=核心正确，仅有不影响答案的轻微问题；3=核心可用但需要明确修订；"
        "2=存在重大错误或证据不足；1=无效、泄漏或与正文矛盾。"
        "decision 与分数一致：4-5 accept，3 review，1-2 reject。"
    )


def _judge_prompt(
    case: DatasetCase,
    *,
    source_excerpt: str,
    judge_round: int,
) -> str:
    rubric_view = _judge_rubric(judge_round)
    payload: dict[str, Any] = {
        "case_id": case.case_id,
        "scenario": case.scenario,
        "input": case.input,
        "reference": case.reference,
        "hard_negative_chapters": [ref.chapter_index for ref in case.hard_negative_refs],
    }
    return (
        f"judge_round={judge_round}\n{rubric_view}\n"
        f"case={json.dumps(payload, ensure_ascii=False)}\n\n"
        f"独立正文摘录：\n{source_excerpt}"
    )


def _judge_batch_prompt(
    cases: list[DatasetCase],
    *,
    source_excerpt: str,
    judge_round: int,
) -> str:
    rubric_view = _judge_rubric(judge_round)
    payloads = [
        {
            "case_id": case.case_id,
            "scenario": case.scenario,
            "input": case.input,
            "reference": case.reference,
            "hard_negative_chapters": [
                ref.chapter_index for ref in case.hard_negative_refs
            ],
        }
        for case in cases
    ]
    return (
        f"judge_round={judge_round}\n{rubric_view}\n"
        "必须为每个 case_id 输出且只输出一条 decision。\n"
        f"cases={json.dumps(payloads, ensure_ascii=False)}\n\n"
        f"独立正文摘录：\n{source_excerpt}"
    )
