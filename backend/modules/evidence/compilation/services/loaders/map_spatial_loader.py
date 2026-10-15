"""Load a bounded adopted-map brief as an advisory context source."""

from __future__ import annotations

from core.config import get_settings
from core.container import get
from core.service_keys import WORLD_READ_MAP_SPATIAL_BRIEF
from modules.evidence.compilation.contracts import CompileOptions, StructureContextBundle
from modules.evidence.compilation.services.protocol import Loader

_ACTION_CAPABILITIES = {
    "writing.generate": "writing.generate",
    "writing.targeted_revision": "writing.targeted_revision",
    "writing.semantic_review": "writing.semantic_review",
    "writing.conflict_check.ai_review": "writing.conflict_check.ai_review",
    "story.script.generate": "story.script",
    "story.one_click.simulate": "story.one_click",
    "world.ask": "world.ask",
}


def map_spatial_capability(action: str | None) -> str | None:
    return _ACTION_CAPABILITIES.get(str(action or ""))


class MapSpatialLoader(Loader):
    @property
    def name(self) -> str:
        return "map_spatial"

    async def load(
        self,
        db,
        options: CompileOptions,
        bundle: StructureContextBundle,
    ) -> None:
        action = options.map_spatial_consumer_action or options.consumer_action
        capability = map_spatial_capability(action)
        enabled = get_settings().map_spatial_enabled_capabilities
        if capability is None or capability not in enabled:
            return
        if not options.scene_id and action != "world.ask":
            return

        excluded_id_kinds = {
            "map_spatial": "map_spatial",
            "map_spatial_nodes": "map_spatial_node",
            "world_entities": "world_entity",
            "world_bible_pages": "world_bible_page",
            "writing_drafts": "writing_draft",
            "project_vocabulary_terms": "project_vocabulary",
        }
        excluded_ids = list(
            dict.fromkeys(
                value if ":" in value else f"{excluded_id_kinds.get(kind, kind)}:{value}"
                for kind, values in options.excluded_asset_ids.items()
                for value in (str(item) for item in values)
            )
        )
        for ref in options.excluded_refs:
            target = ref.get("target_ref") or {}
            if target.get("target_type") and target.get("target_id"):
                excluded_ids.append(f"{target['target_type']}:{target['target_id']}")
            source = ref.get("source_ref") or {}
            if source.get("draft_id"):
                excluded_ids.append(f"writing_draft:{source['draft_id']}")
        excluded_ids = list(dict.fromkeys(excluded_ids))
        # Never silently drop an exclusion to fit the facade's request limit.
        if len(excluded_ids) > 200:
            return
        result = await get(WORLD_READ_MAP_SPATIAL_BRIEF)(
            db,
            {
                "novel_id": options.novel_id,
                "scene_id": options.scene_id,
                "chapter_index": options.visible_until_chapter or options.chapter_index,
                "reveal_mode": (
                    options.reveal_mode
                    if options.reveal_mode in {"reader", "character"}
                    else "author_safe"
                ),
                "viewpoint_character_id": options.viewpoint_character_id,
                "query_text": (options.task if action == "world.ask" else ""),
                "excluded_ids": excluded_ids,
            },
        )
        if result.items:
            bundle.map_spatial_brief = result.model_dump(mode="json")
