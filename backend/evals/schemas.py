"""Stable repository-owned schemas for semantic evaluation artifacts."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# 评测模型合同（2026-10-14 用户裁定，G6a 生效）：
# - 教师、judge/复核（reviewer、adjudicator）与 scene-gold 参考答案固定 Sol/xhigh，
#   经 evals.codex_executor 的独立 schema 守卫 Codex 执行器；解除暂停前仍拒绝新调用。
# - 被测业务生成经 evals.project_executor 的 ProjectStructuredExecutor 走 Project
#   facade 的产品侧 Luna/max（见 infrastructure.llm.codex_provider.CODEX_MODEL）。
# 两类执行器不同模型，避免同模型自评。
EVAL_TEACHER_MODEL = "gpt-6.1-sol"
EVAL_TEACHER_REASONING_EFFORT = "xhigh"
ALLOWED_EVAL_TEACHER_MODELS = frozenset({EVAL_TEACHER_MODEL})

# 以下旧合同常量自 G6a 起降级为冻结元数据：仅用于识别与校验历史数据集、账本和
# executor hash 重建，不得用于新调用；旧合同分数与新合同分数不可直接比较。
HIGH_QUALITY_LLM_MODEL = "gpt-5.3-codex-spark"
HIGH_QUALITY_LLM_FALLBACK_MODEL = "gpt-5.6-luna"
EVAL_REVIEWER_A_MODEL = "deepseek-v4-flash"
EVAL_REVIEWER_B_MODEL = "gpt-5.6-luna"
EVAL_ADJUDICATOR_MODEL = "gpt-5.6-terra"
ALLOWED_HIGH_QUALITY_LLM_MODELS = frozenset(
    {HIGH_QUALITY_LLM_MODEL, HIGH_QUALITY_LLM_FALLBACK_MODEL}
)
FROZEN_LEGACY_EVAL_MODELS = frozenset(
    {
        HIGH_QUALITY_LLM_MODEL,
        HIGH_QUALITY_LLM_FALLBACK_MODEL,
        EVAL_REVIEWER_A_MODEL,
        EVAL_REVIEWER_B_MODEL,
        EVAL_ADJUDICATOR_MODEL,
    }
)
# 冻结与未来数据集的 generator/judge 溯源模型：旧 Spark/Luna 合同 + 新 Sol 教师
# 合同；terra/DeepSeek 从未担任 dataset generator/judge，不在其中。
ALLOWED_DATASET_PROVENANCE_MODELS = (
    ALLOWED_HIGH_QUALITY_LLM_MODELS | ALLOWED_EVAL_TEACHER_MODELS
)
DATASET_SCHEMA_VERSION = "1.0"
RUBRIC_VERSION = "v1"
METRIC_VERSION = "v1"


class EvalSuite(StrEnum):
    rag = "rag"
    scene = "scene"
    world = "world"
    outline = "outline"


class DatasetSplit(StrEnum):
    train = "train"
    dev = "dev"
    test = "test"


class RiskLevel(StrEnum):
    normal = "normal"
    safety_critical = "safety_critical"


class LogicalSourceRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    corpus_id: str = Field(min_length=1)
    source_alias: str = Field(min_length=1)
    source_group_id: str = Field(min_length=1)
    chapter_index: int = Field(ge=1)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    range_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    start_offset: int | None = Field(default=None, ge=0)
    end_offset: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_range(self) -> LogicalSourceRef:
        if (self.start_offset is None) != (self.end_offset is None):
            raise ValueError("start_offset and end_offset must be supplied together")
        if self.start_offset is not None and self.end_offset <= self.start_offset:
            raise ValueError("end_offset must be greater than start_offset")
        return self


class VisibilitySpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["author", "reader", "character"] = "author"
    visible_until_chapter: int | None = Field(default=None, ge=1)
    viewpoint_character_id: str | None = None


class GenerationMeta(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str = HIGH_QUALITY_LLM_MODEL
    reasoning_effort: str | None = None
    profile_hash: str = ""
    prompt_hash: str = ""
    seed: int | None = None
    source_hash: str = ""
    duration_ms: int = Field(default=0, ge=0)
    cost_usd: float | None = Field(default=None, ge=0)
    cost_status: str = "unavailable_codex_cli"
    cached: bool = False
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class QCDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["pending", "accepted", "rejected", "review"] = "pending"
    deterministic_errors: list[str] = Field(default_factory=list)
    deterministic_warnings: list[str] = Field(default_factory=list)
    judge_decisions: list[dict[str, Any]] = Field(default_factory=list)


class HumanReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["unreviewed", "accepted", "edited", "rejected", "ambiguous"] = (
        "unreviewed"
    )
    reviewer_version: str | None = None
    reason: str | None = None
    score: int | None = Field(default=None, ge=1, le=5)
    reviewed_at: datetime | None = None
    independent_reviews: list[HumanReviewDecision] = Field(default_factory=list)
    original_reference: dict[str, Any] | None = None
    adjudicated: bool = False


class HumanReviewDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["accepted", "edited", "rejected", "ambiguous"]
    reviewer_version: str = Field(min_length=1)
    reason: str | None = None
    score: int | None = Field(default=None, ge=1, le=5)
    corrected_reference: dict[str, Any] | None = None
    reviewed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class DatasetCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1, pattern=r"^[a-z0-9][a-z0-9._-]+$")
    suite: EvalSuite
    scenario: str = Field(min_length=1)
    risk_level: RiskLevel = RiskLevel.normal
    source_group_id: str = Field(min_length=1)
    source_refs: list[LogicalSourceRef] = Field(default_factory=list)
    input: dict[str, Any]
    reference: dict[str, Any]
    hard_negative_refs: list[LogicalSourceRef] = Field(default_factory=list)
    visibility: VisibilitySpec = Field(default_factory=VisibilitySpec)
    rubric: dict[str, Any] = Field(default_factory=dict)
    generation_meta: GenerationMeta = Field(default_factory=GenerationMeta)
    qc: QCDecision = Field(default_factory=QCDecision)
    human_review: HumanReview = Field(default_factory=HumanReview)
    split: DatasetSplit

    @field_validator("source_refs")
    @classmethod
    def source_refs_are_unique(
        cls,
        refs: list[LogicalSourceRef],
    ) -> list[LogicalSourceRef]:
        keys = [
            (ref.source_alias, ref.chapter_index, ref.start_offset, ref.end_offset)
            for ref in refs
        ]
        if len(keys) != len(set(keys)):
            raise ValueError("source_refs must be unique")
        return refs


class DatasetManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_id: str
    version: str
    schema_version: str = DATASET_SCHEMA_VERSION
    corpus_id: str
    corpus_hash: str
    source_aliases: list[str]
    case_count: int = Field(ge=0)
    suite_counts: dict[EvalSuite, int] = Field(default_factory=dict)
    split_counts: dict[DatasetSplit, int] = Field(default_factory=dict)
    generator_model: str = HIGH_QUALITY_LLM_MODEL
    judge_model: str = HIGH_QUALITY_LLM_MODEL
    prompt_hashes: dict[str, str] = Field(default_factory=dict)
    generation_runs: list[dict[str, Any]] = Field(default_factory=list)
    judge_runs: list[dict[str, Any]] = Field(default_factory=list)
    range_locator_runs: list[dict[str, Any]] = Field(default_factory=list)
    selection_meta: dict[str, Any] = Field(default_factory=dict)
    rubric_version: str = RUBRIC_VERSION
    metric_version: str = METRIC_VERSION
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class MetricValue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    value: float | None = None
    available: bool = True
    blocking: bool = False
    threshold: float | None = None
    passed: bool | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class SystemUnderTestProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider_id: str
    model: str
    profile_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    label: str | None = None


class EvalResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    suite: EvalSuite
    dataset_id: str
    dataset_version: str
    system_under_test: SystemUnderTestProfile | None = None
    run_context: dict[str, Any] = Field(default_factory=dict)
    metrics: list[MetricValue] = Field(default_factory=list)
    case_results: list[dict[str, Any]] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None
