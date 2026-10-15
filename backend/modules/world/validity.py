"""Shared Scene/Chapter anchor validation for author-owned World intervals."""

from typing import Any

from core.container import get
from core.errors import ValidationError
from core.service_keys import STORY_SCENE_SOURCE
from modules.world.map_spatial_anchors import resolve_validity
from modules.world.schemas.dossier import DossierValidity


async def validate_scene_validity(
    db,
    novel_id: str,
    validity: Any | None,
) -> None:
    if validity is None:
        return
    scenes = await get(STORY_SCENE_SOURCE).read_temporal_anchor_scenes(db, str(novel_id))
    result = resolve_validity(validity, scenes)
    if not result.valid:
        raise ValidationError("生效范围的 Scene 或章节锚点无效，请核对后重试")


async def validate_changed_alias_intervals(
    db,
    novel_id: str,
    aliases: list,
) -> None:
    # A previously valid Scene anchor can disappear after an outline edit.
    # Recheck every retained interval whenever an alias payload is saved.
    for item in aliases:
        if not isinstance(item, dict) or item.get("validity") is None:
            continue
        validity = DossierValidity.model_validate(item["validity"])
        await validate_scene_validity(db, novel_id, validity)
