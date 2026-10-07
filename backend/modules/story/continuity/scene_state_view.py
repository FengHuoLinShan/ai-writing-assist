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
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from core.container import get
from core.errors import NotFoundError, ValidationError
from core.service_keys import WORLD_GET_CHARACTER_ID_BY_WORLD_ENTITY
from infrastructure.stable_hash import stable_hash
from modules.story.continuity.basis import basis_hash, compute_scene_basis
from modules.story.continuity.contracts import SCENE_MEMORY_DIMENSIONS
from modules.story.continuity.field_provenance import (
    FIELD_PROVENANCE_STATE_KEY,
    FieldProvenance,
    read_field_provenance,
    resolve_field_status,
)
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
    return summaries


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
        current_basis_hash = basis_hash(
            await compute_scene_basis(
                db,
                novel_id,
                scenes,
                up_to_scene_index=int(checkpoint_set.scene_index),
            )
        )

        knowledge_grants = (
            self._knowledge_grants(items.get("knowledge"), target_id)
            if kind == "character"
            else {}
        )
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
            )
            if kind == "reader"
            else {}
        )

        dimensions: list[SceneStateDimensionView] = []
        omissions: list[str] = []
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
            visible, suppressed = self._filter_entries(
                dimension,
                entries,
                kind=kind,
                target_id=target_id,
                knowledge_grants=knowledge_grants,
                reveal_cache=reveal_cache,
            )
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
        return SceneStateViewResponse(
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
                # 位置 fact 是整份 payload 的聚合条目；逐字段来源挂主锚字段
                # location_id（entity_ref），仅当事件只写描述时退 text_state。
                # 查询键带实体锚，多角色位置互不串链。
                location_provenance = next(
                    (
                        provenance_by_field[(key, str(entity_id))]
                        for key in ("location_id", "text_state")
                        if (key, str(entity_id)) in provenance_by_field
                    ),
                    None,
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
                # moon_phase 是 timeline 维度唯一登记的受控母题字段（无实体
                # 容器，subject_ref=None）；只有该 fact 本身携带月相值时才
                # 挂链，普通时间事实不冒充。
                moon_provenance = (
                    provenance_by_field.get(("moon_phase", None))
                    if payload.get("moon_phase") is not None
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
    ) -> dict[str, dict[str, set[str]]]:
        """角色的知识绑定到字段值，旧知识不能放行未目击的后来变化。

        - 带 false/false_belief 标记的误信条目不授予（误信不是知识）。
        - 授予需要显式 ``fields`` 与 ``known_values``；缺失则仅为 belief
          （A03：丙知道 holder 不等于知道 owner）。
        """
        grants: dict[str, dict[str, set[str]]] = {}
        if checkpoint is None:
            return grants
        state = checkpoint.state_json or {}
        for payload in state.get("character_knowledge") or []:
            if not isinstance(payload, dict):
                continue
            holder = payload.get("character_id") or payload.get("holder_id")
            if str(holder or "") != target_id:
                continue
            if any(bool(payload.get(marker)) for marker in _FALSE_MARKERS):
                continue
            subject = payload.get("subject_id") or payload.get("subject")
            fields = payload.get("fields")
            values = payload.get("known_values")
            if (
                not subject
                or not isinstance(fields, list)
                or not isinstance(values, dict)
            ):
                continue
            for field in fields:
                if isinstance(field, str) and field in values:
                    grants.setdefault(str(subject), {}).setdefault(field, set()).add(
                        stable_hash(values[field])
                    )
        return grants

    def _filter_entries(
        self,
        dimension: str,
        entries: list[SceneStateFactEntry],
        *,
        kind: str,
        target_id: str | None,
        knowledge_grants: dict[str, dict[str, set[str]]],
        reveal_cache: dict[str, bool],
    ) -> tuple[list[SceneStateFactEntry], int]:
        if kind == "author":
            return entries, 0

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
            if entry.subject_id:
                return reveal_cache.get(entry.subject_id, False)
            return False

        visible = [entry for entry in entries if keep(entry)]
        return visible, len(entries) - len(visible)

    async def _reveal_cache(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        cutoff_chapter: int | None,
        subjects: set[str],
    ) -> dict[str, bool]:
        if cutoff_chapter is None:
            # 无章节锚点时保守：全部按未揭示处理，不猜测揭示位置。
            return {subject: False for subject in subjects}
        cache: dict[str, bool] = {}
        for subject in sorted(subjects):
            decision = await get_reader_reveal_decision(
                db,
                novel_id=novel_id,
                target_type="entity",
                target_id=subject,
                cutoff_chapter=cutoff_chapter,
            )
            cache[subject] = bool(decision and getattr(decision, "revealed", False))
        return cache


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
