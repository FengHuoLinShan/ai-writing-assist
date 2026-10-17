"""Regression targets from the map-series review (T-20261016-map-series-claude-review).

Each case encodes the specified behavior for a confirmed review finding. Cases are
strict xfail while the defect is open: a fix turns them into an unexpected pass,
which fails the run until the marker is removed and the case becomes a plain
regression test.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from core.errors import ConflictError
from modules.world.assistant_vocabulary_tools import _ensure_unique
from modules.world.map_atlas_models import MapAtlasNode, MapAtlasRevision
from modules.world.map_auto_draft_models import MapAutoDraftBatchRecord
from modules.world.map_auto_draft_schemas import (
    MapAutoDraftBuildRequest,
    MapAutoDraftRedoRequest,
)
from modules.world.map_auto_draft_service import (
    build_map_auto_drafts,
    redo_map_auto_drafts,
)
from modules.world.map_spatial_clue_models import MapSpatialClueRecord
from modules.world.map_spatial_clue_schemas import (
    MapSpatialClueDecisionRequest,
    MapSpatialClueTypeProposalDraft,
    MapSpatialClueTypeRef,
)
from modules.world.map_spatial_clue_service import (
    read_spatial_discovery_context,
    review_spatial_clue,
    spatial_clue_review_hash,
    stage_spatial_discovery,
)
from modules.world.map_structure_schemas import (
    MapDocument,
    MapNodeCreate,
    MapRevisionReview,
    MapSaveRequest,
)
from modules.world.map_structure_service import MapStructureService
from modules.world.models import CoreEntity, WorldObjectDossierEntry
from modules.world.project_vocabulary_models import (
    ProjectVocabularyRevision,
    ProjectVocabularyTerm,
)
from modules.world.project_vocabulary_schemas import (
    VocabularyMergeRequest,
    VocabularyTermCreate,
    VocabularyTermFields,
    VocabularyTermUpdate,
    VocabularyTraits,
    vocabulary_evidence_hash,
)
from modules.world.project_vocabulary_service import (
    archive_project_vocabulary_term,
    create_project_vocabulary_term,
    merge_project_vocabulary_terms,
    update_project_vocabulary_term,
)
from modules.world.tests.test_map_auto_draft_service import (
    _adopt_clue,
    _build_request,
    _stage_bound_clue,
    _stage_related_clue,
)
from modules.world.tests.test_map_spatial_clue_boundaries import _source
from modules.world.tests.test_map_spatial_clues import (
    QUOTE_ONE,
    QUOTE_TWO,
    _batch,
    _clue,
    _resolved_sources,
)


def _typed_document(feature_type, relation_type):
    """Point a north of b while placing it south, so a computable map conflicts."""
    feature_ref = {
        "type_ref": str(feature_type.id),
        "type_revision_id": str(feature_type.revision_id),
    }
    return MapDocument.model_validate(
        {
            "schema_version": 2,
            "features": [
                {
                    "id": "a",
                    "kind": "location",
                    "label": "甲",
                    "points": [{"x": 0, "y": 100}],
                    **feature_ref,
                },
                {
                    "id": "b",
                    "kind": "location",
                    "label": "乙",
                    "points": [{"x": 0, "y": 0}],
                    **feature_ref,
                },
            ],
            "constraints": [
                {
                    "id": "north",
                    "subject": "a",
                    "relation": "north",
                    "target": "b",
                    "type_ref": str(relation_type.id),
                    "type_revision_id": str(relation_type.revision_id),
                }
            ],
        }
    )


async def test_f1_merging_a_type_keeps_pinned_map_geometry_computable(
    db_session, test_project_id
):
    merged_away = await create_project_vocabulary_term(
        db_session,
        test_project_id,
        VocabularyTermCreate(
            kind="feature", name="洞府", traits=VocabularyTraits(geometry=["point"])
        ),
    )
    target = await create_project_vocabulary_term(
        db_session,
        test_project_id,
        VocabularyTermCreate(
            kind="feature",
            name="地点",
            traits=VocabularyTraits(geometry=["point"], other=["movable"]),
        ),
    )
    relation = await create_project_vocabulary_term(
        db_session,
        test_project_id,
        VocabularyTermCreate(
            kind="relation",
            name="北向",
            traits=VocabularyTraits(orientation=["compass"]),
        ),
    )
    service = MapStructureService()
    node = await service.create_node(
        db_session, test_project_id, MapNodeCreate(title="区域")
    )
    request = MapSaveRequest(
        base_revision_id=node["current_revision_id"],
        document=_typed_document(merged_away, relation),
    )
    await update_project_vocabulary_term(
        db_session,
        test_project_id,
        str(relation.id),
        VocabularyTermUpdate(
            expected_revision_id=relation.revision_id,
            name="北向",
            description="",
            aliases=[],
            traits=VocabularyTraits(),
        ),
    )
    before = await service.preview_layout(
        db_session, test_project_id, node["id"], request
    )
    assert [problem.code for problem in before.problems] == ["direction_conflict"]

    merged_target = await merge_project_vocabulary_terms(
        db_session,
        test_project_id,
        VocabularyMergeRequest(
            confirmed=True,
            target_id=target.id,
            source_ids=[merged_away.id],
            expected_revision_ids={
                merged_away.id: merged_away.revision_id,
                target.id: target.revision_id,
            },
        ),
    )
    terminal = await create_project_vocabulary_term(
        db_session,
        test_project_id,
        VocabularyTermCreate(
            kind="feature", name="终点", traits=VocabularyTraits(geometry=["point"])
        ),
    )
    merged_terminal = await merge_project_vocabulary_terms(
        db_session,
        test_project_id,
        VocabularyMergeRequest(
            confirmed=True,
            target_id=terminal.id,
            source_ids=[target.id],
            expected_revision_ids={
                target.id: merged_target.revision_id,
                terminal.id: terminal.revision_id,
            },
        ),
    )
    terminal = await update_project_vocabulary_term(
        db_session,
        test_project_id,
        str(terminal.id),
        VocabularyTermUpdate(
            expected_revision_id=merged_terminal.revision_id,
            name="终点",
            description="",
            aliases=[],
            traits=VocabularyTraits(geometry=["point"], other=["movable"]),
        ),
    )
    after = await service.preview_layout(db_session, test_project_id, node["id"], request)

    codes = [problem.code for problem in after.problems]
    assert "spatial_type_not_computable" not in codes
    assert "direction_conflict" in codes
    from modules.world.map_structure_service import resolve_spatial_vocabulary_references

    resolved = await resolve_spatial_vocabulary_references(
        db_session,
        test_project_id,
        {(merged_away.id, merged_away.revision_id): "feature"},
    )
    assert resolved[(merged_away.id, merged_away.revision_id)]["traits"].other == [
        "movable"
    ]

    await archive_project_vocabulary_term(
        db_session, test_project_id, str(terminal.id), terminal.revision_id
    )
    archived = await service.preview_layout(
        db_session, test_project_id, node["id"], request
    )
    assert "spatial_type_not_computable" in [
        problem.code for problem in archived.problems
    ]


async def test_f2_assistant_uniqueness_preview_matches_service_after_merge(
    db_session, test_project_id
):
    merged_away = await create_project_vocabulary_term(
        db_session, test_project_id, VocabularyTermCreate(kind="feature", name="洞府")
    )
    target = await create_project_vocabulary_term(
        db_session, test_project_id, VocabularyTermCreate(kind="feature", name="地点")
    )
    merged_target = await merge_project_vocabulary_terms(
        db_session,
        test_project_id,
        VocabularyMergeRequest(
            confirmed=True,
            target_id=target.id,
            source_ids=[merged_away.id],
            expected_revision_ids={
                merged_away.id: merged_away.revision_id,
                target.id: target.revision_id,
            },
        ),
    )
    # The author later removes the absorbed old name from the merge target.
    await update_project_vocabulary_term(
        db_session,
        test_project_id,
        str(target.id),
        VocabularyTermUpdate(
            name="地点",
            aliases=[],
            expected_revision_id=merged_target.revision_id,
        ),
    )
    with pytest.raises(ConflictError):
        await create_project_vocabulary_term(
            db_session,
            test_project_id,
            VocabularyTermCreate(kind="feature", name="洞府"),
        )

    by_id = {
        str(merged_away.id): {
            "kind": "feature",
            "status": "merged",
            "name": "洞府",
            "aliases": [],
            "redirect_to_id": str(target.id),
        },
        str(target.id): {
            "kind": "feature",
            "status": "active",
            "name": "地点",
            "aliases": [],
            "redirect_to_id": None,
        },
    }
    with pytest.raises(ConflictError):
        _ensure_unique(by_id, "feature", VocabularyTermFields(name="洞府"), set())


async def test_b2_reproposed_type_outside_context_keeps_the_spatial_clue(
    db_session, project_novel_id, monkeypatch
):
    import modules.world.map_spatial_clue_service as service

    monkeypatch.setattr(
        service,
        "_resolve_binding",
        AsyncMock(
            side_effect=lambda _db, _novel, _scene, _index, binding: _resolved_sources(
                binding, f"{QUOTE_ONE}{QUOTE_TWO}"
            )
        ),
    )
    monkeypatch.setattr(service, "_evidence_is_current", AsyncMock(return_value=True))

    def draft():
        # Each Scene that cannot see the earlier emerging type proposes it anew.
        return MapSpatialClueTypeProposalDraft(
            kind="relation",
            proposal_run_id=uuid.uuid4(),
            name="潮汐暗道",
            description="只在潮水退去时可通行的连接关系。",
        )

    scene_one, scene_two = str(uuid.uuid4()), str(uuid.uuid4())
    first = await stage_spatial_discovery(
        db_session,
        project_novel_id,
        _batch(
            project_novel_id,
            scene_one,
            1,
            [
                _clue(
                    scene_id=scene_one,
                    clue_key="8" * 64,
                    quote=QUOTE_ONE,
                    type_proposal_draft=draft(),
                )
            ],
        ),
    )
    assert first.accepted

    second = await stage_spatial_discovery(
        db_session,
        project_novel_id,
        _batch(
            project_novel_id,
            scene_two,
            2,
            [
                _clue(
                    scene_id=scene_two,
                    clue_key="9" * 64,
                    quote=QUOTE_TWO,
                    type_proposal_draft=draft(),
                )
            ],
        ),
    )

    assert not second.rejected, second.diagnostics
    assert len(second.result_refs) == 1
    row = await db_session.get(MapSpatialClueRecord, second.result_refs[0].clue_id)
    stored_clue = service.MapSpatialClue.model_validate(row.clue_payload)
    assert stored_clue.type_proposal is None
    assert stored_clue.type_proposal_draft is None
    adopted = await _adopt_clue(db_session, project_novel_id, row)
    assert adopted.status == "adopted"


async def test_b2_spatial_context_prioritizes_emerging_types_over_archived(
    db_session, project_novel_id
):
    scene, _draft, _span, binding, evidence = await _source(
        db_session, project_novel_id, index=1, chapter=1
    )
    proposal = MapSpatialClueTypeProposalDraft(
        kind="relation",
        proposal_run_id=uuid.uuid4(),
        name="潮汐暗道",
        description="只在潮水退去时可通行的连接关系。",
    )
    clue = _clue(
        scene_id=str(scene.id),
        clue_key="b" * 64,
        quote=QUOTE_ONE,
        type_proposal_draft=proposal,
    )
    clue.review.evidence_hash = vocabulary_evidence_hash([evidence])
    batch = _batch(project_novel_id, str(scene.id), scene.scene_index, [clue])
    batch.source_binding = binding
    staged = await stage_spatial_discovery(db_session, project_novel_id, batch)
    assert len(staged.accepted) == 1, staged.diagnostics

    archived = await create_project_vocabulary_term(
        db_session,
        project_novel_id,
        VocabularyTermCreate(kind="relation", name="旧驿道关系"),
    )
    archived = await archive_project_vocabulary_term(
        db_session,
        project_novel_id,
        str(archived.id),
        archived.revision_id,
    )
    terms = (
        await db_session.scalars(
            select(ProjectVocabularyTerm).where(
                ProjectVocabularyTerm.novel_id == uuid.UUID(project_novel_id),
                ProjectVocabularyTerm.source == "model",
                ProjectVocabularyTerm.kind == "relation",
            )
        )
    ).all()
    emerging = None
    for term in terms:
        revision = await db_session.get(
            ProjectVocabularyRevision, term.current_revision_id
        )
        if revision.snapshot_json["name"] == proposal.name:
            emerging = term
            break
    assert emerging is not None
    next_scene, _draft, _span, _binding, _evidence = await _source(
        db_session, project_novel_id, index=2, chapter=2
    )

    context = await read_spatial_discovery_context(
        db_session,
        project_novel_id,
        scene_id=str(next_scene.id),
        scene_index=next_scene.scene_index,
        endpoint_ids=[],
        endpoint_surfaces=[],
        type_limit=64,
        clue_limit=0,
    )

    context_type_ids = [item.id for item in context.types]
    assert emerging.id in context_type_ids
    assert archived.id in context_type_ids
    assert context_type_ids.index(emerging.id) < context_type_ids.index(archived.id)


async def test_b2_clue_stays_adoptable_after_its_place_is_adopted(
    db_session, project_novel_id
):
    _scene, start, end, row = await _stage_bound_clue(
        db_session, project_novel_id, entity_status="candidate"
    )
    # The author adopts both places in World review before reviewing the clue.
    start.status = "canonical"
    end.status = "canonical"
    await db_session.flush()

    adopted = await _adopt_clue(db_session, project_novel_id, row)

    assert adopted.status == "adopted"


async def test_b2_clue_keeps_its_pinned_type_after_author_revision(
    db_session, project_novel_id, monkeypatch
):
    import modules.world.map_spatial_clue_service as service

    monkeypatch.setattr(service, "_evidence_is_current", AsyncMock(return_value=True))
    scene, _draft, _span, binding, evidence = await _source(
        db_session, project_novel_id
    )

    original_type = await create_project_vocabulary_term(
        db_session,
        project_novel_id,
        VocabularyTermCreate(kind="relation", name="潮汐通道"),
    )
    scene_id = str(scene.id)
    clue = _clue(scene_id=scene_id, clue_key="a" * 64, quote=QUOTE_ONE)
    clue.type_ref = original_type.id
    clue.type_revision_id = original_type.revision_id
    clue.type_kind = "relation"
    clue.review.proposal_hash = spatial_clue_review_hash(clue)
    clue.review.evidence_hash = vocabulary_evidence_hash([evidence])
    batch = _batch(project_novel_id, scene_id, scene.scene_index, [clue])
    batch.source_binding = binding
    batch.allowed_type_revisions = [
        MapSpatialClueTypeRef(
            type_ref=original_type.id,
            type_revision_id=original_type.revision_id,
            kind="relation",
        )
    ]
    staged = await stage_spatial_discovery(db_session, project_novel_id, batch)
    assert len(staged.accepted) == 1, staged.diagnostics
    row = await db_session.get(MapSpatialClueRecord, staged.accepted[0].clue_id)

    revised_type = await update_project_vocabulary_term(
        db_session,
        project_novel_id,
        str(original_type.id),
        VocabularyTermUpdate(
            expected_revision_id=original_type.revision_id,
            name="退潮通道",
        ),
    )
    assert revised_type.revision_id != original_type.revision_id

    adopted = await _adopt_clue(db_session, project_novel_id, row)

    assert adopted.status == "adopted"
    assert row.clue_payload["type_revision_id"] == str(original_type.revision_id)

    import modules.world.map_auto_draft_service as auto_draft

    valid, invalid = await auto_draft._validated_clue_inputs(
        db_session,
        project_novel_id,
        [row],
        through_scene_index=scene.scene_index,
    )
    assert [item["row"].id for item in valid] == [row.id]
    assert invalid == []


async def test_b3_rejected_clue_has_no_tray_effect_in_implicit_build(
    db_session, project_novel_id
):
    scene, _start, _end, row = await _stage_bound_clue(db_session, project_novel_id)
    first = await build_map_auto_drafts(
        db_session, project_novel_id, _build_request(scene, row)
    )
    rejected = await review_spatial_clue(
        db_session,
        project_novel_id,
        str(row.id),
        MapSpatialClueDecisionRequest(
            action="reject", expected_fingerprint=row.fingerprint, confirmed=True
        ),
    )
    assert rejected.status == "rejected"

    # Evolution always builds with clue_ids=None ("eligible, reviewed clues").
    result = await build_map_auto_drafts(
        db_session,
        project_novel_id,
        _build_request(scene, row).model_copy(update={"clue_ids": None}),
    )

    assert [item.reason for item in result.tray_items] == []
    assert result.revisions == []
    rebuilt = await redo_map_auto_drafts(
        db_session,
        project_novel_id,
        str(first.batch_id),
        MapAutoDraftRedoRequest(
            expected_fingerprint=first.fingerprint,
            reason="author_requested",
            confirmed=True,
        ),
    )
    assert rebuilt.revisions == []
    assert rebuilt.tray_items == []


async def test_b3_auto_draft_targets_the_adopted_node_for_a_place(
    db_session, project_novel_id
):
    scene, start, _end, row = await _stage_bound_clue(db_session, project_novel_id)
    await _adopt_clue(db_session, project_novel_id, row)
    adopted = await MapStructureService().create_node(
        db_session,
        project_novel_id,
        MapNodeCreate(title="西岸", level="city", location_entity_id=start.id),
    )
    # An unfinished atlas plan also left a provisional node for the same place.
    atlas_node = MapAtlasNode(
        novel_id=uuid.UUID(project_novel_id),
        location_entity_id=start.id,
        semantic_key=f"atlas-plan:{uuid.uuid4()}",
        title="西岸（地图册规划）",
        level="district",
        status="provisional",
    )
    db_session.add(atlas_node)
    await db_session.flush()

    result = await build_map_auto_drafts(
        db_session, project_novel_id, _build_request(scene, row)
    )

    revision = await db_session.get(MapAtlasRevision, result.revisions[0].revision_id)
    assert str(revision.node_id) == str(adopted["id"])
    await db_session.refresh(atlas_node)
    assert atlas_node.level == "district"


async def test_b3_rejecting_a_clue_only_blocks_the_shard_that_depends_on_it(
    db_session, project_novel_id
):
    scene, start, _end, first = await _stage_bound_clue(db_session, project_novel_id)
    other_start = CoreEntity(
        novel_id=uuid.UUID(project_novel_id),
        entity_type="location",
        name="北山",
        status="canonical",
    )
    other_end = CoreEntity(
        novel_id=uuid.UUID(project_novel_id),
        entity_type="location",
        name="南谷",
        status="canonical",
    )
    db_session.add_all([other_start, other_end])
    await db_session.flush()
    next_scene, second = await _stage_related_clue(
        db_session,
        project_novel_id,
        scene_index=2,
        start=other_start,
        end=other_end,
    )
    result = await build_map_auto_drafts(
        db_session,
        project_novel_id,
        MapAutoDraftBuildRequest(
            run_id=first.run_id,
            build_key=f"aggregate-{uuid.uuid4()}",
            through_scene_id=next_scene.id,
            through_scene_index=next_scene.scene_index,
            clue_ids=[first.id, second.id],
        ),
    )
    assert len(result.revisions) == 2
    unrelated = next(ref for ref in result.revisions if ref.source_clue_ids == [first.id])
    await review_spatial_clue(
        db_session,
        project_novel_id,
        str(second.id),
        MapSpatialClueDecisionRequest(
            action="reject", expected_fingerprint=second.fingerprint, confirmed=True
        ),
    )
    batch = await db_session.get(MapAutoDraftBatchRecord, result.batch_id)
    assert batch.status == "completed"
    assert (
        next(
            ref for ref in batch.result_refs if ref["source_clue_ids"] == [str(second.id)]
        )["status"]
        == "stale"
    )
    assert (
        next(
            ref for ref in batch.result_refs if ref["source_clue_ids"] == [str(first.id)]
        )["status"]
        == "candidate"
    )

    saved = await MapStructureService().review(
        db_session,
        project_novel_id,
        str(unrelated.node_id),
        str(unrelated.revision_id),
        MapRevisionReview(action="adopt", base_revision_id=None),
    )

    assert saved.status == "saved"


async def test_b3_bounded_relation_does_not_unplace_its_endpoints(
    db_session, project_novel_id
):
    _scene, start, end, bounded = await _stage_bound_clue(
        db_session, project_novel_id, effective=True
    )
    next_scene, plain = await _stage_related_clue(
        db_session, project_novel_id, scene_index=2, start=start, end=end
    )
    result = await build_map_auto_drafts(
        db_session,
        project_novel_id,
        MapAutoDraftBuildRequest(
            run_id=bounded.run_id,
            build_key=f"aggregate-{uuid.uuid4()}",
            through_scene_id=next_scene.id,
            through_scene_index=next_scene.scene_index,
            clue_ids=[bounded.id, plain.id],
        ),
    )
    revision = await db_session.get(MapAtlasRevision, result.revisions[0].revision_id)
    document = MapDocument.model_validate(revision.document)

    # The validity belongs to the bounded connection only (ADR-0035: features,
    # relations and journeys each carry their own range).
    places = [item for item in document.features if item.entity_id is not None]
    assert [item.effective for item in places] == [None, None]
    assert all(item.points for item in places)
    assert "placement_failed" not in {item.reason for item in result.tray_items}


async def test_b3_assistant_structure_edit_upgrades_a_legacy_v1_map(
    db_session, test_project_id
):
    from app.assistant_operation_registry import world_map_operations
    from modules.world.assistant_map_tools import (
        AssistantSpaceArrangement,
        EditMapStructure,
        MapStructureEdit,
    )
    from modules.world.map_structure_geometry import geometry_hash
    from modules.world.tests.test_assistant_map_tools import _persist_author_turn

    service = MapStructureService()
    created = await service.create_node(
        db_session, test_project_id, MapNodeCreate(title="旧地图")
    )
    node = await service.node(db_session, test_project_id, created["id"])
    # Maps saved before spatial model v2 keep schema_version 1; the v2
    # migration does not rewrite stored revisions.
    legacy = MapDocument.model_validate(
        {
            "schema_version": 1,
            "features": [
                {"id": "gate", "kind": "location", "label": "城门", "points": []}
            ],
        }
    )
    head = MapAtlasRevision(
        novel_id=node.novel_id,
        node_id=node.id,
        base_revision_id=node.current_revision_id,
        status="saved",
        document=legacy.model_dump(mode="json"),
        geometry_hash=geometry_hash(legacy),
        problems=[],
    )
    db_session.add(head)
    await db_session.flush()
    node.current_revision_id = head.id
    await db_session.flush()
    context, _message = await _persist_author_turn(db_session, test_project_id)
    args = EditMapStructure(
        node_id=node.id,
        base_revision_id=head.id,
        edits=[
            MapStructureEdit(
                kind="add_space",
                space=AssistantSpaceArrangement(id="dream", label="梦境"),
            )
        ],
    )

    preview = await world_map_operations["map.edit_spatial_structure"].prepare(
        db_session, test_project_id, args, context=context
    )

    assert preview["after"]["schema_version"] == 2
    assert {space["id"] for space in preview["after"]["spaces"]} == {"main", "dream"}


async def test_b3_reader_preview_omits_journeys_without_verbatim_sources(
    db_session, test_project_id
):
    from modules.world.map_structure_schemas import (
        MapAuthorDecision,
        MapSource,
        SpatialJourney,
    )
    from modules.world.tests.test_map_structure import create_map, document

    service, node = await create_map(db_session, test_project_id)
    doc = document()
    doc.journeys = [
        SpatialJourney(
            id="ferry-trip",
            origin="harbor",
            destination="pass",
            transport_label="渡船",
            sources=[
                MapSource(
                    kind="entity",
                    id=uuid.uuid4(),
                    source_hash="a" * 64,
                    quote="乘船半日可达",
                )
            ],
        ),
        # The author's private arrangement: no manuscript quote reveals it.
        SpatialJourney(
            id="secret-tunnel",
            origin="harbor",
            destination="pass",
            transport_label="地下暗道",
            duration={"minimum": 1, "maximum": 2, "unit": "hour"},
            author_decision=MapAuthorDecision(origin="manual"),
        ),
    ]
    with (
        patch.object(
            MapStructureService, "source", autospec=True, return_value="乘船半日可达"
        ),
        patch.object(
            MapStructureService,
            "reader_source_visible",
            autospec=True,
            return_value=True,
        ),
    ):
        await service.save(
            db_session,
            test_project_id,
            node["id"],
            MapSaveRequest(base_revision_id=node["current_revision_id"], document=doc),
        )
        projection = await service.reader_preview(
            db_session, test_project_id, node["id"], chapter=1
        )

    # docs/modules/15_map.md: reader journeys must pass the verbatim-source check.
    assert [journey["id"] for journey in projection["journeys"]] == ["ferry-trip"]


async def test_b4_route_through_text_only_waypoint_is_not_reported_disconnected(
    db_session, test_project_id
):
    from copy import deepcopy

    from core.container import get
    from core.service_keys import WORLD_READ_MAP_SPATIAL_ADVISORIES
    from modules.world.map_structure_service import source_digest, source_payload
    from modules.world.tests.test_map_spatial_advisory_integration import seed

    scene, node, revision, places, _ = await seed(db_session, test_project_id)
    towns = [
        CoreEntity(
            novel_id=revision.novel_id,
            entity_type="location",
            name=name,
            summary=name,
            public_info=name,
            reveal_level="revealed",
            status="canonical",
        )
        for name in ("北镇", "南镇")
    ]
    db_session.add_all(towns)
    await db_session.flush()

    def source(place):
        return {
            "kind": "entity",
            "id": str(place.id),
            "quote": place.name,
            "source_hash": source_digest(source_payload(place)),
        }

    document = deepcopy(revision.document)
    document["features"] += [
        {
            "id": key,
            "kind": "location",
            "label": town.name,
            "entity_id": str(town.id),
            "sources": [source(town)],
        }
        for key, town in (("north-town", towns[0]), ("south-town", towns[1]))
    ]
    # A drawn mountain pass the author labelled without binding a world object.
    document["features"].append({"id": "pass", "kind": "landmark", "label": "山口"})
    east, west = places
    document["constraints"] = [
        {
            "id": "pass-road",
            "subject": "east",
            "target": "west",
            "relation": "connects",
            "via": ["pass"],
            "sources": [source(east), source(west)],
        },
        {
            "id": "east-north",
            "subject": "east",
            "target": "north-town",
            "relation": "adjacent",
            "sources": [source(east), source(towns[0])],
        },
        {
            "id": "west-south",
            "subject": "west",
            "target": "south-town",
            "relation": "adjacent",
            "sources": [source(west), source(towns[1])],
        },
    ]
    revision.document = MapDocument.model_validate(document).model_dump(mode="json")
    await db_session.flush()

    result = await get(WORLD_READ_MAP_SPATIAL_ADVISORIES)(
        db_session,
        {
            "novel_id": test_project_id,
            "scene_id": str(scene.id),
            "transitions": [
                {"from_location_id": str(east.id), "to_location_id": str(west.id)}
            ],
        },
    )

    # The map declares 东城 → 山口 → 西城 as one active road.
    codes = [item.rule_code for item in result.items]
    assert "route_no_active_connection" not in codes, result.items


async def _location_with_backfilled_public_info(async_client, db_session, name):
    """A location whose public_info predates the dossier tables.

    The entry mirrors the 20261015_object_dossier_v2 backfill row for
    ``core_entities.public_info`` (facing ``public_info``, legacy key, legacy_import).
    """
    project = await async_client.post("/api/projects", json={"title": "档案回填"})
    assert project.status_code == 201, project.text
    params = {"novel_id": project.json()["id"]}
    created = await async_client.post(
        "/api/world/entities",
        params=params,
        json={
            "entity_type": "location",
            "name": name,
            "status": "canonical",
        },
    )
    assert created.status_code == 201, created.text
    legacy_entity = await db_session.get(CoreEntity, uuid.UUID(created.json()["id"]))
    assert legacy_entity is not None
    legacy_entity.public_info = "城门日落关闭"
    await db_session.flush()
    await db_session.refresh(legacy_entity)
    entry = WorldObjectDossierEntry(
        id=uuid.uuid4(),
        novel_id=uuid.UUID(params["novel_id"]),
        entity_id=uuid.UUID(created.json()["id"]),
        entry_group_id=uuid.uuid4(),
        revision_number=1,
        facing_kind="core",
        facing_key="public_info",
        legacy_field_key="public_info",
        content="城门日落关闭",
        tags_json=[],
        metadata_json={},
        source="legacy_import",
        source_refs_json=[],
        visibility="public",
        status="active",
        revision_reason="legacy_backfill",
    )
    db_session.add(entry)
    await db_session.flush()
    entity_response = created.json()
    entity_response["updated_at"] = legacy_entity.updated_at.isoformat()
    entity_response["public_info"] = legacy_entity.public_info
    return params, entity_response, entry


async def test_b6_entity_public_info_edit_keeps_its_dossier_entry_current(
    async_client, db_session
):
    params, entity, _entry = await _location_with_backfilled_public_info(
        async_client, db_session, "旧城"
    )

    edited = await async_client.put(
        f"/api/world/entities/{entity['id']}",
        params=params,
        json={
            "public_info": "城门彻夜开放",
            "expected_updated_at": entity["updated_at"],
        },
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["public_info"] == "城门彻夜开放"

    dossier = await async_client.get(
        f"/api/world/entities/{entity['id']}/dossier", params=params
    )
    assert dossier.status_code == 200, dossier.text
    # ADR-0039: public_info is the aggregate of the public entries, so the dossier
    # read (and the Evidence brief built from it) must not keep the old value.
    contents = [
        item["content"]
        for item in dossier.json()["entries"]
        if item.get("legacy_field_key") == "public_info"
    ]
    assert contents == ["城门彻夜开放"], contents


async def test_b6_backfilled_public_info_entry_is_editable_in_the_dossier(
    async_client, db_session
):
    params, entity, entry = await _location_with_backfilled_public_info(
        async_client, db_session, "旧城"
    )

    edited = await async_client.patch(
        f"/api/world/entities/{entity['id']}/dossier/entries/{entry.id}",
        params=params,
        json={"expected_revision_id": str(entry.id), "content": "城门彻夜开放"},
    )

    # ADR-0039: author edits go through the dossier revision entry point.
    assert edited.status_code == 200, edited.text
    assert edited.json()["content"] == "城门彻夜开放"


async def test_b6_manifest_with_backfilled_public_info_can_be_imported(
    async_client, db_session
):
    params, entity, _entry = await _location_with_backfilled_public_info(
        async_client, db_session, "旧城"
    )
    exported = await async_client.get(
        f"/api/world/entities/{entity['id']}/dossier/manifest", params=params
    )
    assert exported.status_code == 200, exported.text
    target = await async_client.post(
        "/api/world/entities",
        params=params,
        json={"entity_type": "location", "name": "新城", "status": "canonical"},
    )
    assert target.status_code == 201, target.text

    preview = await async_client.post(
        f"/api/world/entities/{target.json()['id']}/dossier/manifest/preview",
        params=params,
        json={"manifest": exported.json()},
    )

    # The export the product produced for this object must be importable.
    assert preview.status_code == 200, preview.text
    assert preview.json()["create_count"] == 1
