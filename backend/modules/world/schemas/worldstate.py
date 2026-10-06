"""World State 设计态 schema。"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

WorldStateAuthorityStatus = Literal[
    "draft", "proposed", "canon", "author-required", "deprecated"
]
WorldStateCoverageStatus = Literal["gap", "partial", "covered", "not-applicable"]
WORLD_STATE_FACETS = (
    "本体法则与不可行域",
    "地理、生态与气候",
    "资源、承载力与城市代谢",
    "技术、魔法与基础设施",
    "故障、维修与韧性",
    "人口结构与生命历程",
    "家庭、亲属与照护",
    "身体、医疗、残障与死亡",
    "劳动、职业与技能传承",
    "住房、消费与日常时间",
    "财产、货币、信用、债务与供应链",
    "正式制度、非正式制度与组织政治",
    "行政能力、裁量与合法性",
    "法律、证据、申诉与多法域",
    "阶层、地位、身份与社会边界",
    "战争、边境、迁徙与外部关系",
    "知识、教育、档案与谣言",
    "语言、语域、命名与翻译",
    "宗教、仪式、禁忌与道德经济",
    "情绪规则、身体经验与物质文化",
    "历史沉积与路径依赖",
    "网络、集体行动、涌现与反馈",
)
WORLD_STATE_COUPLING_CHAINS = (
    "权利链",
    "技术链",
    "身份链",
    "证据链",
    "分配链",
)
WORLD_STATE_PRESSURE_TESTS = (
    "主角移除",
    "普通星期二",
    "一生",
    "最贫者",
    "上层例外",
    "一项权利",
    "一件商品",
    "故障与维修",
    "跨境",
    "历史来源",
    "集体行动",
    "十年后",
)


class WorldStateDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$", max_length=128)
    question: str = Field(..., max_length=5000)
    status: WorldStateAuthorityStatus
    evidence: list[str] = Field(default_factory=list, max_length=64)

    @model_validator(mode="after")
    def validate_authority(self) -> WorldStateDecision:
        if self.status == "canon" and not self.evidence:
            raise ValueError("canon decision requires evidence")
        return self


class WorldStateKnowledge(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$", max_length=128)
    claim: str = Field(..., max_length=5000)
    status: WorldStateAuthorityStatus
    known_by: list[str] = Field(default_factory=list, max_length=64)
    evidence: list[str] = Field(default_factory=list, max_length=64)

    @model_validator(mode="after")
    def validate_authority(self) -> WorldStateKnowledge:
        if self.status == "canon" and not self.evidence:
            raise ValueError("canon knowledge requires evidence")
        return self


class WorldStateRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$", max_length=128)
    name: str = Field(..., max_length=500)
    status: WorldStateAuthorityStatus
    capability: str = Field(..., min_length=1, max_length=5000)
    impossibility: str = Field(..., min_length=1, max_length=5000)
    inputs: list[str] = Field(default_factory=list, max_length=64)
    outputs: list[str] = Field(default_factory=list, max_length=64)
    costs: list[str] = Field(default_factory=list, max_length=64)
    losses: list[str] = Field(default_factory=list, max_length=64)
    access: list[str] = Field(default_factory=list, max_length=64)
    visibility: list[str] = Field(default_factory=list, max_length=64)
    scale_limits: list[str] = Field(default_factory=list, max_length=64)
    failure_modes: list[str] = Field(default_factory=list, max_length=64)
    maintenance: list[str] = Field(default_factory=list, max_length=64)
    countermeasures: list[str] = Field(default_factory=list, max_length=64)
    knowledge_layer: Literal[
        "author_truth", "expert_model", "public_belief", "mixed", "unknown"
    ]
    dependencies: list[str] = Field(default_factory=list, max_length=64)
    evidence: list[str] = Field(default_factory=list, max_length=64)

    @model_validator(mode="after")
    def validate_authority(self) -> WorldStateRule:
        if not self.capability.strip() or not self.impossibility.strip():
            raise ValueError("rule capability and impossibility must be non-empty")
        if self.status == "canon" and not self.evidence:
            raise ValueError("canon rule requires evidence")
        for name in (
            "inputs",
            "outputs",
            "costs",
            "losses",
            "access",
            "visibility",
            "scale_limits",
            "failure_modes",
            "maintenance",
            "countermeasures",
            "dependencies",
            "evidence",
        ):
            if any(not value.strip() for value in getattr(self, name)):
                raise ValueError(f"{name} entries must be non-empty")
        return self


class WorldStateCoverageEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: WorldStateCoverageStatus
    chain: list[str] = Field(default_factory=list, max_length=64)
    evidence: list[str] = Field(default_factory=list, max_length=64)
    gaps: list[str] = Field(default_factory=list, max_length=64)
    reason: str = Field(default="", max_length=5000)

    @model_validator(mode="after")
    def validate_coverage(self) -> WorldStateCoverageEntry:
        if self.status in {"partial", "covered"} and not self.evidence:
            raise ValueError(f"{self.status} coverage requires evidence")
        if self.status == "not-applicable" and not self.reason.strip():
            raise ValueError("not-applicable coverage requires reason")
        return self


class WorldStateMaturity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    framework: int = Field(..., ge=0, le=6)
    instance: int = Field(..., ge=0, le=6)


class WorldStateFacet(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., pattern=r"^F(?:0[1-9]|1[0-9]|2[0-2])$")
    name: str = Field(..., max_length=500)
    status: WorldStateCoverageStatus
    maturity: WorldStateMaturity
    evidence: list[str] = Field(default_factory=list, max_length=64)
    gaps: list[str] = Field(default_factory=list, max_length=64)
    dependencies: list[str] = Field(default_factory=list, max_length=64)
    reason: str = Field(default="", max_length=5000)

    @model_validator(mode="after")
    def validate_maturity(self) -> WorldStateFacet:
        if (self.maturity.framework or self.maturity.instance) and not self.evidence:
            raise ValueError("non-zero maturity requires evidence")
        if self.status in {"partial", "covered"} and not self.evidence:
            raise ValueError(f"{self.status} facet requires evidence")
        if self.status == "not-applicable" and not self.reason.strip():
            raise ValueError("not-applicable facet requires reason")
        return self


class WorldStateCouplingChain(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., pattern=r"^C0[1-5]$")
    name: str = Field(..., max_length=500)
    status: WorldStateCoverageStatus
    nodes: list[str] = Field(default_factory=list, max_length=64)
    breaks: list[str] = Field(default_factory=list, max_length=64)
    evidence: list[str] = Field(default_factory=list, max_length=64)
    reason: str = Field(default="", max_length=5000)

    @model_validator(mode="after")
    def validate_coverage(self) -> WorldStateCouplingChain:
        if self.status in {"partial", "covered"} and not self.evidence:
            raise ValueError(f"{self.status} coupling chain requires evidence")
        if self.status == "not-applicable" and not self.reason.strip():
            raise ValueError("not-applicable coupling chain requires reason")
        return self


class WorldStateSituatedTest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: WorldStateCoverageStatus
    scenario: str = Field(default="", max_length=5000)
    actors: list[str] = Field(default_factory=list, max_length=64)
    evidence: list[str] = Field(default_factory=list, max_length=64)
    contradictions: list[str] = Field(default_factory=list, max_length=64)
    reason: str = Field(default="", max_length=5000)

    @model_validator(mode="after")
    def validate_coverage(self) -> WorldStateSituatedTest:
        if self.status in {"partial", "covered"} and not self.evidence:
            raise ValueError(f"{self.status} situated test requires evidence")
        if self.status == "not-applicable" and not self.reason.strip():
            raise ValueError("not-applicable situated test requires reason")
        return self


class WorldStatePressureTest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., pattern=r"^T(?:0[1-9]|1[0-2])$")
    name: str = Field(..., max_length=500)
    status: Literal["not-run", "pass", "mixed", "fail"]
    result: str = Field(default="", max_length=5000)
    evidence: list[str] = Field(default_factory=list, max_length=64)
    failures: list[str] = Field(default_factory=list, max_length=64)

    @model_validator(mode="after")
    def validate_run(self) -> WorldStatePressureTest:
        if self.status != "not-run" and not self.evidence:
            raise ValueError("completed pressure test requires evidence")
        return self


class WorldStateEntity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$", max_length=128)
    name: str = Field(..., max_length=500)
    status: WorldStateAuthorityStatus
    summary: str = Field(default="", max_length=5000)
    evidence: list[str] = Field(default_factory=list, max_length=64)

    @model_validator(mode="after")
    def validate_authority(self) -> WorldStateEntity:
        if self.status == "canon" and not self.evidence:
            raise ValueError("canon entity requires evidence")
        return self


class WorldStatePipelineEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal[
        "not-started",
        "ready",
        "in-progress",
        "valid",
        "needs-review",
        "invalidated",
        "blocked",
    ]
    artifacts: list[str] = Field(default_factory=list, max_length=64)
    invalidated_by: list[str] = Field(default_factory=list, max_length=64)
    notes: list[str] = Field(default_factory=list, max_length=64)


class WorldStateDependency(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    source: str = Field(
        ..., alias="from", pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$", max_length=128
    )
    to: str = Field(..., pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$", max_length=128)
    kind: Literal["requires", "informs", "derives", "contradicts"]
    status: Literal["active", "proposed", "deprecated"]


class WorldStateChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$", max_length=128)
    at: datetime | None = None
    summary: str = Field(default="", max_length=5000)
    source: str = Field(default="", max_length=500)
    authority: WorldStateAuthorityStatus
    changed_ids: list[str] = Field(default_factory=list, max_length=128)
    invalidated_layers: list[str] = Field(default_factory=list, max_length=64)


class WorldStateProject(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$", max_length=128)
    title: str = Field(default="", max_length=500)
    language: str = Field(..., min_length=2, max_length=32)
    seed: str = Field(default="", max_length=5000)
    mode: Literal["create", "expand", "audit", "repair", "promote", "export"]
    status: Literal["developing", "review", "stable", "archived"]
    created_at: datetime | None = None
    updated_at: datetime | None = None


class WorldStateAuthority(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_of_truth: list[str] = Field(default_factory=list, max_length=128)
    read_only: list[str] = Field(default_factory=list, max_length=128)
    constraints: list[str] = Field(default_factory=list, max_length=128)
    locked_decisions: list[WorldStateDecision] = Field(
        default_factory=list, max_length=128
    )
    author_required: list[WorldStateDecision] = Field(
        default_factory=list, max_length=128
    )
    open_questions: list[WorldStateDecision] = Field(default_factory=list, max_length=128)


class WorldStatePremise(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: WorldStateAuthorityStatus
    core_difference: str = Field(default="", max_length=5000)
    human_experience: str = Field(default="", max_length=5000)
    scale: str = Field(default="", max_length=500)
    aesthetic_surface: list[str] = Field(default_factory=list, max_length=64)
    themes: list[str] = Field(default_factory=list, max_length=64)
    evidence: list[str] = Field(default_factory=list, max_length=64)

    @model_validator(mode="after")
    def validate_authority(self) -> WorldStatePremise:
        if self.status == "canon" and not self.evidence:
            raise ValueError("canon premise requires evidence")
        return self


class WorldStateKnowledgeLayers(BaseModel):
    model_config = ConfigDict(extra="forbid")

    author_truth: list[WorldStateKnowledge] = Field(default_factory=list, max_length=128)
    expert_models: list[WorldStateKnowledge] = Field(default_factory=list, max_length=128)
    public_beliefs: list[WorldStateKnowledge] = Field(
        default_factory=list, max_length=128
    )
    reader_unknowns: list[WorldStateKnowledge] = Field(
        default_factory=list, max_length=128
    )


class WorldStateReproductionLoops(BaseModel):
    model_config = ConfigDict(extra="forbid")

    material: WorldStateCoverageEntry
    population_care: WorldStateCoverageEntry
    economic: WorldStateCoverageEntry
    institutional: WorldStateCoverageEntry
    knowledge: WorldStateCoverageEntry
    meaning_identity: WorldStateCoverageEntry


class WorldStateSituatedTests(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ordinary_tuesday: WorldStateSituatedTest
    seven_day_failure: WorldStateSituatedTest
    life_course: WorldStateSituatedTest
    ten_year_feedback: WorldStateSituatedTest


class WorldStateFictionCore(BaseModel):
    model_config = ConfigDict(extra="forbid")

    world: WorldStatePipelineEntry
    character: WorldStatePipelineEntry
    story: WorldStatePipelineEntry
    outline: WorldStatePipelineEntry
    prose: WorldStatePipelineEntry
    editor: WorldStatePipelineEntry


class WorldStateAudit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    last_run_at: datetime | None = None
    engine_version: str = Field(default="", max_length=64)
    valid: bool | None = None
    blocking_gaps: list[str] = Field(default_factory=list, max_length=128)
    warnings: list[str] = Field(default_factory=list, max_length=128)
