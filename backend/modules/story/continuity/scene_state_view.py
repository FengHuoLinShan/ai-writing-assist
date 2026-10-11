"""指定场景状态读取：视角分层的只读投影（M2 契约 scene-state-view-v1）。

同一 Scene 的 ``is_current`` checkpoint 是唯一状态源；视角只决定分层输出的
可见性，不改变投影本体。事实（entities/relations/locations/timeline）、
信念（knowledge，可含 false_belief）与观察（未锚定 changes）分开呈现；
缺口显式返回，不用空列表冒充「确定不存在」，也不读今天 World 补过去。

M4 追加读时来源基线比对（basis.py）：系统行构建时登记的环境基线与当前不符即
degraded + gap_reason，绕过失效钩子的正文/结构变更不再静默供给；manual/confirmed
作者行豁免。世界正典修订不自动失效本视图（观察层记录「当时所见」），
以 unsupported_dependencies 显式列出，核对待走 World 复核。

P2-A 追加逐字段来源（field_provenance.py）：受控母题字段的 fact 在
``source["provenance"]`` 携带单条记录 ``{field, event_id, source_refs, status}``；
status 三态 exact/unverified/conflict，无记录（含旧格式 checkpoint）不冒充——
不带 provenance，展示层显示「来源待核实」。历史 checkpoint 摘要与列表出口
（``summarize_field_provenance`` / ``list_scene_checkpoints``）也由本模块提供。

P2-B 追加视角边界接线（knowledge_contract.py，B1 契约）：

- character 视角的知识授予与逐条拒绝原因同源于契约条目——
  ``read_knowledge_statements`` 读入 checkpoint 知识列表，
  ``build_knowledge_grants`` 构建授予表（与原 ``_knowledge_grants`` 口径
  对拍相等），``denial_reason`` 给每个被抑制 fact 归因三类互斥拒绝原因
  （no_knowledge_entry / knowledge_value_mismatch / false_belief），装进
  ``SceneStateViewDetailResponse.denied_facts``（仅 character 填充；
  reader 拒绝维持 omissions 数量口径，不泄露对象身份）。
- reader 揭示闸：``_reveal_cache`` 之上叠 ``evaluate_reader_reveal``（主张
  锚 = outline 策略已达到章 ∪ 全书 timeline 揭示事件的锚章
  ``field_path={subject}.{field}``）+ ``reveal_within_proven_shown`` 证明闸
  （固定来源回读中实际出现该字段值，unverified/conflict 或无值证明不算）。

  揭示的授权单位是**字段**而不是对象：主张锚按 ``{subject}.{field}`` 点名，
  证明也按 ``(subject, field)`` 取，同对象的其他字段不连坐（知道谁保管
  不等于知道其秘密关系）。**无策略且无主张锚也不豁免证明**——缺策略不代表
  存在证明，字段自身没有已展示原文时不对读者公开（P2-B 第 37 行）。
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncSession

from core.container import get
from core.errors import DomainError, NotFoundError, ValidationError
from core.service_keys import WORLD_GET_CHARACTER_ID_BY_WORLD_ENTITY
from infrastructure.stable_hash import stable_hash
from modules.story.continuity.basis import basis_hash, compute_scene_basis
from modules.story.continuity.contracts import SCENE_MEMORY_DIMENSIONS
from modules.story.continuity.field_provenance import (
    FIELD_PROVENANCE_STATE_KEY,
    FieldProvenance,
    read_field_provenance,
    resolve_field_status,
    timeline_fact_instance_key,
)
from modules.story.continuity.knowledge_contract import (
    KnowledgeStatement,
    RevealDomain,
    build_knowledge_grants,
    denial_reason,
    evaluate_reader_reveal,
    read_knowledge_statements,
    reveal_within_proven_shown,
)
from modules.story.continuity.repositories import EventRepository
from modules.story.continuity.scene_projection import SceneMemoryProjectionService
from modules.story.continuity.schemas import (
    SceneStateDimensionView,
    SceneStateFactEntry,
    SceneStateViewResponse,
)
from modules.story.outline_state.facade import (
    get_reader_reveal_decision,
    get_scene_contract,
)
from modules.writing.contracts import SourceRangeRefContract
from modules.writing.facade import build_manuscript_range_ref, read_manuscript_range
from shared.utils import parse_uuid

SCENE_STATE_VIEW_CONTRACT_VERSION = "scene-state-view-v1"

UNSUPPORTED_DIMENSIONS = ("world_valid_time", "belief_fact_diff")

# 依赖来源存在但不自动失效本视图的类别（M4 契约 §3.3）。
UNSUPPORTED_DEPENDENCIES = ("world_canon_revision", "map_atlas")

_BASIS_DRIFT_REASON = "来源基线已变化（正文/场景结构修订），投影待重验"
_BASIS_MISSING_REASON = "缺少来源基线登记，待重建后补齐"

_DIMENSION_LABELS = {
    "entities": "人物与对象",
    "relations": "关系",
    "locations": "空间与位置",
    "knowledge": "知识边界",
    "timeline": "时间顺序",
    "causality": "因果与前提",
}

# 实体负载里的身份/展示字段不作为状态字段重复输出；meta 是事件键等
# 注入元数据（services._with_scene_event_key），不属于状态。
_ENTITY_META_KEYS = frozenset({"id", "name", "label", "title", "full_name", "meta"})
_BELIEF_TEXT_KEYS = ("knowledge", "content", "belief", "summary", "text")
_FALSE_MARKERS = ("false", "false_belief")


def _clean_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if key != "meta"}


def _scene_payload(scene_contract: Any) -> dict[str, Any]:
    if scene_contract is None:
        raise NotFoundError("Scene not found", code="scene_not_found")
    if isinstance(scene_contract, dict):
        return scene_contract
    from dataclasses import asdict

    return asdict(scene_contract)


def _scene_chapters(scene: dict[str, Any]) -> list[int]:
    values = list(scene.get("chapter_ids") or [])
    values.extend(
        chunk.get("chapter_index", chunk.get("chapter_id"))
        for chunk in scene.get("scene_chunks") or []
        if isinstance(chunk, dict)
    )
    return [int(value) for value in values if str(value).isdigit()]


def _reveal_keys(entry: Any) -> tuple[tuple[str, str], ...]:
    """一条事实在 reader 揭示表里的候选键（``(subject, field)``）。

    聚合条目（位置 fact 字段名 ``location``）的证明挂在底层受控字段
    （``location_id``/``text_state``）上，故同时查字段名本身与证明里点名的
    字段；嵌套负载键（``x.y``）同时查其顶层键，揭示主张按 ``{subject}.{x}``
    点名时也能命中。查不到即未揭示，不按对象放宽。
    """
    subject = str(entry.subject_id)
    keys = [(subject, entry.field)]
    provenance = (entry.source or {}).get("provenance") or {}
    provenance_field = provenance.get("field")
    if isinstance(provenance_field, str) and provenance_field != entry.field:
        keys.append((subject, provenance_field))
    head = str(entry.field).split(".", 1)[0]
    if head != entry.field:
        keys.append((subject, head))
    return tuple(dict.fromkeys(keys))


def _occurred_at(payload: dict[str, Any]) -> dict[str, int] | None:
    occurred: dict[str, int] = {}
    for key in ("scene_index", "scene_sequence"):
        value = payload.get(key)
        if isinstance(value, bool) or not isinstance(value, int):
            continue
        occurred[key] = value
    return occurred or None


def summarize_field_provenance(
    state_json: Mapping[str, Any] | None,
    dimension: str | None = None,
    *,
    include_value_hash: bool = False,
) -> dict[tuple[str, str | None], dict[str, Any]]:
    """checkpoint 内嵌逐字段来源 → ``{(field_key, subject_ref): 单记录摘要}``。

    摘要形态由 A0 夹具钉定，仅四键::

        {"field": str, "status": "exact"|"unverified"|"conflict",
         "event_id": str | None, "source_refs": [SourceRangeRefContract 形态 dict]}

    - 分组键 ``(field_key, subject_ref)``：同维度多实体的同名字段各走各的
      裁决链（entities/locations 的 subject_ref 为实体 ID，timeline 等无
      实体容器为 None），互相不污染。
    - 判定与 ``resolve_field_status`` 同源：最新链唯一且有稿源区间 → exact；
      只追到事件 → unverified（保留已知 event_id，source_refs 为空）；
      同序多条不同链 → conflict，无法唯一归因时不冒充（event_id=None、
      source_refs 空）；历史链（更早事件序）不参与展示。
    - 旧格式（无 ``_field_provenance`` 键）或无记录 → 空 dict，调用方不得
      据此宣称 exact；「来源待核实」的展示语义归展示层。
    - ``dimension`` 给定时只聚合该维度的链（checkpoint 本就按维度分行，
      过滤防止跨维度串链）。
    """
    grouped: dict[tuple[str, str | None], list[FieldProvenance]] = {}
    for record in read_field_provenance(state_json):
        if dimension is not None and record.dimension != dimension:
            continue
        grouped.setdefault((record.field_key, record.subject_ref), []).append(record)
    summaries: dict[tuple[str, str | None], dict[str, Any]] = {}
    for (field_key, subject_ref), records in grouped.items():
        status = resolve_field_status(records)
        if status is None:
            continue
        deduped = {
            json.dumps(record.model_dump(mode="json")): record for record in records
        }
        top_sequence = max(record.recorded_at_sequence for record in deduped.values())
        latest = [
            record
            for record in deduped.values()
            if record.recorded_at_sequence == top_sequence
        ]
        chosen = latest[0] if len(latest) == 1 else None
        summaries[(field_key, subject_ref)] = {
            "field": field_key,
            "status": status.value,
            "event_id": chosen.event_id if chosen else None,
            "source_refs": [ref.model_dump(mode="json") for ref in chosen.source_refs]
            if chosen
            else [],
        }
        if include_value_hash:
            summaries[(field_key, subject_ref)]["value_hash"] = (
                chosen.value_hash if chosen else None
            )
    return summaries


class SceneStateViewDetailResponse(SceneStateViewResponse):
    """P2-B：视角视图 + character 侧逐条拒绝原因（``denied_facts``）。

    ``SceneStateViewResponse`` 的超集——既有字段语义不变、只增不删，序列化
    出口兼容（FastAPI response_model 按父类校验时子类实例原样通过，
    jsonable_encoder 按实例 dump，新字段保留）。

    - ``denied_facts`` 仅 character 视角填充：每个因知识边界被抑制的 fact
      逐条归因三类互斥原因（``knowledge_contract.denial_reason``：
      no_knowledge_entry / knowledge_value_mismatch / false_belief），供作者
      解释「为什么这个角色不知道」；作者视角全见不产生拒绝。
    - reader 视角恒为空列表：读者拒绝维持 omissions 的数量口径（揭示前
      不泄露对象身份，B0 契约第 5 条钉定）。
    - 不参与 ``state_fingerprint``：拒绝原因是视角解释，不改变可见状态
      本体（同一 checkpoint 重复请求结果确定）。
    """

    denied_facts: list[dict[str, Any]] = Field(default_factory=list)


class SceneStateViewService:
    """视角分层读取；纯读，不 ensure、不重建、不写库。"""

    def __init__(self, projection: SceneMemoryProjectionService | None = None) -> None:
        self._projection = projection or SceneMemoryProjectionService()

    async def get_view(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        scene_id: str,
        viewpoint: dict[str, Any],
        include_dimensions: list[str] | None = None,
    ) -> SceneStateViewResponse:
        kind = str(viewpoint.get("kind") or "author")
        target_id = str(viewpoint.get("target_id") or "") if kind == "character" else None
        if kind not in {"author", "character", "reader"}:
            raise ValidationError(
                "viewpoint.kind 必须是 author/character/reader",
                code="invalid_viewpoint",
                status_code=422,
            )
        if kind == "character" and not target_id:
            raise ValidationError(
                "character 视角必须提供 target_id",
                code="invalid_viewpoint",
                status_code=422,
            )

        if kind == "character":
            if not await get(WORLD_GET_CHARACTER_ID_BY_WORLD_ENTITY)(
                db, novel_id, target_id
            ):
                raise NotFoundError(
                    "本作品未登记该人物", code="scene_viewpoint_not_found"
                )
        scene = _scene_payload(await get_scene_contract(db, novel_id, scene_id))
        chapters = _scene_chapters(scene)
        cutoff_chapter = max(chapters) if chapters else None

        scenes = await SceneMemoryProjectionService._ordered_scenes(db, novel_id)
        checkpoint_set = await self._projection.get_scene(
            db, novel_id, scene_id, scenes=scenes
        )
        items = {item.dimension: item for item in checkpoint_set.items}
        dimensions_filter = include_dimensions or list(SCENE_MEMORY_DIMENSIONS)
        current_basis = await compute_scene_basis(
            db, novel_id, scenes, up_to_scene_index=int(checkpoint_set.scene_index)
        )
        current_basis_hash = basis_hash(current_basis)

        # P2-B：character 视角的知识授予与拒绝原因同源（契约条目单一事实源）。
        knowledge_statements: list[KnowledgeStatement] = []
        knowledge_grants: dict[str, dict[str, frozenset[str]]] = {}
        if kind == "character":
            knowledge_checkpoint = items.get("knowledge")
            knowledge_statements = read_knowledge_statements(
                knowledge_checkpoint.state_json
                if knowledge_checkpoint is not None
                else None
            )
            knowledge_grants = build_knowledge_grants(knowledge_statements, target_id)
        reveal_cache = (
            await self._reveal_cache(
                db,
                novel_id=novel_id,
                cutoff_chapter=cutoff_chapter,
                subjects={
                    str(entry_subject)
                    for dim in ("entities", "locations", "relations")
                    if dim in dimensions_filter
                    for entry_subject, _layer in self._dim_subjects(items.get(dim), dim)
                },
                scenes=scenes,
                proven_chapters=await self._proven_shown_by_field(
                    db,
                    novel_id,
                    items,
                    scenes=scenes,
                    up_to_scene_index=int(checkpoint_set.scene_index),
                    source_hashes=current_basis["manuscript"],
                ),
            )
            if kind == "reader"
            else {}
        )

        dimensions: list[SceneStateDimensionView] = []
        omissions: list[str] = []
        denied_facts: list[dict[str, Any]] = []
        for dimension in dimensions_filter:
            checkpoint = items.get(dimension)
            if checkpoint is None or checkpoint.status == "missing":
                dimensions.append(
                    SceneStateDimensionView(
                        dimension=dimension,
                        label=_DIMENSION_LABELS.get(dimension, dimension),
                        status="missing",
                        gap_reason=str(
                            getattr(checkpoint, "gap_reason", None)
                            or "该维度尚未建立 checkpoint"
                        ),
                    )
                )
                continue
            if kind == "reader" and dimension == "timeline":
                dimensions.append(
                    SceneStateDimensionView(
                        dimension=dimension,
                        label=_DIMENSION_LABELS[dimension],
                        status="unsupported",
                        gap_reason="时间事实尚未登记读者揭示范围，未向读者提供",
                    )
                )
                omissions.append("时间顺序：读者揭示范围尚未核对")
                continue
            entries = self._entries_for(dimension, checkpoint)
            visible, suppressed, denied = self._filter_entries(
                dimension,
                entries,
                kind=kind,
                target_id=target_id,
                knowledge_grants=knowledge_grants,
                reveal_cache=reveal_cache,
                knowledge_statements=knowledge_statements,
            )
            denied_facts.extend(denied)
            status = "ok" if checkpoint.status == "ready" else "degraded"
            gap_reason = str(checkpoint.gap_reason) if checkpoint.gap_reason else None
            basis_reason = self._basis_gap_reason(checkpoint, current_basis_hash)
            if basis_reason:
                status = "degraded"
                gap_reason = gap_reason or basis_reason
            dimensions.append(
                SceneStateDimensionView(
                    dimension=dimension,
                    label=_DIMENSION_LABELS.get(dimension, dimension),
                    status=status,
                    gap_reason=gap_reason,
                    # checkpoint 的引用覆盖整个维度，不能证明过滤后的单条知识。
                    evidence_refs=[dict(ref) for ref in checkpoint.evidence_refs or []]
                    if kind == "author"
                    else [],
                    facts=visible,
                )
            )
            if suppressed:
                reason = {
                    "character": "角色视角未获得依据",
                    "reader": "读者视角尚未揭示",
                }.get(kind, "")
                omissions.append(
                    f"{_DIMENSION_LABELS.get(dimension, dimension)}：{reason}"
                    f"{suppressed} 项"
                )

        labels = self._subject_labels(items)
        if kind != "author":
            visible_subjects = {
                fact.subject_id for dim in dimensions for fact in dim.facts
            }
            labels = {
                key: label for key, label in labels.items() if key in visible_subjects
            }
        fingerprint = stable_hash(
            {
                "contract_version": SCENE_STATE_VIEW_CONTRACT_VERSION,
                "viewpoint": {"kind": kind, "target_id": target_id},
                "dimensions": [
                    {
                        "dimension": dim.dimension,
                        "facts": [fact.model_dump(mode="json") for fact in dim.facts],
                        "evidence_refs": dim.evidence_refs,
                    }
                    for dim in dimensions
                ],
                "subject_labels": labels,
                "checkpoints": sorted(
                    [
                        [item.dimension, str(item.id), str(item.source_hash)]
                        for item in checkpoint_set.items
                        if item.dimension in dimensions_filter
                    ]
                ),
            }
        )
        return SceneStateViewDetailResponse(
            novel_id=str(novel_id),
            scene_id=str(scene_id),
            scene_index=int(checkpoint_set.scene_index),
            chapter_index=cutoff_chapter,
            contract_version=SCENE_STATE_VIEW_CONTRACT_VERSION,
            viewpoint={"kind": kind, **({"target_id": target_id} if target_id else {})},
            state_fingerprint=fingerprint,
            subject_labels=labels,
            dimensions=dimensions,
            unsupported_dependencies=list(UNSUPPORTED_DEPENDENCIES),
            unsupported_dimensions=list(UNSUPPORTED_DIMENSIONS),
            omissions=omissions,
            denied_facts=denied_facts,
        )

    # ── 来源基线新鲜度（M4 契约 §3.2）──

    @staticmethod
    def _basis_gap_reason(checkpoint: Any, current_basis_hash: str | None) -> str | None:
        """系统行基线漂移/缺失的降级原因；manual/confirmed 作者行豁免。"""
        if getattr(checkpoint, "source", "system_generated") != "system_generated":
            return None
        if getattr(checkpoint, "confirmed", False):
            return None
        recorded = basis_hash(getattr(checkpoint, "basis_json", None))
        if recorded is None:
            return _BASIS_MISSING_REASON
        if recorded != current_basis_hash:
            return _BASIS_DRIFT_REASON
        return None

    # ── 分维度条目提取（纯函数，输出 author 基线三层全集）──

    @classmethod
    def _entries_for(cls, dimension: str, checkpoint: Any) -> list[SceneStateFactEntry]:
        state = checkpoint.state_json or {}
        confidence = (
            "confirmed"
            if checkpoint.confirmed or checkpoint.source == "manual"
            else "derived"
        )
        source = {
            "checkpoint_id": str(checkpoint.id),
            "dimension": dimension,
            "confirmed": bool(checkpoint.confirmed),
        }
        # P2-A：受控母题字段的逐字段来源单记录；旧格式/无记录 → 空 dict，
        # 对应 fact 不带 provenance，不冒充精确。
        provenance_by_field = summarize_field_provenance(state, dimension)
        entries: list[SceneStateFactEntry] = []

        def add(
            *,
            subject_id: str | None,
            subject_label: str,
            field: str,
            value: Any,
            layer: str,
            payload: dict[str, Any] | None = None,
            possibly_false: bool = False,
            provenance: dict[str, Any] | None = None,
        ) -> None:
            entries.append(
                SceneStateFactEntry(
                    subject_id=subject_id,
                    subject_label=subject_label,
                    field=field,
                    value=value,
                    layer=layer,
                    occurred_at=_occurred_at(payload or {}),
                    source={
                        **source,
                        **(
                            {
                                "known_fields": list(payload.get("fields") or []),
                                "known_values": {
                                    key: value
                                    for key, value in (
                                        payload["known_values"]
                                        if isinstance(payload.get("known_values"), dict)
                                        else {}
                                    ).items()
                                    if key in (payload.get("fields") or [])
                                },
                            }
                            if layer == "belief" and payload
                            else {}
                        ),
                        **({"provenance": provenance} if provenance else {}),
                    },
                    confidence=confidence,
                    possibly_false=possibly_false,
                )
            )

        if dimension == "entities":
            for entity_id, payload in (state.get("entities") or {}).items():
                if not isinstance(payload, dict):
                    continue
                label = cls._entity_label(payload, str(entity_id))
                for field, value in cls._flatten_fields(payload):
                    add(
                        subject_id=str(entity_id),
                        subject_label=label,
                        field=field,
                        value=value,
                        layer="fact",
                        payload=payload,
                        # 逐字段来源按受控 payload 键登记；查询键带实体锚，
                        # 多实体同名字段各走各的链。未登记键查不到摘要。
                        provenance=provenance_by_field.get((field, str(entity_id))),
                    )
            for payload in state.get("changes") or []:
                if not isinstance(payload, dict):
                    continue
                add(
                    subject_id=str(payload.get("id")) if payload.get("id") else None,
                    subject_label=cls._entity_label(payload, "未锚定观察"),
                    field="observation",
                    value=_clean_payload(payload),
                    layer="observation",
                    payload=payload,
                )
        elif dimension == "locations":
            for entity_id, payload in (state.get("character_locations") or {}).items():
                if not isinstance(payload, dict):
                    continue
                # 位置 fact 是整份 payload 的聚合条目；逐字段来源只挂**当前
                # payload 仍存在**的受控字段，且取其中赋值序最新的那条链：
                # 新位置只写描述（text_state）时不得回开旧 location_id 的
                # 事件——聚合条目不能挑一个与当前值无关的旧字段当精确来源。
                location_provenance = cls._location_provenance(
                    state, str(entity_id), payload, provenance_by_field
                )
                add(
                    subject_id=str(entity_id),
                    subject_label=cls._entity_label(payload, str(entity_id)),
                    field="location",
                    value=_clean_payload(payload),
                    layer="fact",
                    payload=payload,
                    provenance=location_provenance,
                )
        elif dimension == "knowledge":
            for payload in state.get("character_knowledge") or []:
                if not isinstance(payload, dict):
                    continue
                holder = payload.get("character_id") or payload.get("holder_id")
                text = next(
                    (str(payload[key]) for key in _BELIEF_TEXT_KEYS if payload.get(key)),
                    "未记载内容的知识条目",
                )
                knows_subject = str(
                    payload.get("subject_id") or payload.get("subject") or "unspecified"
                )
                add(
                    subject_id=str(holder) if holder else None,
                    subject_label=text,
                    field=f"knows:{knows_subject}",
                    value=text,
                    layer="belief",
                    payload=payload,
                    possibly_false=any(
                        bool(payload.get(marker)) for marker in _FALSE_MARKERS
                    ),
                )
        elif dimension == "relations":
            for payload in state.get("relations") or []:
                if not isinstance(payload, dict):
                    continue
                relation_id = payload.get("id") or payload.get("relation_id")
                add(
                    subject_id=str(relation_id) if relation_id else None,
                    subject_label=str(
                        payload.get("label") or payload.get("kind") or "关系"
                    ),
                    field="relation",
                    value=_clean_payload(payload),
                    layer="fact",
                    payload=payload,
                )
        elif dimension == "timeline":
            for payload in state.get("facts") or []:
                if not isinstance(payload, dict):
                    continue
                # moon_phase 是 timeline 维度唯一登记的受控母题字段：按该
                # fact 的**实例键**挂链（多条月相事实各挂各的赋值，不共用
                # 最后一条链）；旧载荷无实例键时保留待核实，不冒充实例级
                # 证明。只有该 fact 本身携带月相值时才挂链。
                moon_provenance = None
                if payload.get("moon_phase") is not None:
                    fact_key = timeline_fact_instance_key(payload)
                    moon_provenance = (
                        provenance_by_field.get(("moon_phase", fact_key))
                        if fact_key is not None
                        else None
                    )
                add(
                    subject_id=str(payload.get("id")) if payload.get("id") else None,
                    subject_label=str(
                        payload.get("label") or payload.get("text") or "时间事实"
                    ),
                    field="timeline_fact",
                    value=_clean_payload(payload),
                    layer="fact",
                    payload=payload,
                    provenance=moon_provenance,
                )
        elif dimension == "causality":
            for payload in state.get("claims") or []:
                if not isinstance(payload, dict):
                    continue
                add(
                    subject_id=str(payload.get("id")) if payload.get("id") else None,
                    subject_label=str(
                        payload.get("label") or payload.get("text") or "因果主张"
                    ),
                    field="causality_claim",
                    value=_clean_payload(payload),
                    layer="fact",
                    payload=payload,
                )
        return entries

    @staticmethod
    def _location_provenance(
        state: Mapping[str, Any],
        subject_id: str,
        payload: Mapping[str, Any],
        provenance_by_field: Mapping[tuple[str, str | None], dict[str, Any]],
    ) -> dict[str, Any] | None:
        """位置聚合条目的来源链：只在当前 payload 仍有的受控字段里挑最新赋值。

        位置事件可能只改描述（``text_state``）而不再给 ``location_id``；此时
        回开旧 ``location_id`` 的事件会把读者/作者带到与当前值无关的来源上。
        按「字段仍在当前 payload」过滤后取赋值序最新的一条链，多字段同序时
        ``location_id`` 优先（主锚字段）。
        """
        present = [key for key in ("location_id", "text_state") if key in payload]
        if not present:
            return None
        records = [
            record
            for record in read_field_provenance(state)
            if record.subject_ref == subject_id and record.field_key in present
        ]
        if not records:
            return None
        latest = max(
            records,
            key=lambda item: (
                item.recorded_at_sequence,
                1 if item.field_key == "location_id" else 0,
            ),
        )
        return provenance_by_field.get((latest.field_key, subject_id))

    @staticmethod
    def _subject_labels(items: dict[str, Any]) -> dict[str, str]:
        """subject → 展示名（entities/locations 维度 payload 的 name 类字段）。"""
        labels: dict[str, str] = {}
        for dimension, keys in (
            ("entities", ("entities",)),
            ("locations", ("character_locations",)),
        ):
            checkpoint = items.get(dimension)
            if checkpoint is None:
                continue
            state = checkpoint.state_json or {}
            for key in keys:
                for subject, payload in (state.get(key) or {}).items():
                    if not isinstance(payload, dict):
                        continue
                    label = SceneStateViewService._entity_label(payload, str(subject))
                    if label != str(subject):
                        labels.setdefault(str(subject), label)
        return labels

    @staticmethod
    def _entity_label(payload: dict[str, Any], fallback: str) -> str:
        for key in ("name", "label", "title", "full_name"):
            if payload.get(key):
                return str(payload[key])
        return fallback

    @staticmethod
    def _flatten_fields(payload: dict[str, Any]) -> list[tuple[str, Any]]:
        fields: list[tuple[str, Any]] = []
        for key, value in payload.items():
            if key in _ENTITY_META_KEYS:
                continue
            if isinstance(value, dict):
                for sub_key, sub_value in value.items():
                    fields.append((f"{key}.{sub_key}", sub_value))
            else:
                fields.append((key, value))
        return fields

    # ── 视角过滤 ──

    @staticmethod
    def _dim_subjects(checkpoint: Any, dimension: str) -> set[tuple[str, str]]:
        """(subject_id, layer) 全集，供 reader 预取 reveal 判定。"""
        subjects: set[tuple[str, str]] = set()
        if checkpoint is None:
            return subjects
        state = checkpoint.state_json or {}
        if dimension == "entities":
            subjects.update((str(key), "fact") for key in state.get("entities") or {})
        elif dimension == "locations":
            subjects.update(
                (str(key), "fact") for key in state.get("character_locations") or {}
            )
        elif dimension == "relations":
            subjects.update(
                (str(payload.get("id") or payload.get("relation_id") or ""), "fact")
                for payload in state.get("relations") or []
                if isinstance(payload, dict)
            )
        subjects.discard(("", "fact"))
        return subjects

    @staticmethod
    def _knowledge_grants(
        checkpoint: Any, target_id: str
    ) -> dict[str, dict[str, frozenset[str]]]:
        """角色的知识绑定到字段值，旧知识不能放行未目击的后来变化。

        P2-B 起委托统一契约（``read_knowledge_statements`` +
        ``build_knowledge_grants``，与原内联实现逐位对拍相等——
        test_p2b_knowledge_contract 钉定）；授予语义不变：

        - 带 false/false_belief 标记的误信条目不授予（误信不是知识）。
        - 授予需要显式 ``fields`` 与 ``known_values``；缺失则仅为 belief
          （A03：丙知道 holder 不等于知道 owner）。
        """
        if checkpoint is None:
            return {}
        statements = read_knowledge_statements(checkpoint.state_json)
        return build_knowledge_grants(statements, target_id)

    def _filter_entries(
        self,
        dimension: str,
        entries: list[SceneStateFactEntry],
        *,
        kind: str,
        target_id: str | None,
        knowledge_grants: dict[str, dict[str, frozenset[str]]],
        reveal_cache: dict[tuple[str, str], bool],
        knowledge_statements: list[KnowledgeStatement] | None = None,
    ) -> tuple[list[SceneStateFactEntry], int, list[dict[str, Any]]]:
        if kind == "author":
            return entries, 0, []

        def keep(entry: SceneStateFactEntry) -> bool:
            if kind == "character":
                if entry.layer == "belief":
                    return entry.subject_id == target_id
                if entry.layer == "observation":
                    return False
                # 本人位置可见；本人身份/秘密与提及自己的关系仍需知识依据。
                if dimension == "locations" and entry.subject_id == target_id:
                    return True
                values = knowledge_grants.get(str(entry.subject_id or ""), {}).get(
                    entry.field, set()
                )
                return stable_hash(entry.value) in values
            # reader：belief/observation 不输出；timeline 按叙述呈现；
            # 因果主张是作者层断言，不进入读者视图。
            if entry.layer != "fact":
                return False
            if dimension in {"timeline", "causality"}:
                return False
            if not entry.subject_id:
                return False
            # 逐字段揭示：键是该条事实自己的字段（或其底层受控字段），
            # 同对象其他字段的证明不连坐。
            return any(reveal_cache.get(key, False) for key in _reveal_keys(entry))

        visible: list[SceneStateFactEntry] = []
        denied: list[dict[str, Any]] = []
        for entry in entries:
            if (
                dimension == "locations"
                and kind == "reader"
                and isinstance(entry.value, dict)
            ):
                value = {
                    key: value
                    for key, value in entry.value.items()
                    if reveal_cache.get((str(entry.subject_id), key), False)
                }
                if value:
                    source = dict(entry.source)
                    provenance = source.get("provenance") or {}
                    if provenance.get("field") not in value:
                        source.pop("provenance", None)
                    visible.append(
                        entry.model_copy(update={"value": value, "source": source})
                    )
                continue
            if keep(entry):
                visible.append(entry)
                continue
            # P2-B：character 视角对每个被抑制的 fact 逐条归因（三类互斥，
            # denial_reason 与授予同一契约口径）；belief/observation 的
            # 拒绝是视角层排除，不是知识原因，维持维度级 omissions 计数。
            if kind != "character" or entry.layer != "fact":
                continue
            if knowledge_statements is None or target_id is None:
                continue
            cause = denial_reason(
                knowledge_statements,
                holder_id=target_id,
                subject_id=str(entry.subject_id or ""),
                field=entry.field,
                value=entry.value,
            )
            if cause is None:
                continue
            denied.append(
                {
                    "dimension": dimension,
                    "subject_id": entry.subject_id,
                    "subject_label": entry.subject_label,
                    "field": entry.field,
                    "cause": cause.value,
                }
            )
        return visible, len(entries) - len(visible), denied

    async def _reveal_cache(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        cutoff_chapter: int | None,
        subjects: set[str],
        scenes: list[dict[str, Any]] | None = None,
        proven_chapters: dict[tuple[str, str], frozenset[int]] | None = None,
    ) -> dict[tuple[str, str], bool]:
        """reader 视角的逐**字段**揭示判定（P2-B 双闸，按字段而非整对象）。

        揭示授权的最小单位是「对象的哪个字段」，不是整个对象：知道某人保管
        什么，不等于知道他的秘密关系。判定返回键 ``(subject, field)``。

        - cutoff 闸（``evaluate_reader_reveal``）：有策略或揭示主张记录
          （timeline 揭示事件 ``field_path={subject}.{field}``）的字段移入
          须证明域——无 cutoff 不猜、当章不揭示（严格 ``<``）。
        - 证明闸（``reveal_within_proven_shown``）：锚章须落在该**字段**自身
          exact 稿源章内；unverified/conflict 不构成证明。
        - 无策略且无揭示主张的字段**不豁免证明**：只在该字段自身有已展示原文
          （读者已读到的章，含当章）时对读者可见。缺策略不等于存在证明——
          否则没有登记揭示的秘密会被默认公开。
        """
        if cutoff_chapter is None:
            # 无章节锚点时保守：全部按未揭示处理，不猜测揭示位置。
            return {}
        claims = await self._reveal_claim_chapters(
            db, novel_id=novel_id, subjects=subjects, scenes=scenes or []
        )
        proven = proven_chapters or {}
        cache: dict[tuple[str, str], bool] = {}
        for subject in sorted(subjects):
            decision = await get_reader_reveal_decision(
                db,
                novel_id=novel_id,
                target_type="entity",
                target_id=subject,
                cutoff_chapter=cutoff_chapter,
            )
            if decision is None:
                # 决策服务契约上恒返回决策对象；真缺失时保守隐藏。
                continue
            has_policy = bool(getattr(decision, "has_policy", False))
            reveal_chapter = getattr(decision, "reveal_chapter", None)
            fields = sorted(
                {field for (owner, field) in claims if owner == subject}
                | {field for (owner, field) in proven if owner == subject}
            )
            for field in fields:
                anchors: set[int] = set(claims.get((subject, field), ()))
                if has_policy and reveal_chapter is not None:
                    # 策略是对象级锚（无字段粒度）：作用到该对象全部字段。
                    anchors.add(int(reveal_chapter))
                shown = proven.get((subject, field), frozenset())
                if not has_policy and not anchors:
                    cache[(subject, field)] = any(
                        chapter <= cutoff_chapter for chapter in shown
                    )
                    continue
                cache[(subject, field)] = evaluate_reader_reveal(
                    domain=RevealDomain.outline_structure,
                    has_policy=has_policy,
                    cutoff_chapter=cutoff_chapter,
                    reveal_chapters=frozenset(anchors),
                ) and any(
                    chapter < cutoff_chapter
                    and reveal_within_proven_shown(chapter, shown)
                    for chapter in anchors
                )
        return cache

    @staticmethod
    async def _reveal_claim_chapters(
        db: AsyncSession,
        *,
        novel_id: str,
        subjects: set[str],
        scenes: list[dict[str, Any]],
    ) -> dict[str, frozenset[int]]:
        """全书 timeline 揭示主张事件的锚章（B1 契约 ``field_path`` 形态）。

        揭示主张记录跨 Scene 生效：后文 Scene 的揭示事件把对象移入须证明
        域，早 Scene 的读者视图不得默认公开。锚章 = 事件章节；无点号或首段
        非本视图 subject 的 ``field_path``（如既有 ``handover`` 标签形态的
        普通时间事实）不算揭示主张。
        """
        if not subjects or not scenes:
            return {}
        max_scene_index = max(int(scene["scene_index"]) for scene in scenes)
        events = await EventRepository().get_through_scene(
            db, parse_uuid(novel_id, "novel_id"), max_scene_index, dimension="timeline"
        )
        claims: dict[tuple[str, str], set[int]] = {}
        for event in events:
            payload = event.snapshot_after
            if not isinstance(payload, dict):
                continue
            field_path = payload.get("field_path")
            if not isinstance(field_path, str) or "." not in field_path:
                continue
            subject, _, field = field_path.partition(".")
            if subject not in subjects or not field or event.chapter_index is None:
                continue
            claims.setdefault((subject, field), set()).add(int(event.chapter_index))
        return {key: frozenset(values) for key, values in claims.items()}

    @staticmethod
    async def _shown_ranges(db, novel_id, ref, scenes, up_to_scene_index):
        """Keep reader proof inside the already-read Scene prefix of this source."""
        anchored = [
            scene for scene in scenes if ref.chapter_index in _scene_chapters(scene)
        ]
        ranges = []
        for scene in anchored:
            if int(scene["scene_index"]) > up_to_scene_index:
                continue
            chunks = [
                chunk
                for chunk in scene.get("scene_chunks") or []
                if isinstance(chunk, dict)
                and ref.chapter_index in _scene_chapters({"scene_chunks": [chunk]})
            ]
            bounded = [
                chunk
                for chunk in chunks
                if isinstance(chunk.get("start_offset"), int)
                and isinstance(chunk.get("end_offset"), int)
            ]
            if not bounded:
                # One Scene owns the chapter; shared chapters require real offsets.
                if len(anchored) == 1:
                    ranges.append((ref.start_offset, ref.end_offset))
                continue
            for chunk in bounded:
                if (
                    chunk.get("source_draft_id")
                    and str(chunk["source_draft_id"]) != ref.draft_id
                ):
                    continue
                if (
                    chunk.get("source_content_hash")
                    and chunk["source_content_hash"] != ref.source_hash
                ):
                    continue
                try:
                    bound = await build_manuscript_range_ref(
                        db,
                        novel_id,
                        draft_id=ref.draft_id,
                        start_offset=chunk["start_offset"],
                        end_offset=chunk["end_offset"],
                        content_mode="working",
                    )
                except DomainError:
                    continue
                if bound.source_hash != ref.source_hash:
                    continue
                start = max(ref.start_offset, chunk["start_offset"])
                end = min(ref.end_offset, chunk["end_offset"])
                if 0 <= start < end:
                    ranges.append((start, end))
        return ranges

    @classmethod
    async def _proven_shown_by_field(
        cls, db, novel_id, items, *, scenes, up_to_scene_index, source_hashes
    ):
        """逐字段/值回读固定来源；仅可证明已出现在该范围里的值进入 reader。"""
        labels = cls._subject_labels(items)
        chapters = {}
        reads = {}
        shown_ranges = {}
        for dimension, container in (
            ("entities", "entities"),
            ("locations", "character_locations"),
        ):
            checkpoint = items.get(dimension)
            if checkpoint is None:
                continue
            state = checkpoint.state_json or {}
            for (field, subject), summary in summarize_field_provenance(
                state, dimension, include_value_hash=True
            ).items():
                payload = (state.get(container) or {}).get(subject, {})
                value = payload.get(field)
                if summary.get("status") != "exact" or summary.get(
                    "value_hash"
                ) != stable_hash(value):
                    continue
                witness = (
                    labels.get(str(value), str(value)) if isinstance(value, str) else None
                )
                if not witness:
                    continue
                for raw in summary.get("source_refs") or ():
                    ref = SourceRangeRefContract(**raw)
                    if source_hashes.get(str(ref.chapter_index)) != ref.source_hash:
                        continue
                    key = stable_hash(raw)
                    if key not in reads:
                        try:
                            read = await read_manuscript_range(
                                db, novel_id, ref, before=0, after=0
                            )
                        except DomainError:
                            reads[key] = None
                        else:
                            reads[key] = read.text[
                                read.highlight_start : read.highlight_end
                            ]
                    if key not in shown_ranges:
                        shown_ranges[key] = await cls._shown_ranges(
                            db, novel_id, ref, scenes, up_to_scene_index
                        )
                    text = reads[key]
                    if text is not None and any(
                        witness in text[start - ref.start_offset : end - ref.start_offset]
                        for start, end in shown_ranges[key]
                    ):
                        chapters.setdefault((str(subject), field), set()).add(
                            ref.chapter_index
                        )
        return {key: frozenset(values) for key, values in chapters.items()}


_service = SceneStateViewService()


async def get_scene_state_view(
    db: AsyncSession,
    novel_id: str,
    scene_id: str,
    *,
    viewpoint: dict[str, Any],
    include_dimensions: list[str] | None = None,
) -> SceneStateViewResponse:
    return await _service.get_view(
        db,
        novel_id=novel_id,
        scene_id=scene_id,
        viewpoint=viewpoint,
        include_dimensions=include_dimensions,
    )


async def list_scene_checkpoints(
    db: AsyncSession,
    novel_id: str,
    scene_id: str,
    *,
    dimension: str | None = None,
) -> list[dict[str, Any]]:
    """该 Scene 的 checkpoint 历史摘要（P2-A 历史回开的数据来源，只读）。

    - 按创建时间倒序（新版本在前），含已 supersede 的历史行——「历史版本
      可回开」经 ``get_record(checkpoint_id)`` 逐条取回。
    - 只读本作品（novel_id + scene_id 双过滤）；``dimension`` 可选收窄，
      非法维度名直接 422，不静默返回空表。
    - ``version`` 是同维度链上的时间序号（1 起，越大越新），由行序派生，
      非存储列；``chapter_index`` 取 Scene 章节锚（chapter_ids 最大值），
      无章节锚时为 None。
    - ``has_field_provenance`` 标记该行 state_json 是否内嵌
      ``_field_provenance``（旧格式行为 False，回开后 provenance 为空表）。
    """
    from shared.utils import parse_uuid

    if dimension is not None and dimension not in SCENE_MEMORY_DIMENSIONS:
        raise ValidationError(
            "unknown memory checkpoint dimension",
            code="invalid_dimension",
            status_code=422,
        )
    nid = parse_uuid(novel_id, "novel_id")
    sid = parse_uuid(scene_id, "scene_id")
    scene = _scene_payload(await get_scene_contract(db, novel_id, scene_id))
    chapters = _scene_chapters(scene)
    chapter_index = max(chapters) if chapters else None

    from modules.story.continuity.repositories import SceneCheckpointRepository

    rows = await SceneCheckpointRepository().list_history_for_scene(
        db, nid, sid, dimension=dimension
    )
    # 仓库层已按 created_at 倒序返回；取反得时间升序，为同维度链编号 version。
    version_counter: dict[str, int] = {}
    versions: dict[Any, int] = {}
    for row in reversed(rows):
        version_counter[row.dimension] = version_counter.get(row.dimension, 0) + 1
        versions[row.id] = version_counter[row.dimension]
    return [
        {
            "checkpoint_id": str(row.id),
            "dimension": row.dimension,
            "scene_index": int(row.scene_index),
            "chapter_index": chapter_index,
            "version": versions[row.id],
            "is_current": bool(row.is_current),
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "has_field_provenance": FIELD_PROVENANCE_STATE_KEY in (row.state_json or {}),
        }
        for row in rows
    ]
