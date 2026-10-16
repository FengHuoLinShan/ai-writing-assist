"""Regression targets from the map-series review (T-20261016-map-series-claude-review).

Each case encodes the specified behavior for a confirmed review finding. Cases are
strict xfail while the defect is open: a fix turns them into an unexpected pass,
which fails the run until the marker is removed and the case becomes a plain
regression test.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest

from core.errors import ConflictError
from modules.world.assistant_vocabulary_tools import _ensure_unique
from modules.world.map_spatial_clue_schemas import MapSpatialClueTypeProposalDraft
from modules.world.map_spatial_clue_service import stage_spatial_discovery
from modules.world.map_structure_schemas import (
    MapDocument,
    MapNodeCreate,
    MapSaveRequest,
)
from modules.world.map_structure_service import MapStructureService
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
    _stage_bound_clue,
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
