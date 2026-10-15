"""Load the explicitly enabled, Scene-bounded object reference dimensions."""

from __future__ import annotations

import uuid
from typing import Any

from core.config import get_settings
from modules.evidence.compilation.contracts import CompileOptions, StructureContextBundle
from modules.evidence.compilation.services.object_dossier_brief import (
    ObjectDossierBriefService,
)
from modules.evidence.compilation.services.protocol import Loader

_ACTION_CAPABILITIES = {
    "writing.generate": "writing.generate",
    "writing.targeted_revision": "writing.targeted_revision",
    "writing.semantic_review": "writing.semantic_review",
    "writing.conflict_check.ai_review": "writing.conflict_check.ai_review",
    "story.character_card.generate": "story.character_card",
    "story.reaction.generate": "story.reaction",
    "story.one_click.simulate": "story.one_click",
}


def object_dossier_capability(action: str | None) -> str | None:
    return _ACTION_CAPABILITIES.get(str(action or ""))


def enabled_object_reference_capabilities(settings: Any) -> tuple[set[str], set[str]]:
    """Return separately enabled dossier and pattern references; both default off."""
    dossier = getattr(settings, "object_dossier_enabled_capabilities", ()) or ()
    patterns = getattr(settings, "character_pattern_enabled_capabilities", ()) or ()
    return set(dossier), set(patterns)


def _entity_id(value: Any) -> str | None:
    text = str(value or "").strip()
    if ":" in text:
        text = text.rsplit(":", 1)[-1]
    try:
        return str(uuid.UUID(text))
    except (TypeError, ValueError, AttributeError):
        return None


def _item_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    dump = getattr(value, "model_dump", None)
    return dump(mode="json") if callable(dump) else {}


def _selected_entity_ids(
    options: CompileOptions, bundle: StructureContextBundle
) -> list[str]:
    selected: list[str] = []
    seen: set[str] = set()

    def add(value: Any) -> None:
        normalized = _entity_id(value)
        if normalized and normalized not in seen:
            seen.add(normalized)
            selected.append(normalized)

    for value in (
        options.focus_entity_id,
        options.viewpoint_character_id,
        *(options.entity_ids or []),
        *(options.character_ids or []),
        *(options.location_ids or []),
    ):
        add(value)
    for item in [*(bundle.characters or []), *(bundle.world_entities or [])]:
        payload = _item_dict(item)
        add(payload.get("character_id") or payload.get("entity_id") or payload.get("id"))
    scene = bundle.scene or {}
    add(scene.get("pov_character_id"))
    structure_meta = scene.get("structure_meta") or {}
    for key in (
        "related_character_ids",
        "present_character_ids",
        "character_ids",
        "related_entity_ids",
        "world_entity_ids",
        "item_ids",
        "related_location_ids",
    ):
        for value in structure_meta.get(key) or []:
            add(value)
    for key in ("location_id", "location_entity_id"):
        add(structure_meta.get(key) or scene.get(key))
    return selected


class ObjectDossierLoader(Loader):
    """Materialize optional object and pattern references after core loaders."""

    def __init__(self, service: ObjectDossierBriefService | None = None) -> None:
        self._service = service or ObjectDossierBriefService()

    @property
    def name(self) -> str:
        return "object_dossier"

    async def load(
        self,
        db,
        options: CompileOptions,
        bundle: StructureContextBundle,
    ) -> None:
        action = options.consumer_action
        capability = object_dossier_capability(action)
        if capability is None or not options.scene_id or options.reveal_mode == "reader":
            return

        settings = get_settings()
        dossier_capabilities, pattern_capabilities = (
            enabled_object_reference_capabilities(settings)
        )
        dossier_enabled = capability in dossier_capabilities
        patterns_enabled = capability in pattern_capabilities
        if not dossier_enabled and not patterns_enabled:
            return
        if options.reveal_mode == "character" and not options.viewpoint_character_id:
            bundle.warnings.append("角色对象参考缺少 POV 人物，已关闭可选资料")
            return

        entity_ids = _selected_entity_ids(options, bundle)
        if not entity_ids:
            return
        brief = await self._service.load(
            db,
            options,
            entity_ids=entity_ids,
            include_patterns=patterns_enabled,
        )
        if not dossier_enabled:
            brief = {
                **brief,
                "world_items": [],
                "continuity_items": [],
                "checkpoint_refs": [],
                "world_dossier_fingerprints": [],
                "world_fingerprint": None,
                "continuity_fingerprint": None,
            }
        if not patterns_enabled:
            brief = {
                **brief,
                "pattern_items": [],
                "pattern_fingerprint": None,
                "layers": [
                    layer for layer in brief.get("layers", []) if layer != "evolution"
                ],
            }
        bundle.object_dossier_brief = brief
        bundle.object_reference_dimensions = [
            *(["object_dossier"] if dossier_enabled else []),
            *(["character_pattern"] if patterns_enabled else []),
        ]
