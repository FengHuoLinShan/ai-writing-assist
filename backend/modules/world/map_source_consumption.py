"""Bounded read-only consumption of canonical prose by saved current maps."""

from __future__ import annotations

from pydantic import ValidationError
from sqlalchemy import and_, select

from modules.project.facade import require_active_project
from modules.world.map_atlas_models import MapAtlasNode, MapAtlasRevision
from modules.world.map_auto_draft_models import MapAutoDraftBatchRecord
from modules.world.map_spatial_clue_models import MapSpatialClueRecord
from modules.world.map_spatial_clue_schemas import MapSpatialClueSourceBinding
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
    content_mode: str = "canonical",
) -> dict:
    """Revalidate historical source identity, then compare with current canonical."""
    if content_mode not in {"canonical", "working"}:
        raise ValueError("content_mode must be canonical or working")
    await require_active_project(db, novel_id, allow_demo_readonly=False)
    nid = parse_uuid(novel_id, "novel_id")
    rows = []
    if content_mode == "canonical":
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

    (
        auto_drafts,
        auto_draft_unverified,
        auto_draft_truncated,
    ) = await _read_auto_draft_chapter_consumers(
        db,
        novel_id,
        chapter_index=chapter_index,
        current_draft_id=current_draft_id,
        current_source_hash=current_source_hash,
        content_mode=content_mode,
    )
    return {
        "maps": list(affected.values()),
        "auto_drafts": auto_drafts,
        "auto_draft_unverified": auto_draft_unverified,
        "auto_draft_truncated": auto_draft_truncated,
        "truncated": truncated,
        "unverified_sources": unverified,
        "checked": True,
        "coverage": (
            "当前已保存地图和待审空间草图的canonical正文来源"
            if content_mode == "canonical"
            else "仅核对待审空间草图的working正文来源；已保存地图不参与working变化核对"
        ),
    }


async def _read_auto_draft_chapter_consumers(
    db,
    novel_id: str,
    *,
    chapter_index: int,
    current_draft_id: str | None,
    current_source_hash: str | None,
    content_mode: str,
) -> tuple[list[dict], int, bool]:
    nid = parse_uuid(novel_id, "novel_id")
    batches = (
        await db.scalars(
            select(MapAutoDraftBatchRecord)
            .where(MapAutoDraftBatchRecord.novel_id == nid)
            .order_by(
                MapAutoDraftBatchRecord.created_at.desc(), MapAutoDraftBatchRecord.id
            )
            .limit(MAP_CONSUMPTION_LIMIT + 1)
        )
    ).all()
    truncated = len(batches) > MAP_CONSUMPTION_LIMIT
    refs: list[tuple[MapAutoDraftBatchRecord, dict, list[str]]] = []
    for batch in batches[:MAP_CONSUMPTION_LIMIT]:
        tray_clues_by_node: dict[str, set[str]] = {}
        for item in batch.tray_items or []:
            tray_clues_by_node.setdefault(str(item.get("node_id")), set()).add(
                str(item.get("clue_id"))
            )
        for ref in batch.result_refs or []:
            if ref.get("status") != "candidate":
                continue
            node_id = str(ref.get("node_id") or "")
            clue_ids = {
                str(item) for item in ref.get("source_clue_ids", [])
            } | tray_clues_by_node.get(node_id, set())
            refs.append((batch, ref, sorted(clue_ids)))
            if len(refs) > MAP_CONSUMPTION_LIMIT:
                truncated = True
                break
        if len(refs) > MAP_CONSUMPTION_LIMIT:
            break
    refs = refs[:MAP_CONSUMPTION_LIMIT]
    if not refs:
        return [], 0, truncated

    unverified = 0
    revision_ids = set()
    for _batch, ref, _clue_ids in refs:
        try:
            revision_ids.add(parse_uuid(ref.get("revision_id"), "revision_id"))
        except (ValueError, TypeError):
            unverified += 1
    joined = (
        await db.execute(
            select(MapAtlasNode, MapAtlasRevision)
            .join(
                MapAtlasRevision,
                and_(
                    MapAtlasRevision.novel_id == MapAtlasNode.novel_id,
                    MapAtlasRevision.node_id == MapAtlasNode.id,
                ),
            )
            .where(
                MapAtlasNode.novel_id == nid,
                MapAtlasRevision.novel_id == nid,
                MapAtlasRevision.id.in_(revision_ids),
                MapAtlasRevision.status == "candidate",
            )
        )
    ).all()
    node_revision = {str(revision.id): (node, revision) for node, revision in joined}
    requested_clue_ids = set()
    for _batch, _ref, clue_ids in refs:
        for clue_id in clue_ids:
            try:
                requested_clue_ids.add(parse_uuid(clue_id, "clue_id"))
            except (ValueError, TypeError):
                unverified += 1
                continue
    source_omissions = 0
    if len(requested_clue_ids) > MAP_SOURCE_LIMIT:
        truncated = True
        source_omissions = len(requested_clue_ids) - MAP_SOURCE_LIMIT
        requested_clue_ids = set(sorted(requested_clue_ids, key=str)[:MAP_SOURCE_LIMIT])
    clue_rows = (
        await db.scalars(
            select(MapSpatialClueRecord).where(
                MapSpatialClueRecord.novel_id == nid,
                MapSpatialClueRecord.id.in_(requested_clue_ids),
            )
        )
    ).all()
    clues_by_id = {str(row.id): row for row in clue_rows}
    source_draft_ids = set()
    binding_by_clue: dict[str, MapSpatialClueSourceBinding] = {}
    unverified += source_omissions
    for clue_id, row in clues_by_id.items():
        try:
            binding = MapSpatialClueSourceBinding.model_validate(row.source_binding)
        except (ValidationError, ValueError, TypeError):
            unverified += 1
            continue
        if row.source_content_mode != binding.content_mode:
            unverified += 1
            continue
        binding_by_clue[clue_id] = binding
        if row.status not in {"pending_review", "adopted"}:
            unverified += 1
        if binding.content_mode != content_mode:
            continue
        source_draft_ids.update(
            item.draft_id
            for item in binding.ranges()
            if item.chapter_index == chapter_index
        )
    drafts = {
        item["id"]: item
        for item in await get_historical_source_identities(
            db, novel_id, sorted(source_draft_ids)
        )
    }

    affected: dict[tuple[str, str, int], dict] = {}
    missing_clues = requested_clue_ids - {
        parse_uuid(item, "clue_id") for item in clues_by_id
    }
    unverified += len(missing_clues)
    for batch, ref, clue_ids in refs:
        revision_id = str(ref.get("revision_id") or "")
        target = node_revision.get(revision_id)
        if target is None:
            unverified += 1
            continue
        node, revision = target
        expected_marker = f"auto-draft:{batch.id}:"
        if not (revision.context_fingerprint or "").startswith(expected_marker):
            unverified += 1
            continue
        affected_chapter = False
        for clue_id in clue_ids:
            row = clues_by_id.get(clue_id)
            binding = binding_by_clue.get(clue_id)
            if row is None or binding is None:
                continue
            if (
                row.source_content_mode != content_mode
                or binding.content_mode != content_mode
            ):
                continue
            for source in binding.ranges():
                if source.chapter_index != chapter_index:
                    continue
                draft = drafts.get(source.draft_id)
                if (
                    draft is None
                    or draft["chapter_index"] != source.chapter_index
                    or draft["content_hash"] != source.content_hash
                    or (
                        content_mode == "canonical"
                        and draft["status"] != "published"
                        and draft["deprecated_from_status"] != "published"
                    )
                ):
                    unverified += 1
                    continue
                if (
                    draft["id"] == current_draft_id
                    and draft["content_hash"] == current_source_hash
                ):
                    continue
                affected_chapter = True
        if affected_chapter:
            key = (str(node.id), str(revision.id), chapter_index)
            affected[key] = {
                "node_id": str(node.id),
                "revision_id": str(revision.id),
                "title": node.title,
                "chapter_index": chapter_index,
                "status": "candidate",
                "kind": "auto_draft",
            }
    return list(affected.values()), unverified, truncated
