"""Materialize explicitly selected copied director references for Writing only."""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy

from core.container import get
from modules.evidence.compilation.contracts import (
    EVIDENCE_READ_STORY_DIRECTOR_REFERENCES,
    CompileOptions,
    StructureContextBundle,
)
from modules.evidence.compilation.services.director_reference_config import (
    director_reference_char_limit,
    enabled_director_reference_capabilities,
)
from modules.evidence.compilation.services.protocol import Loader

_ALLOWED_ACTIONS = frozenset({"writing.generate", "writing.targeted_revision"})


def _character_projection(item: dict, viewpoint_character_id: str) -> dict | None:
    """Keep only self-performance and materials with a deterministic POV receipt."""
    source_copy = item.get("content_copy") or {}
    if source_copy.get("line"):
        if str(
            source_copy.get("target_ref") or ""
        ) != viewpoint_character_id or source_copy.get("candidate_only"):
            return None
        return {
            **item,
            "content_copy": {
                "line": source_copy["line"],
                "action": source_copy.get("action"),
                "target_ref": viewpoint_character_id,
            },
            "annotation": "",
        }
    materials = []
    for raw in source_copy.get("materials") or []:
        if not isinstance(raw, dict) or raw.get("candidate_only"):
            continue
        senses = set(raw.get("senses") or [])
        if "inner" in senses:
            visible = raw.get("internal_character_id") == viewpoint_character_id
        else:
            visible = raw.get(
                "perception_status"
            ) == "known" and viewpoint_character_id in set(raw.get("perceiver_ids") or [])
        source_kind = str(raw.get("source_kind") or "")
        if not visible or source_kind in {"candidate", "director_inference"}:
            continue
        materials.append(
            {
                key: deepcopy(raw.get(key))
                for key in (
                    "material_id",
                    "category",
                    "content",
                    "object_refs",
                    "senses",
                    "source_kind",
                    "source_ids",
                    "source_fingerprints",
                    "conflict_status",
                )
                if raw.get(key) is not None
            }
        )
    performances = [
        deepcopy(raw)
        for raw in source_copy.get("performances") or []
        if isinstance(raw, dict)
        and str(raw.get("character_id") or "") == viewpoint_character_id
    ]
    raw_angle = source_copy.get("angle") or {}
    angle = None
    if (
        raw_angle.get("viewpoint_kind") == "character"
        and str(raw_angle.get("viewpoint_character_id") or "") == viewpoint_character_id
    ):
        angle = {
            key: deepcopy(raw_angle.get(key))
            for key in (
                "label",
                "viewpoint_kind",
                "viewpoint_character_id",
                "narrative_distance",
                "focus",
                "detail_and_pacing",
                "material_ids",
            )
        }
        angle["material_ids"] = [
            item_id
            for item_id in angle.get("material_ids") or []
            if item_id in {item.get("material_id") for item in materials}
        ]
    if not materials and not performances:
        return None
    projected_copy = {
        "materials": materials,
        "performances": performances,
        "angle": angle,
    }
    return {
        **item,
        "content_copy": projected_copy,
        "annotation": "",
        "warnings": list(
            dict.fromkeys(
                [
                    *(item.get("warnings") or []),
                    "已按当前 POV 过滤为本人表演和可感知素材；导演批注未提供给角色视角。",
                    *(
                        ["原参考角度与当前 POV 不一致，未提供原角度。"]
                        if raw_angle and angle is None
                        else []
                    ),
                ]
            )
        ),
    }


class DirectorReferenceLoader(Loader):
    def __init__(self, reader: Callable | None = None) -> None:
        self._reader = reader

    @property
    def name(self) -> str:
        return "director_reference"

    async def load(
        self,
        db,
        options: CompileOptions,
        bundle: StructureContextBundle,
    ) -> None:
        action = str(options.consumer_action or "")
        reference_ids = list(options.director_reference_ids or [])
        if action not in _ALLOWED_ACTIONS or not reference_ids:
            return
        if options.reveal_mode == "reader":
            bundle.director_reference_brief = {
                "items": [],
                "omitted": reference_ids,
                "warnings": ["读者视角不使用作者保存的导演参考副本。"],
            }
            return
        if not options.scene_id:
            bundle.director_reference_brief = {
                "items": [],
                "omitted": reference_ids,
                "warnings": ["导演参考副本需要当前 Scene，已作为可选资料省略。"],
            }
            return
        if options.reveal_mode == "character" and not options.viewpoint_character_id:
            bundle.director_reference_brief = {
                "items": [],
                "omitted": reference_ids,
                "warnings": ["角色视角缺少 POV 人物，导演参考副本未提供。"],
            }
            return

        if action not in enabled_director_reference_capabilities():
            bundle.director_reference_brief = {
                "items": [],
                "omitted": reference_ids,
                "warnings": ["项目未启用导演参考维度；本次只记录提醒，不影响写作。"],
            }
            return

        reader = self._reader or get(EVIDENCE_READ_STORY_DIRECTOR_REFERENCES)
        raw = await reader(
            db,
            novel_id=options.novel_id,
            scene_id=options.scene_id,
            reference_ids=reference_ids,
            consumer_action=action,
            max_chars=director_reference_char_limit(options.budget_tokens),
        )
        data = raw.model_dump(mode="json")
        items = list(data.get("items") or [])
        omitted = list(data.get("omitted") or [])
        warnings = list(data.get("warnings") or [])
        if options.reveal_mode == "character":
            filtered = []
            viewpoint = str(options.viewpoint_character_id)
            for item in items:
                projected = _character_projection(item, viewpoint)
                if projected is None:
                    omitted.append(str(item.get("reference_id") or ""))
                    warnings.append(
                        "部分导演参考副本没有可供当前角色视角使用的材料，已作为可选资料省略。"
                    )
                    continue
                filtered.append(projected)
            items = filtered
        bundle.director_reference_brief = {
            "scene_id": options.scene_id,
            "items": items,
            "omitted": list(dict.fromkeys(value for value in omitted if value)),
            "warnings": list(dict.fromkeys(warnings)),
        }
        bundle.warnings.extend(bundle.director_reference_brief["warnings"])
