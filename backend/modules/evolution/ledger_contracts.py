"""Author-only derived understanding; neither observations nor decisions are Canon."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from modules.evolution.contracts import (
    ObservationModality,
    SourceRevisionRef,
    StoryPosition,
)

LEDGER_CONTRACT_VERSION = 1
DISCOVERY_METHOD_VERSION = "evolution.discovery.v1"

LedgerCategory = Literal["conditional_behavior", "clue", "commitment"]


class LedgerModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LedgerTarget(LedgerModel):
    domain: Literal["world", "story"]
    kind: Literal["entity", "scene", "foreshadowing", "reveal"]
    target_id: UUID
    version_fingerprint: str = Field(min_length=1, max_length=128)
    binding: Literal["resolved", "needs_revalidation"] = "resolved"
    label: str = Field(default="", max_length=200)
    version_kind: Literal["observation_binding"] = "observation_binding"

    @model_validator(mode="after")
    def owning_domain(self):
        if (self.kind == "entity") != (self.domain == "world"):
            raise ValueError("Target identity remains owned by its original domain")
        return self


class LedgerEvidence(LedgerModel):
    observation_id: str = Field(min_length=1, max_length=128)
    position: StoryPosition
    modality: ObservationModality
    quote: str = Field(min_length=1, max_length=2000)
    source_ref: SourceRevisionRef
    role: Literal["support", "exception_case", "counterevidence"] = "support"
    occurrence_id: str | None = Field(default=None, max_length=128)
    purpose: Literal["occurrence", "context"] = "context"
    occurrence_kind: Literal["event", "recall", "claim", "unknown", "context"] = "unknown"
    occurrence_origin: (
        Literal["event", "recall", "claim", "unknown", "context"] | None
    ) = None

    @model_validator(mode="after")
    def occurrence_is_not_a_citation(self):
        if self.occurrence_kind in {"event", "recall"} and not self.occurrence_id:
            raise ValueError(
                "A proven occurrence needs an identity independent of citations"
            )
        if self.occurrence_kind == "event" and self.modality != "event_observed":
            raise ValueError("A claim cannot count as an observed occurrence")
        if self.source_ref.start_offset == self.source_ref.end_offset:
            raise ValueError("Ledger evidence cannot use an empty source range")
        return self


class LedgerDependency(LedgerModel):
    run_key: str = Field(min_length=1, max_length=120)
    attempt_id: str = Field(min_length=1, max_length=120)
    scene_id: UUID
    scene_index: int = Field(ge=0)
    source_manifest_hash: str = Field(min_length=32, max_length=64)


class LedgerClaim(LedgerModel):
    category: LedgerCategory
    label: str = Field(min_length=1, max_length=200)
    statement: str = Field(min_length=1, max_length=2000)
    conditions: list[str] = Field(
        default_factory=list,
        max_length=12,
        description=(
            "有原文依据的追踪维度；原文明示与动作相连的可对照基础状态/约束必须包含，外部触发不替代它，不将整个情境拼为必要合取门槛。原文或作者明确适用限制仍须保留。具体触发、程度与伴随体征以原事实/context及竞争解释保留，不宣告无关，"
            "不自动成为每次必须逐字重现的必要条件。更新保留原实质条件及当前情境差别；"
            "重新解释旧条件须有来源说明，不得任取交集制造例外。"
            "单次外部触发不因曾入字段就成必要门槛；有据重释须核原/新情境来源并经conditions_review。"
        ),
    )
    realm: Literal["history", "plan", "rehearsal"] = "history"
    modality: ObservationModality = "hypothesis"
    confidence: float = Field(ge=0, le=1)
    competing_explanations: list[str] = Field(default_factory=list, max_length=8)
    targets: list[LedgerTarget] = Field(default_factory=list, max_length=32)
    unresolved_subjects: list[str] = Field(default_factory=list, max_length=128)
    evidence: list[LedgerEvidence] = Field(min_length=1, max_length=512)
    dependencies: list[LedgerDependency] = Field(min_length=1, max_length=512)
    method_fingerprint: str = Field(min_length=32, max_length=64)
    method_version: str = DISCOVERY_METHOD_VERSION
    contract_version: Literal[1] = LEDGER_CONTRACT_VERSION


class DiscoveryEvidenceChoice(LedgerModel):
    observation_id: str = Field(min_length=1, max_length=128)
    role: Literal["support", "exception_case", "counterevidence"] = "support"
    purpose: Literal["occurrence", "context"] = Field(
        default="context",
        description=(
            "occurrence须匹配目标原具体细节的发生单位，不能随新statement扩大。"
            "线索的含义解释、相关后续交付/不同动作仅context；承诺的明确兑现可作该承诺实例。"
            "已认证旧源默认继承，重新选择时保留evidence_uses既有用途及锚，不把旧物理出现改成context。"
        ),
    )
    occurrence_kind: Literal["event", "recall", "claim", "unknown", "context"] = "unknown"
    same_occurrence_as: str | None = Field(
        default=None,
        max_length=128,
        description=(
            "For occurrence-purpose event, null computes the host anchor, or use the "
            "exact event_occurrence_id for this provided observation. Other event/recall "
            "links must cite an original occurrence_id from the bound theme; context "
            "must be null. Never use an observation_id."
        ),
    )


class DiscoveryChange(LedgerModel):
    action: Literal["new", "enhance", "narrow", "exception", "question"] = Field(
        description="new包含无既有目标的独立待核实条目；question及其它更新只针对本批完整theme，必须绑定它的准确entry_id/revision，缺目标只记unresolved。"
    )
    target_entry_id: UUID | None = Field(
        default=None,
        description="更新只复制本批historical_context完整theme的entry_id；theme_index和prior_review不是更新目标。",
    )
    expected_revision: int | None = Field(
        default=None,
        ge=1,
        description="只复制同一完整theme当前revision；不取prior_review理由、作者basis_revision或其它批次旧值。",
    )
    category: LedgerCategory
    label: str = Field(min_length=1, max_length=200)
    statement: str = Field(
        min_length=1,
        max_length=2000,
        description=(
            "最小充分主张；说话人/知情/自述等归属须原句，叙述者说明不能改成角色言语。"
            "转述优先原姓名/原引语，性别代词须本项原句依据，不能由姓名、旧摘要或后文猜得。"
            "回忆者与原动作主体分位，按整段原句核定，不采信派生predicate或旧主张自证。"
            "首次明确情境动作只写这次事实，不概括习惯；清楚段落共指可还原人物，World新候选不等于文本主体未知。"
        ),
    )
    conditions: list[str] = Field(
        default_factory=list,
        max_length=12,
        description=(
            "有原文依据的追踪维度；原文明示与动作相连的可对照基础状态/约束必须包含，外部触发不替代它，不将整个情境拼为必要合取门槛。原文或作者明确适用限制仍须保留。具体触发、程度与伴随体征以原事实/context及竞争解释保留，不宣告无关，"
            "不自动成为每次必须逐字重现的必要条件。同人同具体动作的明确再现可有不同触发，"
            "保留情境差别、未知物件同一性与机理，不自动拒绝动作实例或推普遍性。更新保留原实质条件；"
            "重新解释旧条件须有来源说明，不得任取交集制造例外。"
            "单次外部触发不因曾入字段就成必要门槛；有据重释须核原/新情境来源并经conditions_review。"
        ),
    )
    modality: ObservationModality = "hypothesis"
    confidence: float = Field(ge=0, le=1)
    evidence: list[DiscoveryEvidenceChoice] = Field(min_length=1, max_length=64)
    competing_explanations: list[str] = Field(default_factory=list, max_length=8)

    @model_validator(mode="after")
    def revision_binding(self):
        if self.action == "new":
            if self.target_entry_id is not None or self.expected_revision is not None:
                raise ValueError("New themes cannot silently rebind another theme")
        elif self.target_entry_id is None or self.expected_revision is None:
            raise ValueError("A theme change must bind its exact existing revision")
        if self.action == "exception" and not any(
            item.role in {"exception_case", "counterevidence"} for item in self.evidence
        ):
            raise ValueError(
                "An exception requires explicit evidence; "
                "missing description is not a counterexample"
            )
        if any(item.role == "exception_case" for item in self.evidence) and (
            self.category != "conditional_behavior" or not self.conditions
        ):
            raise ValueError("A behavioral exception needs explicit conditions")
        if len({(item.observation_id, item.role) for item in self.evidence}) != len(
            self.evidence
        ):
            raise ValueError("Repeated citations are not independent evidence")
        return self


class DiscoveryOutput(LedgerModel):
    changes: list[DiscoveryChange] = Field(default_factory=list, max_length=32)
    unresolved: list[str] = Field(
        default_factory=list,
        max_length=32,
        description=(
            "实际未解/未覆盖范围；保留原叙述与指称资格，不把说明写成角色自认，"
            "不把缺完整目标或World未入库当成文本主体歧义，也不与已明确的本轮观察矛盾。"
        ),
    )
    coverage: Literal["inspected", "partial", "unsupported"]
    coverage_note: str = Field(min_length=1, max_length=2000)


class ConditionsReview(LedgerModel):
    """Source-bound qualification of a change to an existing theme's conditions."""

    verdict: Literal["supported", "uncertain", "rejected"]
    observation_ids: list[str] = Field(default_factory=list, max_length=64)
    reason: str = Field(min_length=1, max_length=2000)


class RecallIdentityReview(LedgerModel):
    """Certify one newly proposed recall-to-original-event link, not just its action."""

    observation_id: str = Field(min_length=1, max_length=128)
    occurrence_id: str = Field(min_length=1, max_length=128)
    verdict: Literal["supported", "uncertain", "rejected"]
    original_observation_ids: list[str] = Field(default_factory=list, max_length=64)
    identity_observation_ids: list[str] = Field(default_factory=list, max_length=64)
    reason: str = Field(min_length=1, max_length=2000)


class DiscoveryVerdict(LedgerModel):
    """Certify only IDs selected in this change's evidence or inherited through
    its matching target_theme.evidence_observation_ids. Other visible observations
    are comparison material for the reason, not additional bound evidence.
    """

    change_index: int = Field(ge=0)
    verdict: Literal["supported", "uncertain", "rejected"]
    reason: str = Field(min_length=1, max_length=2000)
    conditions_review: ConditionsReview | None = Field(
        default=None,
        description=(
            "已有目标conditions变化时必须专审：逐项解释旧实质条件的保留/删除/重新解释依据，"
            "不能只认证本轮传闻。supported须非空来源，且仅本项已选/继承并在本批实际可见的观察；"
            "原条件混入单次触发背景时，以原情境及当前明示对照状态/约束的两侧原句核有据重释；"
            "不把旧字段自证为必要条件，也不任取共同词。保留原情境和旧动作事实。"
            "不足则uncertain/rejected。条件未变或new用null。"
        ),
    )
    recall_identity_reviews: list[RecallIdentityReview] = Field(
        default_factory=list,
        max_length=64,
        description=(
            "本轮recall链接具体旧occurrence时，逐pair独立核身份，不能只核动作。"
            "original_observation_ids必须选目标该occurrence的已定位原event动作；"
            "identity_observation_ids须包含本轮recall动作及用于指认的原句，两侧均为本项已选/继承且本批可见。"
            "对照旧原动作与新指认，说明为何唯一对应、是否可能另次旧事件；无新动作、只有一条已存候选、"
            "相同主体动作或新句说同一个事件均不能单独证明具体旧锚。合法唯一间接指认亦可，不设关键词门。"
            "关键实例身份未决用uncertain/rejected，不能把它藏在整体supported的竞争解释中；"
            "无specific锚的recall/null及继承旧use无需新证书。"
        ),
    )
    occurrence_observation_ids: list[str] = Field(
        default_factory=list,
        max_length=64,
        description=(
            "Certified positive occurrence witnesses, including a recall bound to an "
            "existing occurrence and reviewed original sources. This is not a list "
            "of newly occurring events; the host deduplicates occurrence identities."
        ),
    )
    exception_observation_ids: list[str] = Field(
        default_factory=list,
        max_length=64,
        description=(
            "有实质条件来源的明确负向/不同选择实例；过去单次动作、未证习惯或作者instance不禁止独立例外。"
            "旧conditions混入初次触发时，先以conditions_review核候选有据重释，再判例外；"
            "不证伪过去动作、不盲删实质条件，不把缺描写当负向。"
        ),
    )
    context_observation_ids: list[str] = Field(
        default_factory=list,
        max_length=64,
        description=(
            "Observations independently classified as background or conditions, "
            "not occurrence witnesses. Correct a generator's occurrence purpose "
            "here; do not list an ambiguous occurrence as context."
        ),
    )
    counterevidence_observation_ids: list[str] = Field(
        default_factory=list, max_length=64
    )


class DiscoveryReview(LedgerModel):
    verdicts: list[DiscoveryVerdict] = Field(default_factory=list, max_length=32)


class LedgerDecision(LedgerModel):
    operation_id: UUID
    expected_revision: int = Field(ge=1)
    decision: Literal["keep", "reject", "corrected", "unreviewed"]
    note: str = Field(default="", max_length=2000)
    corrected_statement: str | None = Field(default=None, min_length=1, max_length=2000)
    scope: Literal["instance", "theme"] = "instance"
    confirmed_scope_expansion: bool = False

    @model_validator(mode="after")
    def author_scope(self):
        if self.decision == "corrected" and not self.corrected_statement:
            raise ValueError("A correction needs the author's replacement statement")
        if self.scope == "theme" and not self.confirmed_scope_expansion:
            raise ValueError(
                "Expanding the author's decision needs explicit confirmation"
            )
        return self


def evidence_counts(evidence: list[LedgerEvidence]) -> dict[str, int]:
    """Generation count is never an occurrence count."""
    return {
        "occurrences": len(
            {
                item.occurrence_id
                for item in evidence
                if item.purpose == "occurrence"
                and item.role == "support"
                and item.occurrence_id
                and item.occurrence_kind in {"event", "recall"}
            }
        ),
        "exception_occurrences": len(
            {
                item.occurrence_id
                for item in evidence
                if item.purpose == "occurrence"
                and item.role == "exception_case"
                and item.occurrence_id
                and item.occurrence_kind in {"event", "recall"}
            }
        ),
        "counter_occurrences": len(
            {
                item.occurrence_id
                for item in evidence
                if item.purpose == "occurrence"
                and item.role == "counterevidence"
                and item.occurrence_id
                and item.occurrence_kind in {"event", "recall"}
            }
        ),
        "observations": len({item.observation_id for item in evidence}),
        "sources": len(
            {
                (
                    item.source_ref.draft_id,
                    item.source_ref.content_hash,
                    item.source_ref.start_offset,
                    item.source_ref.end_offset,
                )
                for item in evidence
            }
        ),
        "unknown_occurrences": len(
            {
                item.observation_id
                for item in evidence
                if item.purpose == "occurrence" and item.occurrence_kind == "unknown"
            }
            - {
                item.observation_id
                for item in evidence
                if item.purpose == "occurrence"
                and item.occurrence_kind in {"event", "recall"}
                and item.occurrence_id
            }
        ),
    }
