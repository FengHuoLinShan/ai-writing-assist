"""Read only the current, source-bound map signals named by a change event."""

from uuid import UUID

from sqlalchemy import select

from core.container import get
from core.errors import ConflictError, NotFoundError, ValidationError
from core.service_keys import SOURCE_CHANGED, STORY_SCENE_SOURCE
from infrastructure.stable_hash import stable_hash
from modules.project.facade import require_active_project
from modules.world.map_atlas_models import MapAtlasNode, MapAtlasRevision
from modules.world.map_auto_draft_models import MapAutoDraftBatchRecord
from modules.world.map_auto_draft_service import _marker_batch_id
from modules.world.map_spatial_advisory_service import MapSpatialAdvisoryService
from modules.world.map_spatial_clue_models import MapSpatialClueRecord
from modules.world.map_spatial_clue_schemas import (
    MapSpatialClue,
    MapSpatialClueSourceBinding,
)
from modules.world.map_spatial_clue_service import (
    _SPATIAL_KINDS,
    _evidence_is_current,
    _revalidate_stored_clue,
    _type_references,
)
from modules.world.project_vocabulary_models import (
    ProjectVocabularyRevision,
    ProjectVocabularyTerm,
)
from modules.world.project_vocabulary_schemas import VocabularyEvidence


async def mark_map_changed(db, novel_id, asset_type, asset_id, *, scene_ids=()):
    await get(SOURCE_CHANGED)(
        db,
        str(novel_id),
        asset_type,
        str(asset_id),
        related_scene_ids=list(scene_ids)[:20],
    )


async def read_map_notification_signals(db, novel_id, request):
    await require_active_project(db, novel_id)
    nid = UUID(str(novel_id))
    asset_type, asset_id = request["asset_type"], str(request["asset_id"])
    excluded_ids = request.get("excluded_ids") or []
    if len(excluded_ids) > 200:
        return None
    excluded = {part for value in excluded_ids for part in str(value).split(":")}
    if asset_id in excluded:
        return None
    counts = {"tray": 0, "types": 0, "pending": 0, "spatial": 0}
    baseline = []
    scenes = set(str(value) for value in request.get("scene_ids", [])[:20])
    if asset_type == "map_auto_draft_batch":
        batch = await db.scalar(
            select(MapAutoDraftBatchRecord).where(
                MapAutoDraftBatchRecord.novel_id == nid,
                MapAutoDraftBatchRecord.id == UUID(asset_id),
            )
        )
        if batch is None or batch.status != "completed":
            return None
        valid_clues = set()
        clue_ids = {
            value
            for ref in (batch.result_refs or [])[:20]
            for value in ref.get("source_clue_ids", [])[:20]
        } | {item["clue_id"] for item in (batch.tray_items or [])[:20]}
        for clue_id in sorted(clue_ids)[:20]:
            row = await db.scalar(
                select(MapSpatialClueRecord).where(
                    MapSpatialClueRecord.novel_id == nid,
                    MapSpatialClueRecord.id == UUID(str(clue_id)),
                )
            )
            if row is None or row.status not in {"pending_review", "adopted"}:
                continue
            clue = MapSpatialClue.model_validate(row.clue_payload)
            binding = MapSpatialClueSourceBinding.model_validate(row.source_binding)
            identities = (
                {str(row.id), str(row.scene_id)}
                | {
                    str(endpoint.entity_id)
                    for endpoint in (clue.subject, clue.target)
                    if endpoint is not None and endpoint.entity_id is not None
                }
                | {
                    str(source.draft_id)
                    for source in [binding, *binding.additional_sources]
                }
            )
            if binding.content_mode != "canonical" or identities & excluded:
                continue
            try:
                endpoints = await _revalidate_stored_clue(
                    db,
                    novel_id,
                    row,
                    clue,
                    allow_identity_transitions=True,
                    allow_author_confirmed_transitions=True,
                )
            except (ConflictError, NotFoundError, ValidationError):
                continue
            if any(str(item.id) in excluded for item in endpoints.values()) or any(
                str(ref) in excluded or str(revision) in excluded
                for ref, revision, _kind in _type_references(clue)
            ):
                continue
            valid_clues.add(str(row.id))
            baseline.append(
                [
                    str(row.id),
                    row.clue_payload,
                    row.source_binding,
                    [
                        [
                            str(item.id),
                            item.status,
                            item.name,
                            item.summary,
                            item.content_json,
                        ]
                        for item in endpoints.values()
                    ],
                ]
            )
        candidate_nodes = set()
        for ref in (batch.result_refs or [])[:20]:
            if {str(ref.get("node_id")), str(ref.get("revision_id"))} & excluded:
                continue
            revision = await db.scalar(
                select(MapAtlasRevision)
                .join(
                    MapAtlasNode,
                    (MapAtlasNode.id == MapAtlasRevision.node_id)
                    & (MapAtlasNode.novel_id == MapAtlasRevision.novel_id),
                )
                .where(
                    MapAtlasNode.merged_into_node_id.is_(None),
                    MapAtlasRevision.novel_id == nid,
                    MapAtlasRevision.id == UUID(ref["revision_id"]),
                    MapAtlasRevision.node_id == UUID(ref["node_id"]),
                    MapAtlasRevision.status == "candidate",
                )
            )
            if revision is not None and valid_clues.intersection(
                ref.get("source_clue_ids", [])
            ):
                counts["pending"] += 1
                candidate_nodes.add(str(revision.node_id))
                baseline.append([str(revision.id), revision.document])
        counts["tray"] = sum(
            str(item.get("clue_id")) in valid_clues
            and str(item.get("node_id")) in candidate_nodes
            and not item.get("placed_feature_id")
            for item in (batch.tray_items or [])[:20]
        )
        baseline.append([batch.input_fingerprint, batch.cursor, batch.tray_items])
    elif asset_type == "project_vocabulary_term":
        row = (
            await db.execute(
                select(ProjectVocabularyTerm, ProjectVocabularyRevision)
                .join(
                    ProjectVocabularyRevision,
                    ProjectVocabularyRevision.id
                    == ProjectVocabularyTerm.current_revision_id,
                )
                .where(
                    ProjectVocabularyTerm.novel_id == nid,
                    ProjectVocabularyTerm.id == UUID(asset_id),
                    ProjectVocabularyRevision.novel_id == nid,
                    ProjectVocabularyRevision.term_id == ProjectVocabularyTerm.id,
                )
            )
        ).one_or_none()
        if row is None:
            return None
        term, revision = row
        if (
            str(revision.id) in excluded
            or term.kind not in _SPATIAL_KINDS
            or term.source != "model"
            or term.status not in {"emerging", "active"}
            or term.author_confirmed
        ):
            return None
        evidence = [
            VocabularyEvidence.model_validate(item)
            for item in revision.snapshot_json.get("evidence", [])[:20]
        ]
        if not evidence or any(str(item.scene_id) in excluded for item in evidence):
            return None
        for item in evidence:
            spans = await get(STORY_SCENE_SOURCE).get_scene_spans_for_scene(
                db,
                novel_id,
                str(item.scene_id),
                status_filter=["draft", "canonical"],
                content_mode="canonical",
            )
            if any(str(span.source_draft_id) in excluded for span in spans):
                return None
        if not all(
            [
                await _evidence_is_current(db, novel_id, item, content_mode="canonical")
                for item in evidence
            ]
        ):
            return None
        counts["types"] = 1
        baseline.append([str(revision.id), revision.content_hash])
    elif asset_type == "map_atlas_node":
        node = await db.scalar(
            select(MapAtlasNode).where(
                MapAtlasNode.novel_id == nid, MapAtlasNode.id == UUID(asset_id)
            )
        )
        if (
            node is None
            or node.status != "adopted"
            or node.merged_into_node_id is not None
            or str(node.current_revision_id) in excluded
        ):
            return None
        original = await db.scalar(
            select(MapAtlasRevision)
            .where(
                MapAtlasRevision.novel_id == nid,
                MapAtlasRevision.node_id == node.id,
                MapAtlasRevision.context_fingerprint.like("auto-draft:%"),
            )
            .order_by(MapAtlasRevision.created_at.desc())
            .limit(1)
        )
        if original is not None and str(original.id) not in excluded:
            batch_id = _marker_batch_id(original.context_fingerprint)
            batch = await db.scalar(
                select(MapAutoDraftBatchRecord).where(
                    MapAutoDraftBatchRecord.novel_id == nid,
                    MapAutoDraftBatchRecord.id == batch_id,
                )
            )
            if batch is not None:
                scenes.add(str(batch.through_scene_id))
    elif asset_type == "outline_scene":
        scenes.add(asset_id)
    else:
        return None
    for scene_id in sorted(scenes - excluded)[:20]:
        result = await MapSpatialAdvisoryService().read(
            db,
            {
                "novel_id": str(novel_id),
                "scene_id": scene_id,
                "reveal_mode": "author_safe",
                "excluded_ids": excluded_ids,
            },
        )
        items = [
            item
            for item in result.items
            if asset_type != "map_atlas_node" or item.node_id == asset_id
        ]
        counts["spatial"] += len(items)
        baseline.extend(item.model_dump(mode="json") for item in items)
    if not any(counts.values()):
        return None
    return {"counts": counts, "fingerprint": stable_hash(baseline), "page": "map"}
