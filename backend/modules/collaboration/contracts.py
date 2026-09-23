"""V2 authority, exact inputs, work graph and supported resource ports."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    model_serializer,
    model_validator,
)

from infrastructure.llm.collaboration import content_hash
from modules.evolution.contracts import CommittedUnderstanding
from modules.imports.contracts import ImportConsultScope

Hash = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
ResourceKind = Literal[
    "writing_draft", "scene", "foreshadowing_plan", "reveal_plan", "world_bible_draft"
]
WorkState = Literal[
    "pending", "running", "succeeded", "failed", "blocked", "cancelled", "superseded"
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ResourceRef(StrictModel):
    kind: ResourceKind
    id: UUID

    @property
    def key(self) -> str:
        return f"{self.kind}:{self.id}"


class ResourceSnapshot(ResourceRef):
    kind: Literal[
        "writing_draft",
        "scene",
        "foreshadowing_plan",
        "reveal_plan",
        "world_bible_draft",
        "external_reference",
        "import_review_group",
    ]
    revision: str = Field(min_length=1, max_length=200)
    source_hash: Hash
    label: str = Field(max_length=500)
    content: dict[str, Any]
    read_range: tuple[int, int] | None = None
    range_hash: Hash | None = None
    chapter_index: int | None = Field(default=None, ge=1)


class Grant(StrictModel):
    """Submitted by the author, validated and frozen by the host; never LLM output."""

    resources: list[ResourceRef] = Field(default_factory=list, max_length=64)
    import_scope: ImportConsultScope | None = None
    read_scope: Literal["selected", "project"] = "selected"
    read_kinds: list[ResourceKind] = Field(default_factory=lambda: ["writing_draft"])
    cutoff_chapter: int | None = Field(default=None, ge=1)
    reading_stops: dict[str, list[Annotated[int, Field(ge=1)]]] = Field(
        default_factory=dict, max_length=8
    )
    excluded: list[ResourceRef] = Field(default_factory=list, max_length=200)
    model_connections: dict[
        Literal["plan", "member", "check"],
        Annotated[str, Field(min_length=1, max_length=100)],
    ] = Field(default_factory=dict)
    follow_changes: bool = False
    retain_understanding: bool = False
    allow_background_web: bool = False
    allow_web: bool = False
    request_limit: int = Field(default=60, ge=4, le=120)
    run_request_limit: int = Field(default=30, ge=4, le=30)
    expires_at: AwareDatetime
    merge_policy: Literal["confirm", "whitespace_only"] = "confirm"
    context_confirmation_id: UUID | None = None
    context_confirmation_action: str | None = Field(default=None, max_length=100)

    @field_serializer("expires_at")
    def normalized_expiry(self, value):
        return value.astimezone(UTC).isoformat()

    @model_serializer(mode="wrap")
    def preserve_existing_grant_hash(self, handler):
        data = handler(self)
        if not self.retain_understanding:
            data.pop("retain_understanding", None)
        return data

    @model_validator(mode="after")
    def authority(self):
        if self.allow_background_web and not (self.follow_changes and self.allow_web):
            raise ValueError("后台联网需要同时授权自动跟进和公开查证")
        if self.follow_changes and (self.import_scope or self.context_confirmation_id):
            raise ValueError("精确导入组或原资料确认变化后需要作者重新选材")
        if not self.resources and not self.import_scope:
            raise ValueError("请选择本次资料或精确导入组")
        if self.import_scope and (
            not self.import_scope.expected_hash
            or self.context_confirmation_id
            or self.excluded
        ):
            raise ValueError("导入会诊须绑定原组指纹，不能混用其他确认或排除范围")
        if (
            self.import_scope
            and self.cutoff_chapter
            and self.import_scope.chapter_to > self.cutoff_chapter
        ):
            raise ValueError("导入组超出本次截止范围")
        keys = [ref.key for ref in self.resources]
        if len(keys) != len(set(keys)) or set(keys) & {ref.key for ref in self.excluded}:
            raise ValueError("资源不可重复或同时排除")
        if any(ref.kind not in self.read_kinds for ref in self.resources):
            raise ValueError("试改资源必须在读取授权内")
        if set(self.reading_stops) - {
            ref.key for ref in self.resources if ref.kind == "writing_draft"
        }:
            raise ValueError("阅读停点必须属于所选正文")
        if any(
            stops != sorted(set(stops)) or len(stops) > 8
            for stops in self.reading_stops.values()
        ):
            raise ValueError("阅读停点必须按顺序排列且不重复")
        if bool(self.context_confirmation_id) != bool(self.context_confirmation_action):
            raise ValueError("原资料确认必须同时提供用途与标识")
        if self.run_request_limit > self.request_limit:
            raise ValueError("单轮额度不能超过累计额度")
        return self


class CaseCreate(StrictModel):
    operation_id: UUID
    goal: str = Field(min_length=1, max_length=8000)
    constraints: list[Annotated[str, Field(min_length=1, max_length=2000)]] = Field(
        default_factory=list, max_length=24
    )
    grant: Grant
    custom_recipe: Recipe | None = None
    recipe_id: str = Field(default="revision", pattern=r"^[a-z][a-z0-9_-]{0,63}$")


class GrantUpdate(StrictModel):
    expected_grant_hash: Hash
    grant: Grant
    status: Literal["active", "revoked"] = "active"


class GoalUpdate(StrictModel):
    expected_version: int = Field(ge=1)
    goal: str = Field(min_length=1, max_length=8000)
    constraints: list[Annotated[str, Field(min_length=1, max_length=2000)]] = Field(
        default_factory=list, max_length=24
    )


class RunCreate(StrictModel):
    operation_id: UUID
    expected_goal_version: int = Field(ge=1)
    request: str = Field(default="", max_length=4000)
    workspace_revision_id: UUID | None = None


class SubjectView(StrictModel):
    kind: Literal["author", "character", "reader", "environment"] = "author"
    actor_id: UUID | None = None
    cutoff_chapter: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def subject(self):
        if (self.kind == "character") != bool(self.actor_id):
            raise ValueError("角色投影必须绑定人物")
        if self.kind == "reader" and self.cutoff_chapter is None:
            raise ValueError("读者必须有阅读截止点")
        return self


class CognitionRef(StrictModel):
    commit_id: UUID
    record_id: UUID
    revision_id: UUID
    content_hash: Hash
    content: dict[str, Any]
    author_status: Literal["derived", "corrected"] = "derived"
    purpose: str = "复用本次所选资料上的派生理解；不作为独立事实证据"


class CognitionSelection(StrictModel):
    inspected: bool = False
    head_commit_id: UUID | None = None
    records: list[CognitionRef] = Field(default_factory=list, max_length=32)
    excluded: list[dict[str, str]] = Field(default_factory=list, max_length=200)
    complete: bool = True


class CognitionCorrection(StrictModel):
    operation_id: UUID
    expected_commit_id: UUID
    expected_revision_id: UUID
    action: Literal["correct", "withdraw"]
    text: str = Field(default="", max_length=3000)
    confirm_withdrawal: bool = False

    @model_validator(mode="after")
    def correction(self):
        if self.action == "correct" and not self.text.strip():
            raise ValueError("请填写修正后的理解")
        if self.action == "withdraw" and not self.confirm_withdrawal:
            raise ValueError("请确认撤回这条理解；历史仍会保留")
        return self


class InputManifest(StrictModel):
    protocol: Literal["collaboration_v2"] = "collaboration_v2"
    goal_version: int = Field(ge=1)
    grant_hash: Hash
    resources: list[ResourceSnapshot] = Field(max_length=200)
    query_receipt: dict[str, Any] | None = None
    query_scope_hash: Hash
    workspace_revision_id: UUID | None = None
    subject: SubjectView = Field(default_factory=SubjectView)
    cognition: CognitionSelection = Field(default_factory=CognitionSelection)
    evolution: list[CommittedUnderstanding] = Field(default_factory=list, max_length=3)
    evolution_omissions: list[str] = Field(default_factory=list)

    @model_serializer(mode="wrap")
    def preserve_existing_manifest_hash(self, handler):
        data = handler(self)
        if self.cognition == CognitionSelection():
            data.pop("cognition", None)
        if not self.evolution:
            data.pop("evolution", None)
        if not self.evolution_omissions:
            data.pop("evolution_omissions", None)
        return data

    @property
    def fingerprint(self) -> str:
        return content_hash(self.model_dump(mode="json"))


class WorkProposal(StrictModel):
    logical_key: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    capability: Literal["investigate", "countercheck", "revise", "test", "compare"]
    question: str = Field(min_length=1, max_length=3000)
    depends_on: list[str] = Field(default_factory=list, max_length=16)
    dependency_policy: Literal["all_succeeded", "all_terminal"] = "all_succeeded"
    search_query: str | None = Field(default=None, min_length=1, max_length=200)
    web_queries: list[Annotated[str, Field(min_length=1, max_length=600)]] = Field(
        default_factory=list, max_length=2
    )
    workspace_revision_id: UUID | None = None


class GraphDelta(StrictModel):
    expected_plan_revision: int = Field(ge=0)
    items: list[WorkProposal] = Field(default_factory=list, max_length=12)
    finish: bool = Field(
        default=False, description="已执行的调查足以回答目标时结束；不能代替工作成果"
    )
    question_for_author: str | None = Field(default=None, max_length=2000)
    reason: str = Field(
        min_length=1,
        max_length=3000,
        description="工作安排的简短理由，不在此输出调查结论",
    )


class Claim(StrictModel):
    kind: Literal["source_statement", "interpretation", "hypothesis", "proposal"]
    text: str = Field(min_length=1, max_length=3000)
    evidence_keys: list[str] = Field(default_factory=list, max_length=32)
    counterevidence_keys: list[str] = Field(default_factory=list, max_length=32)
    assumptions: list[str] = Field(default_factory=list, max_length=12)
    uncertainty: str = Field(default="", max_length=1000)

    @model_validator(mode="after")
    def observed(self):
        if self.kind == "source_statement" and not self.evidence_keys:
            raise ValueError("事实判断必须引用本轮资料")
        return self


class ResourcePatch(ResourceRef):
    operation: Literal["replace", "delete"] = "replace"
    value: dict[str, Any] | None = None

    @model_validator(mode="after")
    def replacement(self):
        if (self.operation == "delete") != (self.value is None):
            raise ValueError("删除必须是显式空覆盖；替换必须提供内容")
        return self


class ScenarioSpec(StrictModel):
    expected: Literal["holds", "violated", "unchanged"] = "holds"
    key: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    title: str = Field(min_length=1, max_length=200)
    source_keys: list[str] = Field(min_length=1, max_length=12)
    invariant: str = Field(min_length=1, max_length=1500)
    assumptions: list[str] = Field(default_factory=list, max_length=8)
    actions: list[str] = Field(min_length=1, max_length=8)


class WorkOutput(StrictModel):
    scenarios: list[ScenarioSpec] = Field(default_factory=list, max_length=8)
    summary: str = Field(min_length=1, max_length=6000)
    claims: list[Claim] = Field(default_factory=list, max_length=24)
    patches: list[ResourcePatch] = Field(default_factory=list, max_length=16)
    followups: list[WorkProposal] = Field(default_factory=list, max_length=3)
    omissions: list[str] = Field(default_factory=list, max_length=24)


class WorkspaceCreate(StrictModel):
    operation_id: UUID
    label: str = Field(min_length=1, max_length=200)
    parent_revision_id: UUID | None = None


class WorkspaceEdit(StrictModel):
    expected_revision_id: UUID
    patches: list[ResourcePatch] = Field(min_length=1, max_length=16)


class RevisionRequest(StrictModel):
    revision_id: UUID
    expected_digest: Hash


class MergeRequest(RevisionRequest):
    operation_id: UUID
    confirmed: bool = False
    editor_state: Literal["saved", "dirty"]

    @model_validator(mode="after")
    def saved_only(self):
        if self.editor_state != "saved":
            raise ValueError("请先保存当前输入再采用")
        return self


class RebaseRequest(StrictModel):
    operation_id: UUID
    expected_revision_id: UUID
    expected_current_hash: Hash | None = None
    resolutions: list[ResourcePatch] = Field(default_factory=list, max_length=16)


class CheckOutput(StrictModel):
    verdict: Literal["passed", "blocked", "uncertain"]
    findings: list[str] = Field(default_factory=list, max_length=24)
    preserved_constraints: list[Annotated[str, Field(min_length=1, max_length=2000)]] = (
        Field(default_factory=list, max_length=24)
    )
    completed_checks: list[str] = Field(default_factory=list, max_length=12)
    omissions: list[str] = Field(default_factory=list, max_length=24)


class Recipe(StrictModel):
    strategy: Literal["adaptive", "single"] = "adaptive"
    id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    revision: Literal[1] = 1
    label: str = Field(min_length=1, max_length=120)
    questions: list[str] = Field(min_length=1, max_length=6)
    capabilities: list[
        Literal["investigate", "countercheck", "revise", "test", "compare"]
    ] = Field(min_length=1, max_length=5)
    required_checks: list[str] = Field(min_length=1, max_length=12)


@dataclass(frozen=True)
class CreativeResourcePort:
    """Domain-owned operations. Apply must only flush within the caller's UoW."""

    inventory: Callable[..., Awaitable[list[ResourceSnapshot]]]
    read: Callable[..., Awaitable[ResourceSnapshot]]
    validate: Callable[..., Awaitable[dict]]
    apply: Callable[..., Awaitable[dict]]


CaseCreate.model_rebuild()
