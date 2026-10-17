"""Pure projections for optional World/Story/Evolution object references."""

from __future__ import annotations

import json
from typing import Any

from infrastructure.llm.token_estimation import estimate_token_count
from infrastructure.stable_hash import stable_hash
from modules.evidence.compilation.contracts import (
    CompileOptions,
    StructureContextBundle,
)
from modules.evidence.compilation.services.compiled_context import (
    ContextItem,
    ContextSection,
    Tier,
)


class ObjectDossierSectionBuilder:
    @classmethod
    def restrict_brief(cls, brief: dict, compiled) -> dict:
        """Intersect a POV brief with complete items in the final confirmed context."""
        selected = {
            (section.key, item.key, item.content, stable_hash(item.source))
            for section in compiled.sections
            for item in section.materialize_items().items
            if item.selection_state not in {"excluded", "omitted"}
        }
        fields = {
            "world_items": (
                "entity_id",
                "entity_type",
                "kind",
                "entry_id",
                "revision_id",
                "profile_id",
                "template_id",
                "field_key",
                "facing",
                "facing_label",
                "content",
                "value",
            ),
            "continuity_items": (
                "entity_id",
                "dimension",
                "field",
                "layer",
                "value",
                "checkpoint_id",
                "checkpoint_source_hash",
                "possibly_false",
            ),
            "pattern_items": ("entry_id", "revision_id", "statement", "modality"),
        }
        result = {"scene_id": brief.get("scene_id"), "coverage": "confirmed_scope"}
        for group, keys in fields.items():
            result[group] = []
            for row in brief.get(group) or []:
                candidate = {"scene_id": brief.get("scene_id"), group: [row]}
                sections = cls.build(
                    StructureContextBundle(
                        novel_id="",
                        task="",
                        scope="full",
                        object_dossier_brief=candidate,
                        object_reference_dimensions=[
                            "object_dossier",
                            "character_pattern",
                        ],
                    ),
                    None,
                )
                if not any(
                    (section.key, item.key, item.content, stable_hash(item.source))
                    in selected
                    for section in sections
                    for item in section.items
                    if item.key
                    not in {"object_dossier:coverage", "character_pattern:coverage"}
                ):
                    continue
                projected = {key: row[key] for key in keys if key in row}
                if group == "world_items" and row.get("content") is not None:
                    projected.pop("value", None)
                if group == "continuity_items":
                    provenance = row.get("provenance") or {}
                    projected["provenance"] = {
                        key: provenance[key]
                        for key in ("status", "field")
                        if key in provenance
                    }
                result[group].append(projected)
        result["fingerprint"] = stable_hash(result)
        result["omitted_count"] = sum(
            len(brief.get(group) or []) - len(result[group]) for group in fields
        )
        result["omissions"] = (
            ["未获本次资料确认的档案条目已排除"] if result["omitted_count"] else []
        )
        return result

    @staticmethod
    def _reference_text(value: Any) -> str:
        if isinstance(value, str):
            return value.strip()
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)

    @classmethod
    def build(
        cls,
        bundle: StructureContextBundle,
        options: CompileOptions | None,
    ) -> list[ContextSection]:
        brief = bundle.object_dossier_brief or {}
        enabled = set(bundle.object_reference_dimensions)
        if not brief or not enabled or (options and options.reveal_mode == "reader"):
            return []

        scene_id = str(
            brief.get("scene_id") or (options.scene_id if options else "") or ""
        )
        role_view = bool(options and options.reveal_mode == "character")
        fact_basis: list[dict[str, Any]] = []
        world_items: list[dict[str, Any]] = []
        for raw in brief.get("world_items") or []:
            if not isinstance(raw, dict):
                continue
            entity_id = str(raw.get("entity_id") or "")
            kind = str(raw.get("kind") or "")
            value = (
                raw.get("content") if raw.get("content") is not None else raw.get("value")
            )
            value_text = cls._reference_text(value)
            if not (entity_id and value_text):
                continue
            entry_id = str(raw.get("entry_id") or "") or None
            profile_id = str(raw.get("profile_id") or "") or None
            field_key = str(raw.get("field_key") or "") or None
            if kind == "legacy_profile_field" and not (profile_id and field_key):
                # The character-safe projection intentionally strips an unmapped legacy
                # source identity. Do not manufacture provenance for that value.
                continue
            ref_hash = stable_hash(
                {
                    key: raw.get(key)
                    for key in ("entity_id", "kind", "content", "value", "facing")
                }
            )
            fact_id = (
                f"world:{entry_id}"
                if entry_id
                else f"world:{entity_id}:legacy:{profile_id}:{field_key}"
                if profile_id and field_key
                else f"world:{entity_id}:{ref_hash[:24]}"
            )
            fact = {
                "fact_id": fact_id,
                "kind": kind,
                "layer": "fact",
                "subject_id": entity_id,
                "dimension": str(
                    raw.get("facing") or raw.get("facing_label") or "world_dossier"
                ),
                "field": field_key or str(raw.get("facing") or "entry"),
                "value": value_text,
                "source_refs": [
                    ref
                    for ref in (
                        {"entry_id": entry_id, "revision_id": raw.get("revision_id")}
                        if entry_id
                        else {
                            "profile_id": profile_id,
                            "template_id": raw.get("template_id"),
                            "field_key": field_key,
                        },
                    )
                    if ref
                ],
                "entry_id": entry_id,
                "revision_id": str(raw.get("revision_id") or "") or None,
                "as_of_scene_id": scene_id or None,
                "possibly_false": False,
            }
            fact_basis.append(fact)
            world_items.append({"fact": fact, "raw": raw})

        continuity_items: list[dict[str, Any]] = []
        for raw in brief.get("continuity_items") or []:
            if not isinstance(raw, dict):
                continue
            entity_id = str(raw.get("entity_id") or "")
            value_text = cls._reference_text(raw.get("value"))
            layer = str(raw.get("layer") or "")
            if not (
                entity_id and value_text and layer in {"fact", "belief", "observation"}
            ):
                continue
            dimension = str(raw.get("dimension") or "unknown")
            field_name = str(raw.get("field") or "unknown")
            checkpoint_id = str(raw.get("checkpoint_id") or "") or None
            fact_id = (
                "story:"
                + stable_hash(
                    [
                        scene_id,
                        entity_id,
                        dimension,
                        field_name,
                        value_text,
                        checkpoint_id,
                    ]
                )[:32]
            )
            fact = {
                "fact_id": fact_id,
                "kind": "story_state",
                "layer": layer,
                "subject_id": entity_id,
                "dimension": dimension,
                "field": field_name,
                "value": value_text,
                "source_refs": list(raw.get("source_refs") or []),
                "checkpoint_id": checkpoint_id,
                "checkpoint_source_hash": raw.get("checkpoint_source_hash"),
                "as_of_scene_id": scene_id or None,
                "possibly_false": bool(raw.get("possibly_false")),
            }
            fact_basis.append(fact)
            continuity_items.append({"fact": fact, "raw": raw})

        pattern_basis: list[dict[str, Any]] = []
        if "character_pattern" in enabled and not role_view:
            for raw in brief.get("pattern_items") or []:
                if not isinstance(raw, dict):
                    continue
                entry_id = str(raw.get("entry_id") or "")
                revision_id = str(raw.get("revision_id") or "")
                statement = str(raw.get("statement") or "").strip()
                if not (entry_id and revision_id and statement):
                    continue
                pattern_basis.append(
                    {
                        "pattern_id": f"pattern:{entry_id}:{revision_id}",
                        "statement": statement,
                        "modality": str(raw.get("modality") or "interpretation_only"),
                        "evidence_refs": list(raw.get("evidence_refs") or []),
                    }
                )

        sections: list[ContextSection] = []
        object_items: list[ContextItem] = []
        if "object_dossier" in enabled:
            for data in world_items:
                fact = data["fact"]
                raw = data["raw"]
                content = f"- [{fact['dimension']}] {fact['value']}"
                source = {
                    "type": "world_dossier_entry",
                    "id": str(fact.get("entry_id") or fact["fact_id"]),
                    "label": str(
                        raw.get("facing_label") or raw.get("facing") or "对象档案"
                    ),
                    "status": "adopted",
                    "revision_id": fact.get("revision_id"),
                    "fact_id": fact["fact_id"],
                }
                object_items.append(
                    ContextItem(
                        key=fact["fact_id"],
                        content=content,
                        token_count=estimate_token_count(content),
                        title=source["label"],
                        preview=content[:160],
                        status="adopted",
                        activation_reason="Scene 截止范围内的稳定对象档案参考",
                        source=source,
                        can_exclude=True,
                    )
                )
            for data in continuity_items:
                fact = data["fact"]
                content = f"- [{fact['dimension']}/{fact['layer']}] {fact['value']}"
                source = {
                    "type": "story_state_fact",
                    "id": fact["fact_id"],
                    "label": f"Story {fact['dimension']}（{fact['layer']}）",
                    "status": "scene_cutoff",
                    "checkpoint_id": fact.get("checkpoint_id"),
                    "checkpoint_source_hash": fact.get("checkpoint_source_hash"),
                    "fact_id": fact["fact_id"],
                }
                object_items.append(
                    ContextItem(
                        key=fact["fact_id"],
                        content=content,
                        token_count=estimate_token_count(content),
                        title=source["label"],
                        preview=content[:160],
                        status="scene_cutoff",
                        activation_reason="Story Scene 截止点的四维时态状态",
                        source=source,
                        can_exclude=True,
                    )
                )
            if object_items:
                content = "\n".join(item.content for item in object_items)
            else:
                omissions = brief.get("omissions") or [
                    "没有可用的对象档案或 Scene 状态事实"
                ]
                content = "对象档案参考未提供可用条目：" + "；".join(
                    map(str, omissions[:8])
                )
                object_items.append(
                    ContextItem(
                        key="object_dossier:coverage",
                        content=content,
                        token_count=estimate_token_count(content),
                        title="对象档案覆盖",
                        preview=content[:160],
                        status=str(brief.get("coverage") or "unknown"),
                        activation_reason="显式标明来源缺失或覆盖范围",
                        source={
                            "type": "object_dossier_brief",
                            "id": scene_id,
                            "status": brief.get("coverage"),
                        },
                        can_exclude=True,
                    )
                )
            source_refs = [item.source for item in object_items]
            section_dimensions = ["object_dossier"]
            if any(
                item.source.get("type") == "story_state_fact" for item in object_items
            ):
                section_dimensions.append("scene_state")
            sections.append(
                ContextSection(
                    key="object_dossier",
                    tier=Tier.P3,
                    content=content,
                    token_count=estimate_token_count(content),
                    truncatable_per_item=True,
                    max_items=48,
                    title="对象档案与 Scene 截止事实",
                    preview=content[:160],
                    status=str(brief.get("coverage") or "partial"),
                    activation_reason=(
                        "可选稳定对象事实与 Scene 截止状态；非时点字段仅作作者备注"
                    ),
                    sources=source_refs,
                    can_exclude=True,
                    retrieval_metadata={
                        "novel_id": brief.get("novel_id"),
                        "scene_id": scene_id,
                        "scene_index": brief.get("scene_index"),
                        "checkpoint_refs": list(brief.get("checkpoint_refs") or []),
                        "checkpoint_fingerprint": brief.get("checkpoint_fingerprint"),
                        "world_fingerprint": brief.get("world_fingerprint"),
                        "continuity_fingerprint": brief.get("continuity_fingerprint"),
                        "fact_basis": fact_basis if "object_dossier" in enabled else [],
                        "pattern_basis": [],
                        "reference_dimensions": section_dimensions,
                        "coverage": brief.get("coverage"),
                        "omitted_count": int(brief.get("omitted_count") or 0),
                        "omissions": list(brief.get("omissions") or []),
                    },
                    items=object_items,
                )
            )

        if "character_pattern" in enabled:
            pattern_items: list[ContextItem] = []
            for pattern in pattern_basis:
                content = (
                    f"- [解释性倾向；不是事实；{pattern['modality']}] "
                    f"{pattern['statement']}"
                )
                pattern_items.append(
                    ContextItem(
                        key=pattern["pattern_id"],
                        content=content,
                        token_count=estimate_token_count(content),
                        title="人物倾向解释",
                        preview=content[:160],
                        status="interpretation_only",
                        activation_reason="Evolution 作者审阅的解释性模式与来源坐标",
                        source={
                            "type": "character_pattern",
                            "id": pattern["pattern_id"],
                            "status": "interpretation_only",
                        },
                        can_exclude=True,
                    )
                )
            if pattern_items:
                content = "\n".join(item.content for item in pattern_items)
            elif role_view:
                content = "角色视角无法逐条证明台账条件与来源可见，人物倾向解释已排除。"
            else:
                messages = brief.get("omissions") or ["没有可用的已审阅倾向解释"]
                content = "人物倾向参考不可用：" + "；".join(map(str, messages[:8]))
                pattern_items.append(
                    ContextItem(
                        key="character_pattern:coverage",
                        content=content,
                        token_count=estimate_token_count(content),
                        title="人物倾向覆盖",
                        preview=content[:160],
                        status="unknown",
                        activation_reason="未把未知或未验证台账当作事实",
                        source={
                            "type": "character_pattern",
                            "id": scene_id,
                            "status": "unknown",
                        },
                        can_exclude=True,
                    )
                )
            sections.append(
                ContextSection(
                    key="character_pattern",
                    tier=Tier.P3,
                    content=content,
                    token_count=estimate_token_count(content),
                    truncatable_per_item=True,
                    max_items=24,
                    title="人物倾向（解释，不是事实）",
                    preview=content[:160],
                    status="interpretation_only" if pattern_basis else "unknown",
                    activation_reason="可选参考；不得转成确定事实或世界档案",
                    sources=[item.source for item in pattern_items],
                    can_exclude=True,
                    retrieval_metadata={
                        "scene_id": scene_id,
                        "scene_index": brief.get("scene_index"),
                        "pattern_fingerprint": brief.get("pattern_fingerprint"),
                        "pattern_basis": pattern_basis,
                        "reference_dimensions": ["character_pattern"],
                        "coverage": brief.get("coverage"),
                        "omitted_count": int(brief.get("omitted_count") or 0),
                        "omissions": list(brief.get("omissions") or []),
                    },
                    items=pattern_items,
                )
            )
        return sections
