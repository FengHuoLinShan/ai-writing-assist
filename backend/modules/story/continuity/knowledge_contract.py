"""P2-B 统一知识方言契约（契约先行单元，只定结构与纯函数，不做接线）。

同一 Scene 的角色知识此前存在两套方言：

1. **Story 事件路径**（探索 services / reducer 落库的 ``knowledge_changed``
   payload）：``character_id`` + ``subject_id`` + ``fields`` +
   ``known_values``（值绑定，值经 ``stable_hash`` 绑定）+ 文本 +
   ``false``/``false_belief`` 误信标记。``scene_state_view._knowledge_grants``
   据此授予角色视角，误信永不授予。
2. **Evolution 机器路径**（``state_gate`` 派生观察 →
   ``KnowledgeInPanorama`` 校验）：``character_id`` + ``target_type``/
   ``target_id`` + ``knowledge_level`` + ``known_content`` 文本——只有
   "谁知道关于某对象的什么内容"，**表达不了值绑定**（不知道哪个值）。

本契约把两套方言读进同一 ``KnowledgeStatement`` 形态，保持三分类
``known / unknown / false_belief`` 与「知道哪个值」的区别：

- ``known``：值绑定三件套齐备（subject + fields + known_values 的交集），
  每个绑定字段的值经 ``stable_hash`` 哈希（口径与
  ``scene_state_view._knowledge_grants`` 完全一致）。
- ``unknown``：有知识主张（文本层），但无法表达值绑定——机器路径一律
  落此层，不冒充值绑定；事件路径缺三件套之一也落此层。
- ``false_belief``：误信标记（``false``/``false_belief``）。误信不是知识，
  永不授予——条目上不承载任何值绑定（结构上杜绝）。

兼容语义：现有事件 payload（含旧格式、机器路径形态）经
``read_knowledge_statement`` 容错读取进新契约，缺什么落什么层，不报错、
不冒充。揭示边界（两套揭示系统默认相反的调和）见模块尾部
``evaluate_reader_reveal`` 段：Story RevealPlan 管 outline 结构层、
World ReaderRevealPolicy 管世界知识层；读者揭示只在已证明展示的原文
范围内启用（``proven_shown_chapters`` 从 A2 逐字段来源的稿源区间提取
证明材料）。第一阶段未支持的 reader timeline / causality 保持显式
unsupported。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from infrastructure.stable_hash import stable_hash
from modules.story.continuity.field_provenance import (
    FieldProvenance,
    ProvenanceSourceRef,
)

KNOWLEDGE_CONTRACT_VERSION = "knowledge-dialect-v1"

# ============================================================
# 三分类与来源
# ============================================================


class KnowledgeClass(StrEnum):
    """知识条目的方言分类。"""

    known = "known"  # 知道哪个值：值绑定三件套齐备
    unknown = "unknown"  # 有知识主张但无法表达值绑定（文本知识层）
    false_belief = "false_belief"  # 误信：与事实可能相悖，永不授予


class KnowledgeOrigin(StrEnum):
    """知识条目的来源路径。"""

    scene_event = "scene_event"  # Story 事件路径（作者确认/抽取事件落库）
    machine_observation = (
        "machine_observation"  # evolution 机器路径（观察派生，无值级证据）
    )


# 误信标记键与 belief 文本键 —— 与 scene_state_view 现状口径一致
# （_FALSE_MARKERS / _BELIEF_TEXT_KEYS）；镜像而非 import，避免读取端
# 模块对契约模块产生实现向依赖。
FALSE_MARKER_KEYS: tuple[str, ...] = ("false", "false_belief")
BELIEF_TEXT_KEYS: tuple[str, ...] = ("knowledge", "content", "belief", "summary", "text")

# 机器路径（KnowledgeInPanorama 形态）的文本键与传闻级证据标记。
_MACHINE_TEXT_KEYS: tuple[str, ...] = ("known_content", *BELIEF_TEXT_KEYS)
_RUMOR_LEVELS: frozenset[str] = frozenset({"rumor", "hearsay"})

# 值绑定三件套键：机器路径 payload 出现这些键时不作为值绑定采信
# （隐式透传红线：Pydantic 默认忽略额外键，见 ``read_machine_knowledge``）。
VALUE_BINDING_KEYS: tuple[str, ...] = ("subject_id", "fields", "known_values")


# ============================================================
# Scene 锚（当时适用范围）
# ============================================================


class SceneAnchor(BaseModel):
    """知识条目当时适用范围的 Scene 锚。

    ``scene_id`` 为知识建立时的场景锚（可缺省——旧事件 payload 只带序）；
    ``scene_index``/``scene_sequence`` 容错提取自 payload 的发生序键
    （与 ``scene_state_view._occurred_at`` 同口径：非整数视为缺失）。
    """

    model_config = ConfigDict(frozen=True)

    scene_id: str | None = Field(default=None, min_length=1)
    scene_index: int | None = None
    scene_sequence: int | None = None

    @property
    def has_anchor(self) -> bool:
        return any(
            value is not None
            for value in (self.scene_id, self.scene_index, self.scene_sequence)
        )


def extract_scene_anchor(payload: Mapping[str, Any] | None) -> SceneAnchor:
    """从知识 payload 容错提取 Scene 锚；类型不符视为缺失，永不报错。"""
    if not isinstance(payload, Mapping):
        return SceneAnchor()
    anchor: dict[str, Any] = {}
    scene_id = payload.get("scene_id")
    if isinstance(scene_id, str) and scene_id:
        anchor["scene_id"] = scene_id
    for key in ("scene_index", "scene_sequence"):
        value = payload.get(key)
        if isinstance(value, bool) or not isinstance(value, int):
            continue
        anchor[key] = value
    return SceneAnchor.model_validate(anchor)


# ============================================================
# 统一知识条目契约
# ============================================================


class KnowledgeStatement(BaseModel):
    """单个角色的一条版本化知识主张（方言统一契约）。

    - ``holder_id``：谁知道（事件路径 ``character_id``/``holder_id``；
      机器路径 ``character_id``，state_gate 强制与 ``knowledge_subject`` 一致）。
    - ``subject_id``：关于谁知道——值绑定三件套的对象锚。机器路径没有
      字段语义的对象锚，不冒充（``read_machine_knowledge`` 不把
      ``target_id`` 填进来）。
    - ``value_bindings``：field → ``stable_hash(known_values[field])``。
      仅 ``known`` 分类非空；``false_belief`` 条目上恒为空（误信不承载
      知识绑定，结构上杜绝授予）；``unknown`` 恒为空。
    - ``known_fields``：原 ``fields`` 列表原样保留（含绑不上的字段——
      它们是「知道有该字段但值未知」，不冒充）。
    - ``text_summary``：文本知识层（无法表达值绑定的描述主内容）。
    - ``origin``/``event_id``/``source_refs``：知识来源（事件/稿源），
      稿源区间沿 A1 ``ProvenanceSourceRef`` 结构。
    - ``scene_anchor``：当时适用范围（Scene 锚）。
    - ``unchecked_note``：未检查说明（如机器路径传闻级证据、稿源缺失）。
    - ``entry_id``：reducer 幂等键（``knowledge_changed`` 按 id 去重替换；
      机器路径由 state_gate 生成 uuid5）。
    """

    model_config = ConfigDict(frozen=True)

    holder_id: str = Field(min_length=1)
    subject_id: str | None = Field(default=None, min_length=1)
    knowledge_class: KnowledgeClass
    value_bindings: dict[str, str] = Field(default_factory=dict)
    known_fields: tuple[str, ...] = ()
    text_summary: str | None = Field(default=None, min_length=1)
    origin: KnowledgeOrigin
    event_id: str | None = Field(default=None, min_length=1)
    source_refs: tuple[ProvenanceSourceRef, ...] = ()
    scene_anchor: SceneAnchor | None = None
    unchecked_note: str | None = Field(default=None, min_length=1)
    entry_id: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def _validate_class_bindings(self) -> KnowledgeStatement:
        if self.knowledge_class is KnowledgeClass.known:
            if not self.value_bindings:
                raise ValueError("known statement requires at least one value binding")
            if self.subject_id is None:
                raise ValueError("known statement requires subject_id as binding anchor")
        else:
            if self.value_bindings:
                raise ValueError(
                    "only known statements carry value bindings; "
                    "false beliefs and unbound knowledge never grant"
                )
        if self.knowledge_class is KnowledgeClass.unknown and not self.text_summary:
            raise ValueError(
                "unknown statement must keep a text summary (unbound knowledge layer)"
            )
        return self

    def binding_hashes(self, subject_id: str, field: str) -> frozenset[str]:
        """该条目对 (subject, field) 授予的值哈希集；无绑定为空集。"""
        if self.knowledge_class is not KnowledgeClass.known:
            return frozenset()
        if self.subject_id != subject_id:
            return frozenset()
        hash_value = self.value_bindings.get(field)
        return frozenset({hash_value}) if hash_value else frozenset()


# ============================================================
# 值绑定哈希口径（对齐 scene_state_view._knowledge_grants 现状）
# ============================================================


def bind_value(value: Any) -> str:
    """值 → 绑定哈希。口径与 ``_knowledge_grants`` 授予、
    ``_filter_entries`` 比对完全一致：``stable_hash(value)`` 默认参数。"""
    return stable_hash(value)


def value_matches(binding_hash: str, value: Any) -> bool:
    """视角过滤口径：候选值哈希后与绑定哈希比对。"""
    return stable_hash(value) == binding_hash


# ============================================================
# 三分类判定（纯函数）
# ============================================================


def _is_false_belief(payload: Mapping[str, Any]) -> bool:
    return any(bool(payload.get(marker)) for marker in FALSE_MARKER_KEYS)


def classify_knowledge(
    payload: Mapping[str, Any] | None,
    *,
    origin: KnowledgeOrigin = KnowledgeOrigin.scene_event,
) -> KnowledgeClass:
    """旧 payload → 三分类判定（与 ``_knowledge_grants`` 的授予行为对齐）。

    分类绑定来源方言——同一键形态在两个方言下语义不同：

    - ``origin=scene_event``（事件方言）：
      1. 误信标记（``false``/``false_belief``）→ ``false_belief``（先判，
         即使带值绑定也不授予——误信不是知识）。
      2. 值绑定三件套交集非空（``subject_id``/``subject`` + ``fields``
         列表 + ``known_values`` 字典，且 fields∩known_values 非空）→
         ``known``。
      3. 其余 → ``unknown``（文本知识层，不冒充值绑定）。
    - ``origin=machine_observation``（机器方言）：恒 ``unknown``——机器
      观察没有值级证据（GROUNDING_MODALITIES 分级），方言本身表达不了
      值绑定；payload 偷带三件套键也**不采信**（Pydantic extra=ignore
      的隐式透传红线，见 ``read_machine_knowledge``）。
    """
    if origin is KnowledgeOrigin.machine_observation:
        return KnowledgeClass.unknown
    if not isinstance(payload, Mapping):
        return KnowledgeClass.unknown
    if _is_false_belief(payload):
        return KnowledgeClass.false_belief
    subject = payload.get("subject_id") or payload.get("subject")
    fields = payload.get("fields")
    values = payload.get("known_values")
    if not subject or not isinstance(fields, list) or not isinstance(values, dict):
        return KnowledgeClass.unknown
    bound = [field for field in fields if isinstance(field, str) and field in values]
    return KnowledgeClass.known if bound else KnowledgeClass.unknown


def _belief_text(payload: Mapping[str, Any], keys: Sequence[str]) -> str | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None


def _scene_event_statement(
    payload: Mapping[str, Any],
    *,
    event_id: str | None,
    source_refs: tuple[ProvenanceSourceRef, ...],
    scene_anchor: SceneAnchor | None,
    unchecked_note: str | None,
) -> KnowledgeStatement | None:
    """事件路径 payload → 契约条目；无 holder 的条目无法归属，返回 None。"""
    holder = payload.get("character_id") or payload.get("holder_id")
    if not isinstance(holder, str) or not holder:
        return None
    knowledge_class = classify_knowledge(payload)
    subject = payload.get("subject_id") or payload.get("subject")
    fields = payload.get("fields")
    known_fields = tuple(
        field for field in (fields if isinstance(fields, list) else ()) if field
    )
    value_bindings: dict[str, str] = {}
    if knowledge_class is KnowledgeClass.known:
        raw_values = payload.get("known_values")
        values = raw_values if isinstance(raw_values, dict) else {}
        for field in known_fields:
            if field in values:
                value_bindings[str(field)] = bind_value(values[field])
    text_summary = _belief_text(payload, BELIEF_TEXT_KEYS)
    if text_summary is None and knowledge_class is KnowledgeClass.unknown:
        # 与视图现状同文案：无文本的未绑定条目仍是知识主张，不静默丢弃。
        text_summary = "未记载内容的知识条目"
    return KnowledgeStatement(
        holder_id=holder,
        subject_id=str(subject) if subject else None,
        knowledge_class=knowledge_class,
        value_bindings=value_bindings,
        known_fields=known_fields,
        text_summary=text_summary,
        origin=KnowledgeOrigin.scene_event,
        event_id=event_id,
        source_refs=source_refs,
        scene_anchor=scene_anchor or extract_scene_anchor(payload),
        unchecked_note=unchecked_note,
        entry_id=payload.get("id") if isinstance(payload.get("id"), str) else None,
    )


def read_knowledge_statement(
    payload: Mapping[str, Any] | None,
    *,
    origin: KnowledgeOrigin = KnowledgeOrigin.scene_event,
    event_id: str | None = None,
    source_refs: tuple[ProvenanceSourceRef, ...] = (),
    scene_anchor: SceneAnchor | None = None,
    unchecked_note: str | None = None,
) -> KnowledgeStatement | None:
    """单条旧 payload → 统一契约条目（兼容读取入口）。

    - ``origin=scene_event``：事件路径形态（``character_id``/``holder_id`` +
      三件套 + 文本 + 误信标记）；缺 holder 无法归属 → ``None``（不冒充）。
    - ``origin=machine_observation``：机器路径形态（``KnowledgeInPanorama``
      键），见 ``read_machine_knowledge``。此处按同函数分发。

    非法形态（非 dict）返回 ``None``，不报错——读取兼容层永不因旧数据
    形状抛错；写入端若需强校验应直接构造 ``KnowledgeStatement``。
    """
    if not isinstance(payload, Mapping):
        return None
    if origin is KnowledgeOrigin.machine_observation:
        return read_machine_knowledge(
            payload,
            event_id=event_id,
            source_refs=source_refs,
            scene_anchor=scene_anchor,
            extra_unchecked_note=unchecked_note,
        )
    return _scene_event_statement(
        payload,
        event_id=event_id,
        source_refs=source_refs,
        scene_anchor=scene_anchor,
        unchecked_note=unchecked_note,
    )


def read_machine_knowledge(
    payload: Mapping[str, Any] | None,
    *,
    event_id: str | None = None,
    source_refs: tuple[ProvenanceSourceRef, ...] = (),
    scene_anchor: SceneAnchor | None = None,
    extra_unchecked_note: str | None = None,
) -> KnowledgeStatement | None:
    """机器路径 payload（``KnowledgeInPanorama`` 形态）→ 契约条目。

    **裁定（P2-B，B2 沿此执行）**：机器断言一律降级为「文本知识（无值
    绑定）」——``knowledge_class`` 恒为 ``unknown``。字段级映射：

    - ``character_id`` → ``holder_id``（state_gate 已强制 == knowledge_subject）。
    - ``known_content``（及 belief 文本键兜底）→ ``text_summary``。
    - ``knowledge_level`` ∈ 传闻级（rumor/hearsay）→ ``unchecked_note``
      「传闻级证据，未直接目击」；其余级别不追加未检查说明。
    - ``id`` → ``entry_id``；``target_type``/``target_id``/``status`` 不映射
      ——``target_id`` 无字段语义，不冒充值绑定对象锚 ``subject_id``。

    **隐式透传红线**：``KnowledgeInPanorama`` 未声明 ``extra``（Pydantic
    默认忽略额外键），机器 payload 即便携带 ``subject_id``/``fields``/
    ``known_values``（VALUE_BINDING_KEYS）也会静默透传持久化、再在
    panorama 读回时静默消失。本函数**只认上述白名单结构**：透传出现的
    值绑定键一律不采信为绑定，条目仍落 ``unknown``——方言统一时机器
    路径不得因 extra ignore 而"看起来支持值绑定"。该行为由契约测试
    钉死（test_p2b_knowledge_contract.py）。
    """
    if not isinstance(payload, Mapping):
        return None
    holder = payload.get("character_id")
    if not isinstance(holder, str) or not holder:
        return None
    text_summary = _belief_text(payload, _MACHINE_TEXT_KEYS) or "未记载内容的机器知识条目"
    level = payload.get("knowledge_level")
    rumor_note = (
        "传闻级证据，未直接目击"
        if isinstance(level, str) and level.strip().lower() in _RUMOR_LEVELS
        else None
    )
    notes = [note for note in (rumor_note, extra_unchecked_note) if note]
    return KnowledgeStatement(
        holder_id=holder,
        subject_id=None,  # target_id 无字段语义，不冒充绑定对象锚
        knowledge_class=KnowledgeClass.unknown,
        value_bindings={},
        known_fields=(),
        text_summary=text_summary,
        origin=KnowledgeOrigin.machine_observation,
        event_id=event_id,
        source_refs=source_refs,
        scene_anchor=scene_anchor or extract_scene_anchor(payload),
        unchecked_note="；".join(notes) if notes else None,
        entry_id=payload.get("id") if isinstance(payload.get("id"), str) else None,
    )


def read_knowledge_statements(
    state_json: Mapping[str, Any] | None,
    *,
    event_id: str | None = None,
    source_refs: tuple[ProvenanceSourceRef, ...] = (),
    scene_anchor: SceneAnchor | None = None,
) -> list[KnowledgeStatement]:
    """checkpoint ``state_json`` 的 ``character_knowledge`` 列表 → 契约条目。

    旧格式（无知识键/空列表/非 dict 元素）返回 ``[]``；holder 缺失或形态
    非法的条目跳过（不报错、不冒充）。列表形态保留 reducer 语义：按
    ``entry_id`` 后写覆盖（无 id 追加），本函数只做读取投影，不去重。
    """
    if not isinstance(state_json, Mapping):
        return []
    entries = state_json.get("character_knowledge")
    if not isinstance(entries, list):
        return []
    statements: list[KnowledgeStatement] = []
    for payload in entries:
        statement = read_knowledge_statement(
            payload,
            origin=KnowledgeOrigin.scene_event,
            event_id=event_id,
            source_refs=source_refs,
            scene_anchor=scene_anchor,
        )
        if statement is not None:
            statements.append(statement)
    return statements


# ============================================================
# 角色视角授予（与 _knowledge_grants 同口径的纯函数）
# ============================================================


def build_knowledge_grants(
    statements: Sequence[KnowledgeStatement], target_id: str
) -> dict[str, dict[str, frozenset[str]]]:
    """从契约条目构建角色的知识授予表：subject → field → 值哈希集。

    与 ``scene_state_view._knowledge_grants`` 的授予行为逐条对齐：

    - 只取 ``knowledge_class is known`` 的条目（``unknown`` 不授予——
      知道有这回事不等于知道哪个值；``false_belief`` 不授予——误信不是
      知识，契约结构上该类条目无绑定）。
    - ``holder_id != target_id`` 的条目不授予（只看目标角色自己的知识）。
    - 授予哈希 = ``stable_hash(known_values[field])``，视角过滤用
      ``value_matches(hash, entry.value)`` 比对。
    """
    grants: dict[str, dict[str, frozenset[str]]] = {}
    for statement in statements:
        if statement.knowledge_class is not KnowledgeClass.known:
            continue
        if statement.holder_id != target_id or statement.subject_id is None:
            continue
        per_subject = grants.setdefault(statement.subject_id, {})
        for field, hash_value in statement.value_bindings.items():
            per_subject[field] = per_subject.get(field, frozenset()) | {hash_value}
    return grants


# ============================================================
# 逐条拒绝原因（三类互斥，B0 xfail 钉定的缺口承载）
# ============================================================


class KnowledgeDenialCause(StrEnum):
    """角色视角对单个 fact 的拒绝原因（三类互斥）。"""

    no_knowledge_entry = "no_knowledge_entry"  # 持有者对该对象字段没有任何条目
    knowledge_value_mismatch = (
        "knowledge_value_mismatch"  # 有 known 条目但绑的是旧值/别的值
    )
    false_belief = "false_belief"  # 仅有误信条目（误信不是知识）


def denial_reason(
    statements: Sequence[KnowledgeStatement],
    *,
    holder_id: str,
    subject_id: str,
    field: str,
    value: Any,
) -> KnowledgeDenialCause | None:
    """角色视角对 (subject, field, value) 的拒绝原因；``None`` = 授予。

    三类互斥判定（与 ``_knowledge_grants``/``_filter_entries`` 的授予语义
    逐条对齐，B3 接线把它装进 omissions/denied 结构）：

    1. 该 holder 存在 known 条目绑定 (subject, field) 且 ``stable_hash(value)``
       在绑定哈希集内 → 授予（``None``）。
    2. 存在 known 绑定 (subject, field) 但值不匹配 → ``knowledge_value_mismatch``
       （旧值授权对新值即此因；known 条目的授予不受同对象误信条目影响——
       授予来自知识，拒绝原因归因到值不匹配）。
    3. 无 known 绑定、但存在该 holder 针对 (subject, field) 的误信条目
       （``known_fields`` 含该字段）→ ``false_belief``。
    4. 无任何条目（unknown 文本条目不构成字段级授予，等同无条目）→
       ``no_knowledge_entry``（不知道 ≠ 知道没有）。
    """
    has_known_binding = False
    has_false_belief_entry = False
    for statement in statements:
        if statement.holder_id != holder_id or statement.subject_id != subject_id:
            continue
        if statement.knowledge_class is KnowledgeClass.known:
            if field in statement.value_bindings:
                has_known_binding = True
                if value_matches(statement.value_bindings[field], value):
                    return None
        elif (
            statement.knowledge_class is KnowledgeClass.false_belief
            and field in statement.known_fields
        ):
            has_false_belief_entry = True
    if has_known_binding:
        return KnowledgeDenialCause.knowledge_value_mismatch
    if has_false_belief_entry:
        return KnowledgeDenialCause.false_belief
    return KnowledgeDenialCause.no_knowledge_entry


# ============================================================
# 揭示边界（两套揭示系统的调和 + 已展示证明判定，纯函数）
# ============================================================

# 读者视角显式不支持的维度（第一阶段未支持，不得以作者全知视图补齐）：
# timeline 的读者揭示范围未登记（scene_state_view 现状），causality 是
# 作者层断言。B3 接线时读者视图对这两维保持 unsupported + omissions。
UNSUPPORTED_READER_VIEW_DIMENSIONS: tuple[str, ...] = ("timeline", "causality")


class RevealDomain(StrEnum):
    """两套揭示系统各自的适用域（默认相反的调和裁定）。"""

    outline_structure = "outline_structure"  # Story RevealPlan：大纲结构层
    world_knowledge = "world_knowledge"  # World ReaderRevealPolicy：世界知识层


# 调和要点（全文裁定见 TASK.md「B1 产出」）：
# - 无策略时默认相反是**各自域的既定语义**：outline 结构层的 RevealPlan
#   是作者大纲资产（伏笔/揭示计划），无计划且无揭示主张记录 = 没有读者
#   限制，默认公开（test_reader_view_gates_entities_by_reveal 钉定）；世界
#   知识层的 ReaderRevealPolicy 是附加闸门（有策略才介入），public_baseline
#   显式公开优先，对象默认可见性由 visibility_mode 决定。
# - **B0 钉定的缺口修正**：outline 域「无策略」只在**也无揭示主张记录**
#   （reveal_chapters 为空）时默认公开；一旦存在揭示主张锚（策略阶段或
#   timeline 揭示事件记录的揭示章），对象即移入「须证明」域——锚未到
#   cutoff（当章不揭示）或 cutoff 未知 → 隐藏。无证明不得默认公开后文
#   才揭示的秘密（world map_structure_service:893 的同款保守口径）。
# - 两域共享的保守红线：当章不揭示（严格 ``<`` cutoff）；无 cutoff 不猜。
def evaluate_reader_reveal(
    *,
    domain: RevealDomain,
    has_policy: bool,
    cutoff_chapter: int | None,
    reveal_chapters: frozenset[int] | set[int] = frozenset(),
    public_baseline: bool = False,
) -> bool:
    """统一读者揭示判定（纯函数；两套系统现状行为的参数化统一）。

    ``reveal_chapters`` 为该对象已记录的揭示主张锚章集合：outline 域由
    调用方合并策略 reveal_stages 与 timeline 揭示事件的锚章（B3 接线），
    world 域为策略单锚。

    - ``world_knowledge``（world ``ReaderRevealPolicy._reader_revealed`` 口径）：
      ``public_baseline`` 优先 → True；无 cutoff 或无已揭示锚 → False；
      已揭示锚中存在 ``< cutoff`` 的章 → True。仅在 ``has_policy`` 时由
      调用方介入（与 world ``_decide`` 现状一致）。
    - ``outline_structure``（story ``reveal_visibility.evaluate`` 口径 +
      B0 缺口修正）：无策略且无揭示主张记录 → True（结构层默认公开）；
      有策略或有主张记录 → 保守判定——无 cutoff 或无 ``< cutoff`` 的
      锚 → False，否则 True。
    """
    if domain is RevealDomain.world_knowledge:
        if public_baseline:
            return True
        if cutoff_chapter is None or not reveal_chapters:
            return False
        return any(chapter < cutoff_chapter for chapter in reveal_chapters)
    if not has_policy and not reveal_chapters:
        return True
    if cutoff_chapter is None or not reveal_chapters:
        return False
    return any(chapter < cutoff_chapter for chapter in reveal_chapters)


def proven_shown_chapters(
    provenance: Sequence[FieldProvenance],
) -> frozenset[int]:
    """从已展示 Scene 的逐字段来源提取「已证明展示」的章节集合。

    证明材料 = A2 写入端的 ``FieldProvenance.source_refs``（事件依据的
    working 稿区间，其 ``chapter_index`` 即正文已展示位置）。无稿源区间
    的链（unverified）不构成已展示证明——追到事件不等于读者见过原文。
    """
    return frozenset(
        ref.chapter_index for record in provenance for ref in record.source_refs
    )


def reveal_within_proven_shown(
    reveal_chapter: int | None,
    proven: frozenset[int] | set[int],
) -> bool:
    """揭示主张是否落在已证明展示的原文范围内。

    「读者揭示只在能够证明已展示的原文范围内启用」的判定通路（B3 接线）：

    1. 策略/揭示计划给出揭示主张锚 ``reveal_chapter``；
    2. ``proven_shown_chapters`` 从已展示 Scene 的 checkpoint/事件稿源
       提取证明材料；
    3. 本函数判定：``reveal_chapter`` 无锚（None）→ False（不猜）；
       未落在证明集合内 → False（策略可以计划未来揭示，但在正文证明
       展示之前不得对读者启用）。

    注意与 cutoff 的分工：cutoff 判定「读者读到哪里」（当章不揭示），
    本判定「揭示主张是否有已展示原文背书」——两者都通过才启用读者揭示。
    """
    if reveal_chapter is None:
        return False
    return reveal_chapter in proven


__all__ = [
    "KNOWLEDGE_CONTRACT_VERSION",
    "BELIEF_TEXT_KEYS",
    "FALSE_MARKER_KEYS",
    "VALUE_BINDING_KEYS",
    "KnowledgeClass",
    "KnowledgeDenialCause",
    "KnowledgeOrigin",
    "KnowledgeStatement",
    "SceneAnchor",
    "RevealDomain",
    "UNSUPPORTED_READER_VIEW_DIMENSIONS",
    "bind_value",
    "build_knowledge_grants",
    "classify_knowledge",
    "denial_reason",
    "evaluate_reader_reveal",
    "extract_scene_anchor",
    "proven_shown_chapters",
    "read_knowledge_statement",
    "read_knowledge_statements",
    "read_machine_knowledge",
    "reveal_within_proven_shown",
    "value_matches",
]
