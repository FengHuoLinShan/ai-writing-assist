"""Author-facing contracts for director multi-scale exploration (P0 冻结).

请求模型、四类输出 payload、统一信封与预算模型。起点判别联合定义于
``modules.evidence.compilation.exploration_start``（Evidence 侧权威），
本模块只经 ``modules.evidence.contracts`` 再导出引用，不复制定义。
字段语义见 ``.agent/tasks/2026/T-20261017-director-scales-impl/P0-CONTRACTS.md``
§1/§4/§5/§8。
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from infrastructure.llm.collaboration import content_hash
from modules.evidence.contracts import (
    Assumption,
    ExplorationStart,
    ProvisionalStart,
    SceneAnchorStart,
)

EXPLORATION_OUTPUT_SCHEMA_VERSION: Literal[1] = 1

# 反事实条件对照（M2 沙盘）：可改条件只限世界规则与状态，身份假设不属于“条件”。
COUNTERFACTUAL_ASSUMPTION_KINDS: tuple[str, ...] = ("world_rule", "state")
COUNTERFACTUAL_MAX_ASSUMPTIONS = 10

# 事件任务模式提示（M2）：info_gap → 信息差诊断（配 diagnose 动作）；
# goal → 导向路径（配 bridge 动作，复用 B2，不另造规划器）。
EVENT_MODE_HINTS: tuple[str, ...] = ("info_gap", "goal")
EVENT_HINT_LITERAL = Literal["info_gap", "goal"]
EVENT_HINT_REQUIRED_ACTION: dict[str, str] = {
    "info_gap": "story.exploration.event.diagnose",
    "goal": "story.exploration.event.bridge",
}

SANDBOX_OUTPUT_KIND = "story.exploration.sandbox"
EVENT_OUTPUT_KIND = "story.exploration.event"
SCENE_LINE_OUTPUT_KIND = "story.exploration.scene_line"
AUTHOR_EDIT_OUTPUT_KIND = "story.exploration.author_edit"
LOCK_SET_OUTPUT_KIND = "story.exploration.lock_set"
FULL_REHEARSAL_OUTPUT_KIND = "story.exploration.full_rehearsal"

# 场景人物差异（M2）：同一情境对 2..4 个目标各生成一句；每人独立知识包。
MULTI_TARGETS_MIN = 2
MULTI_TARGETS_MAX = 4
TARGET_REF_MAX_LENGTH = 64

# 临时起点完整排演（M3-B）：显式展开的多轮排演，目标 1..6 个、轮次 1..3 轮。
FULL_REHEARSAL_TARGETS_MIN = 1
FULL_REHEARSAL_TARGETS_MAX = 6
FULL_REHEARSAL_ROUNDS_MIN = 1
FULL_REHEARSAL_ROUNDS_MAX = 3
FULL_REHEARSAL_AUTHOR_GOAL_MAX_LENGTH = 2000

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


class InfoGap(ExplorationModel):
    """事件信息差（M2）：单个主体的知识边界与缺失接触路径。

    主体用候选 ref 或描述之一标识；knows/not_known 逐条列出，未声明即未知，
    不替角色补全未发生的信息。
    """

    subject_ref: str | None = Field(default=None, min_length=1, max_length=64)
    subject_description: str | None = Field(
        default=None, min_length=1, max_length=500
    )
    knows: list[str] = Field(default_factory=list, max_length=12)
    not_known: list[str] = Field(default_factory=list, max_length=12)
    missing_contact_path: bool

    @field_validator("knows", "not_known")
    @classmethod
    def validate_knowledge_lists(cls, values: list[str]) -> list[str]:
        _check_text_list("info_boundary text list", values, max_length=500)
        return values

    @model_validator(mode="after")
    def validate_subject_identified(self):
        if not self.subject_ref and not self.subject_description:
            raise ValueError("info_boundary 条目必须提供 subject_ref 或主体描述之一")
        return self


class GoalPathStep(ExplorationModel):
    """导向路径的最小环节：行动—条件—响应—后果—代价，缺一不可。"""

    action: str = Field(min_length=1, max_length=500)
    condition: str = Field(min_length=1, max_length=500)
    response: str = Field(min_length=1, max_length=500)
    consequence: str = Field(min_length=1, max_length=500)
    cost_or_risk: str = Field(min_length=1, max_length=500)


class GoalPath(ExplorationModel):
    """事件导向路径（M2）：指定结果的最小行动链；缺条件走 unsolvable，
    不编造巧合或性格突变。"""

    goal: str = Field(min_length=1, max_length=1000)
    steps: list[GoalPathStep] = Field(min_length=1, max_length=8)
    rule_constraints: list[str] = Field(default_factory=list, max_length=10)
    unsolvable: EventUnsolvable | None = None

    @field_validator("rule_constraints")
    @classmethod
    def validate_rule_constraints(cls, values: list[str]) -> list[str]:
        _check_text_list("goal_path.rule_constraints", values, max_length=500)
        return values


class EventOutputV1(ExplorationModel):
    """B2 事件输出：诊断缺口、补桥候选或导向路径；三模式输出互斥。

    v1 内扩展（M2）：新增可选 ``info_boundary``（信息差模式逐人列知识边界）
    与 ``goal_path``（导向模式），旧载荷缺省字段即可读，不升 schema 版本。
    """

    mode: Literal["diagnose", "bridge", "goal"]
    original_excerpt: str = Field(min_length=1, max_length=4000)
    gaps: list[GapFinding] = Field(default_factory=list, max_length=12)
    bridge_candidates: list[BridgePath] = Field(default_factory=list, max_length=6)
    goal_path: GoalPath | None = None
    info_boundary: list[InfoGap] = Field(default_factory=list, max_length=12)
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
            if self.goal_path is not None:
                raise ValueError("diagnose 模式不得给出导向路径")
        elif self.mode == "bridge":
            if self.goal_path is not None:
                raise ValueError("bridge 模式不得给出导向路径")
            if not self.bridge_candidates and self.unsolvable is None:
                raise ValueError("bridge 模式无可信路径时必须给出 unsolvable 及缺项")
        else:
            if self.goal_path is None:
                raise ValueError("goal 模式必须给出 goal_path")
            if self.bridge_candidates:
                raise ValueError("goal 模式不得给出补桥候选")
        return self


class SpatialAssessment(ExplorationModel):
    """场景空间诊断结论（M2）：constraints 只引用已确认资料，缺失项列 unknowns。"""

    supported: bool | None = None
    constraints: list[str] = Field(default_factory=list, max_length=10)
    unknowns: list[str] = Field(default_factory=list, max_length=10)

    @field_validator("constraints", "unknowns")
    @classmethod
    def validate_text_lists(cls, values: list[str]) -> list[str]:
        _check_text_list("spatial_assessment text list", values, max_length=500)
        return values


class SceneLineOutputV1(ExplorationModel):
    """B3 场景一句对白：一句台词 + 依据 + withheld（知道但不说出）。

    v1 内扩展（M2），三种形态互斥、由模型校验兜底：
    - 单目标（默认）：target_ref/line 必填；
    - 多目标（人物差异）：顶层 target_ref/line 置空，由 ``variants`` 承载
      每目标一行（不嵌套、target_ref 互不相同）；
    - 空间诊断：``spatial_assessment`` 承载结论，line/target_ref 可为空。
    """

    target_ref: str = Field(default="", max_length=TARGET_REF_MAX_LENGTH)
    line: str = Field(default="", max_length=500)
    rationale: str = Field(min_length=1, max_length=2000)
    action: str | None = Field(default=None, max_length=300)
    knowledge_basis: list[str] = Field(default_factory=list, max_length=12)
    withheld: list[str] = Field(default_factory=list, max_length=12)
    unknowns: list[str] = Field(default_factory=list, max_length=12)
    warnings: list[str] = Field(default_factory=list, max_length=12)
    variants: list[SceneLineOutputV1] | None = Field(
        default=None,
        min_length=MULTI_TARGETS_MIN,
        max_length=MULTI_TARGETS_MAX,
    )
    spatial_assessment: SpatialAssessment | None = None

    @field_validator(
        "knowledge_basis", "withheld", "unknowns", "warnings"
    )
    @classmethod
    def validate_text_lists(cls, values: list[str]) -> list[str]:
        _check_text_list("scene_line text list", values, max_length=1000)
        return values

    @model_validator(mode="after")
    def validate_scene_line_shape(self):
        if self.variants is not None and self.spatial_assessment is not None:
            raise ValueError("variants 与 spatial_assessment 不得同时出现")
        if self.variants is not None:
            if self.target_ref or self.line:
                raise ValueError(
                    "多目标输出的顶层 target_ref/line 必须为空，由 variants 承载"
                )
            refs = [variant.target_ref for variant in self.variants]
            if len(set(refs)) != len(refs):
                raise ValueError("variants 的 target_ref 必须互不相同")
            for variant in self.variants:
                if variant.variants is not None or variant.spatial_assessment is not None:
                    raise ValueError("variants 每项必须是单目标台词行，不得再嵌套")
                if not variant.target_ref or not variant.line:
                    raise ValueError("variants 每项必须有 target_ref 与台词")
        elif self.spatial_assessment is None:
            if not self.target_ref or not self.line:
                raise ValueError("单目标对白必须给出 target_ref 与台词")
        return self


class FullRehearsalPerformance(ExplorationModel):
    """一张表演卡（M3-B）：某目标某一轮的对白或节拍 + 依据 + 来源引用。

    语义对齐旧导演 ``DirectorPerformance`` 的“行动—台词—动机”骨架，但
    不伪造 canonical 字段（无 character_id/正式档案指纹/感知核实状态）；
    目标身份只以候选 ref_id 或正式 entity_id 出现。
    """

    target_ref: str = Field(min_length=1, max_length=TARGET_REF_MAX_LENGTH)
    line_or_beat: str = Field(min_length=1, max_length=500)
    rationale: str = Field(min_length=1, max_length=2000)
    basis_refs: list[str] = Field(default_factory=list, max_length=12)

    @field_validator("basis_refs")
    @classmethod
    def validate_basis_refs(cls, values: list[str]) -> list[str]:
        _check_text_list("performance.basis_refs", values, max_length=200)
        return values


class FullRehearsalMaterial(ExplorationModel):
    """一条排演素材（M3-B）：类别沿用旧导演素材六类；感知者只引用目标子集。"""

    kind: Literal["environment", "object", "crowd", "mood", "pacing", "time"]
    text: str = Field(min_length=1, max_length=2000)
    perceiver_refs: list[str] = Field(default_factory=list, max_length=6)

    @field_validator("perceiver_refs")
    @classmethod
    def validate_perceiver_refs(cls, values: list[str]) -> list[str]:
        _check_text_list(
            "material.perceiver_refs", values, max_length=TARGET_REF_MAX_LENGTH
        )
        return values


class FullRehearsalObservation(ExplorationModel):
    """一条观察回执（M3-B）：某目标上一轮实际注意到的事，进入其下一轮知识。"""

    target_ref: str = Field(min_length=1, max_length=TARGET_REF_MAX_LENGTH)
    observed: str = Field(min_length=1, max_length=500)


class FullRehearsalRound(ExplorationModel):
    """一轮排演：全部目标的表演卡 + 本轮素材与观察回执。"""

    round_number: int = Field(ge=1)
    performances: list[FullRehearsalPerformance] = Field(
        min_length=FULL_REHEARSAL_TARGETS_MIN, max_length=FULL_REHEARSAL_TARGETS_MAX
    )
    materials: list[FullRehearsalMaterial] = Field(default_factory=list, max_length=8)
    observations: list[FullRehearsalObservation] = Field(
        default_factory=list, max_length=12
    )


class FullRehearsalRoundOrchestration(ExplorationModel):
    """一轮统筹的生成载荷（M3-B worker 内部）：素材、观察回执与状态要点。

    只作为每轮统筹调用的结构化 schema，不单独落库：materials/observations
    并入当轮 ``FullRehearsalRound``，state_notes 累积进
    ``FullRehearsalOutputV1.state_notes``。每轮 state_notes 上限 4 条 ×
    最多 3 轮，保证不超过输出信封的 12 条上限，不因末轮超限失败关闭。
    """

    materials: list[FullRehearsalMaterial] = Field(default_factory=list, max_length=8)
    observations: list[FullRehearsalObservation] = Field(
        default_factory=list, max_length=12
    )
    state_notes: list[str] = Field(default_factory=list, max_length=4)

    @field_validator("state_notes")
    @classmethod
    def validate_state_notes(cls, values: list[str]) -> list[str]:
        _check_text_list("orchestration.state_notes", values, max_length=500)
        return values


class FullRehearsalOutputV1(ExplorationModel):
    """临时起点完整排演输出（M3-B）：多轮表演卡/素材/观察回执与状态记录。

    与聚焦输出分开计量、独立 output_kind；``targets`` 随载荷冻结，供校验
    “每轮表演卡恰好覆盖全部目标”。不创建假正式角色或 Scene，也不伪造
    canonical 感知字段；能力不足时不会产出本载荷（请求侧拒绝并保留紧凑
    结果路径）。
    """

    targets: list[str] = Field(
        min_length=FULL_REHEARSAL_TARGETS_MIN, max_length=FULL_REHEARSAL_TARGETS_MAX
    )
    rounds: list[FullRehearsalRound] = Field(
        min_length=FULL_REHEARSAL_ROUNDS_MIN, max_length=FULL_REHEARSAL_ROUNDS_MAX
    )
    state_notes: list[str] = Field(default_factory=list, max_length=12)
    unknowns: list[str] = Field(default_factory=list, max_length=12)
    warnings: list[str] = Field(default_factory=list, max_length=12)

    @field_validator("targets")
    @classmethod
    def validate_targets(cls, values: list[str]) -> list[str]:
        for item in values:
            if not item or len(item) > TARGET_REF_MAX_LENGTH:
                raise ValueError(
                    f"targets entries must be 1..{TARGET_REF_MAX_LENGTH} characters"
                )
        if len(set(values)) != len(values):
            raise ValueError("targets 不能包含重复目标")
        return values

    @field_validator("state_notes", "unknowns", "warnings")
    @classmethod
    def validate_text_lists(cls, values: list[str]) -> list[str]:
        _check_text_list("full_rehearsal text list", values, max_length=500)
        return values

    @model_validator(mode="after")
    def validate_rounds_shape(self):
        for index, round_item in enumerate(self.rounds):
            if round_item.round_number != index + 1:
                raise ValueError("rounds 编号必须从 1 起连续")
            refs = [item.target_ref for item in round_item.performances]
            if len(set(refs)) != len(refs) or set(refs) != set(self.targets):
                raise ValueError("每轮表演卡必须恰好覆盖全部目标且不重复")
            for observation in round_item.observations:
                if observation.target_ref not in self.targets:
                    raise ValueError("观察回执的 target_ref 必须在本次排演目标内")
            for material in round_item.materials:
                outside = [
                    ref
                    for ref in material.perceiver_refs
                    if ref not in self.targets
                ]
                if outside:
                    raise ValueError("素材感知者必须引用本次排演目标")
        return self


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


class LockedItem(ExplorationModel):
    """一条锁定项：复用 revise 的 chain:N/gap:N/bridge:N/line 路径语法。

    ``item_content_hash`` 由服务端在锁定时按该结果行对应条目内容计算；
    ``label`` 为条目展示文本截选（0..200），供前端不解锁即可显示锁定内容。
    """

    item_path: str = Field(min_length=1, max_length=120)
    item_content_hash: str = Field(pattern="^[a-f0-9]{64}$")
    label: str = Field(default="", max_length=200)


# 影响与比较标记（M3-A 切片 2）：compare 的结构化受影响项上限与摘录截选。
AFFECTED_ITEMS_MAX = 24
AFFECTED_ITEM_EXCERPT_MAX_LENGTH = 120
AffectedItemStatus = Literal["changed", "added", "removed"]
AffectedItemsGranularity = Literal["exact", "conservative"]


class AffectedItem(ExplorationModel):
    """一条结构化受影响项：路径语法与修订/锁定一致（chain:N/gap:N/bridge:N/line）。

    判定以两侧条目内容哈希为准；``base_excerpt``/``derived_excerpt`` 只是
    两侧条目展示文本截选（0..120），供作者不看全文也能定位——摘录相同但
    其他字段变化时状态仍为 changed。条目只在一侧出现时另一侧摘录为空。
    """

    item_path: str = Field(min_length=1, max_length=120)
    status: AffectedItemStatus
    base_excerpt: str = Field(
        default="", max_length=AFFECTED_ITEM_EXCERPT_MAX_LENGTH
    )
    derived_excerpt: str = Field(
        default="", max_length=AFFECTED_ITEM_EXCERPT_MAX_LENGTH
    )


class LockSetPayloadV1(ExplorationModel):
    """锁定集结果行（M3-A）：内容 = 该分支当前全部锁定项。

    零模型调用、无预算；author_edit 与 lock_set 都不算 AI 结果——lock_set
    不参与比较与历史 AI 列表，也不改变“分支最新 AI 结果”指针。
    """

    locked_items: list[LockedItem] = Field(default_factory=list, max_length=50)
    note: str | None = Field(default=None, max_length=500)


ExplorationOutputKind = Literal[
    "story.exploration.sandbox",
    "story.exploration.event",
    "story.exploration.scene_line",
    "story.exploration.author_edit",
    "story.exploration.lock_set",
    "story.exploration.full_rehearsal",
]


class ExplorationOutputEnvelope(ExplorationModel):
    """结果行 payload 的统一包装：旧载荷不含 output_kind，读取方据此区分。"""

    output_kind: ExplorationOutputKind
    schema_version: Literal[1] = EXPLORATION_OUTPUT_SCHEMA_VERSION
    payload: (
        SandboxOutputV1
        | EventOutputV1
        | SceneLineOutputV1
        | AuthorEditPayloadV1
        | LockSetPayloadV1
        | FullRehearsalOutputV1
    )


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


def apply_changed_assumptions(
    start: ProvisionalStart, changed: list[Assumption]
) -> ProvisionalStart:
    """反事实克隆（M2 沙盘条件对照）：只改指定条件，其余逐字保留。

    替换语义：对每条 changed 假设，按顺序消耗基线中第一条同 kind 且尚未被
    替换的假设——其 text 以 changed 为准，其余字段与位置保留；基线中没有
    同 kind 假设时追加到末尾。问题、时点、候选、知识包等其余起点内容一律
    原样保留，保证“共同基底一致、只改变指定条件”。
    """

    assumptions = [item.model_copy(deep=True) for item in start.assumptions]
    replaced: set[int] = set()
    appended: list[Assumption] = []
    for change in changed:
        target = next(
            (
                index
                for index, item in enumerate(assumptions)
                if index not in replaced and item.kind == change.kind
            ),
            None,
        )
        if target is None:
            appended.append(change.model_copy(deep=True))
        else:
            assumptions[target] = assumptions[target].model_copy(
                update={"text": change.text}
            )
            replaced.add(target)
    assumptions.extend(appended)
    return start.model_copy(update={"assumptions": assumptions})


# ---------------------------------------------------------------------------
# 请求模型（P0 §8）
# ---------------------------------------------------------------------------


def validate_counterfactual_pair(
    *,
    scale: str | None,
    start: ExplorationStart | None,
    counterfactual_of_result_id: str | None,
    changed_assumptions: list[Assumption] | None,
) -> None:
    """反事实字段一致性（预览/确认/start 请求共用）：要么全普通起点，要么全反事实。

    不校验“非反事实时必须有 start”——确认/start 请求由
    ``ExplorationRequestBase`` 补上该规则；preview 允许无 start 的名义预算。
    """

    if counterfactual_of_result_id is None and changed_assumptions is None:
        return
    if counterfactual_of_result_id is None or changed_assumptions is None:
        raise ValueError("反事实对照需要同时提供基线结果与变更条件")
    if start is not None:
        raise ValueError("反事实对照的起点由基线结果克隆得出，请勿直接传 start")
    if scale is not None and scale != "sandbox":
        raise ValueError("反事实条件对照仅支持沙盘尺度")


class SceneSpatialDiagnosticRequest(ExplorationModel):
    """场景空间诊断请求（M2）：询问某动作是否有空间/道具支持。

    ``subject_ref`` 可选（做动作的主体）；空间资料只来自本次已确认的
    Evidence 编译产物，缺尺寸/路线时输出必须列 unknowns，不把想象当证明。
    """

    question: str = Field(min_length=1, max_length=2000)
    subject_ref: str | None = Field(
        default=None, min_length=1, max_length=TARGET_REF_MAX_LENGTH
    )


class FullRehearsalRequest(ExplorationModel):
    """临时起点完整排演意图（M3-B）：目标、轮次与作者私密目标。

    ``targets`` 是候选 ref_id（``c_`` 前缀）或正式角色 entity_id，都必须落在
    本次起点的候选/正式角色范围内；``author_goal`` 是作者侧排演目的，只进
    作者输入包，不进入任何角色知识包。执行步骤与预算按
    “(目标数 + 1) × 轮次”计量，与聚焦输出分开。
    """

    targets: list[str] = Field(
        min_length=FULL_REHEARSAL_TARGETS_MIN, max_length=FULL_REHEARSAL_TARGETS_MAX
    )
    rounds: int = Field(
        default=FULL_REHEARSAL_ROUNDS_MIN,
        ge=FULL_REHEARSAL_ROUNDS_MIN,
        le=FULL_REHEARSAL_ROUNDS_MAX,
    )
    author_goal: str = Field(
        default="", max_length=FULL_REHEARSAL_AUTHOR_GOAL_MAX_LENGTH
    )

    @field_validator("targets")
    @classmethod
    def validate_targets(cls, values: list[str]) -> list[str]:
        for item in values:
            if not item or len(item) > TARGET_REF_MAX_LENGTH:
                raise ValueError(
                    f"full_rehearsal targets entries must be 1..{TARGET_REF_MAX_LENGTH}"
                    " characters"
                )
        if len(set(values)) != len(values):
            raise ValueError("full_rehearsal targets 不能包含重复目标")
        return values


class FullRehearsalPreviewIntent(ExplorationModel):
    """/preview 预算与步骤披露用的排演意图：不含起点，作者目标未定时忽略。"""

    targets: list[str] = Field(
        min_length=FULL_REHEARSAL_TARGETS_MIN, max_length=FULL_REHEARSAL_TARGETS_MAX
    )
    rounds: int = Field(
        default=FULL_REHEARSAL_ROUNDS_MIN,
        ge=FULL_REHEARSAL_ROUNDS_MIN,
        le=FULL_REHEARSAL_ROUNDS_MAX,
    )

    @field_validator("targets")
    @classmethod
    def validate_targets(cls, values: list[str]) -> list[str]:
        for item in values:
            if not item or len(item) > TARGET_REF_MAX_LENGTH:
                raise ValueError(
                    f"preview_full_rehearsal targets entries must be 1.."
                    f"{TARGET_REF_MAX_LENGTH} characters"
                )
        if len(set(values)) != len(values):
            raise ValueError("preview_full_rehearsal targets 不能包含重复目标")
        return values


class ExplorationRequestBase(ExplorationModel):
    novel_id: str
    scale: ExplorationScale
    start: Annotated[ExplorationStart | None, Field(discriminator="kind")] = None
    focus: str = Field(default="", max_length=2000)
    counterfactual_of_result_id: str | None = Field(default=None, max_length=64)
    changed_assumptions: list[Assumption] | None = Field(
        default=None,
        min_length=1,
        max_length=COUNTERFACTUAL_MAX_ASSUMPTIONS,
    )
    event_mode_hint: EVENT_HINT_LITERAL | None = None
    multi_targets: list[str] | None = Field(
        default=None,
        min_length=MULTI_TARGETS_MIN,
        max_length=MULTI_TARGETS_MAX,
    )
    diagnostic: SceneSpatialDiagnosticRequest | None = None
    full_rehearsal: FullRehearsalRequest | None = None

    @field_validator("novel_id")
    @classmethod
    def normalize_novel_id(cls, value: str) -> str:
        return _uuid(value)

    @field_validator("counterfactual_of_result_id")
    @classmethod
    def normalize_counterfactual_result_id(cls, value: str | None) -> str | None:
        return _uuid_or_none(value)

    @field_validator("changed_assumptions")
    @classmethod
    def validate_changed_assumption_kinds(
        cls, values: list[Assumption] | None
    ) -> list[Assumption] | None:
        if values is None:
            return None
        for item in values:
            if item.kind not in COUNTERFACTUAL_ASSUMPTION_KINDS:
                raise ValueError(
                    "反事实对照只支持 world_rule/state 两种条件类型"
                )
        return values

    @field_validator("multi_targets")
    @classmethod
    def validate_multi_targets(
        cls, values: list[str] | None
    ) -> list[str] | None:
        if values is None:
            return None
        for item in values:
            if not item or len(item) > TARGET_REF_MAX_LENGTH:
                raise ValueError(
                    f"multi_targets entries must be 1..{TARGET_REF_MAX_LENGTH} characters"
                )
        if len(set(values)) != len(values):
            raise ValueError("multi_targets 不能包含重复目标")
        return values

    @model_validator(mode="after")
    def validate_counterfactual_request(self):
        validate_counterfactual_pair(
            scale=self.scale,
            start=self.start,
            counterfactual_of_result_id=self.counterfactual_of_result_id,
            changed_assumptions=self.changed_assumptions,
        )
        if self.counterfactual_of_result_id is None and self.start is None:
            raise ValueError("请提供探索起点 start，或反事实基线与变更条件")
        if self.event_mode_hint is not None and self.scale != "event":
            raise ValueError("event_mode_hint 仅支持事件尺度")
        if (
            self.multi_targets is not None or self.diagnostic is not None
        ) and self.scale != "scene_line":
            raise ValueError("multi_targets/diagnostic 仅支持场景一句对白尺度")
        if self.multi_targets is not None and self.diagnostic is not None:
            raise ValueError("multi_targets 与 diagnostic 互斥，请选择其一")
        # 完整排演（M3-B）：仅临时起点的场景一句对白尺度接受；与聚焦变体互斥。
        # “仅 provisional 起点”由 API 层以 409 拒绝（场景锚点起点是合法的
        # 聚焦请求起点，只在显式展开完整排演时冲突）。
        if self.full_rehearsal is not None:
            if self.scale != "scene_line":
                raise ValueError("full_rehearsal 仅支持场景一句对白尺度")
            if self.multi_targets is not None or self.diagnostic is not None:
                raise ValueError("full_rehearsal 与 multi_targets/diagnostic 互斥")
            if self.counterfactual_of_result_id is not None:
                raise ValueError("反事实对照不支持 full_rehearsal")
        return self


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
        # 事件模式提示与动作配对：信息差走诊断，导向走补桥（复用 B2 链路）。
        expected = EVENT_HINT_REQUIRED_ACTION.get(self.event_mode_hint or "")
        if expected is not None and self.action != expected:
            raise ValueError("event_mode_hint 与事件动作不匹配")
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


def validate_scene_targets(
    start: ExplorationStart, targets: list[str]
) -> None:
    """多目标/诊断主体归属校验：必须落在本次起点的候选或正式角色内。

    临时起点逐个核对；场景锚点起点没有候选清单，交给确认与 hidden guard 把关。
    """

    if getattr(start, "kind", "") != "provisional":
        return
    allowed = {item.ref_id for item in start.candidates} | set(start.canonical_refs)
    for target in targets:
        if target not in allowed:
            raise ValueError("目标角色不在本次探索的候选或正式角色范围内")


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
    """两结果比较（read）：same_start 要求起点指纹一致，同根父子一跳时标记
    relation=parent_child 并给出受影响项；counterfactual 要求两行互为反事实
    衍生或共享同一基线，成功后回传 changed_conditions 与 affected_items
    （来源粒度不足时保守披露，不伪称精确）。"""

    novel_id: str
    first_result_id: str
    second_result_id: str
    mode: Literal["same_start", "counterfactual"] = "same_start"

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
    "AFFECTED_ITEM_EXCERPT_MAX_LENGTH",
    "AFFECTED_ITEMS_MAX",
    "AUTHOR_EDIT_OUTPUT_KIND",
    "AffectedItem",
    "AffectedItemStatus",
    "AffectedItemsGranularity",
    "COUNTERFACTUAL_ASSUMPTION_KINDS",
    "COUNTERFACTUAL_MAX_ASSUMPTIONS",
    "EVENT_HINT_LITERAL",
    "EVENT_HINT_REQUIRED_ACTION",
    "EVENT_MODE_HINTS",
    "EVENT_OUTPUT_KIND",
    "EXPLORATION_ACTIONS",
    "EXPLORATION_OUTPUT_SCHEMA_VERSION",
    "FULL_REHEARSAL_AUTHOR_GOAL_MAX_LENGTH",
    "FULL_REHEARSAL_OUTPUT_KIND",
    "FULL_REHEARSAL_ROUNDS_MAX",
    "FULL_REHEARSAL_ROUNDS_MIN",
    "FULL_REHEARSAL_TARGETS_MAX",
    "FULL_REHEARSAL_TARGETS_MIN",
    "LOCK_SET_OUTPUT_KIND",
    "MULTI_TARGETS_MAX",
    "MULTI_TARGETS_MIN",
    "SANDBOX_OUTPUT_KIND",
    "SCENE_LINE_OUTPUT_KIND",
    "TARGET_REF_MAX_LENGTH",
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
    "FullRehearsalMaterial",
    "FullRehearsalObservation",
    "FullRehearsalOutputV1",
    "FullRehearsalPerformance",
    "FullRehearsalPreviewIntent",
    "FullRehearsalRequest",
    "FullRehearsalRound",
    "FullRehearsalRoundOrchestration",
    "GapFinding",
    "GoalPath",
    "GoalPathStep",
    "InfluenceLink",
    "InfoGap",
    "LockedItem",
    "LockSetPayloadV1",
    "ProvisionalStart",
    "PAYLOAD_MODELS_BY_BASE_KIND",
    "SandboxOutputV1",
    "SceneAnchorStart",
    "SceneLineOutputV1",
    "SceneSpatialDiagnosticRequest",
    "SpatialAssessment",
    "apply_changed_assumptions",
    "exploration_start_fingerprint",
    "validate_counterfactual_pair",
    "validate_scene_targets",
]


# ---------------------------------------------------------------------------
# 修订条目定位与防漂移（纯载荷逻辑；tasks/service/api 共用，避免模块环）
# ---------------------------------------------------------------------------

EXPLORATION_CAPABILITY = "story.exploration"

_BASE_KIND_BY_SCALE = {
    "sandbox": SANDBOX_OUTPUT_KIND,
    "event": EVENT_OUTPUT_KIND,
    "scene_line": SCENE_LINE_OUTPUT_KIND,
}


def _normalize_base_kind(kind_or_scale: str) -> str:
    return _BASE_KIND_BY_SCALE.get(kind_or_scale, kind_or_scale)


def exploration_entry_display_text(item_path: str, item: Any) -> str:
    """条目展示文本（与前端卡片渲染口径一致）：锁定标签、防漂移与摘录共用。"""

    kind = str(item_path or "").partition(":")[0]
    if kind == "line":
        return str(item or "")
    if kind == "chain":
        return str((item or {}).get("effect") or "")
    if kind == "gap":
        return str((item or {}).get("description") or "")
    return "\n".join(str(step) for step in (item or {}).get("steps") or [])


def revision_items(payload: dict, base_kind: str) -> list[dict]:
    """可修订条目枚举：与前端卡片同构（sandbox 链环 / event 缺口或补桥 / 整句）。"""
    base_kind = _normalize_base_kind(base_kind)
    if base_kind == SANDBOX_OUTPUT_KIND:
        return [
            {"key": f"chain:{index}", "item": item}
            for index, item in enumerate(payload.get("influence_chain") or [])
        ]
    if base_kind == EVENT_OUTPUT_KIND:
        bridge = payload.get("mode") == "bridge"
        rows = (
            payload.get("bridge_candidates") if bridge else payload.get("gaps")
        ) or []
        prefix = "bridge" if bridge else "gap"
        return [
            {"key": f"{prefix}:{index}", "item": item}
            for index, item in enumerate(rows)
        ]
    return [{"key": "line", "item": payload.get("line")}]


def revision_entry_text(key: str, item) -> str:
    """条目当前展示文本；推导唯一实现，锁定标签与影响标记摘录共用同一口径。"""
    return exploration_entry_display_text(key, item)


def check_revision_target(
    parent_payload: dict, item_path: str, item_text: str | None, base_kind: str
) -> dict:
    """按冻结路径语法（chain:N/gap:N/bridge:N/line）定位父条目并做防漂移比对。

    解析不到、路径越界或 item_text 与父内容不一致即失败关闭；返回
    ``{"key", "item", "item_content_hash", "label"}``，内容哈希与展示标签
    （锁定项用，截选 0..200）由服务端计算。
    """

    path = str(item_path or "").strip()
    matches = [
        row for row in revision_items(parent_payload, base_kind) if row["key"] == path
    ]
    if len(matches) != 1:
        raise ValueError(
            f"修订路径 {path or '(空)'} 不在父结果的可修订条目中；请刷新结果后重选"
        )
    target = matches[0]
    if item_text is not None and str(item_text) != revision_entry_text(
        target["key"], target["item"]
    ):
        raise ValueError("所选条目内容已变化，请刷新结果后再提交修订")
    return {
        "key": target["key"],
        "item": target["item"],
        "item_content_hash": content_hash(target["item"]),
        "label": revision_entry_text(target["key"], target["item"])[:200],
    }


def validate_start_dump(start_dump: dict):
    """起点载荷校验的稳定入口（operations 复用）。"""
    if start_dump.get("kind") == "scene_anchor":
        return SceneAnchorStart.model_validate(start_dump)
    return ProvisionalStart.model_validate(start_dump)


# ---------------------------------------------------------------------------
# 助手操作目录请求模型（operations/api 共用，避免 api↔operations 导入环）
# ---------------------------------------------------------------------------

class ExplorationPreviewOperationRequest(BaseModel):
    """确定性推荐 + 预算/确认范围预览；无模型调用。

    ``multi_targets``（M2 场景多目标）仅场景尺度接受：名义预算 = 目标数。
    """

    model_config = ConfigDict(extra="forbid")

    novel_id: str
    question: str | None = Field(default=None, max_length=4000)
    scale: ExplorationScale | None = None
    focus: str = Field(default="", max_length=2000)
    task_hint: str | None = Field(default=None, max_length=120)
    has_selection: bool = False
    multi_targets: list[str] | None = Field(
        default=None,
        min_length=MULTI_TARGETS_MIN,
        max_length=MULTI_TARGETS_MAX,
    )
    diagnostic: SceneSpatialDiagnosticRequest | None = None


class ExplorationStartOperationRequest(BaseModel):
    """发起探索任务；与 REST /start 同一执行路径（幂等 operation_id）。

    ``event_mode_hint``（M2）仅事件尺度接受：info_gap → 信息差诊断，
    goal → 导向路径；与 action 的配对校验由 apply 侧契约模型完成。
    ``multi_targets`` / ``diagnostic``（M2）仅场景尺度接受，二者互斥。
    ``full_rehearsal``（M3-B）仅临时起点 + 场景尺度接受，与前两者互斥；
    资格校验（404/409）由 apply 侧 start 执行路径完成。
    """

    model_config = ConfigDict(extra="forbid")

    novel_id: str
    scale: ExplorationScale
    start: dict
    focus: str = Field(default="", max_length=2000)
    action: str = Field(min_length=1, max_length=128)
    context_confirmation_id: str = Field(min_length=1, max_length=128)
    budget_preview_hash: str = Field(pattern="^[a-f0-9]{64}$")
    operation_id: str = Field(min_length=1, max_length=64)
    time_budget_seconds: int = Field(default=3600, ge=1, le=6 * 3600)
    target_ref: str | None = Field(default=None, min_length=1, max_length=64)
    event_mode_hint: EVENT_HINT_LITERAL | None = None
    multi_targets: list[str] | None = Field(
        default=None,
        min_length=MULTI_TARGETS_MIN,
        max_length=MULTI_TARGETS_MAX,
    )
    diagnostic: SceneSpatialDiagnosticRequest | None = None
    full_rehearsal: FullRehearsalRequest | None = None


class ExplorationDetailOperationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    novel_id: str
    result_id: str
    focus: str = Field(default="", max_length=2000)
    operation_id: str = Field(min_length=1, max_length=64)


class ExplorationReviseOperationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    novel_id: str
    result_id: str
    item_path: str = Field(min_length=1, max_length=120)
    item_text: str | None = Field(default=None, max_length=4000)
    instruction: str = Field(min_length=1, max_length=2000)
    bridge_target: str | None = Field(default=None, max_length=500)
    operation_id: str = Field(min_length=1, max_length=64)


class ExplorationHistoryOperationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    novel_id: str
    root_id: str | None = Field(default=None, max_length=64)
    scale: ExplorationScale | None = None
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)
