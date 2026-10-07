"""P2-C 消费登记契约（C1 契约先行单元，只定结构与纯函数，不做接线）。

失效传播的现状是**保守扩大**：``invalidation.apply_source_invalidation``
从锚定受影响章的最早 Scene（含）起失效全部后续派生投影，coverage_note
明言"细粒度依赖登记后可收窄"；writing 变更入口调 DI 缝
``EVOLUTION_RECORD_WRITING_SOURCE_CHANGE`` 却丢弃返回的
``InvalidationReceipt``。本契约补两块缺口的结构：

1. **消费登记**（``ConsumptionRecord``）：实际消费入口（Scene checkpoint
   投影、evidence 章索引、scene lens）登记所用稿件范围 + 版本 +
   content_mode、checkpoint/basis 锚、选中/排除资产摘要与方法版本。
   登记跟随消费产物行内嵌 JSON（键 ``_consumption_registry``，沿 P2-A
   ``_field_provenance`` 先例：随产物行一起 supersede 软删、生命周期一致、
   不新增数据库表/列——落点裁定全文见任务记录 C1 节）。
2. **细粒度影响计算**（``assess_source_impact`` 纯函数）：给定
   source_change + 登记集 → 受影响消费者逐条判定（含 reason）+ unknown
   判定。对拍口径：**无登记时行为与现状保守扩大完全一致**（评估窗口 ==
   回执 ``earliest_affected_scene_index`` 起的全部后续）；有登记时输出是
   保守行为的**细化**（只细化、不隐藏：登记覆盖不到的窗口显式进
   ``unknown_scope``，保守扩大语义保留）。登记区间与变更偏移窗口不相交
   可判 ``unaffected``——"已知依赖零无关重生成"的证明材料。章级确定性
   消费者（evidence 章索引）由失效引擎无条件重建，不依赖登记判定；
   world_knowledge/map_atlas 留在 unsupported 列表恒展示、不参与窗口。

**回执透传与重算三分类**也在本模块：``receipt_public_view`` 把
``InvalidationReceipt`` 投影为作者语言 dict（writing 层不能 import
evolution——模块依赖冻结集合无 writing→evolution 边，透传经 DI 键
``EVOLUTION_INVALIDATION_RECEIPT_VIEW`` 由组合根注入，接线归 C2/C3）；
``RecomputeScope`` 三分类区分"重新读取证据 / 重建派生状态 / 重生成正文"
的成本与写入效果，预览（``mode="preview"``）结构上零正史写入，执行须
``confirmed=True``（沿 collaboration merge 的确认门与 operation_id +
request_hash 双幂等口径）。

存放规范：本文件是 evolution 模块内契约模块（零 DB、零 LLM）。story 侧
接线（C2/C3）跨模块导入时须经 ``modules.evolution.contracts`` 或
``facade`` 再出口（import-gate 合法形态），本单元不改这两个文件。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

from infrastructure.llm.collaboration import content_hash
from modules.evolution.invalidation import (
    UNSUPPORTED_CONSUMERS,
    InvalidationReceipt,
    SourceChange,
)

CONSUMPTION_CONTRACT_VERSION = "consumption-registry-v1"

#: 消费产物行 state_json（或等价 JSON 载荷）内嵌登记集的键；
#: 存在性即新旧格式判别（沿 P2-A ``_field_provenance`` 惯例）。
CONSUMPTION_REGISTRY_STATE_KEY = "_consumption_registry"

# ============================================================
# 消费者引用
# ============================================================


class ConsumerKind(StrEnum):
    """已接入登记缝的消费者类别（受控集合；world_knowledge/map_atlas 不在此）。

    键名对齐 C0 夹具钉定的目标形态（``test_p2c_revision_adoption.py``）。
    """

    story_scene_checkpoint = (
        "story_scene_checkpoint"  # story Scene checkpoint/派生投影（维度级）
    )
    evidence_chapter_index = "evidence_chapter_index"  # evidence 章索引（requested_hash）
    scene_lens = "scene_lens"  # evidence scene lens 摘要（Scene 证据镜头）


#: 各消费者类别的必填定位键：登记必须能定位到具体消费产物，
#: 缺锚的登记无法参与影响计算（不冒充覆盖）。
CONSUMER_REF_REQUIRED_KEYS: Mapping[str, tuple[str, ...]] = {
    ConsumerKind.story_scene_checkpoint: ("scene_id", "dimension"),
    ConsumerKind.evidence_chapter_index: ("chapter_index", "content_mode"),
    ConsumerKind.scene_lens: ("scene_id",),
}


class ConsumerRef(BaseModel):
    """消费者定位引用：一次消费发生在哪个产物上。

    - ``scene_id``/``scene_index``：Scene 锚（checkpoint/lens 用；
      ``scene_index`` 供影响计算推导投影失效窗口）。
    - ``dimension``：scene checkpoint 维度（entities/knowledge/timeline…）。
    - ``chapter_index``/``content_mode``：章级消费者定位（evidence 索引）。
    必填键由 ``CONSUMER_REF_REQUIRED_KEYS[kind]`` 决定。
    """

    model_config = ConfigDict(frozen=True)

    kind: ConsumerKind
    scene_id: str | None = Field(default=None, min_length=1)
    scene_index: int | None = Field(default=None, ge=0)
    dimension: str | None = Field(default=None, min_length=1)
    chapter_index: int | None = Field(default=None, ge=0)
    content_mode: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def _validate_locator(self) -> ConsumerRef:
        required = CONSUMER_REF_REQUIRED_KEYS[self.kind]
        missing = [key for key in required if getattr(self, key) is None]
        if missing:
            raise ValueError(
                f"consumer ref of kind {self.kind.value} requires "
                f"{', '.join(required)}; missing {', '.join(missing)}"
            )
        return self


# ============================================================
# 稿源绑定
# ============================================================


class OffsetRange(BaseModel):
    """消费正文中声明的精确窗口（码点偏移，end 为开区间，与 SourceChange 同口径）。"""

    model_config = ConfigDict(frozen=True)

    start_offset: int = Field(ge=0)
    end_offset: int = Field(ge=0)

    @model_validator(mode="after")
    def _validate_range(self) -> OffsetRange:
        if self.end_offset < self.start_offset:
            raise ValueError("end_offset must be >= start_offset")
        return self


class ChapterConsumption(BaseModel):
    """消费了某一章的哪个具体版本、哪些区间。

    ``ranges`` 为空 = 整章消费（未细化区间，任何该章变更都命中）；
    非空 = 只消费这些区间（变更窗口与全部区间不相交时可判无关）。
    """

    model_config = ConfigDict(frozen=True)

    chapter_index: int = Field(ge=0)
    draft_id: str | None = Field(default=None, min_length=1)
    version_number: int | None = Field(default=None, ge=1)
    source_hash: str | None = Field(default=None, min_length=1)
    ranges: tuple[OffsetRange, ...] = ()


class SourceBinding(BaseModel):
    """一次消费实际读取的稿件范围：content_mode + 各章版本锚。

    多章 Scene（跨章 additional_sources）用多个 ``chapters`` 项表达，
    每章各自的 draft/version/hash；章号不得重复。
    """

    model_config = ConfigDict(frozen=True)

    content_mode: Literal["working", "canonical"]
    chapters: tuple[ChapterConsumption, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_chapters(self) -> SourceBinding:
        indices = [item.chapter_index for item in self.chapters]
        if len(set(indices)) != len(indices):
            raise ValueError("source binding chapters must be unique")
        return self

    def chapter(self, chapter_index: int) -> ChapterConsumption | None:
        """该章的消费锚；未消费该章返回 None。"""
        for item in self.chapters:
            if item.chapter_index == chapter_index:
                return item
        return None


# ============================================================
# basis 锚与资产摘要
# ============================================================

BasisAnchorKind = Literal["scene_checkpoint", "chapter_basis", "evidence_index_state"]


class BasisAnchor(BaseModel):
    """消费时依据的 checkpoint/basis 锚（重建派生状态时的重验引用）。"""

    model_config = ConfigDict(frozen=True)

    anchor_kind: BasisAnchorKind
    ref_id: str = Field(min_length=1)
    fingerprint: str | None = Field(default=None, min_length=1)


class AssetDigest(BaseModel):
    """选中/排除资产的摘要引用（摘要而非全集；重算重验时按 id 重读）。"""

    model_config = ConfigDict(frozen=True)

    asset_kind: str = Field(min_length=1, max_length=64)
    asset_id: str = Field(min_length=1)
    digest: str | None = Field(default=None, min_length=1)


# ============================================================
# 消费登记记录
# ============================================================


class ConsumptionRecord(BaseModel):
    """单次实际消费的登记记录（P2-C 依赖登记的最小完整单元）。

    - ``novel_id``：隔离锚——影响计算只评估同 novel 登记（信任边界不变量，
      与 ``invalidation.novel_scope_guard`` 同口径）。
    - ``consumer``：消费发生在哪个产物上。
    - ``binding``：实际读取的稿件范围 + 版本 + content_mode。
    - ``basis``：依据的 checkpoint/basis 锚（可缺省——消费产物自身即锚）。
    - ``selected_assets``/``excluded_assets``：选中/排除资产摘要
      （Evidence confirmation 的 selected/excluded 语义随消费固化）。
    - ``method_version``：消费方法版本（方法升级即登记失效，需重算）。
    - ``registered_at``：登记时间（ISO，由写入端 ``datetime.now(UTC)``）。
    """

    model_config = ConfigDict(frozen=True)

    novel_id: str = Field(min_length=1)
    consumer: ConsumerRef
    binding: SourceBinding
    basis: BasisAnchor | None = None
    selected_assets: tuple[AssetDigest, ...] = ()
    excluded_assets: tuple[AssetDigest, ...] = ()
    method_version: str = Field(min_length=1, max_length=120)
    registered_at: datetime


# ============================================================
# 登记集兼容读取（旧数据不报错、不冒充）
# ============================================================

_RECORD_LIST_ADAPTER: TypeAdapter[list[ConsumptionRecord]] = TypeAdapter(
    list[ConsumptionRecord]
)


def read_consumption_records(
    payload: Mapping[str, Any] | None,
) -> list[ConsumptionRecord]:
    """读消费产物 JSON 载荷内嵌的登记集。

    旧格式（无 ``_consumption_registry`` 键）与非 dict 载荷返回 ``[]``，
    不报错、不冒充覆盖——旧数据一律走现状保守扩大。新格式键存在但内容
    非法时抛 ``ValidationError``：写入端已过校验，读回非法属数据损坏，
    显式暴露而非静默降级（沿 P2-A ``read_field_provenance`` 同裁定）。
    """
    if not isinstance(payload, Mapping):
        return []
    if CONSUMPTION_REGISTRY_STATE_KEY not in payload:
        return []
    return _RECORD_LIST_ADAPTER.validate_python(payload[CONSUMPTION_REGISTRY_STATE_KEY])


# ============================================================
# 细粒度影响计算（纯函数，对拍现状保守行为）
# ============================================================


class ConsumerImpact(StrEnum):
    """单个登记消费者对一次正文变更的判定（三态）。"""

    affected = "affected"  # 命中：该消费需要失效/重算
    unaffected = "unaffected"  # 登记证明与本次变更无关（零无关重生成的证明）
    unknown = "unknown"  # 无法判定：保守按受影响处理，不隐藏


class ImpactReason(StrEnum):
    """判定的受控原因（机器可读，写入 UI 范围展示；值对齐 C0 夹具目标形态）。"""

    anchored_chapter_edited = (
        "anchored_chapter_edited"  # 消费锚定的章被编辑（整章消费/无窗口保守）
    )
    offset_window_hit = "offset_window_hit"  # 变更窗口与登记区间相交
    offset_window_miss = "offset_window_miss"  # 登记区间与变更窗口不相交
    content_mode_mismatch = "content_mode_mismatch"  # 登记读的是另一 content_mode
    conservative_expansion_unregistered = (
        "conservative_expansion_unregistered"  # 依赖未登记，保守扩大（basis=unknown）
    )
    unregistered_consumer = "unregistered_consumer"  # 无登记缝的消费者（恒保守列出）


class ConsumerVerdict(BaseModel):
    """一个登记消费者对一次变更的判定结果。"""

    model_config = ConfigDict(frozen=True)

    consumer: ConsumerRef
    impact: ConsumerImpact
    reason: ImpactReason
    note: str = Field(min_length=1, description="作者语言说明")


class UnknownScope(BaseModel):
    """登记覆盖不到的保守范围（显式列出，不隐藏）。

    ``conservative`` 只衡量**投影失效窗口能否收窄**的 unknown 来源：
    变更章无登记、保守窗口内有场景无登记、或场景清单不可用——任一为
    真时评估不得收窄窗口（保守扩大语义保留）。``unregistered_consumers``
    （world_knowledge/map_atlas）是独立的缺口可见性，对齐现状回执
    ``unsupported_consumers`` 的角色：恒列出、不参与窗口判定（现状也不
    因它们改变传播行为）。
    """

    model_config = ConfigDict(frozen=True)

    chapter_registration_missing: bool = False
    scenes_without_registration: tuple[int, ...] = ()
    scene_roster_unavailable: bool = False
    unregistered_consumers: tuple[str, ...] = ()
    note: str = Field(min_length=1)

    @property
    def conservative(self) -> bool:
        """投影窗口是否必须保持保守扩大（登记覆盖不全）。"""
        return bool(
            self.chapter_registration_missing
            or self.scenes_without_registration
            or self.scene_roster_unavailable
        )


def _windows_overlap(change: SourceChange, ranges: Sequence[OffsetRange]) -> bool | None:
    """变更窗口与登记区间是否相交；``None`` = 变更未带窗口（保守，视为相交）。"""
    if change.first_offset is None or change.last_offset is None:
        return None
    for span in ranges:
        # 双开区间相交；相邻（end == start）不算相交。
        if (
            span.start_offset < change.last_offset
            and change.first_offset < span.end_offset
        ):
            return True
    return False


def assess_source_impact(
    *,
    novel_id: str,
    chapter_index: int,
    change: SourceChange,
    content_mode: str = "working",
    records: Sequence[ConsumptionRecord] = (),
    earliest_affected_scene_index: int | None = None,
    scene_indexes: Sequence[int] | None = None,
) -> ImpactAssessment:
    """一次正文变更对登记消费集的影响评估（纯函数）。

    对拍口径（与 ``invalidation.apply_source_invalidation`` 的保守行为）：

    - ``change.changed`` 为 False → ``nothing_to_do``（回执同语义）。
    - **无登记（或登记覆盖不全）→ 行为不变**：``from_scene_index`` 恒等于
      调用方传入的 ``earliest_affected_scene_index``（即回执
      ``earliest_affected_scene_index``，现状"从锚定最早 Scene 起全部后续
      失效"），unknown 来源显式列出。
    - **登记完备 → 细化**：只命中登记证明消费了变更窗口的消费者；
      全部 unaffected 时 ``from_scene_index`` 为 None（零投影失效——
      "已知依赖零无关重生成"）。跨章 Scene 消费变更章且早于保守锚时
      取更早者（登记修复保守扩大漏掉的跨章前缀）。

    参数 ``earliest_affected_scene_index`` 由调用方经
    ``invalidation.affected_scene_window`` 查得；``scene_indexes`` 为该
    novel 的全部 Scene 序（缺省 None = 未提供清单，无法证明场景覆盖，
    恒保守）。``records`` 中的跨 novel 记录直接忽略（隔离不变量）。
    """
    scoped = [record for record in records if record.novel_id == novel_id]

    if not change.changed:
        return ImpactAssessment(
            novel_id=novel_id,
            chapter_index=chapter_index,
            content_mode=content_mode,
            nothing_to_do=True,
            verdicts=(),
            unknown_scope=UnknownScope(
                unregistered_consumers=_unsupported_consumer_names(),
                note="内容指纹未变化，无失效需要传播",
            ),
            conservative_from_scene_index=earliest_affected_scene_index,
            from_scene_index=None,
            refined=False,
        )

    verdicts: list[ConsumerVerdict] = []
    chapter_registered = False
    for record in scoped:
        binding = record.binding
        chapter_binding = binding.chapter(chapter_index)
        if chapter_binding is None:
            continue  # 不消费变更章：与本次变更无关，不进判定列表
        chapter_registered = True
        consumer = record.consumer
        if binding.content_mode != content_mode:
            verdicts.append(
                ConsumerVerdict(
                    consumer=consumer,
                    impact=ConsumerImpact.unaffected,
                    reason=ImpactReason.content_mode_mismatch,
                    note=f"该消费读取的是{binding.content_mode}稿，本次变更为{content_mode}稿",
                )
            )
            continue
        overlap = _windows_overlap(change, chapter_binding.ranges)
        if not chapter_binding.ranges or overlap is None or overlap:
            if chapter_binding.ranges and overlap is None:
                reason = ImpactReason.anchored_chapter_edited
                note = "变更未携带偏移窗口，按整章消费保守判定命中"
            elif chapter_binding.ranges:
                reason = ImpactReason.offset_window_hit
                note = "变更窗口与该消费登记的稿件区间相交"
            else:
                reason = ImpactReason.anchored_chapter_edited
                note = "该消费读取变更章节的整章内容"
            verdicts.append(
                ConsumerVerdict(
                    consumer=consumer,
                    impact=ConsumerImpact.affected,
                    reason=reason,
                    note=note,
                )
            )
        else:
            verdicts.append(
                ConsumerVerdict(
                    consumer=consumer,
                    impact=ConsumerImpact.unaffected,
                    reason=ImpactReason.offset_window_miss,
                    note="该消费登记的稿件区间与变更窗口不相交",
                )
            )

    registered_scene_indexes = {
        record.consumer.scene_index
        for record in scoped
        if record.consumer.scene_index is not None
    }
    if scene_indexes is None:
        unknown_scenes: tuple[int, ...] = ()
        roster_unavailable = True
    else:
        scenes_after = {
            index
            for index in scene_indexes
            if earliest_affected_scene_index is None
            or index >= earliest_affected_scene_index
        }
        unknown_scenes = tuple(sorted(scenes_after - registered_scene_indexes))
        roster_unavailable = False

    unknown_notes: list[str] = []
    if not chapter_registered:
        unknown_notes.append("变更章节没有任何消费登记")
    if roster_unavailable:
        unknown_notes.append("未提供场景清单，无法证明后续场景的依赖覆盖")
    elif unknown_scenes:
        unknown_notes.append(
            "场景 " + "、".join(f"#{index}" for index in unknown_scenes) + " 无消费登记"
        )
    unsupported = _unsupported_consumer_names()
    if unsupported:
        unknown_notes.append("世界知识/地图册尚无登记缝（按保守扩大处理）")
    unknown_scope = UnknownScope(
        chapter_registration_missing=not chapter_registered,
        scenes_without_registration=unknown_scenes,
        scene_roster_unavailable=roster_unavailable,
        unregistered_consumers=unsupported,
        note="；".join(unknown_notes) or "登记覆盖完整",
    )

    affected_scenes = [
        verdict.consumer.scene_index
        for verdict in verdicts
        if verdict.impact is ConsumerImpact.affected
        and verdict.consumer.scene_index is not None
    ]
    if unknown_scope.conservative:
        from_scene_index: int | None = earliest_affected_scene_index
    elif affected_scenes:
        from_scene_index = min(
            value
            for value in (min(affected_scenes), earliest_affected_scene_index)
            if value is not None
        )
    else:
        from_scene_index = None

    return ImpactAssessment(
        novel_id=novel_id,
        chapter_index=chapter_index,
        content_mode=content_mode,
        nothing_to_do=False,
        verdicts=tuple(verdicts),
        unknown_scope=unknown_scope,
        conservative_from_scene_index=earliest_affected_scene_index,
        from_scene_index=from_scene_index,
        refined=bool(verdicts) and not unknown_scope.conservative,
    )


class ImpactAssessment(BaseModel):
    """一次变更的完整影响评估（``assess_source_impact`` 输出）。

    - ``conservative_from_scene_index``：现状保守窗口起点（对拍锚，
      == 回执 ``earliest_affected_scene_index``）。
    - ``from_scene_index``：考虑登记后的投影失效起点。unknown 存在时恒
      等于保守锚（行为不变）；登记完备时为最早命中 Scene（可能早于保守
      锚——跨章消费）或 None（零投影失效）。
    - ``refined``：本评估是否在保守行为之上给出了细化判定。
    """

    model_config = ConfigDict(frozen=True)

    novel_id: str
    chapter_index: int
    content_mode: str
    nothing_to_do: bool
    verdicts: tuple[ConsumerVerdict, ...]
    unknown_scope: UnknownScope
    conservative_from_scene_index: int | None
    from_scene_index: int | None
    refined: bool

    def affected(self) -> tuple[ConsumerVerdict, ...]:
        """命中的消费者判定（按登记顺序）。"""
        return tuple(
            verdict
            for verdict in self.verdicts
            if verdict.impact is ConsumerImpact.affected
        )


def _unsupported_consumer_names() -> tuple[str, ...]:
    return tuple(item["consumer"] for item in UNSUPPORTED_CONSUMERS)


# ============================================================
# 重算三分类（请求/响应结构；编排端点归 C3）
# ============================================================


class RecomputeScope(StrEnum):
    """重算三分类：成本与写入效果严格区分（作者显式触发）。

    枚举值对齐 C0 夹具目标形态（``recompute_options`` 的 ``kind`` 键）。
    """

    reload_evidence = "reload_evidence"  # 重读证据（低成本：索引换源重读）
    rebuild_derived_state = "rebuild_derived_state"  # 重建派生状态（投影重算）
    regenerate_prose = "regenerate_prose"  # 重生成正文（昂贵，作者显式选择）


#: 各分类覆盖的消费者键（C0 目标形态的 ``covers``；``prose_generation``
#: 是重生成正文的虚拟消费者，仅用于成本展示，不存在失效登记）。
RECOMPUTE_SCOPE_COVERS: Mapping[str, tuple[str, ...]] = {
    RecomputeScope.reload_evidence.value: ("evidence_chapter_index",),
    RecomputeScope.rebuild_derived_state.value: ("story_scene_projections",),
    RecomputeScope.regenerate_prose.value: ("prose_generation",),
}

#: 各分类的成本与写入效果（作者语言；预览/执行响应共用）。
RECOMPUTE_SCOPE_EFFECTS: Mapping[str, dict[str, str]] = {
    RecomputeScope.reload_evidence.value: {
        "cost": "低：仅重新读取证据/重建章索引，不调用模型、不改状态",
        "write_effect": "替换章索引/证据缓存；不触碰 Scene 状态与正文",
    },
    RecomputeScope.rebuild_derived_state.value: {
        "cost": "中：重算派生状态（Scene checkpoint/投影），可能触发已登记的审查任务",
        "write_effect": "软失效旧派生行并生成新行；作者确认与历史行保留",
    },
    RecomputeScope.regenerate_prose.value: {
        "cost": "高：调用模型重写正文段落，消耗生成额度",
        "write_effect": "产生新草稿版本，须经作者确认采用；旧稿与人工修改保留",
    },
}


# ============================================================
# 回执透传（作者语言投影；writing 层经 DI 键调用，不 import 本模块类型）
# ============================================================

#: 回执 ``invalidated_consumers`` 内部键 → 作者语言标签（受控映射；
#: 未知键原样保留进诊断区，不冒充翻译）。
CONSUMER_LABELS: Mapping[str, str] = {
    "evidence_chapter_index": "章节证据索引",
    "canonical_chapter_index": "正史章节索引",
    "interaction_source_cache": "对话来源缓存",
    "assistant_suggestion_validity": "助手建议有效性",
    "evolution_runs": "演化理解任务",
    "story_state": "场景派生状态",
    "story_scene_projections": "场景派生投影",
    "scene_event_order": "场景事件顺序",
}


def receipt_fingerprint(receipt: InvalidationReceipt) -> str:
    """回执稳定指纹（``receipt_id`` 的 C1 实现；C2 落库回执后可换行 id）。

    同一失效重放（相同 novel/章/变更/失效键集/范围说明）指纹不变——
    写作端透传、前端查重与幂等对账共用。
    """
    return content_hash(
        {
            "novel_id": receipt.novel_id,
            "chapter_index": receipt.chapter_index,
            "source_change": (
                receipt.source_change.model_dump(mode="json")
                if receipt.source_change
                else None
            ),
            "invalidated_consumers": sorted(receipt.invalidated_consumers),
            "earliest_affected_scene_index": receipt.earliest_affected_scene_index,
            "nothing_to_do": receipt.nothing_to_do,
            "coverage_note": receipt.coverage_note,
        }
    )


def affected_view_entries(
    receipt: InvalidationReceipt,
    *,
    assessment: ImpactAssessment | None = None,
) -> list[dict[str, Any]]:
    """受影响条目投影（C0 目标形态 ``affected`` 列表，键名级对齐）。

    每条 ``{consumer, scene_id, scene_index, dimension, reason, basis, note}``：

    - ``basis="known"``：登记命中的消费者（assessment 的 affected 判定）；
      无 assessment 时退化为回执 ``invalidated_consumers`` 的确定性键
      （evidence 索引等——这些由失效引擎无条件处理，basis 恒 known），
      scene 锚缺省 None。
    - ``basis="unknown"``：登记覆盖不到的保守扩大场景（assessment 的
      ``unknown_scope.scenes_without_registration``），reason 恒
      ``conservative_expansion_unregistered``——不为好看列表隐藏未知。
    - 无关 Scene（登记证明 ``offset_window_miss``）不进列表。

    ``assessment=None``（C2 前的现状回执）时 scene 级 unknown 条目无法
    枚举（场景清单不在回执上）——C2 给 ``InvalidationReceipt`` 增补
    affected 后由失效路径传入 assessment 组装完整列表。
    """
    entries: list[dict[str, Any]] = []
    if assessment is not None:
        for verdict in assessment.affected():
            consumer = verdict.consumer
            entries.append(
                {
                    "consumer": consumer.kind.value,
                    "scene_id": consumer.scene_id,
                    "scene_index": consumer.scene_index,
                    "dimension": consumer.dimension,
                    "reason": verdict.reason.value,
                    "basis": "known",
                    "note": verdict.note,
                }
            )
        for scene_index in assessment.unknown_scope.scenes_without_registration:
            entries.append(
                {
                    "consumer": ConsumerKind.story_scene_checkpoint.value,
                    "scene_id": None,
                    "scene_index": scene_index,
                    "dimension": None,
                    "reason": (ImpactReason.conservative_expansion_unregistered.value),
                    "basis": "unknown",
                    "note": f"场景 #{scene_index} 无消费登记，按保守扩大失效",
                }
            )
        return entries
    for key, detail in receipt.invalidated_consumers.items():
        if key in ("interaction_source_cache",):
            continue  # 辅助清理动作不是"受影响消费者"
        entries.append(
            {
                "consumer": key,
                "scene_id": None,
                "scene_index": None,
                "dimension": None,
                "reason": (
                    ImpactReason.anchored_chapter_edited.value
                    if receipt.chapter_index is not None
                    else ImpactReason.unregistered_consumer.value
                ),
                "basis": "known",
                "note": "该消费者由失效传播确定性地重建/失效",
                "detail": detail,
            }
        )
    return entries


def derive_recompute_options(
    receipt: InvalidationReceipt,
    *,
    assessment: ImpactAssessment | None = None,
) -> list[dict[str, Any]]:
    """从回执推导重算三分类选项（C0 目标形态：恒列三类、含 covers）。

    - 有失效传播时恒列全部分类——``regenerate_prose`` 也在列（成本分级
      展示给作者选），但**不在编辑时自动执行**：它只有经
      ``RecomputeRequest(mode="execute", confirmed=True)`` 显式触发，
      预览/执行的编排端点归 C3。
    - ``rebuild_derived_state`` 项附 ``affected``（scene 级条目，含保守
      扩大的 unknown 条目、不含无关 Scene）——仅当传入 assessment 时
      可得；C2 增补回执 affected 后由失效路径组装。
    - ``nothing_to_do``（无失效）返回空列表。
    """
    if receipt.nothing_to_do:
        return []
    scene_entries = [
        entry
        for entry in affected_view_entries(receipt, assessment=assessment)
        if entry.get("scene_index") is not None
    ]
    options: list[dict[str, Any]] = [
        {
            "kind": RecomputeScope.reload_evidence.value,
            "covers": list(RECOMPUTE_SCOPE_COVERS[RecomputeScope.reload_evidence.value]),
        },
        {
            "kind": RecomputeScope.rebuild_derived_state.value,
            "covers": list(
                RECOMPUTE_SCOPE_COVERS[RecomputeScope.rebuild_derived_state.value]
            ),
            "affected": scene_entries,
        },
        {
            "kind": RecomputeScope.regenerate_prose.value,
            "covers": list(RECOMPUTE_SCOPE_COVERS[RecomputeScope.regenerate_prose.value]),
            "author_choice_only": True,
        },
    ]
    return options


def receipt_public_view(
    receipt: InvalidationReceipt,
    *,
    assessment: ImpactAssessment | None = None,
) -> dict[str, Any]:
    """``InvalidationReceipt`` → 作者语言 dict（API 响应字段级契约，C3 接线）。

    C0 目标形态键（writing 契约 ``invalidation`` 字段的最小集）：

    - ``affected``：受影响条目（``affected_view_entries``；known/unknown
      分列，无关 Scene 不进列表）。
    - ``unknown_scope``：是否存在任何未知范围（登记覆盖不到的保守窗口
      或未接线消费者）——True 时 UI 须展示保守说明，不得隐藏。
    - ``receipt_id``：回执稳定指纹（``receipt_fingerprint``）。

    作者语言扩展字段：

    - ``changed``/``nothing_to_do``：本次变更是否有失效要传播。
    - ``invalidated``：失效了什么——每项 ``{consumer, label, detail}``；
      ``detail`` 原样携带该消费者的关键事实（索引 requested_hash、
      失效 run 数等），供前端展示与诊断。
    - ``unsupported``：尚未接线登记缝的消费者及原因（缺口可见）。
    - ``coverage_note``：范围说明（现状保守扩大的原文说明）。
    - ``recompute_options``：三分类选项（``derive_recompute_options``）。
    - ``diagnostics``：``earliest_affected_scene_index``、``source_change``
      与未翻译的内部消费者键——次级入口消费，不在主视图渲染。
    """
    invalidated: list[dict[str, Any]] = []
    unlabeled: list[str] = []
    for key, detail in receipt.invalidated_consumers.items():
        label = CONSUMER_LABELS.get(key)
        if label is None:
            unlabeled.append(key)
        invalidated.append(
            {
                "consumer": key,
                "label": label or key,
                "detail": detail,
            }
        )
    unsupported = [dict(item) for item in receipt.unsupported_consumers]
    if assessment is not None:
        unknown_scope = assessment.unknown_scope.conservative or bool(unsupported)
    else:
        unknown_scope = receipt.earliest_affected_scene_index is not None or bool(
            unsupported
        )
    return {
        "novel_id": receipt.novel_id,
        "chapter_index": receipt.chapter_index,
        "changed": receipt.source_change.changed if receipt.source_change else False,
        "nothing_to_do": receipt.nothing_to_do,
        "affected": affected_view_entries(receipt, assessment=assessment),
        "unknown_scope": unknown_scope,
        "receipt_id": receipt_fingerprint(receipt),
        "invalidated": invalidated,
        "unsupported": unsupported,
        "coverage_note": receipt.coverage_note,
        "recompute_options": derive_recompute_options(receipt, assessment=assessment),
        "diagnostics": {
            "earliest_affected_scene_index": receipt.earliest_affected_scene_index,
            "source_change": (
                receipt.source_change.model_dump(mode="json")
                if receipt.source_change
                else None
            ),
            "untranslated_consumers": unlabeled,
        },
    }


class RecomputeTargetRef(BaseModel):
    """重算目标引用（Scene 锚或章锚；作者语言层，不暴露内部 ID）。"""

    model_config = ConfigDict(frozen=True)

    scene_index: int | None = Field(default=None, ge=0)
    chapter_index: int | None = Field(default=None, ge=0)
    dimension: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def _validate_anchor(self) -> RecomputeTargetRef:
        if self.scene_index is None and self.chapter_index is None:
            raise ValueError("recompute target requires a scene or chapter anchor")
        return self


class RecomputeRequest(BaseModel):
    """作者显式触发的重算请求（预览与执行共用一个结构，``mode`` 区分）。

    幂等：``operation_id``（作者侧确认标识）+ ``recompute_request_hash``
    （请求内容指纹）双幂等，口径沿 collaboration ``merge_workspace``
    （同 operation_id 异内容拒绝，重放返回原回执 ``replayed=True``）。
    ``baseline_receipt_digest`` 锚定本次重算所响应的失效回执；执行时
    服务端重验（漂移则 409，避免对过期范围重算）——重验编排归 C3。
    """

    model_config = ConfigDict(frozen=True)

    novel_id: str = Field(min_length=1)
    operation_id: str = Field(min_length=1, max_length=120)
    scope: RecomputeScope
    targets: tuple[RecomputeTargetRef, ...] = Field(min_length=1)
    mode: Literal["preview", "execute"] = "preview"
    confirmed: bool = False
    baseline_receipt_digest: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def _validate_mode_and_scope(self) -> RecomputeRequest:
        if self.mode == "execute" and not self.confirmed:
            raise ValueError("execute requires author confirmation (confirmed=true)")
        if self.scope is RecomputeScope.regenerate_prose:
            if not any(target.chapter_index is not None for target in self.targets):
                raise ValueError(
                    "regenerate_prose targets must anchor chapters (prose is per chapter)"
                )
        return self


def recompute_request_hash(request: RecomputeRequest) -> str:
    """请求内容指纹（幂等第二键；不含 ``mode``——预览与执行视为同一操作）。"""
    return content_hash(
        {
            "novel_id": request.novel_id,
            "operation_id": request.operation_id,
            "scope": request.scope.value,
            "targets": [target.model_dump(mode="json") for target in request.targets],
            "baseline_receipt_digest": request.baseline_receipt_digest,
        }
    )


class RecomputePreview(BaseModel):
    """重算预览响应（结构上零正史写入）。"""

    model_config = ConfigDict(frozen=True)

    novel_id: str
    operation_id: str
    request_hash: str
    scope: RecomputeScope
    targets: tuple[RecomputeTargetRef, ...]
    cost: str = Field(min_length=1)
    write_effect: str = Field(min_length=1)
    affected_consumers: tuple[ConsumerVerdict, ...] = ()
    domain_write_performed: Literal[False] = False


class RecomputeOutcome(BaseModel):
    """重算执行回执（幂等重放标记沿 collaboration ``receipt_view``）。"""

    model_config = ConfigDict(frozen=True)

    novel_id: str
    operation_id: str
    request_hash: str
    scope: RecomputeScope
    replayed: bool = False
    domain_write_performed: bool = True
    results: dict[str, Any] = Field(default_factory=dict)


def build_recompute_preview(
    request: RecomputeRequest,
    *,
    affected_consumers: Sequence[ConsumerVerdict] = (),
) -> RecomputePreview:
    """由请求 + 影响判定组装预览（纯函数；C3 编排端点调用）。

    成本/写入效果直接取 ``RECOMPUTE_SCOPE_EFFECTS``（受控表，不调用方
    自由文本）；``affected_consumers`` 供调用方传入
    ``assess_source_impact`` 的命中判定。
    """
    effects = RECOMPUTE_SCOPE_EFFECTS[request.scope.value]
    return RecomputePreview(
        novel_id=request.novel_id,
        operation_id=request.operation_id,
        request_hash=recompute_request_hash(request),
        scope=request.scope,
        targets=request.targets,
        cost=effects["cost"],
        write_effect=effects["write_effect"],
        affected_consumers=tuple(affected_consumers),
    )


__all__ = [
    "CONSUMPTION_CONTRACT_VERSION",
    "CONSUMPTION_REGISTRY_STATE_KEY",
    "CONSUMER_LABELS",
    "CONSUMER_REF_REQUIRED_KEYS",
    "AssetDigest",
    "BasisAnchor",
    "BasisAnchorKind",
    "ChapterConsumption",
    "ConsumerImpact",
    "ConsumerKind",
    "ConsumerRef",
    "ConsumerVerdict",
    "ConsumptionRecord",
    "ImpactAssessment",
    "ImpactReason",
    "OffsetRange",
    "RecomputeOutcome",
    "RecomputePreview",
    "RecomputeRequest",
    "RecomputeScope",
    "RecomputeTargetRef",
    "RECOMPUTE_SCOPE_EFFECTS",
    "RECOMPUTE_SCOPE_COVERS",
    "SourceBinding",
    "UnknownScope",
    "affected_view_entries",
    "assess_source_impact",
    "build_recompute_preview",
    "derive_recompute_options",
    "read_consumption_records",
    "receipt_fingerprint",
    "receipt_public_view",
    "recompute_request_hash",
]
