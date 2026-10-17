"""Author-facing contracts for director multi-scale exploration (P0 冻结).

请求模型、四类输出 payload、统一信封与预算模型。起点判别联合定义于
``modules.evidence.compilation.exploration_start``（Evidence 侧权威），
本模块只经 ``modules.evidence.contracts`` 再导出引用，不复制定义。
字段语义见 ``.agent/tasks/2026/T-20261017-director-scales-impl/P0-CONTRACTS.md``
§1/§4/§5/§8。
"""

from __future__ import annotations

import uuid
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from infrastructure.llm.collaboration import content_hash
from modules.evidence.contracts import (
    ExplorationStart,
    ProvisionalStart,
    SceneAnchorStart,
)

EXPLORATION_OUTPUT_SCHEMA_VERSION: Literal[1] = 1

SANDBOX_OUTPUT_KIND = "story.exploration.sandbox"
EVENT_OUTPUT_KIND = "story.exploration.event"
SCENE_LINE_OUTPUT_KIND = "story.exploration.scene_line"
AUTHOR_EDIT_OUTPUT_KIND = "story.exploration.author_edit"

ExplorationScale = Literal["sandbox", "event", "scene_line"]

EXPLORATION_ACTIONS: tuple[str, ...] = (
    "story.exploration.sandbox.generate",
    "story.exploration.event.diagnose",
    "story.exploration.event.bridge",
    "story.exploration.scene_line.generate",
)
ExplorationAction = Literal[
    "story.exploration.sandbox.generate",
    "story.exploration.event.diagnose",
    "story.exploration.event.bridge",
    "story.exploration.scene_line.generate",
]

_SCALE_ACTION_BY_SCALE: dict[str, set[str]] = {
    "sandbox": {"story.exploration.sandbox.generate"},
    "event": {"story.exploration.event.diagnose", "story.exploration.event.bridge"},
    "scene_line": {"story.exploration.scene_line.generate"},
}


class ExplorationModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _uuid(value: str | uuid.UUID) -> str:
    return str(uuid.UUID(str(value)))


def _uuid_or_none(value: str | uuid.UUID | None) -> str | None:
    return None if value is None else _uuid(value)


def _check_text_list(name: str, values: list[str], *, max_length: int) -> None:
    for item in values:
        if not item or len(item) > max_length:
            raise ValueError(f"{name} entries must be 1..{max_length} characters")


# ---------------------------------------------------------------------------
# 输出 payload（P0 §4，四类）
# ---------------------------------------------------------------------------


class InfluenceLink(ExplorationModel):
    """一条有条件的影响环节；“缺条件”用 holds_when/unknown 表达，不编造完成。"""

    condition: str = Field(min_length=1, max_length=1000)
    mechanism: str = Field(min_length=1, max_length=2000)
    effect: str = Field(min_length=1, max_length=2000)
    affected_refs: list[str] = Field(default_factory=list, max_length=50)
    holds_when: str | None = Field(default=None, max_length=1000)
    unknown: str | None = Field(default=None, max_length=1000)

    @field_validator("affected_refs")
    @classmethod
    def validate_affected_refs(cls, values: list[str]) -> list[str]:
        _check_text_list("influence_chain.affected_refs", values, max_length=200)
        return values


class SandboxOutputV1(ExplorationModel):
    """B1 沙盘输出：一条影响链 + 成立条件 + 未知；chain 长度 1 即合法。"""

    question: str = Field(min_length=1, max_length=4000)
    focus: str = Field(default="", max_length=2000)
    influence_chain: list[InfluenceLink] = Field(min_length=1, max_length=12)
    preconditions: list[str] = Field(default_factory=list, max_length=12)
    unknowns: list[str] = Field(default_factory=list, max_length=12)
    warnings: list[str] = Field(default_factory=list, max_length=12)

    @field_validator("preconditions", "unknowns", "warnings")
    @classmethod
    def validate_text_lists(cls, values: list[str]) -> list[str]:
        _check_text_list("sandbox text list", values, max_length=1000)
        return values


class GapFinding(ExplorationModel):
    """事件诊断指出的缺失信息；“无法支持”走 unsolvable，不强行补全。"""

    description: str = Field(min_length=1, max_length=1000)
    why_needed: str = Field(min_length=1, max_length=1000)
    possible_fix_hint: str | None = Field(default=None, max_length=1000)


class BridgePath(ExplorationModel):
    """一条候选补桥路径：有限步骤 + 所需条件 + 代价 + 是否自洽。"""

    steps: list[str] = Field(min_length=1, max_length=8)
    required_conditions: list[str] = Field(default_factory=list, max_length=12)
    cost_or_risk: str = Field(min_length=1, max_length=1000)
    holds: bool

    @field_validator("steps", "required_conditions")
    @classmethod
    def validate_steps(cls, values: list[str]) -> list[str]:
        _check_text_list("bridge path text list", values, max_length=1000)
        return values


class EventUnsolvable(ExplorationModel):
    """补桥无可信路径时的合法结论；missing 列出缺项，不编造路径。"""

    reason: str = Field(min_length=1, max_length=2000)
    missing: list[str] = Field(default_factory=list, max_length=12)

    @field_validator("missing")
    @classmethod
    def validate_missing(cls, values: list[str]) -> list[str]:
        _check_text_list("unsolvable.missing", values, max_length=1000)
        return values


class EventOutputV1(ExplorationModel):
    """B2 事件输出：诊断缺口或补桥候选；诊断模式禁止 bridge_candidates。"""

    mode: Literal["diagnose", "bridge"]
    original_excerpt: str = Field(min_length=1, max_length=4000)
    gaps: list[GapFinding] = Field(default_factory=list, max_length=12)
    bridge_candidates: list[BridgePath] = Field(default_factory=list, max_length=6)
    unsolvable: EventUnsolvable | None = None
    unknowns: list[str] = Field(default_factory=list, max_length=12)
    warnings: list[str] = Field(default_factory=list, max_length=12)

    @field_validator("unknowns", "warnings")
    @classmethod
    def validate_text_lists(cls, values: list[str]) -> list[str]:
        _check_text_list("event text list", values, max_length=1000)
        return values

    @model_validator(mode="after")
    def validate_event_mode(self):
        if self.mode == "diagnose":
            if not self.gaps:
                raise ValueError("diagnose 模式至少给出一处缺口")
            if self.bridge_candidates:
                raise ValueError("diagnose 模式不得给出补桥候选")
        elif not self.bridge_candidates and self.unsolvable is None:
            raise ValueError("bridge 模式无可信路径时必须给出 unsolvable 及缺项")
        return self


class SceneLineOutputV1(ExplorationModel):
    """B3 场景一句对白：一句台词 + 依据 + withheld（知道但不说出）。"""

    target_ref: str = Field(min_length=1, max_length=64)
    line: str = Field(min_length=1, max_length=500)
    rationale: str = Field(min_length=1, max_length=2000)
    action: str | None = Field(default=None, max_length=300)
    knowledge_basis: list[str] = Field(default_factory=list, max_length=12)
    withheld: list[str] = Field(default_factory=list, max_length=12)
    unknowns: list[str] = Field(default_factory=list, max_length=12)
    warnings: list[str] = Field(default_factory=list, max_length=12)

    @field_validator(
        "knowledge_basis", "withheld", "unknowns", "warnings"
    )
    @classmethod
    def validate_text_lists(cls, values: list[str]) -> list[str]:
        _check_text_list("scene_line text list", values, max_length=1000)
        return values


PAYLOAD_MODELS_BY_BASE_KIND: dict[str, type] = {
    SANDBOX_OUTPUT_KIND: SandboxOutputV1,
    EVENT_OUTPUT_KIND: EventOutputV1,
    SCENE_LINE_OUTPUT_KIND: SceneLineOutputV1,
}


class AuthorEditPayloadV1(ExplorationModel):
    """作者编辑保存的新版本：与基础 payload 同构；零模型调用，不覆盖父结果。"""

    base_output_kind: Literal[
        "story.exploration.sandbox",
        "story.exploration.event",
        "story.exploration.scene_line",
    ]
    base_result_id: str
    edited_payload: SandboxOutputV1 | EventOutputV1 | SceneLineOutputV1
    edit_note: str | None = Field(default=None, max_length=500)

    @field_validator("base_result_id")
    @classmethod
    def normalize_base_result_id(cls, value: str) -> str:
        return _uuid(value)

    @model_validator(mode="after")
    def validate_same_shape(self):
        expected = PAYLOAD_MODELS_BY_BASE_KIND[self.base_output_kind]
        if not isinstance(self.edited_payload, expected):
            raise ValueError("edited_payload 必须与基础结果同构")
        return self


ExplorationOutputKind = Literal[
    "story.exploration.sandbox",
    "story.exploration.event",
    "story.exploration.scene_line",
    "story.exploration.author_edit",
]


class ExplorationOutputEnvelope(ExplorationModel):
    """结果行 payload 的统一包装：旧载荷不含 output_kind，读取方据此区分。"""

    output_kind: ExplorationOutputKind
    schema_version: Literal[1] = EXPLORATION_OUTPUT_SCHEMA_VERSION
    payload: SandboxOutputV1 | EventOutputV1 | SceneLineOutputV1 | AuthorEditPayloadV1


# ---------------------------------------------------------------------------
# 预算模型（P0 §5）
# ---------------------------------------------------------------------------


class ExplorationTokenEstimate(ExplorationModel):
    minimum: int = Field(ge=0)
    maximum: int = Field(ge=0)
    method: str = Field(default="按输入包字符长度估算，实际用量以运行账本为准")


class ExplorationBudgetPreview(ExplorationModel):
    """探索任务预算预览：初始恰好 1 次请求；追加详略/补桥/修订每次再授权 1 次。"""

    requests_min: int = Field(default=1, ge=1)
    requests_max: int = Field(default=1, ge=1)
    follow_up_max_requests: int = Field(default=1, ge=1)
    tokens_min: int = Field(ge=0)
    tokens_max: int = Field(ge=0)
    token_estimate: ExplorationTokenEstimate | None = None
    preview_hash: str = Field(pattern="^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def validate_ranges(self):
        if self.requests_min > self.requests_max:
            raise ValueError("requests_min 不能大于 requests_max")
        if self.tokens_min > self.tokens_max:
            raise ValueError("tokens_min 不能大于 tokens_max")
        return self


# ---------------------------------------------------------------------------
# 起点指纹（story 侧共享工具）
# ---------------------------------------------------------------------------


def exploration_start_fingerprint(start: ExplorationStart, scale: str) -> str:
    """冻结“同起点比较”的判别依据：尺度 + 完整起点判别联合的内容哈希。"""

    return content_hash(
        {
            "exploration_scale": scale,
            "exploration_start": start.model_dump(mode="json"),
        }
    )


# ---------------------------------------------------------------------------
# 请求模型（P0 §8）
# ---------------------------------------------------------------------------


class ExplorationRequestBase(ExplorationModel):
    novel_id: str
    scale: ExplorationScale
    start: Annotated[ExplorationStart, Field(discriminator="kind")]
    focus: str = Field(default="", max_length=2000)

    @field_validator("novel_id")
    @classmethod
    def normalize_novel_id(cls, value: str) -> str:
        return _uuid(value)


class ExplorationPreviewRequest(ExplorationRequestBase):
    """推荐 + 预算 + 确认范围预览：确定性，无模型调用。"""

    task_hint: str | None = Field(default=None, max_length=120)


class ExplorationConfirmationPreviewRequest(ExplorationRequestBase):
    """经 Evidence facade 生成探索确认预览。"""

    action: ExplorationAction

    @model_validator(mode="after")
    def validate_action_matches_scale(self):
        if self.action not in _SCALE_ACTION_BY_SCALE[self.scale]:
            raise ValueError("action 与探索尺度不匹配")
        return self


class ExplorationConfirmationRequest(ExplorationConfirmationPreviewRequest):
    """落确认：复用 Context confirm 流的 expected_context_fingerprint 机制。"""

    expected_context_fingerprint: str = Field(min_length=64, max_length=64)


class ExplorationStartTaskRequest(ExplorationConfirmationPreviewRequest):
    """发起任务（202）：幂等 operation_id + 已预览的预算 hash + 已落确认。"""

    context_confirmation_id: str = Field(min_length=1, max_length=128)
    budget_preview_hash: str = Field(pattern="^[a-f0-9]{64}$")
    operation_id: uuid.UUID
    time_budget_seconds: int = Field(default=3600, ge=1, le=6 * 3600)


class ExplorationDetailRequest(ExplorationModel):
    """"说详细点”：绑定当前结果，不暗扩尺度/资料/联网/根预算。"""

    novel_id: str
    result_id: str
    focus: str = Field(min_length=1, max_length=2000)
    operation_id: uuid.UUID

    @field_validator("novel_id", "result_id")
    @classmethod
    def normalize_ids(cls, value: str) -> str:
        return _uuid(value)


class ExplorationReviseRequest(ExplorationModel):
    """局部修订/补桥：item_path 定位父条目，item_text 防漂移（P0 §8.1）。"""

    novel_id: str
    revision_of: str | None = Field(default=None, max_length=64)
    item_path: str = Field(min_length=1, max_length=120)
    item_text: str | None = Field(default=None, max_length=4000)
    instruction: str = Field(min_length=1, max_length=2000)
    bridge_target: str | None = Field(default=None, max_length=500)
    operation_id: uuid.UUID

    @field_validator("novel_id", "revision_of")
    @classmethod
    def normalize_ids(cls, value: str | None) -> str | None:
        return _uuid_or_none(value)


class ExplorationSaveEditRequest(ExplorationModel):
    """作者编辑保存：零模型调用；幂等键 (novel_id, base_result_id, edit_content_hash)。"""

    novel_id: str
    base_result_id: str
    edited_payload: SandboxOutputV1 | EventOutputV1 | SceneLineOutputV1
    edit_note: str | None = Field(default=None, max_length=500)

    @field_validator("novel_id", "base_result_id")
    @classmethod
    def normalize_ids(cls, value: str) -> str:
        return _uuid(value)


class ExplorationCompareRequest(ExplorationModel):
    """同起点两结果比较（read）；起点不同在服务层失败关闭。"""

    novel_id: str
    first_result_id: str
    second_result_id: str

    @field_validator("novel_id", "first_result_id", "second_result_id")
    @classmethod
    def normalize_ids(cls, value: str) -> str:
        return _uuid(value)

    @model_validator(mode="after")
    def validate_distinct(self):
        if self.first_result_id == self.second_result_id:
            raise ValueError("比较需要两个不同的结果")
        return self


class ExplorationHistoryRequest(ExplorationModel):
    """探索历史（read）：按 owner+novel 过滤，gate 关闭后仍可读。"""

    novel_id: str
    scale: ExplorationScale | None = None
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)

    @field_validator("novel_id")
    @classmethod
    def normalize_novel_id(cls, value: str) -> str:
        return _uuid(value)


__all__ = [
    "AUTHOR_EDIT_OUTPUT_KIND",
    "EVENT_OUTPUT_KIND",
    "EXPLORATION_ACTIONS",
    "EXPLORATION_OUTPUT_SCHEMA_VERSION",
    "SANDBOX_OUTPUT_KIND",
    "SCENE_LINE_OUTPUT_KIND",
    "AuthorEditPayloadV1",
    "BridgePath",
    "EventOutputV1",
    "EventUnsolvable",
    "ExplorationAction",
    "ExplorationBudgetPreview",
    "ExplorationCompareRequest",
    "ExplorationConfirmationPreviewRequest",
    "ExplorationConfirmationRequest",
    "ExplorationDetailRequest",
    "ExplorationHistoryRequest",
    "ExplorationOutputEnvelope",
    "ExplorationOutputKind",
    "ExplorationPreviewRequest",
    "ExplorationReviseRequest",
    "ExplorationSaveEditRequest",
    "ExplorationScale",
    "ExplorationStartTaskRequest",
    "ExplorationTokenEstimate",
    "GapFinding",
    "InfluenceLink",
    "ProvisionalStart",
    "PAYLOAD_MODELS_BY_BASE_KIND",
    "SandboxOutputV1",
    "SceneAnchorStart",
    "SceneLineOutputV1",
    "exploration_start_fingerprint",
]
