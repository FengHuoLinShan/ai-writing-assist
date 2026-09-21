"""Evolution 演化系统契约层（V4 E01）。

依据 docs/plans/novelcraft-v4/plans/01-EVOLUTION.md §2–§3 的类型契约草案。
本包当前只提供跨模块稳定契约与稳定观察身份推导，不含 ORM、编排或迁移；
接入顺序由后续 E02–E08 按 owner epoch 与窄事务规则落地。

三条硬语义（G0 契约测试已钉住旧链缺口，本层是新链的规范来源）：

1. 观察（Observation）≠ 解释（Interpretation）≠ 状态操作（StateOperation）。
   逐字证据命中只证明引用定位，不证明该引用蕴含客观状态变化。
2. 事件身份来自来源范围 + 观察语义 + 契约版本，不来自"第几个输出"。
3. 游标只在领域提交成功后推进；模型返回或进度百分比不构成推进依据。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from infrastructure.llm.collaboration import content_hash

EVOLUTION_CONTRACT_VERSION = 1
"""本契约层的稳定版本；解释内核或字段语义变化必须提升版本并保留旧版本读取。"""

# ---------------------------------------------------------------------------
# 来源
# ---------------------------------------------------------------------------

SourceKind = Literal["chapter_draft", "imported_source"]
SourceVisibility = Literal["canonical", "working"]


class SourceRevisionRef(BaseModel):
    """不可变来源引用：定位一段冻结正文，身份不由章节序号独自承担。

    同字数替换、标题修改、复制工作稿、恢复旧稿都会改变 content_hash /
    draft_id / source_revision 中的至少一项，从而产生可识别变化。
    """

    model_config = ConfigDict(extra="forbid")

    novel_id: str = Field(min_length=1)
    source_kind: SourceKind
    draft_id: str = Field(min_length=1)
    content_hash: str = Field(min_length=32, max_length=64)
    chapter_identity: str = Field(
        min_length=1,
        description="稳定章节身份（如章节 UUID）；chapter_index 仅用于展示排序",
    )
    start_offset: int = Field(ge=0)
    end_offset: int = Field(ge=0)
    range_hash: str = Field(min_length=32, max_length=64)
    source_revision: int = Field(ge=0)
    segmentation_version: int = Field(ge=1)
    source_visibility: SourceVisibility

    @model_validator(mode="after")
    def _validate_range(self) -> SourceRevisionRef:
        if self.end_offset < self.start_offset:
            raise ValueError("end_offset must be >= start_offset")
        expected = self.compute_range_hash(
            self.content_hash, self.start_offset, self.end_offset
        )
        if self.range_hash != expected:
            raise ValueError("range_hash does not match content_hash + offsets")
        return self

    @staticmethod
    def compute_range_hash(
        source_content_hash: str, start_offset: int, end_offset: int
    ) -> str:
        return content_hash(
            {
                "content_hash": source_content_hash,
                "start_offset": start_offset,
                "end_offset": end_offset,
            }
        )


class StoryPosition(BaseModel):
    """叙事位置锚点；倒叙与后揭示必须可表达（scene_index 为主序，chapter 为展示）。"""

    model_config = ConfigDict(extra="forbid")

    scene_id: str | None = None
    scene_index: int | None = None
    chapter_index: int | None = None

    @model_validator(mode="after")
    def _validate_anchor(self) -> StoryPosition:
        if (
            self.scene_id is None
            and self.scene_index is None
            and self.chapter_index is None
        ):
            raise ValueError("story position requires at least one anchor")
        return self


# ---------------------------------------------------------------------------
# 观察
# ---------------------------------------------------------------------------

ObservationModality = Literal[
    "event_observed",  # 叙述者视角观察到的事件
    "character_statement",  # 角色陈述：说话内容不等于事实
    "belief",  # 角色信念/误信
    "hypothesis",  # 推测、待证
    "author_plan",  # 作者规划、大纲层信息
    "figurative",  # 比喻/非字面表达
    "unclear",  # 无法判定
]
ObservationDisposition = Literal[
    "recorded",
    "deduplicated",
    "conflicted",
    "superseded",
    "rejected",
]


class MentionRef(BaseModel):
    """可追踪的提及身份；未解析时保留 mention_id，禁止伪造实体 UUID。"""

    model_config = ConfigDict(extra="forbid")

    mention_id: str = Field(min_length=1, max_length=120)
    surface: str = Field(min_length=1, max_length=200)
    entity_type: str | None = Field(default=None, max_length=32)
    resolved_entity_id: str | None = Field(default=None, min_length=1)
    unresolved_reason: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def _validate_resolution(self) -> MentionRef:
        if self.resolved_entity_id is None and not self.unresolved_reason:
            raise ValueError("unresolved mention must record unresolved_reason")
        return self


class EvidenceQuote(BaseModel):
    """逐字证据；必须携带自己的来源范围，引用命中不证明解释成立。"""

    model_config = ConfigDict(extra="forbid")

    quote: str = Field(min_length=1, max_length=2000)
    source_ref: SourceRevisionRef


class ObservationEnvelope(BaseModel):
    """一次窄任务观察的外壳：原文确实出现了什么说法或行为。

    observation_id 由 observations.derive_observation_id 按语义指纹推导，
    不接受调用方任意指定（见 with_stable_id 构造入口）。
    """

    model_config = ConfigDict(extra="forbid")

    observation_id: str = Field(min_length=64, max_length=64)
    source_ref: SourceRevisionRef
    observer_contract_version: int = Field(ge=1)
    mention_refs: list[MentionRef] = Field(default_factory=list, max_length=64)
    predicate_or_description: str = Field(min_length=1, max_length=2000)
    modality: ObservationModality
    speaker_ref: MentionRef | None = None
    valid_story_time: str | None = Field(default=None, max_length=200)
    learned_at_position: StoryPosition
    evidence_quotes: list[EvidenceQuote] = Field(min_length=1, max_length=16)
    unresolved_parts: list[str] = Field(default_factory=list, max_length=32)
    disposition: ObservationDisposition = "recorded"
    producer_run_id: str = Field(min_length=1, max_length=120)
    input_manifest_hash: str = Field(min_length=32, max_length=64)

    @classmethod
    def with_stable_id(cls, **kwargs: Any) -> ObservationEnvelope:
        """按语义指纹推导 observation_id 后构造（详见 observations.py）。"""
        from modules.evolution.observations import derive_observation_id

        payload = {**kwargs}
        payload.pop("observation_id", None)
        source_ref: SourceRevisionRef = payload["source_ref"]
        payload["observation_id"] = derive_observation_id(
            source_ref=source_ref,
            predicate_or_description=payload["predicate_or_description"],
            modality=payload["modality"],
            observer_contract_version=payload["observer_contract_version"],
        )
        return cls(**payload)


# ---------------------------------------------------------------------------
# 身份解析
# ---------------------------------------------------------------------------

IdentityOutcome = Literal["reuse", "new_candidate", "ambiguous", "unrelated"]
EvidenceKind = Literal["exact_name", "exact_alias", "fuzzy", "semantic"]


class IdentityCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entity_id: str = Field(min_length=1)
    evidence: str = Field(min_length=1, max_length=1000)
    evidence_kind: EvidenceKind | None = Field(
        default=None,
        description="适配器归一后的证据类别；解析内核只对 exact_* 证据自动 reuse",
    )
    same_name: bool = False
    alias_used: str | None = Field(default=None, max_length=200)


class IdentityResolution(BaseModel):
    """身份解析结果：身份去重（不建影子）与观察积累（不丢新观察）分离。

    已有身份命中绝不跳过新观察——观察照常记录，解析结论独立持久。
    """

    model_config = ConfigDict(extra="forbid")

    mention_ref: MentionRef
    outcome: IdentityOutcome
    resolved_entity_id: str | None = Field(default=None, min_length=1)
    candidates: list[IdentityCandidate] = Field(default_factory=list, max_length=16)
    rationale: str = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def _validate_outcome(self) -> IdentityResolution:
        if self.outcome == "reuse":
            if not self.resolved_entity_id:
                raise ValueError("reuse requires resolved_entity_id")
            if not self.candidates:
                raise ValueError("reuse requires the matched candidate evidence")
        if self.outcome == "ambiguous" and len(self.candidates) < 2:
            raise ValueError("ambiguous requires at least two candidates")
        if self.outcome in {"new_candidate", "unrelated"} and self.resolved_entity_id:
            raise ValueError("new_candidate/unrelated must not bind an existing entity")
        return self


# ---------------------------------------------------------------------------
# 类型化状态操作
# ---------------------------------------------------------------------------

OperationKind = Literal[
    "entity.create",
    "entity.update",
    "entity.remove",
    "relation.establish",
    "relation.end",
    "location.observe",
    "location.move",
    "knowledge.learn",
    "knowledge.revise",
    "knowledge.revoke",
    "timeline.assert",
    "causal_constraint.assert",
    "documentary_assertion",
]
AuthorityBasis = Literal["derived_observation", "author_confirmation", "author_adoption"]

STATE_CHANGING_OPERATION_KINDS: frozenset[str] = frozenset(
    {
        "entity.create",
        "entity.update",
        "entity.remove",
        "relation.establish",
        "relation.end",
        "location.observe",
        "location.move",
        "knowledge.learn",
        "knowledge.revise",
        "knowledge.revoke",
        "timeline.assert",
        "causal_constraint.assert",
    }
)


def operation_changes_state(operation_kind: OperationKind) -> bool:
    """documentary_assertion 承载尚不能安全投影的观察，不改变核心状态。"""
    return operation_kind in STATE_CHANGING_OPERATION_KINDS


class TypedStateOperation(BaseModel):
    """对指定状态做什么操作；机器产物 authority_basis 固定为 derived_observation。

    位置操作区分 observe（此处出现）与 move（从甲到乙，需移动证据）；
    前值未知时允许 before_precondition 为 None（assert 语义），不得伪造前值。
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: int = Field(ge=1)
    operation_kind: OperationKind
    subject_ref: str = Field(
        min_length=1,
        max_length=120,
        description="已解析实体 ID 或可追踪 mention_id；不得是编造 UUID",
    )
    relation_or_field: str | None = Field(default=None, max_length=200)
    before_precondition: dict[str, Any] | None = None
    value: dict[str, Any] = Field(default_factory=dict)
    story_position: StoryPosition
    valid_time: str | None = Field(default=None, max_length=200)
    knowledge_subject: str | None = Field(
        default=None,
        max_length=120,
        description="knowledge.* 操作必须指明认知主体（谁知道）",
    )
    source_observation_ids: list[str] = Field(min_length=1, max_length=32)
    authority_basis: AuthorityBasis = "derived_observation"
    derivation_version: int = Field(ge=1)

    @model_validator(mode="after")
    def _validate_semantics(self) -> TypedStateOperation:
        if self.operation_kind.startswith("relation.") and not self.relation_or_field:
            raise ValueError("relation operations require relation_or_field")
        if self.operation_kind.startswith("knowledge.") and not self.knowledge_subject:
            raise ValueError("knowledge operations require knowledge_subject")
        return self


# ---------------------------------------------------------------------------
# 回执与游标
# ---------------------------------------------------------------------------

CoverageStatus = Literal[
    "inspected", "not_run", "unknown", "excluded", "stale", "unsupported"
]


class CoverageContract(BaseModel):
    """覆盖度按状态分列；局部完成不得折叠成全量完成。"""

    model_config = ConfigDict(extra="forbid")

    inspected: list[str] = Field(default_factory=list)
    not_run: list[str] = Field(default_factory=list)
    unknown: list[str] = Field(default_factory=list)
    excluded: list[str] = Field(default_factory=list)
    stale: list[str] = Field(default_factory=list)
    unsupported: list[str] = Field(default_factory=list)

    def total_claimed(self) -> int:
        return sum(len(getattr(self, name)) for name in type(self).model_fields)


class CommittedPrefix(BaseModel):
    """已领域提交的前缀游标；重放、恢复与依赖编译以它为唯一依据。"""

    model_config = ConfigDict(extra="forbid")

    through_scene_index: int = Field(ge=0)
    through_source_revision: int = Field(ge=0)

    def covers(self, other: CommittedPrefix) -> bool:
        return (
            self.through_scene_index >= other.through_scene_index
            and self.through_source_revision >= other.through_source_revision
        )


ExecutionStatus = Literal[
    "succeeded",
    "partial",
    "failed",
    "blocked",
    "unknown_billing",
]
OutcomeStatus = Literal["committed", "nothing_to_do", "needs_decision", "abandoned"]
FreshnessStatus = Literal["fresh", "stale", "superseded"]

_NON_ADVANCING_EXECUTION_STATUSES: frozenset[ExecutionStatus] = frozenset(
    {"failed", "blocked", "unknown_billing"}
)


class EvolutionReceipt(BaseModel):
    """跨模块交接证明：本批次读了什么、产出了什么、推进到哪里。

    不复制世界表；world/story/evidence 结果以 result_refs 引用。
    """

    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(min_length=1, max_length=120)
    attempt_id: str = Field(min_length=1, max_length=120)
    owner_epoch: int = Field(ge=1)
    producer_version: str = Field(min_length=1, max_length=64)
    source_manifest_hash: str = Field(min_length=32, max_length=64)
    input_state_receipt: str = Field(min_length=32, max_length=64)
    previous_receipt: str | None = Field(default=None, min_length=32, max_length=64)
    previous_committed_prefix: CommittedPrefix | None = None
    observation_dispositions: dict[ObservationDisposition, int] = Field(
        default_factory=dict
    )
    world_result_refs: list[dict[str, str]] = Field(default_factory=list)
    story_result_refs: list[dict[str, str]] = Field(default_factory=list)
    evidence_result_refs: list[dict[str, str]] = Field(default_factory=list)
    pending_decisions: list[str] = Field(default_factory=list, max_length=64)
    coverage: CoverageContract = Field(default_factory=CoverageContract)
    committed_prefix: CommittedPrefix
    blocked_dependencies: list[str] = Field(default_factory=list)
    paid_call_receipts: list[dict[str, Any]] = Field(default_factory=list)
    execution_status: ExecutionStatus
    outcome_status: OutcomeStatus
    freshness: FreshnessStatus = "fresh"

    @model_validator(mode="after")
    def _validate_cursor_discipline(self) -> EvolutionReceipt:
        previous = self.previous_committed_prefix
        if previous is None:
            return self
        if not self.committed_prefix.covers(previous):
            raise ValueError(
                "committed_prefix must not regress below previous_committed_prefix"
            )
        if (
            self.execution_status in _NON_ADVANCING_EXECUTION_STATUSES
            and self.committed_prefix != previous
        ):
            raise ValueError(
                "committed_prefix may not advance or shift when execution did"
                " not reach domain commit"
            )
        return self


__all__ = [
    "AuthorityBasis",
    "CommittedPrefix",
    "CoverageContract",
    "CoverageStatus",
    "EVOLUTION_CONTRACT_VERSION",
    "EvidenceQuote",
    "EvidenceKind",
    "EvolutionReceipt",
    "ExecutionStatus",
    "FreshnessStatus",
    "IdentityCandidate",
    "IdentityOutcome",
    "IdentityResolution",
    "MentionRef",
    "ObservationDisposition",
    "ObservationEnvelope",
    "ObservationModality",
    "OperationKind",
    "OutcomeStatus",
    "SourceKind",
    "SourceRevisionRef",
    "STATE_CHANGING_OPERATION_KINDS",
    "StoryPosition",
    "TypedStateOperation",
    "operation_changes_state",
]
