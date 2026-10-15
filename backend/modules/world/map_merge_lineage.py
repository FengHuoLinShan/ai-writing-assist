"""Keep confirmed map exclusions across merges and historical restores."""

from uuid import UUID

from sqlalchemy import String, cast, func, or_, select

from modules.world.map_atlas_models import MapAtlasRevision

EXCLUDED_MERGE_UNKNOWN = "部分地图曾合入已排除的资料，已省略；请重新核对参考范围。"


async def excluded_merge_targets(
    db, novel_id, node_ids, *, excluded_nodes, excluded_revisions
) -> set[str]:
    if not node_ids or not (excluded_nodes or excluded_revisions):
        return set()
    # History survives undo/restore and a restored target becoming another source.
    # Without per-item lineage, omit descendant targets even after later edits.
    summary = MapAtlasRevision.change_summary
    merges = (
        select(
            MapAtlasRevision.node_id,
            summary["source_node_id"].as_string().label("source_node_id"),
            summary["source_revision_id"].as_string().label("source_revision_id"),
        )
        .where(
            MapAtlasRevision.novel_id == UUID(str(novel_id)),
            summary["operation"].as_string() == "map_node_merge",
        )
        .cte("map_merges")
    )
    lineage = (
        select(merges.c.node_id)
        .where(
            or_(
                merges.c.source_node_id.in_(excluded_nodes),
                merges.c.source_revision_id.in_(excluded_revisions),
            ),
        )
        .cte("excluded_map_merge_lineage", recursive=True)
    )
    # Normalize UUID text for SQLite's hex storage and PostgreSQL's dashed UUIDs.
    # UNION, rather than UNION ALL, terminates historical merge cycles after undo.
    lineage = lineage.union(
        select(merges.c.node_id).join(
            lineage,
            func.replace(merges.c.source_node_id, "-", "")
            == func.replace(cast(lineage.c.node_id, String), "-", ""),
        )
    )
    rows = await db.scalars(
        select(lineage.c.node_id).where(lineage.c.node_id.in_(node_ids))
    )
    return {str(node_id) for node_id in rows}
