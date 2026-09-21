"""Frozen forecast v1 public and provider contracts."""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

Hash64 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
CapabilityId = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_.]{1,100}$")]
OutputKind = Literal[
    "prepared_reference",
    "next_step",
    "creative_opportunity",
    "impact_preview",
    "decision_prompt",
]
Tier = Literal["attention", "next", "watch"]
RunStatus = Literal[
    "pending",
    "running",
    "completed",
    "failed",
    "cancelled",
    "waiting_approval",
    "budget_exceeded",
]
ResourceKind = Literal[
    "writing_draft",
    "scene",
    "core_entity",
    "world_bible_page",
    "world_bible_draft",
    "map_atlas_node",
    "world_bible_revision",
    "plot_thread",
    "outline_arc",
    "foreshadowing_plan",
    "reveal_plan",
    "context_confirmation",
    "import_workflow",
    "interaction_message",
    "interaction_source_revision",
    "interaction_overview",
    "author_task",
    "domain_finding",
    "domain_result",
    "query_scope",
    "policy",
    "selected_path",
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TextRange(StrictModel):
    start_offset: int = Field(ge=0)
    end_offset: int = Field(gt=0)

    @model_validator(mode="after")
    def ordered(self):
        if self.end_offset <= self.start_offset:
            raise ValueError("Use a nonempty half-open source range")
        return self


class FocusTarget(StrictModel):
    resource_kind: ResourceKind
    resource_id: UUID


class FocusRequest(StrictModel):
    client_context_id: UUID
    focus_seq: int = Field(ge=0)
    page: Literal[
        "today",
        "writing",
        "world",
        "outline",
        "scene",
        "map",
        "rag",
        "imports",
        "assistant",
        "project",
        "generate",
        "account",
        "interaction",
    ]
    # R00：turn 与 forecast 共用同一意图封闭集（schemas.TASK_HINTS）。
    task_hint: Literal[
        "unknown",
        "continue",
        "polish",
        "revise",
        "design",
        "retrieve",
        "review",
        "organize",
        "roleplay",
    ] = "unknown"
    journey_id: UUID | None = None
    selected_leaf_node_id: UUID | None = None
    selection_epoch: int | None = Field(default=None, ge=0)
    source_context_epoch: int | None = Field(default=None, ge=0)
    overview_epoch: int | None = Field(default=None, ge=0)
    prior_forecast_run_id: UUID | None = None
    assistant_session_id: UUID | None = None
    target: FocusTarget | None = None
    scene_id: UUID | None = None
    draft_id: UUID | None = None
    expected_source_hash: Hash64 | None = None
    selected_range: TextRange | None = None
    editor_state: Literal["saved", "dirty", "not_applicable"] = "not_applicable"
    explicit_instruction: str = Field(default="", max_length=4000)
    context_confirmation_id: UUID | None = None
    context_confirmation_action: str | None = Field(default=None, max_length=100)

    @model_validator(mode="after")
    def source_and_confirmation(self):
        if self.selected_range and not (self.draft_id and self.expected_source_hash):
            raise ValueError("A selected range needs a draft and source hash")
        if self.expected_source_hash and not self.draft_id:
            raise ValueError("A source hash needs its draft")
        if bool(self.context_confirmation_id) != bool(self.context_confirmation_action):
            raise ValueError("Confirmation ID and original action are a pair")
        return self


class Horizon(StrictModel):
    unit: Literal["scene", "decision", "operation", "interaction_beat"]
    steps: int = Field(default=1, ge=1, le=3)
    causal_depth: int = Field(default=1, ge=0, le=2)

    @model_validator(mode="after")
    def short_horizon(self):
        if self.unit in {"scene", "interaction_beat"} and self.steps > 2:
            raise ValueError("Narrative horizons are at most two beats/scenes")
        return self


class EvaluateRequest(StrictModel):
    operation_id: UUID
    context: FocusRequest
    horizon: Horizon
    trigger: Literal[
        "manual",
        "saved_change",
        "focus_activated",
        "domain_result_ready",
        "chapter_completed",
    ] = "manual"
    requested_capabilities: list[CapabilityId] = Field(default_factory=list, max_length=8)

    @model_validator(mode="after")
    def v1_saved_only(self):
        if self.context.editor_state == "dirty":
            raise ValueError(
                "V1 compute requires saved content; use feed for old saved results"
            )
        return self


class FeedRequest(StrictModel):
    context: FocusRequest
    include_deferred: bool = False
    max_items: int = Field(default=3, ge=1, le=10)
    cursor: str | None = Field(default=None, max_length=512)


class EvidenceRef(StrictModel):
    evidence_id: str = Field(min_length=1, max_length=80)
    resource_kind: ResourceKind
    resource_id: UUID
    source_hash: Hash64
    revision_token: str = Field(min_length=1, max_length=200)
    source_range: TextRange | None = None
    range_hash: Hash64 | None = None
    label: str = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def range_pair(self):
        if bool(self.source_range) != bool(self.range_hash):
            raise ValueError("Range and range hash must be present together")
        return self


class Statement(StrictModel):
    text: str = Field(min_length=1, max_length=2000)
    basis: Literal["observed", "inferred", "proposed"]
    evidence_ids: list[str] = Field(default_factory=list, max_length=12)
    assumptions: list[str] = Field(default_factory=list, max_length=8)

    @model_validator(mode="after")
    def observations_need_evidence(self):
        if self.basis == "observed" and not self.evidence_ids:
            raise ValueError("Observed statements need host-resolvable evidence")
        return self


class Direction(StrictModel):
    direction_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,39}$")
    title: str = Field(min_length=1, max_length=160)
    condition: str = Field(min_length=1, max_length=1000)
    proposal: str = Field(min_length=1, max_length=2000)
    possible_effects: list[str] = Field(default_factory=list, max_length=6)
    assumptions: list[str] = Field(default_factory=list, max_length=8)
    narrative_commitment: Literal["low", "medium", "high", "unknown"]
    may_leave_open: bool = False


class CandidateProposal(StrictModel):
    """LLM output: deliberately excludes identity, ranking, auth and actions."""

    title: str = Field(min_length=1, max_length=200)
    kind: OutputKind
    statements: list[Statement] = Field(min_length=1, max_length=12)
    why_now: str = Field(min_length=1, max_length=2000)
    directions: list[Direction] = Field(default_factory=list, max_length=3)
    unknowns: list[str] = Field(default_factory=list, max_length=10)
    verdict: Literal["propose", "observe", "abstain"]


class ActionView(StrictModel):
    action_id: str = Field(pattern=r"^[a-z][a-z0-9_.-]{0,99}$")
    label: str = Field(min_length=1, max_length=160)
    kind: Literal["inspect", "explore", "prepare_domain", "schedule_followup"]
    requires_confirmation: bool
    available: bool
    unavailable_reason: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def reason_and_confirmation(self):
        if not self.available and not self.unavailable_reason:
            raise ValueError("Unavailable actions must explain why")
        if self.kind == "prepare_domain" and not self.requires_confirmation:
            raise ValueError(
                "Preparing a domain operation never waives later confirmation"
            )
        return self


class CoverageCounts(StrictModel):
    presented: int = Field(default=0, ge=0)
    merged: int = Field(default=0, ge=0)
    backlog: int = Field(default=0, ge=0)
    waiting_condition: int = Field(default=0, ge=0)
    suppressed: int = Field(default=0, ge=0)
    needs_verification: int = Field(default=0, ge=0)
    not_checked: int = Field(default=0, ge=0)
    source_invalid: int = Field(default=0, ge=0)


class Omission(StrictModel):
    code: Literal[
        "budget",
        "source_unavailable",
        "scope_unsupported",
        "index_stale",
        "retrieval_failed",
        "overflow",
        "not_requested",
        "source_changed",
        "not_run",
    ]
    description: str = Field(min_length=1, max_length=1000)


class CoverageReport(StrictModel):
    scope_label: str = Field(min_length=1, max_length=300)
    enumerated_total: int = Field(ge=0)
    enumeration_complete: bool
    semantic_search: Literal["complete_for_declared_plan", "partial", "not_run"]
    counts: CoverageCounts
    omissions: list[Omission] = Field(default_factory=list, max_length=30)

    @model_validator(mode="after")
    def conservation(self):
        if sum(self.counts.model_dump().values()) != self.enumerated_total:
            raise ValueError(
                "Every enumerated candidate needs exactly one primary disposition"
            )
        return self


class CandidateView(StrictModel):
    navigation: dict | None = None
    candidate_id: UUID
    issue_key: str = Field(min_length=1, max_length=160)
    notice_version: int = Field(ge=0)
    notice_status: Literal["unread", "read", "snoozed", "dismissed"] = "unread"
    disposition: str | None = None
    run_id: UUID
    capability_id: CapabilityId
    assessment_hash: Hash64
    context_hash: Hash64
    title: str = Field(min_length=1, max_length=200)
    kind: OutputKind
    tier: Tier
    verification_status: Literal["supported", "uncertain", "domain_verified"]
    freshness: Literal["valid", "stale", "revoked", "expired"]
    statements: list[Statement] = Field(min_length=1, max_length=12)
    why_now: str = Field(min_length=1, max_length=2000)
    directions: list[Direction] = Field(default_factory=list, max_length=3)
    unknowns: list[str] = Field(default_factory=list, max_length=10)
    evidence: list[EvidenceRef] = Field(default_factory=list, max_length=30)
    domain_finding_ref: UUID | None = None
    actions: list[ActionView] = Field(default_factory=list, max_length=8)
    basis_label: str = Field(min_length=1, max_length=300)
    expires_at: AwareDatetime

    @model_validator(mode="after")
    def public_consistency(self):
        ids = [e.evidence_id for e in self.evidence]
        if len(ids) != len(set(ids)):
            raise ValueError("Evidence IDs must be unique")
        for statement in self.statements:
            if set(statement.evidence_ids) - set(ids):
                raise ValueError(
                    "Statements reference evidence absent from the safe projection"
                )
        if self.verification_status == "domain_verified" and not self.domain_finding_ref:
            raise ValueError("A domain-verified claim needs its real domain finding")
        if self.freshness != "valid" and any(
            a.available for a in self.actions if a.kind == "prepare_domain"
        ):
            raise ValueError("Stale/revoked results cannot prepare domain changes")
        return self


class FeedResponse(StrictModel):
    protocol: Literal["forecast_v1"] = "forecast_v1"
    client_context_id: UUID
    focus_seq: int = Field(ge=0)
    context_hash: Hash64
    items: list[CandidateView] = Field(default_factory=list, max_length=10)
    coverage: CoverageReport
    state: Literal["ready", "empty", "not_checked", "disabled", "unavailable", "stale"]
    next_cursor: str | None = None
    generated_at: AwareDatetime
    references: list[EvidenceRef] = Field(default_factory=list, max_length=30)

    @model_validator(mode="after")
    def feed_state_consistency(self):
        if (
            self.state in {"empty", "disabled", "unavailable", "not_checked"}
            and self.items
        ):
            raise ValueError("An empty/unavailable feed cannot include active items")
        if len({item.candidate_id for item in self.items}) != len(self.items):
            raise ValueError("A feed cannot include the same assessment twice")
        return self


class WakeAt(StrictModel):
    kind: Literal["at_time"]
    at: AwareDatetime


class WakeScene(StrictModel):
    kind: Literal["scene_activated", "chapter_completed"]
    target_id: UUID


class WakeReappearance(StrictModel):
    kind: Literal["object_reappears"]
    object_id: UUID
    after_event_token: str = Field(min_length=1, max_length=200)


class WakeManual(StrictModel):
    kind: Literal["manual_reopen"]


WakeCondition = Annotated[
    WakeAt | WakeScene | WakeReappearance | WakeManual, Field(discriminator="kind")
]


class DecisionRequest(StrictModel):
    expected_notice_version: int = Field(ge=0)
    expected_assessment_hash: Hash64
    action: Literal[
        "read",
        "keep_observing",
        "as_ordinary_detail",
        "not_this_direction",
        "snooze",
        "reopen",
    ]
    wake_condition: WakeCondition | None = None
    direction_id: str | None = Field(default=None, max_length=40)

    @model_validator(mode="after")
    def condition_matches(self):
        if (self.action == "snooze") != (self.wake_condition is not None):
            raise ValueError("Only snooze requires a wake condition")
        if (self.action == "not_this_direction") != bool(self.direction_id):
            raise ValueError("Only a direction rejection carries its stable direction ID")
        return self


class DecisionReceipt(StrictModel):
    candidate_id: UUID
    notice_version: int = Field(ge=1)
    notice_status: Literal["unread", "read", "snoozed", "dismissed"]
    disposition: str
    domain_state_changed: Literal[False] = False


class OperationRequest(StrictModel):
    operation_id: UUID


class PrepareRequest(OperationRequest):
    expected_assessment_hash: Hash64
    action_id: str = Field(pattern=r"^[a-z][a-z0-9_.-]{0,99}$")
    context: FocusRequest

    @model_validator(mode="after")
    def no_unsaved_overwrite(self):
        if self.context.editor_state == "dirty":
            raise ValueError(
                "Preparing an applicable operation must protect unsaved input"
            )
        return self


class UsageView(StrictModel):
    requests: int = Field(ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    usage_complete: bool

    @model_validator(mode="after")
    def honest_unknown(self):
        if self.usage_complete and (
            self.input_tokens is None or self.output_tokens is None
        ):
            raise ValueError("Complete usage cannot omit token totals")
        return self


class RunView(StrictModel):
    run_id: UUID
    task_id: UUID | None = None
    status: RunStatus
    phase: Literal[
        "queued", "materializing", "analyzing", "validating", "publishing", "done"
    ]
    completion: Literal["complete", "partial", "not_run"]
    candidate_ids: list[UUID] = Field(default_factory=list, max_length=64)
    coverage: CoverageReport | None = None
    usage: UsageView
    error_code: str | None = Field(default=None, max_length=100)
    can_resume: bool = False


class RunSubmission(StrictModel):
    operation_id: UUID
    run_id: UUID
    replayed: bool
    status: RunStatus


class PreparationReceipt(StrictModel):
    draft_id: UUID | None = None
    source_hash: Hash64 | None = None
    operation_id: UUID
    run_id: UUID
    parent_forecast_run_id: UUID
    batch_id: UUID | None = None
    batch_fingerprint: Hash64 | None = None
    status: Literal["pending", "preview_ready", "stale", "failed"]
    requires_separate_confirmation: Literal[True] = True
    domain_write_performed: Literal[False] = False

    @model_validator(mode="after")
    def batch_pair(self):
        if bool(self.batch_id) != bool(self.batch_fingerprint):
            raise ValueError("Batch identity and fingerprint must be paired")
        if self.status == "preview_ready" and not self.batch_id:
            raise ValueError("A domain preview requires the real batch")
        return self


class OperationView(StrictModel):
    operation_id: UUID
    kind: Literal["evaluate", "recheck", "prepare"]
    run: RunView
    preparation: PreparationReceipt | None = None


class ForecastPolicy(StrictModel):
    enabled: bool = False
    automatic: bool = False
    display_mode: Literal["manual", "quiet", "standard", "active"] = "standard"
    enabled_capabilities: list[CapabilityId] = Field(default_factory=list, max_length=64)
    shared_daily_limit: int = Field(default=12, ge=1, le=100)
    allow_web: Literal[False] = False
    timezone: str = Field(default="Asia/Shanghai", max_length=64)

    @model_validator(mode="after")
    def policy_consistency(self):
        try:
            ZoneInfo(self.timezone)
        except (ValueError, ZoneInfoNotFoundError) as exc:
            raise ValueError("Use a valid IANA timezone") from exc
        if self.automatic and not self.enabled:
            raise ValueError("Automatic compute requires forecast enablement")
        return self


class PolicyUpdate(StrictModel):
    expected_generation: int = Field(ge=0)
    policy: ForecastPolicy


class PolicyView(StrictModel):
    generation: int = Field(ge=0)
    policy: ForecastPolicy
    available: bool
    reason: str | None = None


class CapabilityView(StrictModel):
    capability_id: CapabilityId
    available: bool
    reason: str | None = None
    compute_kind: Literal["deterministic", "semantic", "specialist"]


class CapabilitiesResponse(StrictModel):
    items: list[CapabilityView] = Field(max_length=64)


class MiddlewareError(StrictModel):
    """Existing Account middleware envelope; not a replacement error format."""

    detail: str


class ErrorResponse(StrictModel):
    code: str = Field(min_length=1, max_length=100)
    message: str = Field(min_length=1, max_length=1000)
    retryable: bool
    correlation_id: UUID


class ResolvedScope(StrictModel):
    """Server-only: never accept this object as browser/LLM authority."""

    novel_id: UUID
    owner_id: UUID
    persona: Literal["author", "rp"]
    audience_key: str = Field(min_length=1, max_length=160)
    scope_hash: Hash64
    context_hash: Hash64
    policy_generation: int = Field(ge=0)
    source_manifest_hash: Hash64
    journey_id: UUID | None = None
    selected_path_hash: Hash64 | None = None
    selection_epoch: int | None = Field(default=None, ge=0)
    source_context_epoch: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def persona_fields(self):
        rp_values = [
            self.journey_id,
            self.selected_path_hash,
            self.selection_epoch,
            self.source_context_epoch,
        ]
        if self.persona == "rp" and any(v is None for v in rp_values):
            raise ValueError("RP must bind journey, selected path and epochs")
        if self.persona == "author" and any(v is not None for v in rp_values):
            raise ValueError("Author scope cannot impersonate an RP context")
        return self
