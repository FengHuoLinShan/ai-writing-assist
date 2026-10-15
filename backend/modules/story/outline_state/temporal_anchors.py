"""Current ordering and replacement identities for source-bound validity anchors."""

from sqlalchemy import select

from modules.story.outline_state.models import Scene
from shared.utils import parse_uuid


async def read_temporal_anchor_scenes(db, novel_id: str) -> list[dict]:
    rows = await db.execute(
        select(
            Scene.id,
            Scene.scene_index,
            Scene.status,
            Scene.chapter_ids,
            Scene.structure_meta,
        )
        .where(Scene.novel_id == parse_uuid(novel_id, "novel_id"))
        .order_by(Scene.scene_index, Scene.id)
    )
    # Retired rows retain the replacement chain; consumers decide anchor validity.
    return [
        {
            "scene_id": str(identity),
            "scene_index": index,
            "status": status,
            "chapter_ids": [str(value) for value in chapters or []],
            "replaced_by_scene_ids": list(
                (metadata or {}).get("replaced_by_scene_ids", [])
            ),
        }
        for identity, index, status, chapters, metadata in rows
    ]
