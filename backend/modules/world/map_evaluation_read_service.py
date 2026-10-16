"""Owner-scoped immutable map evidence, without building or adopting anything."""

from copy import deepcopy
from uuid import UUID

from sqlalchemy import or_, select

from core.errors import ValidationError
from infrastructure.stable_hash import stable_hash
from modules.project.facade import require_active_project
from modules.world.map_atlas_models import MapAtlasNode, MapAtlasRevision
from modules.world.map_auto_draft_models import MapAutoDraftBatchRecord
from modules.world.map_auto_draft_service import list_map_auto_drafts
from modules.world.map_spatial_clue_models import MapSpatialClueRecord
from modules.world.map_spatial_clue_service import list_spatial_clues
from modules.world.project_vocabulary_models import (
    ProjectVocabularyRevision,
    ProjectVocabularyTerm,
)

MAX_EVALUATION_VOCABULARY_REVISIONS = 2_000


def _revision(row):
    return {
        "id": str(row.id),
        "node_id": str(row.node_id),
        "status": row.status,
        "base_revision_id": str(row.base_revision_id) if row.base_revision_id else None,
        "document": deepcopy(row.document),
        "document_hash": stable_hash(row.document),
        "geometry_hash": row.geometry_hash,
        "context_fingerprint": row.context_fingerprint,
        "confirmation_id": str(row.confirmation_id) if row.confirmation_id else None,
        "change_summary": deepcopy(row.change_summary),
    }


async def read_map_spatial_evaluation_artifacts(db, novel_id, run_id, scene_ids):
    scenes = list(dict.fromkeys(str(UUID(str(value))) for value in scene_ids))
    if not scenes or len(scenes) > 200 or not run_id or len(str(run_id)) > 120:
        raise ValidationError("评测须指定实际运行和 1–200 个场景")
    nid = UUID(str(novel_id))
    with db.no_autoflush:
        await require_active_project(db, novel_id)
        clues = []
        for scene in scenes:
            offset = 0
            while True:
                page = await list_spatial_clues(
                    db,
                    novel_id,
                    scene_id=scene,
                    run_id=str(run_id),
                    limit=200,
                    offset=offset,
                )
                clues.extend(page.items)
                offset += len(page.items)
                if offset >= page.total_count or not page.items:
                    break
        clue_ids = {item.id for item in clues}
        rows = (
            (
                await db.scalars(
                    select(MapSpatialClueRecord).where(
                        MapSpatialClueRecord.novel_id == nid,
                        MapSpatialClueRecord.id.in_(clue_ids),
                    )
                )
            ).all()
            if clue_ids
            else []
        )
        batches = (
            await db.scalars(
                select(MapAutoDraftBatchRecord)
                .where(
                    MapAutoDraftBatchRecord.novel_id == nid,
                    MapAutoDraftBatchRecord.run_id == str(run_id),
                )
                .order_by(MapAutoDraftBatchRecord.created_at, MapAutoDraftBatchRecord.id)
            )
        ).all()
        selected_clues = {str(value) for value in clue_ids}
        batches = [
            batch
            for batch in batches
            if batch.through_scene_id in scenes
            or any(
                selected_clues.intersection(ref.get("source_clue_ids", []))
                for ref in batch.result_refs or []
            )
            or any(
                str(item.get("clue_id")) in selected_clues
                for item in batch.tray_items or []
            )
        ]
        drafts, revisions, nodes, missing = [], {}, {}, []
        for batch in batches:
            for ref in batch.result_refs or []:
                if (
                    batch.through_scene_id not in scenes
                    and not selected_clues.intersection(ref.get("source_clue_ids", []))
                ):
                    continue
                row = await db.scalar(
                    select(MapAtlasRevision).where(
                        MapAtlasRevision.novel_id == nid,
                        MapAtlasRevision.id == UUID(ref["revision_id"]),
                        MapAtlasRevision.node_id == UUID(ref["node_id"]),
                    )
                )
                if row is None:
                    missing.append(
                        {"type": "map_atlas_revision", "id": ref["revision_id"]}
                    )
                    continue
                revisions[str(row.id)] = _revision(row)
                page = await list_map_auto_drafts(
                    db, novel_id, revision_id=str(row.id), limit=1
                )
                drafts.extend(item.model_dump(mode="json") for item in page.items)
                node = await db.scalar(
                    select(MapAtlasNode).where(
                        MapAtlasNode.novel_id == nid, MapAtlasNode.id == row.node_id
                    )
                )
                head = (
                    await db.scalar(
                        select(MapAtlasRevision).where(
                            MapAtlasRevision.novel_id == nid,
                            MapAtlasRevision.node_id == row.node_id,
                            MapAtlasRevision.id == node.current_revision_id,
                        )
                    )
                    if node and node.current_revision_id
                    else None
                )
                nodes[str(row.node_id)] = {
                    "id": str(row.node_id),
                    "status": "merged"
                    if node and node.merged_into_node_id
                    else node.status
                    if node
                    else None,
                    "merged_into_node_id": str(node.merged_into_node_id)
                    if node and node.merged_into_node_id
                    else None,
                    "official": bool(
                        node
                        and node.status == "adopted"
                        and node.merged_into_node_id is None
                    ),
                    "merge_metadata": deepcopy(node.merge_metadata) if node else None,
                    "current_revision_id": str(node.current_revision_id)
                    if node and node.current_revision_id
                    else None,
                    "head": _revision(head) if head else None,
                }
        # Vocabulary lineage is limited to terms with evidence in requested Scenes,
        # including archived/merged identities and author revisions of those terms.
        evidence = ProjectVocabularyRevision.snapshot_json["evidence"].as_string()
        relevant_terms = select(ProjectVocabularyRevision.term_id).where(
            ProjectVocabularyRevision.novel_id == nid,
            or_(*(evidence.contains(scene) for scene in scenes)),
        )
        vocabulary_rows = (
            await db.execute(
                select(ProjectVocabularyTerm, ProjectVocabularyRevision)
                .join(
                    ProjectVocabularyRevision,
                    (ProjectVocabularyRevision.term_id == ProjectVocabularyTerm.id)
                    & (
                        ProjectVocabularyRevision.novel_id
                        == ProjectVocabularyTerm.novel_id
                    ),
                )
                .where(
                    ProjectVocabularyTerm.novel_id == nid,
                    ProjectVocabularyTerm.id.in_(relevant_terms),
                )
                .order_by(
                    ProjectVocabularyTerm.id, ProjectVocabularyRevision.revision_number
                )
                .limit(MAX_EVALUATION_VOCABULARY_REVISIONS + 1)
            )
        ).all()
        vocabulary_truncated = len(vocabulary_rows) > MAX_EVALUATION_VOCABULARY_REVISIONS
        vocabulary_rows = vocabulary_rows[:MAX_EVALUATION_VOCABULARY_REVISIONS]
        if vocabulary_truncated:
            missing.append({"type": "vocabulary_history", "reason": "revision_limit"})
        terms = {
            term.id
            for term, revision in vocabulary_rows
            if any(
                str(item.get("scene_id")) in scenes
                for item in revision.snapshot_json.get("evidence", [])
            )
        }
        return {
            "schema_version": 1,
            "novel_id": str(nid),
            "run_id": str(run_id),
            "scene_ids": scenes,
            "clues": [
                {
                    "id": str(row.id),
                    "run_id": row.run_id,
                    "attempt_id": row.attempt_id,
                    "scene_id": row.scene_id,
                    "scene_index": row.scene_index,
                    "source_manifest_hash": row.source_manifest_hash,
                    "method_fingerprint": row.method_fingerprint,
                    "source_content_mode": row.source_content_mode,
                    "source_binding": deepcopy(row.source_binding),
                    "clue_payload": deepcopy(row.clue_payload),
                    "fingerprint": row.fingerprint,
                    "status": row.status,
                    "decision_action": row.decision_action,
                    "decided_at": row.decided_at.isoformat() if row.decided_at else None,
                    "merged_into_id": str(row.merged_into_id)
                    if row.merged_into_id
                    else None,
                }
                for row in rows
            ],
            "batches": [
                {
                    "id": str(batch.id),
                    "run_id": batch.run_id,
                    "status": batch.status,
                    "input_fingerprint": batch.input_fingerprint,
                    "method_fingerprint": batch.method_fingerprint,
                    "through_scene_id": batch.through_scene_id,
                    "through_scene_index": batch.through_scene_index,
                    "result_refs": deepcopy(batch.result_refs),
                    "tray_items": deepcopy(batch.tray_items),
                    "conflicts": deepcopy(batch.conflicts),
                }
                for batch in batches
            ],
            "drafts": drafts,
            "revisions": list(revisions.values()),
            "nodes": list(nodes.values()),
            "vocabulary": [
                {
                    "id": str(term.id),
                    "status": term.status,
                    "kind": term.kind,
                    "source": term.source,
                    "current_revision_id": str(term.current_revision_id)
                    if term.current_revision_id
                    else None,
                    "redirect_to_id": str(term.redirect_to_id)
                    if term.redirect_to_id
                    else None,
                    "revision_id": str(revision.id),
                    "revision_number": revision.revision_number,
                    "previous_revision_id": str(revision.previous_revision_id)
                    if revision.previous_revision_id
                    else None,
                    "content_hash": revision.content_hash,
                    "change_reason": revision.change_reason,
                    "snapshot": deepcopy(revision.snapshot_json),
                }
                for term, revision in vocabulary_rows
                if term.id in terms
            ],
            "coverage": [
                {
                    "scene_id": scene,
                    "status": "recorded"
                    if any(row.scene_id == scene for row in rows)
                    else "unknown",
                }
                for scene in scenes
            ],
            "missing": missing,
            "truncated": vocabulary_truncated,
            "omitted_count": 1 if vocabulary_truncated else 0,
            "human_validated": False,
        }
