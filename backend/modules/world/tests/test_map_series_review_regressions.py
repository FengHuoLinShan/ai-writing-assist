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

from core.errors import ConflictError
from modules.world.assistant_vocabulary_tools import _ensure_unique
from modules.world.map_atlas_models import MapAtlasNode, MapAtlasRevision
from modules.world.map_auto_draft_schemas import MapAutoDraftBuildRequest
from modules.world.map_auto_draft_service import build_map_auto_drafts
from modules.world.map_spatial_clue_schemas import (
    MapSpatialClueDecisionRequest,
    MapSpatialClueTypeProposalDraft,
)
from modules.world.map_spatial_clue_service import (
    review_spatial_clue,
    stage_spatial_discovery,
)
from modules.world.map_structure_schemas import (
    MapDocument,
    MapNodeCreate,
    MapRevisionReview,
    MapSaveRequest,
)
from modules.world.map_structure_service import MapStructureService
from modules.world.models import CoreEntity
from modules.world.project_vocabulary_schemas import (
    VocabularyMergeRequest,
    VocabularyTermCreate,
    VocabularyTermFields,
    VocabularyTermUpdate,
    VocabularyTraits,
)
from modules.world.project_vocabulary_service import (
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


@pytest.mark.xfail(
    strict=True,
    reason="F1: merged vocabulary types are treated as non-computable instead of "
    "following redirect_to_id (ADR-0035 §4)",
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
            kind="feature", name="地点", traits=VocabularyTraits(geometry=["point"])
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
    before = await service.preview_layout(
        db_session, test_project_id, node["id"], request
    )
    assert [problem.code for problem in before.problems] == ["direction_conflict"]

    await merge_project_vocabulary_terms(
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
    after = await service.preview_layout(db_session, test_project_id, node["id"], request)

    codes = [problem.code for problem in after.problems]
    assert "spatial_type_not_computable" not in codes
    assert "direction_conflict" in codes


@pytest.mark.xfail(
    strict=True,
    reason="F2: assistant preview compares a tombstone through its merge target, "
    "while the service rejects the tombstone's own name",
)
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


@pytest.mark.xfail(
    strict=True,
    reason="B2-F4: an emerging model type omitted from bounded context makes the "
    "whole clue invalid instead of dropping only the type proposal",
)
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


@pytest.mark.xfail(
    strict=True,
    reason="B2-F5: adopting a clue revalidates endpoints without allowing the "
    "candidate-to-canonical transition that World adoption performs",
)
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


@pytest.mark.xfail(
    strict=True,
    reason="B3-F1: the implicit build scope loads every clue status, so a clue the "
    "author rejected returns to the placement tray labelled source_stale",
)
async def test_b3_rejected_clue_has_no_tray_effect_in_implicit_build(
    db_session, project_novel_id
):
    scene, _start, _end, row = await _stage_bound_clue(db_session, project_novel_id)
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


@pytest.mark.xfail(
    strict=True,
    reason="B3-F2: _ensure_location_nodes orders status DESC, so a provisional node "
    "outranks the author's adopted node for the same place and gets re-parented",
)
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


@pytest.mark.xfail(
    strict=True,
    reason="B3-F3: rejecting one clue marks the whole batch stale, so candidates for "
    "unrelated nodes cannot be adopted until the author redoes every shard",
)
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

    saved = await MapStructureService().review(
        db_session,
        project_novel_id,
        str(unrelated.node_id),
        str(unrelated.revision_id),
        MapRevisionReview(action="adopt", base_revision_id=None),
    )

    assert saved.status == "saved"


@pytest.mark.xfail(
    strict=True,
    reason="B3-F4: a time-bounded relation clue copies its validity onto both "
    "places, which removes them from layout and sends them to the tray",
)
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


@pytest.mark.xfail(
    strict=True,
    reason="B3-F5: assistant structure edits load a legacy v1 head without upgrading "
    "it, so adding a space or journey fails v1 validation instead of saving v2",
)
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


@pytest.mark.xfail(
    strict=True,
    reason="B3-F6 (Q2): reader_preview checks journey sources with all([...]), so a "
    "journey backed only by an author decision reaches readers without a quote",
)
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
