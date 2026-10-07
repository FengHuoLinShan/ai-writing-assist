"""P2-A 逐字段来源契约（契约先行单元，只定结构与纯函数，不做投影接线）。

阶段二只把「能追到赋值链」的字段标为精确依据：三母题受控字段先在本
注册表登记；``FieldProvenance`` 记录单个受控字段的一条赋值链（赋值
事件 + 稿源区间 + 资料修订版本 + 事件序）；读取端用
``resolve_field_status`` 做三态判定（exact / unverified / conflict）。

兼容语义：第一阶段 checkpoint 的维度级 ``evidence_refs`` 集合照旧透传；
``read_field_provenance`` 对没有字段级来源的旧载荷返回空列表、不报错、
不冒充精确（``provenance_status_for`` 返回 ``None``，展示层显示
「来源待核实」）。

存放规范：字段级来源内嵌在 checkpoint ``state_json`` 的
``_field_provenance`` 键（与 ``_coverage`` 等内部元数据键同惯例），
不新增数据库列；随 checkpoint 行一起 supersede / 软删，生命周期一致。

未登记的 payload 键照旧透传，只是不携带逐字段来源语义。
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

# checkpoint state_json 内嵌字段级来源的键；存在性即新旧格式判别。
FIELD_PROVENANCE_STATE_KEY = "_field_provenance"

# ============================================================
# 三母题受控字段注册表
# ============================================================


@dataclass(frozen=True)
class RegisteredMotifField:
    """一个受控母题字段：字段名、所属维度、作者语言标签、值类型描述。

    ``value_kind`` 为受控描述串（非自由文本），当前取值：
    ``entity_ref``（实体 ID 引用）、``text``（自由文本）、``integer``
    （整数锚）、``moon_phase_enum``（有限月相枚举 full/other）。
    """

    field_key: str
    dimension: str
    label: str
    value_kind: str


_MOTIF_FIELDS: tuple[RegisteredMotifField, ...] = (
    # 母题一：人物位置（locations；对齐 CharacterLocationInPanorama 字段）
    RegisteredMotifField("location_id", "locations", "所在位置", "entity_ref"),
    RegisteredMotifField("text_state", "locations", "位置描述", "text"),
    RegisteredMotifField("chapter_index", "locations", "位置确立章节", "integer"),
    # 母题二：物品所有者/保管者（entities；物品实体 payload 字段）
    RegisteredMotifField("custody_owner", "entities", "所有者", "entity_ref"),
    RegisteredMotifField("custody_holder", "entities", "保管者", "entity_ref"),
    # 母题三：锁的有限条件（entities 锁对象 payload 字段 + timeline 月相事实）
    RegisteredMotifField("opening_key_id", "entities", "开锁所需钥匙", "entity_ref"),
    RegisteredMotifField(
        "opening_moon_phase", "entities", "开锁所需月相", "moon_phase_enum"
    ),
    RegisteredMotifField("opening_passphrase", "entities", "开锁口令", "text"),
    RegisteredMotifField("moon_phase", "timeline", "月相事实", "moon_phase_enum"),
)

MOTIF_FIELD_REGISTRY: Mapping[str, RegisteredMotifField] = MappingProxyType(
    {item.field_key: item for item in _MOTIF_FIELDS}
)


def is_registered_motif_field(field_key: str, dimension: str | None = None) -> bool:
    """字段是否已登记；带 ``dimension`` 时要求所属维度也一致。"""
    registered = MOTIF_FIELD_REGISTRY.get(field_key)
    if registered is None:
        return False
    return dimension is None or registered.dimension == dimension


def motif_fields_for_dimension(dimension: str) -> tuple[RegisteredMotifField, ...]:
    """某维度下已登记的全部受控母题字段（按注册顺序）。"""
    return tuple(item for item in _MOTIF_FIELDS if item.dimension == dimension)


# ============================================================
# 逐字段赋值链结构
# ============================================================


class ProvenanceSourceRef(BaseModel):
    """稿源区间引用 — evidence ``SourceRangeRefContract`` 的 Pydantic 镜像。

    结构镜像而非直接 import 复用：本结构要内嵌 checkpoint JSON 载荷并在
    读回时过 Pydantic 校验（JSON 边界一律 Pydantic）；且 story→evidence
    的导入受 module-import-gate 棘轮约束（函数级导入只减不增），故镜像
    + ``from_source_range_contract``（duck-typed）互转，并由契约测试
    对拍字段集合防止漂移。
    """

    model_config = ConfigDict(frozen=True)

    draft_id: str = Field(min_length=1)
    chapter_index: int = Field(ge=0)
    version_number: int = Field(ge=1)
    content_mode: str = Field(min_length=1)
    start_offset: int = Field(ge=0)
    end_offset: int = Field(ge=0)
    source_hash: str = Field(min_length=1)
    range_hash: str = Field(min_length=1)

    @classmethod
    def from_source_range_contract(cls, contract: Any) -> ProvenanceSourceRef:
        """由 evidence 稿源区间契约实例转换（duck-typed 按属性读取）。

        不 import evidence 契约类型：story→evidence 的函数内导入会推高
        module-import-gate 的函数级导入棘轮（只减不增），而
        ``from_attributes`` 校验已保证实例形状完整，缺字段/类型不符
        抛 ``ValidationError``。
        """
        return cls.model_validate(contract, from_attributes=True)


class FieldProvenance(BaseModel):
    """单个受控字段的一条赋值链记录。

    - ``field_key``/``dimension``：必须已在 ``MOTIF_FIELD_REGISTRY`` 登记，
      未登记字段构造即失败（登记是携带逐字段来源的前置条件）。
    - ``event_id``：造成该赋值的 MemoryEvent。
    - ``source_refs``：赋值依据的稿源区间（镜像 SourceRangeRefContract）。
      非空时所有区间的 ``version_number`` 必须一致并等于 ``version``。
    - ``version``：赋值依据的资料修订版本；无区间锚（追到事件但没追到
      稿件）时为 0。
    - ``recorded_at_sequence``：赋值事件序（Scene 内优先 ``scene_sequence``，
      无 Scene 锚时用章内 ``sequence``），用于多条链的时序裁决。
    """

    model_config = ConfigDict(frozen=True)

    field_key: str = Field(min_length=1)
    dimension: str
    event_id: str = Field(min_length=1)
    source_refs: tuple[ProvenanceSourceRef, ...] = ()
    version: int = Field(ge=0)
    recorded_at_sequence: int = Field(ge=0)

    @model_validator(mode="after")
    def _validate_chain(self) -> FieldProvenance:
        registered = MOTIF_FIELD_REGISTRY.get(self.field_key)
        if registered is None:
            raise ValueError(
                f"field {self.field_key!r} is not registered; "
                "unregistered payload keys carry no field-level provenance"
            )
        if self.dimension != registered.dimension:
            raise ValueError(
                f"field {self.field_key!r} belongs to dimension "
                f"{registered.dimension!r}, got {self.dimension!r}"
            )
        if self.source_refs:
            ref_versions = {ref.version_number for ref in self.source_refs}
            if len(ref_versions) != 1 or self.version not in ref_versions:
                raise ValueError(
                    "source_refs version_number must be uniform and equal to version"
                )
        return self


# ============================================================
# status 三态判定（纯函数，A3 读取端入口）
# ============================================================


class ProvenanceStatus(StrEnum):
    exact = "exact"  # 当前值可精确回溯到唯一赋值链 + 稿源区间
    unverified = "unverified"  # 追到赋值事件，但没有稿源区间锚
    conflict = "conflict"  # 同序多条链，无法裁决当前值来自哪条


def resolve_field_status(
    records: Sequence[FieldProvenance],
) -> ProvenanceStatus | None:
    """裁决一组同字段赋值链记录的三态；无记录返回 ``None``（来源待核实）。

    规则（reducer 为后者胜，链按事件序裁决而非简单计数）：

    1. 空序列 → ``None``。
    2. 完全相同的记录（重复写入/重放）幂等去重。
    3. 取 ``recorded_at_sequence`` 最大的一组；同序仍有多条不同链
       （不同 event 或不同稿源）→ ``conflict``——相对顺序未知时不裁决。
    4. 最新链唯一：带稿源区间 → ``exact``；只追到事件 → ``unverified``。
       历史链（更早事件序）不影响判定，改稿后重抽取即形成新最新链。
    """
    if not records:
        return None
    deduped: dict[str, FieldProvenance] = {}
    for record in records:
        deduped.setdefault(json.dumps(record.model_dump(mode="json")), record)
    top_sequence = max(record.recorded_at_sequence for record in deduped.values())
    latest = [
        record
        for record in deduped.values()
        if record.recorded_at_sequence == top_sequence
    ]
    if len(latest) > 1:
        return ProvenanceStatus.conflict
    return (
        ProvenanceStatus.exact if latest[0].source_refs else ProvenanceStatus.unverified
    )


# ============================================================
# checkpoint 载荷兼容读取（旧格式不报错、不冒充精确）
# ============================================================

_PROVENANCE_LIST_ADAPTER: TypeAdapter[list[FieldProvenance]] = TypeAdapter(
    list[FieldProvenance]
)


def read_field_provenance(
    state_json: Mapping[str, Any] | None,
) -> list[FieldProvenance]:
    """读 checkpoint ``state_json`` 内嵌的字段级来源。

    旧格式（第一阶段维度级集合，无 ``_field_provenance`` 键）与空载荷
    返回 ``[]``，不报错、不冒充精确。新格式键存在但内容非法时抛
    ``ValidationError``：写入端已过校验，读回非法属数据损坏，应显式
    暴露而非静默降级。
    """
    if not isinstance(state_json, Mapping):
        return []
    if FIELD_PROVENANCE_STATE_KEY not in state_json:
        return []
    return _PROVENANCE_LIST_ADAPTER.validate_python(
        state_json[FIELD_PROVENANCE_STATE_KEY]
    )


def provenance_status_for(
    state_json: Mapping[str, Any] | None,
    field_key: str,
    dimension: str | None = None,
) -> ProvenanceStatus | None:
    """查询某受控字段在给定载荷下的三态；旧格式/未登记字段返回 ``None``。"""
    records = [
        record
        for record in read_field_provenance(state_json)
        if record.field_key == field_key
        and (dimension is None or record.dimension == dimension)
    ]
    return resolve_field_status(records)


# ============================================================
# timeline 受控发生时间（相对顺序锚 / 已证明日期）
# ============================================================

# timeline facts payload 的受控发生时间键；未受控键照旧透传，不受影响。
TIMELINE_WHEN_CONTROLLED_KEYS: frozenset[str] = frozenset(
    {
        "scene_index",
        "scene_sequence",
        "relative_to_fact_id",
        "relative_order",
        "stated_date",
    }
)


class TimelineWhenClause(BaseModel):
    """时间事实的发生时间受控子结构。

    只保留文本中已证明的信息：相对顺序锚（Scene 序 / 相对另一事实的
    before/after）或原文明确陈述的日期（``stated_date`` 原样保存，不做
    任何日历换算——未知/虚构历法不推算绝对日期）。相对锚必须成对：
    ``relative_to_fact_id`` 与 ``relative_order`` 同时给出或同时缺省。
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    scene_index: int | None = None
    scene_sequence: int | None = None
    relative_to_fact_id: str | None = Field(default=None, min_length=1)
    relative_order: Literal["before", "after"] | None = None
    stated_date: str | None = Field(
        default=None,
        min_length=1,
        description="原文明确陈述的日期串，原样保存，不换算日历",
    )

    @model_validator(mode="after")
    def _validate_relative_pair(self) -> TimelineWhenClause:
        if (self.relative_to_fact_id is None) != (self.relative_order is None):
            raise ValueError(
                "relative_to_fact_id and relative_order must be given together"
            )
        return self

    @property
    def has_proof(self) -> bool:
        """是否携带任一已证明的时间锚（Scene 锚 / 相对锚 / 明示日期）。"""
        return bool(
            self.scene_index is not None
            or self.scene_sequence is not None
            or self.relative_to_fact_id is not None
            or self.stated_date is not None
        )


def extract_timeline_when(
    payload: Mapping[str, Any] | None,
) -> TimelineWhenClause:
    """从 timeline fact payload 容错提取受控发生时间。

    只挑 ``TIMELINE_WHEN_CONTROLLED_KEYS`` 中的键；类型不符的键视为
    缺失、未受控键忽略，永不因 payload 形状报错（向后兼容：未受控键
    照旧透传由投影层负责，本函数不做写入）。``stated_date`` 只接受
    非空字符串，其他类型视为缺失而非换算；相对锚只出现半个时整个
    丢弃（视为无该锚），不抛错。
    """
    if not isinstance(payload, Mapping):
        return TimelineWhenClause()
    picked: dict[str, Any] = {}
    for key in TIMELINE_WHEN_CONTROLLED_KEYS:
        if key not in payload:
            continue
        value = payload[key]
        if key in ("scene_index", "scene_sequence"):
            if isinstance(value, bool) or not isinstance(value, int):
                continue
        elif key == "stated_date":
            if not isinstance(value, str) or not value.strip():
                continue
        elif not isinstance(value, str):
            continue
        picked[key] = value
    if ("relative_to_fact_id" in picked) != ("relative_order" in picked):
        picked.pop("relative_to_fact_id", None)
        picked.pop("relative_order", None)
    return TimelineWhenClause.model_validate(picked)


__all__ = [
    "FIELD_PROVENANCE_STATE_KEY",
    "MOTIF_FIELD_REGISTRY",
    "RegisteredMotifField",
    "FieldProvenance",
    "ProvenanceSourceRef",
    "ProvenanceStatus",
    "TIMELINE_WHEN_CONTROLLED_KEYS",
    "TimelineWhenClause",
    "extract_timeline_when",
    "is_registered_motif_field",
    "motif_fields_for_dimension",
    "provenance_status_for",
    "read_field_provenance",
    "resolve_field_status",
]
