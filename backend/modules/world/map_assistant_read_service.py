"""Owner-checked, read-only summary for the map cold-start guide."""

from uuid import UUID

from sqlalchemy import select

from modules.world.map_atlas_models import MapAtlasNode
from modules.world.map_auto_draft_models import MapAutoDraftBatchRecord
from modules.world.map_auto_draft_service import list_map_auto_drafts


async def read_map_cold_start_drafts(db, novel_id: str, run_key: str):
    page = await list_map_auto_drafts(db, novel_id, limit=200, offset=0)
    batches = list(
        (
            await db.scalars(
                select(MapAutoDraftBatchRecord).where(
                    MapAutoDraftBatchRecord.novel_id == UUID(str(novel_id)),
                    MapAutoDraftBatchRecord.run_id == run_key,
                )
            )
        ).all()
    )
    batch_ids = {item.id for item in batches}
    relevant = [item for item in page.items if item.batch_id in batch_ids]
    # The author reviews the full map workspace; never infer a completed map
    # solely from a guide button or an empty pending queue.
    nodes = list(
        (
            await db.scalars(
                select(MapAtlasNode).where(
                    MapAtlasNode.novel_id == UUID(str(novel_id)),
                    MapAtlasNode.status == "adopted",
                    MapAtlasNode.current_revision_id.is_not(None),
                )
            )
        ).all()
    )
    return {
        "run_key": run_key,
        "batches_ready": bool(batches)
        and all(item.status == "completed" for item in batches),
        "candidate_count": sum(item.status == "candidate" for item in relevant),
        "saved_node_count": len(nodes),
        "truncated": page.truncated or page.batches_truncated,
        "items": [
            {
                "node_id": str(item.node_id),
                "revision_id": str(item.revision_id),
                "title": item.node_title,
                "stale": item.stale,
                "spaces": [
                    {"id": space.id, "label": space.label}
                    for space in item.document.spaces
                ],
                "warnings": item.warnings,
                "tray_count": len(item.pending_tray),
            }
            for item in relevant
            if item.status == "candidate"
        ],
        "review_capability": "map.review_auto_draft_group",
        "batch_limit": 20,
        "location_adoption_page": "world",
        "cross_domain_atomic": False,
    }
