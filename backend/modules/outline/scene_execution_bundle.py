"""Deterministically compile the outline-owned input for a Scene execution."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import NotFoundError
from modules.outline.contracts import (
    SceneExecutionBundleContract,
    SceneExecutionSceneContract,
)
from modules.outline.services import SceneService
from modules.outline.story_outline_schemas import StoryOutlineProvenance
from modules.outline.story_outline_service import StoryOutlineService

_META_FIELDS = (
    "knowledge_boundary",
    "entry_state",
    "exit_state",
    "outcome",
    "cost",
    "continuity",
    "new_fact_candidates",
)


async def get_scene_execution_bundle(
    db: AsyncSession,
    novel_id: str,
    scene_id: str,
) -> SceneExecutionBundleContract | None:
    """Return one novel-scoped bundle, or ``None`` when the Scene is absent."""
    try:
        scene = await SceneService().get(db, scene_id, novel_id=novel_id)
    except NotFoundError:
        return None

    meta = scene.structure_meta or {}
    execution_scene = SceneExecutionSceneContract(
        id=str(scene.id),
        scene_index=scene.scene_index,
        title=scene.title,
        goal=scene.goal,
        core_conflict=scene.core_conflict,
        emotional_beat=scene.emotional_beat,
        pov_character_id=scene.pov_character_id,
        must_happen=scene.must_happen,
        must_not_happen=scene.must_not_happen,
        **{name: meta.get(name) for name in _META_FIELDS},
    )
    missing_fields = _missing_fields(execution_scene)
    current = await StoryOutlineService().get_current(db, novel_id)
    if current.revision is None:
        payload = {
            "novel_id": novel_id,
            "scene": execution_scene,
            "missing_fields": missing_fields,
            "omissions": ["current_story_outline"],
            "upstream_manifest": [],
        }
        return SceneExecutionBundleContract(
            novel_id=novel_id,
            scene_id=str(scene.id),
            story_outline_revision_id=None,
            story_outline_version=None,
            story_outline_content_hash=None,
            story_execution_profile=None,
            story_execution_profile_hash=None,
            scene=execution_scene,
            missing_fields=missing_fields,
            omissions=["current_story_outline"],
            contract_hash=_hash(payload),
        )

    revision = current.revision
    provenance = StoryOutlineProvenance.model_validate(revision.provenance)
    profile = provenance.story_execution_profile
    profile_hash = provenance.story_execution_profile_hash
    omissions: list[str] = []
    if profile is None or profile_hash is None:
        omissions.append("story_execution_profile")
    manifest = [
        {
            "type": "story_outline_revision",
            "id": str(revision.id),
            "version": str(revision.version_number),
            "hash": revision.content_hash,
        }
    ]
    if profile_hash is not None:
        manifest.append(
            {
                "type": "story_execution_profile.v1",
                "id": str(revision.id),
                "version": "story_execution_profile.v1",
                "hash": profile_hash,
            }
        )
    payload = {
        "novel_id": novel_id,
        "story_outline_revision_id": str(revision.id),
        "story_outline_version": revision.version_number,
        "story_outline_content_hash": revision.content_hash,
        "story_execution_profile": profile.model_dump(mode="json") if profile else None,
        "story_execution_profile_hash": profile_hash,
        "scene": execution_scene,
        "missing_fields": missing_fields,
        "omissions": omissions,
        "upstream_manifest": manifest,
    }
    return SceneExecutionBundleContract(
        **payload,
        scene_id=str(scene.id),
        contract_hash=_hash(payload),
    )


def _missing_fields(scene: SceneExecutionSceneContract) -> list[str]:
    values = {
        "title": scene.title,
        "goal": scene.goal,
        "pov_character_id": scene.pov_character_id,
        "knowledge_boundary": scene.knowledge_boundary,
        "entry_state": scene.entry_state,
        "exit_state": scene.exit_state,
        "outcome": scene.outcome,
        "cost": scene.cost,
        "continuity": scene.continuity,
        "new_fact_candidates": scene.new_fact_candidates,
        "must_happen": scene.must_happen,
        "must_not_happen": scene.must_not_happen,
    }
    return [name for name, value in values.items() if _missing(value)]


def _missing(value: Any) -> bool:
    return value is None or isinstance(value, str) and not value.strip()


def _hash(payload: dict[str, Any]) -> str:
    def serialize(value: Any) -> Any:
        if hasattr(value, "__dataclass_fields__"):
            return {
                key: serialize(getattr(value, key))
                for key in value.__dataclass_fields__
            }
        if isinstance(value, list):
            return [serialize(item) for item in value]
        if isinstance(value, dict):
            return {key: serialize(item) for key, item in value.items()}
        return value

    raw = json.dumps(
        serialize(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(raw.encode()).hexdigest()
