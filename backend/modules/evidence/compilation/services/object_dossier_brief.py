"""Evidence-owned three-layer object brief with fail-closed POV projection."""

from __future__ import annotations

from typing import Any

from infrastructure.stable_hash import stable_hash
from modules.evidence.compilation.contracts import (
    CompileOptions,
    EvolutionObjectPatternReadPort,
)

MAX_OBJECTS = 16
MAX_DOSSIER_ENTRIES = 48
MAX_CONTINUITY_FACTS = 48
MAX_CHARACTER_PATTERNS = 24


def _data(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    dump = getattr(value, "model_dump", None)
    return dump(mode="json") if callable(dump) else {}


def _hashable(value: Any) -> str:
    return stable_hash(value, stringify_unknown=True)


def _evidence_refs(items: list[Any]) -> list[dict[str, Any]]:
    refs = []
    for raw in items:
        item = _data(raw)
        refs.append(
            {
                key: item.get(key)
                for key in (
                    "scene_id",
                    "chapter_id",
                    "source_hash",
                    "start_offset",
                    "end_offset",
                )
                if item.get(key) is not None
            }
        )
    return refs


def _visible_facts(state_view: dict[str, Any]) -> list[dict[str, Any]]:
    facts = []
    for dimension in state_view.get("dimensions") or []:
        if not isinstance(dimension, dict) or dimension.get("status") != "ok":
            continue
        for raw in dimension.get("facts") or []:
            if not isinstance(raw, dict) or raw.get("layer") not in {"fact", "belief"}:
                continue
            facts.append({**raw, "dimension": dimension.get("dimension")})
    return facts


def _legacy_value_visible(
    *,
    entity_id: str,
    value: Any,
    facts: list[dict[str, Any]],
) -> bool:
    target_hash = _hashable(value)
    return any(
        str(fact.get("subject_id") or "") == entity_id
        and fact.get("layer") == "fact"
        and _hashable(fact.get("value")) == target_hash
        for fact in facts
    )


def _dossier_entry_visible(
    *,
    entity_id: str,
    entry: dict[str, Any],
    facts: list[dict[str, Any]],
) -> bool:
    content_hash = _hashable(entry.get("content"))
    return any(
        str(fact.get("subject_id") or "") == entity_id
        and fact.get("layer") == "fact"
        and _hashable(fact.get("value")) == content_hash
        for fact in facts
    )


def _pattern_refs_visible(refs: Any, content_mode: str) -> bool:
    if not isinstance(refs, list) or not refs:
        return False
    allowed_visibility = (
        {"canonical"} if content_mode == "canonical" else {"canonical", "working"}
    )
    for item in refs:
        if not isinstance(item, dict):
            return False
        source = item.get("source")
        if not isinstance(source, dict):
            return False
        if source.get("source_visibility") not in allowed_visibility:
            return False
        if not source.get("draft_id") or not source.get("content_hash"):
            return False
        start = source.get("start_offset")
        end = source.get("end_offset")
        if (
            isinstance(start, bool)
            or not isinstance(start, int)
            or isinstance(end, bool)
            or not isinstance(end, int)
            or start < 0
            or end <= start
        ):
            return False
        scene_index = item.get("scene_index")
        if (
            not item.get("scene_id")
            or isinstance(scene_index, bool)
            or not isinstance(scene_index, int)
        ):
            return False
    return True


class ObjectDossierBriefService:
    """Materialize stable facts, cutoff state and optional derived patterns."""

    def __init__(
        self,
        evolution_pattern_reader: EvolutionObjectPatternReadPort | None = None,
    ) -> None:
        self._evolution_pattern_reader = evolution_pattern_reader

    async def load(
        self,
        db,
        options: CompileOptions,
        *,
        entity_ids: list[str],
        include_patterns: bool,
        only_adopted_patterns: bool = False,
    ) -> dict[str, Any]:
        from modules.project.facade import require_active_project

        await require_active_project(db, options.novel_id)
        scene_id = options.scene_id
        if not scene_id:
            return self._empty(
                options,
                ["缺少 Scene 截止点，未读取对象时点或台账"],
                unknown_layers=["world", "continuity"],
            )

        novel_id = str(options.novel_id)
        scene_id = str(scene_id)
        role_view = options.reveal_mode == "character"
        reader_view = options.reveal_mode == "reader"
        if reader_view:
            return self._empty(options, ["读者视角不使用对象档案与台账参考"])

        viewpoint = (
            {"kind": "character", "target_id": str(options.viewpoint_character_id)}
            if role_view and options.viewpoint_character_id
            else {"kind": "author"}
        )
        if role_view and not options.viewpoint_character_id:
            return self._empty(options, ["角色视角缺少 POV 人物，已排除对象参考"])

        from modules.story.facade import get_scene_checkpoints, get_scene_state_view

        state_value = await get_scene_state_view(
            db,
            novel_id,
            scene_id,
            viewpoint=viewpoint,
        )
        state_view = _data(state_value)
        state_index = state_view.get("scene_index")
        if (
            str(state_view.get("scene_id") or "") != scene_id
            or isinstance(state_index, bool)
            or not isinstance(state_index, int)
            or str(state_view.get("novel_id") or "") != novel_id
            or not str(state_view.get("state_fingerprint") or "").strip()
        ):
            return self._empty(
                options,
                ["Story cutoff 无法核对，未读取档案或台账"],
                unknown_layers=["world", "continuity"],
            )
        scene_index = state_index
        if role_view and (
            str((state_view.get("viewpoint") or {}).get("kind") or "") != "character"
            or str((state_view.get("viewpoint") or {}).get("target_id") or "")
            != str(options.viewpoint_character_id)
        ):
            return self._empty(options, ["Story POV 与请求人物不匹配，已排除对象参考"])

        checkpoint_refs: list[dict[str, Any]] = []
        checkpoint_omissions: list[str] = []
        if not role_view:
            try:
                checkpoint_value = await get_scene_checkpoints(db, novel_id, scene_id)
                checkpoint_set = _data(checkpoint_value)
                if (
                    str(checkpoint_set.get("novel_id") or "") != novel_id
                    or str(checkpoint_set.get("scene_id") or "") != scene_id
                    or checkpoint_set.get("scene_index") != scene_index
                ):
                    checkpoint_omissions.append(
                        "Story checkpoint 身份或顺序与 cutoff 不一致"
                    )
                    checkpoint_set = {}
                checkpoint_refs = [
                    {
                        "checkpoint_id": str(item.get("id")),
                        "dimension": str(item.get("dimension")),
                        "source_hash": item.get("source_hash"),
                        "status": item.get("status"),
                        "stage_index": item.get("stage_index"),
                    }
                    for item in checkpoint_set.get("items") or []
                    if isinstance(item, dict)
                    and item.get("is_current")
                    and item.get("id")
                ]
            except (TypeError, ValueError):
                checkpoint_omissions.append("Story checkpoint 引用暂时无法读取")

        facts = _visible_facts(state_view)
        omissions = [*state_view.get("omissions", []), *checkpoint_omissions]
        unknown_layers = list(
            dict.fromkeys(
                "continuity"
                for dimension in state_view.get("dimensions") or []
                if isinstance(dimension, dict)
                and dimension.get("status") in {"missing", "degraded", "unsupported"}
            )
        )
        if checkpoint_omissions:
            unknown_layers.append("continuity")
        if any(
            isinstance(dimension, dict) and dimension.get("status") == "missing"
            for dimension in state_view.get("dimensions") or []
        ):
            omissions.append("部分 Story 维度没有可用时点事实")
        if role_view:
            degraded = [
                str(item.get("dimension"))
                for item in state_view.get("dimensions") or []
                if isinstance(item, dict) and item.get("status") == "degraded"
            ]
            if degraded:
                omissions.append("部分角色时点状态来源待复核")

        from modules.world.facade import read_world_object_dossier

        selected_ids = sorted({str(item) for item in entity_ids})[:MAX_OBJECTS]
        omitted_count = max(0, len(set(entity_ids)) - len(selected_ids))
        world_items: list[dict[str, Any]] = []
        dossier_fingerprints: list[dict[str, str]] = []
        unmapped_legacy_count = 0
        if omitted_count:
            omissions.append("部分关联对象未进入本次有界读取")
        for entity_id in selected_ids:
            dossier = _data(
                await read_world_object_dossier(
                    db,
                    novel_id,
                    entity_id,
                    as_of_scene_id=scene_id,
                    limit=250,
                    offset=0,
                )
            )
            if (
                str(dossier.get("entity_id") or "") != entity_id
                or str(dossier.get("as_of_scene_id") or "") != scene_id
            ):
                omitted_count += 1
                omissions.append("World 档案对象或截止点不匹配")
                continue
            dossier_fingerprint = str(dossier.get("dossier_fingerprint") or "").strip()
            if not dossier_fingerprint:
                omitted_count += 1
                unknown_layers.append("world")
                omissions.append("World 档案缺少稳定指纹，未使用该结果")
                continue
            dossier_omitted = max(
                int(dossier.get("omitted_count") or 0),
                max(
                    0,
                    int(dossier.get("total_count") or 0)
                    - len(dossier.get("entries") or []),
                ),
            )
            if dossier_omitted:
                if not role_view:
                    omitted_count += dossier_omitted
                    omissions.append("World 档案分页未覆盖全部当前条目")
            if dossier.get("unknown") is True and not role_view:
                unknown_layers.append("world")
            entity_item_start = len(world_items)
            for raw in dossier.get("entries") or []:
                if not isinstance(raw, dict):
                    continue
                if raw.get("effective_at_cutoff") is not True or raw.get(
                    "anchor_problem"
                ):
                    if not role_view:
                        omitted_count += 1
                        omissions.append("存在无效或待核对的档案锚点")
                    continue
                if role_view and raw.get("visibility") != "public":
                    continue
                if role_view and not _dossier_entry_visible(
                    entity_id=entity_id, entry=raw, facts=facts
                ):
                    continue
                source_refs = _evidence_refs(raw.get("evidence") or [])
                item = {
                    "kind": "world_dossier",
                    "entity_id": entity_id,
                    "entity_type": dossier.get("entity_type"),
                    "entry_id": str(raw.get("id") or ""),
                    "entry_group_id": str(raw.get("entry_group_id") or ""),
                    "revision_id": str(raw.get("id") or ""),
                    "revision_number": raw.get("revision_number"),
                    "facing": raw.get("facing"),
                    "facing_label": raw.get("facing_label"),
                    "legacy_field_key": raw.get("legacy_field_key"),
                    "content": str(raw.get("content") or ""),
                    "tags": list(raw.get("tags") or []),
                    "visibility": raw.get("visibility"),
                    "source": raw.get("source"),
                    "source_refs": source_refs,
                    "validity": raw.get("validity"),
                    "dossier_fingerprint": dossier.get("dossier_fingerprint"),
                }
                if role_view:
                    item = {
                        "kind": "world_dossier",
                        "entity_id": entity_id,
                        "entity_type": dossier.get("entity_type"),
                        "entry_id": str(raw.get("id") or ""),
                        "revision_id": str(raw.get("id") or ""),
                        "content": str(raw.get("content") or ""),
                        "visibility": "public",
                    }
                world_items.append(item)
            for raw in dossier.get("legacy_profile_fields") or []:
                if not isinstance(raw, dict):
                    continue
                if not raw.get("mapped") or not raw.get("facing"):
                    if not role_view:
                        unmapped_legacy_count += 1
                    continue
                if role_view and not _legacy_value_visible(
                    entity_id=entity_id,
                    value=raw.get("value"),
                    facts=facts,
                ):
                    continue
                item = {
                    "kind": "legacy_profile_field",
                    "entity_id": entity_id,
                    "entity_type": dossier.get("entity_type"),
                    "profile_id": str(raw.get("profile_id") or ""),
                    "template_id": str(raw.get("template_id") or ""),
                    "template_version_number": raw.get("template_version_number"),
                    "field_key": str(raw.get("field_key") or ""),
                    "facing": raw.get("facing"),
                    "facing_label": raw.get("label"),
                    "value": raw.get("value"),
                    "source_metadata": {
                        key: value
                        for key, value in (raw.get("source_metadata") or {}).items()
                        if key
                        in {
                            "profile_source",
                            "profile_confidence",
                            "template_revision_id",
                        }
                    },
                }
                if role_view:
                    item = {
                        "kind": "legacy_profile_field",
                        "entity_id": entity_id,
                        "entity_type": dossier.get("entity_type"),
                        "value": raw.get("value"),
                    }
                world_items.append(item)
            if role_view:
                safe_items = [
                    {
                        "kind": item.get("kind"),
                        "entity_id": item.get("entity_id"),
                        "entity_type": item.get("entity_type"),
                        "content": item.get("content"),
                        "value": item.get("value"),
                    }
                    for item in world_items[entity_item_start:]
                ]
                dossier_fingerprints.append(
                    {
                        "entity_id": entity_id,
                        "fingerprint": stable_hash(safe_items),
                    }
                )
            else:
                dossier_fingerprints.append(
                    {"entity_id": entity_id, "fingerprint": dossier_fingerprint}
                )

        world_items.sort(
            key=lambda item: (
                item["entity_id"],
                str(item.get("facing_label") or ""),
                str(item.get("entry_id") or item.get("field_key") or ""),
            )
        )
        if len(world_items) > MAX_DOSSIER_ENTRIES:
            if not role_view:
                omitted_count += len(world_items) - MAX_DOSSIER_ENTRIES
            world_items = world_items[:MAX_DOSSIER_ENTRIES]
            if not role_view:
                omissions.append("档案参考超过条数上限")
        if unmapped_legacy_count:
            omitted_count += unmapped_legacy_count
            unknown_layers.append("world")
            omissions.append(
                f"{unmapped_legacy_count} 个旧档案字段未绑定模板面向，"
                "保留在 World 原始档案"
            )

        continuity_items: list[dict[str, Any]] = []
        for dimension in state_view.get("dimensions") or []:
            if not isinstance(dimension, dict):
                continue
            status = str(dimension.get("status") or "unknown")
            if status != "ok":
                if status != "missing":
                    omissions.append(
                        f"{dimension.get('label') or dimension.get('dimension')}: "
                        f"{dimension.get('gap_reason') or status}"
                    )
                continue
            for raw in dimension.get("facts") or []:
                if not isinstance(raw, dict):
                    continue
                source = _data(raw.get("source"))
                checkpoint_id = str(source.get("checkpoint_id") or "")
                provenance = _data(source.get("provenance"))
                refs = [
                    {
                        key: value
                        for key, value in item.items()
                        if key
                        in {
                            "draft_id",
                            "chapter_index",
                            "version_number",
                            "content_mode",
                            "start_offset",
                            "end_offset",
                            "source_hash",
                            "range_hash",
                        }
                    }
                    for item in provenance.get("source_refs") or []
                    if isinstance(item, dict)
                ]
                fact = {
                    "kind": "story_state",
                    "entity_id": str(raw.get("subject_id") or ""),
                    "subject_label": raw.get("subject_label"),
                    "dimension": dimension.get("dimension"),
                    "field": raw.get("field"),
                    "value": raw.get("value"),
                    "layer": raw.get("layer"),
                    "possibly_false": bool(raw.get("possibly_false")),
                    "occurred_at": raw.get("occurred_at"),
                    "confidence": raw.get("confidence"),
                    "checkpoint_id": checkpoint_id,
                    "checkpoint_source_hash": next(
                        (
                            item.get("source_hash")
                            for item in checkpoint_refs
                            if item.get("checkpoint_id") == checkpoint_id
                        ),
                        None,
                    ),
                    "provenance": {
                        key: provenance[key]
                        for key in ("field", "event_id", "status", "object_type")
                        if key in provenance
                    }
                    or None,
                    "source_refs": refs,
                }
                if role_view and raw.get("layer") == "observation":
                    continue
                continuity_items.append(fact)
        if len(continuity_items) > MAX_CONTINUITY_FACTS:
            if not role_view:
                omitted_count += len(continuity_items) - MAX_CONTINUITY_FACTS
            continuity_items = continuity_items[:MAX_CONTINUITY_FACTS]
            if role_view:
                omissions.append("部分 Story 时点事实超过有界读取上限")
            else:
                omissions.append("Scene 时点事实超过条数上限")

        if role_view:
            omissions.append("角色视角只使用已有可见事实证明的对象资料")

        pattern_items: list[dict[str, Any]] = []
        pattern_fingerprint = None
        if include_patterns:
            if role_view:
                omissions.append(
                    "角色视角下未能逐条证明台账条件与来源可见，已排除人物倾向"
                )
                omitted_count += 1
            else:
                try:
                    provider = self._evolution_pattern_reader
                    if provider is None:
                        from core.container import get

                        provider = get("evidence.read_evolution_object_patterns")
                except KeyError:
                    omissions.append("Evolution 台账只读 DI 尚未接线，未回退读取其他数据")
                    omitted_count += 1
                    unknown_layers.append("evolution")
                else:
                    ledger = _data(
                        await provider(
                            db,
                            novel_id=novel_id,
                            scene_id=scene_id,
                            entity_ids=selected_ids,
                            only_adopted=only_adopted_patterns,
                        )
                    )
                    if (
                        str(ledger.get("novel_id") or "") != novel_id
                        or str(ledger.get("scene_id") or "") != scene_id
                        or ledger.get("scene_index") != scene_index
                    ):
                        omissions.append("Evolution 台账截止范围不匹配，未使用该结果")
                        omitted_count += 1
                    else:
                        pattern_fingerprint = str(ledger.get("ledger_fingerprint") or "")
                        omitted_count += int(ledger.get("omitted_count") or 0)
                        omissions.extend(
                            str(item) for item in ledger.get("omissions") or []
                        )
                        if ledger.get("coverage") == "unknown":
                            unknown_layers.append("evolution")
                        for raw in ledger.get("items") or []:
                            if (
                                not isinstance(raw, dict)
                                or raw.get("interpretation_only") is not True
                            ):
                                omitted_count += 1
                                continue
                            decision = str(raw.get("author_decision") or "")
                            if decision in {"reject", "unreviewed"}:
                                omitted_count += 1
                                continue
                            if (
                                raw.get("review_verdict") != "supported"
                                and decision not in {"keep", "corrected"}
                            ) or (
                                only_adopted_patterns
                                and decision not in {"keep", "corrected"}
                            ):
                                omitted_count += 1
                                continue
                            pattern_entity_ids = {
                                str(value) for value in raw.get("entity_ids") or []
                            }
                            if not pattern_entity_ids or not pattern_entity_ids.issubset(
                                set(selected_ids)
                            ):
                                omitted_count += 1
                                continue
                            refs = raw.get("evidence_refs") or []
                            if not _pattern_refs_visible(refs, options.content_mode):
                                omitted_count += 1
                                omissions.append("人物倾向与本次正文来源范围不一致")
                                continue
                            pattern_items.append(
                                {
                                    key: raw.get(key)
                                    for key in (
                                        "entry_id",
                                        "revision_id",
                                        "revision",
                                        "entity_ids",
                                        "category",
                                        "statement",
                                        "conditions",
                                        "modality",
                                        "confidence",
                                        "competing_explanations",
                                        "review_verdict",
                                        "author_decision",
                                        "evidence_refs",
                                        "interpretation_only",
                                    )
                                }
                            )
        if include_patterns and not role_view and not pattern_fingerprint:
            if "evolution" not in unknown_layers:
                omitted_count += 1
                omissions.append("Evolution 台账缺少稳定指纹，未使用该结果")
            unknown_layers.append("evolution")
            pattern_items = []
            pattern_fingerprint = None
        if len(pattern_items) > MAX_CHARACTER_PATTERNS:
            omitted_count += len(pattern_items) - MAX_CHARACTER_PATTERNS
            pattern_items = pattern_items[:MAX_CHARACTER_PATTERNS]
            omissions.append("人物倾向参考超过条数上限")

        checkpoint_fingerprint = str(state_view.get("state_fingerprint") or "")
        world_fingerprint = stable_hash(dossier_fingerprints)
        continuity_fingerprint = stable_hash(
            {"state": checkpoint_fingerprint, "checkpoints": checkpoint_refs}
        )
        fingerprint = stable_hash(
            {
                "novel_id": novel_id,
                "scene_id": scene_id,
                "scene_index": scene_index,
                "viewpoint": state_view.get("viewpoint"),
                "world": world_fingerprint,
                "continuity": continuity_fingerprint,
                "patterns": pattern_fingerprint,
                "world_items": world_items,
                "continuity_items": continuity_items,
                "pattern_items": pattern_items,
            }
        )
        return {
            "novel_id": novel_id,
            "scene_id": scene_id,
            "scene_index": scene_index,
            "viewpoint": state_view.get("viewpoint"),
            "world_items": world_items,
            "continuity_items": continuity_items,
            "pattern_items": pattern_items,
            "checkpoint_refs": checkpoint_refs,
            "checkpoint_fingerprint": checkpoint_fingerprint,
            "world_dossier_fingerprints": dossier_fingerprints,
            "world_fingerprint": world_fingerprint,
            "continuity_fingerprint": continuity_fingerprint,
            "pattern_fingerprint": pattern_fingerprint,
            "omitted_count": omitted_count,
            "omissions": list(dict.fromkeys(str(item) for item in omissions if item)),
            "layers": [
                "world",
                "continuity",
                *(["evolution"] if pattern_fingerprint else []),
            ],
            "unknown_layers": list(dict.fromkeys(unknown_layers)),
            "coverage": (
                "unknown"
                if unknown_layers
                else "partial"
                if omitted_count
                else "complete"
            ),
            "fingerprint": fingerprint,
        }

    @staticmethod
    def _empty(
        options: CompileOptions,
        omissions: list[str],
        *,
        unknown_layers: list[str] | None = None,
    ) -> dict[str, Any]:
        return {
            "novel_id": options.novel_id,
            "scene_id": options.scene_id,
            "scene_index": None,
            "viewpoint": {"kind": options.reveal_mode},
            "world_items": [],
            "continuity_items": [],
            "pattern_items": [],
            "checkpoint_refs": [],
            "checkpoint_fingerprint": None,
            "world_dossier_fingerprints": [],
            "world_fingerprint": None,
            "continuity_fingerprint": None,
            "pattern_fingerprint": None,
            "omitted_count": len(omissions),
            "omissions": omissions,
            "layers": [],
            "unknown_layers": list(unknown_layers or []),
            "coverage": "unknown" if unknown_layers else "partial",
            "fingerprint": stable_hash([options.novel_id, options.scene_id, omissions]),
        }
