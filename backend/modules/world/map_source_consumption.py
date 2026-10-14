"""Bounded read-only consumption of canonical prose by saved current maps."""

from __future__ import annotations

from pydantic import ValidationError
from sqlalchemy import and_, select

from modules.project.facade import require_active_project
from modules.world.map_atlas_models import MapAtlasNode, MapAtlasRevision
from modules.world.map_structure_schemas import MapDocument
from modules.writing.facade import get_historical_source_identities
from shared.utils import parse_uuid

MAP_CONSUMPTION_LIMIT = 200
MAP_SOURCE_LIMIT = 1000


async def read_map_chapter_consumers(
    db,
    novel_id: str,
    *,
    chapter_index: int,
    current_draft_id: str | None,
    current_source_hash: str | None,
) -> dict:
    """Revalidate historical source identity, then compare with current canonical."""
    await require_active_project(db, novel_id, allow_demo_readonly=False)
    nid = parse_uuid(novel_id, "novel_id")
    rows = (
        await db.execute(
            select(MapAtlasNode, MapAtlasRevision)
            .join(
                MapAtlasRevision,
                and_(
                    MapAtlasRevision.id == MapAtlasNode.current_revision_id,
                    MapAtlasRevision.node_id == MapAtlasNode.id,
                    MapAtlasRevision.novel_id == MapAtlasNode.novel_id,
                ),
            )
            .where(
                MapAtlasNode.novel_id == nid,
                MapAtlasRevision.novel_id == nid,
                MapAtlasRevision.status == "saved",
            )
            .order_by(MapAtlasNode.sort_order, MapAtlasNode.id)
            .limit(MAP_CONSUMPTION_LIMIT + 1)
        )
    ).all()
    truncated = len(rows) > MAP_CONSUMPTION_LIMIT
    unverified = 0
    references = []
    source_count = 0
    for node, revision in rows[:MAP_CONSUMPTION_LIMIT]:
        try:
            document = MapDocument.model_validate(revision.document)
        except ValidationError:
            unverified += 1
            continue
        for item in [*document.features, *document.constraints]:
            for source in item.sources:
                if source.kind != "source_range":
                    continue
                source_count += 1
                if source_count > MAP_SOURCE_LIMIT:
                    truncated = True
                    break
                references.append((node, revision, source))
            if source_count > MAP_SOURCE_LIMIT:
                break
        if source_count > MAP_SOURCE_LIMIT:
            break
    drafts = {
        draft["id"]: draft
        for draft in await get_historical_source_identities(
            db, novel_id, sorted({str(source.id) for _, _, source in references})
        )
    }
    affected = {}
    for node, revision, source in references:
        draft = drafts.get(str(source.id))
        ref = source.source_ref
        if (
            draft is None
            or draft["chapter_index"] != ref["chapter_index"]
            or draft["version_number"] != ref["version_number"]
            or draft["content_hash"] != source.source_hash
            or (
                draft["status"] != "published"
                and draft["deprecated_from_status"] != "published"
            )
        ):
            unverified += 1
            continue
        if draft["chapter_index"] != chapter_index:
            continue
        if (
            draft["id"] == current_draft_id
            and draft["content_hash"] == current_source_hash
        ):
            continue
        affected[str(node.id)] = {
            "node_id": str(node.id),
            "revision_id": str(revision.id),
            "title": node.title,
            "chapter_index": chapter_index,
        }
    return {
        "maps": list(affected.values()),
        "truncated": truncated,
        "unverified_sources": unverified,
        "checked": True,
        "coverage": "当前已保存地图的正史正文来源；对象、世界书页与待审候选未覆盖",
    }
