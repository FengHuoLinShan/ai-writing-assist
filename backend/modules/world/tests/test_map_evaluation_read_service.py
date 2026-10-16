"""Evaluation exports consume persisted evidence without domain writes."""

import json
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event

from core.errors import NotFoundError, ValidationError
from modules.account.context import bind_principal, reset_principal
from modules.account.contracts import AccountPrincipal
from modules.world.facade import read_map_spatial_evaluation_artifacts
from modules.world.map_auto_draft_service import build_map_auto_drafts
from modules.world.tests.test_map_auto_draft_service import (
    _build_request,
    _stage_bound_clue,
)


@pytest.mark.asyncio
async def test_artifacts_exact_run_scene_immutable_documents_and_read_only(
    db_session, test_project_id
):
    scene, _a, _b, clue = await _stage_bound_clue(db_session, test_project_id)
    request = _build_request(scene, clue)
    built = await build_map_auto_drafts(db_session, test_project_id, request)
    statements = []

    def capture(_conn, _cursor, statement, *_rest):
        statements.append(statement)

    engine = db_session.bind.sync_engine
    event.listen(engine, "before_cursor_execute", capture)
    try:
        result = await read_map_spatial_evaluation_artifacts(
            db_session, test_project_id, clue.run_id, [str(scene.id)]
        )
        empty = await read_map_spatial_evaluation_artifacts(
            db_session, test_project_id, "other-run", [str(scene.id)]
        )
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert result["clues"][0]["id"] == str(clue.id)
    assert result["clues"][0]["source_binding"] == clue.source_binding
    assert result["clues"][0]["clue_payload"]["review"] == clue.clue_payload["review"]
    assert result["batches"][0]["id"] == str(built.batch_id)
    assert result["revisions"][0]["document_hash"]
    assert result["nodes"][0]["head"] is None
    assert not empty["clues"] and not empty["batches"]
    assert empty["coverage"][0]["status"] == "unknown"
    assert not result["truncated"] and result["omitted_count"] == 0
    assert not any(
        sql.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))
        for sql in statements
    )
    assert not db_session.new and not db_session.dirty
    assert "api_key" not in json.dumps(result)
    with pytest.raises(ValidationError):
        await read_map_spatial_evaluation_artifacts(
            db_session, test_project_id, clue.run_id, []
        )


@pytest.mark.asyncio
async def test_artifacts_owner_gate_precedes_reading_project_evidence(
    db_session, test_project_id
):
    token = bind_principal(
        AccountPrincipal(
            account_id=uuid4(),
            session_id=uuid4(),
            status="active",
            identity_type="registered",
            support_code="test",
        )
    )
    try:
        with pytest.raises(NotFoundError):
            await read_map_spatial_evaluation_artifacts(
                db_session, test_project_id, "run", [str(uuid4())]
            )
    finally:
        reset_principal(token)


@pytest.mark.asyncio
async def test_evaluation_discloses_merged_source_as_historical_only(
    db_session, test_project_id
):
    from sqlalchemy import select

    from modules.world.map_atlas_models import MapAtlasNode
    from modules.world.map_structure_schemas import MapNodeCreate
    from modules.world.map_structure_service import MapStructureService

    scene, _a, _b, clue = await _stage_bound_clue(db_session, test_project_id)
    built = await build_map_auto_drafts(
        db_session, test_project_id, _build_request(scene, clue)
    )
    target = await MapStructureService().create_node(
        db_session, test_project_id, MapNodeCreate(title="目标地图")
    )
    source = await db_session.scalar(
        select(MapAtlasNode).where(MapAtlasNode.id == built.revisions[0].node_id)
    )
    source.status = "adopted"
    source.merged_into_node_id = UUID(target["id"])
    await db_session.flush()
    result = await read_map_spatial_evaluation_artifacts(
        db_session, test_project_id, clue.run_id, [str(scene.id)]
    )
    exported = result["nodes"][0]
    assert exported["id"] == str(source.id)
    assert exported["status"] == "merged"
    assert exported["merged_into_node_id"] == target["id"]
    assert exported["official"] is False
    assert result["revisions"][0]["node_id"] == str(source.id)


@pytest.mark.asyncio
async def test_tray_only_candidate_retains_scoped_provenance_and_can_be_rejected(
    db_session, test_project_id
):
    from modules.world.map_spatial_clue_schemas import MapSpatialClueDecisionRequest
    from modules.world.map_spatial_clue_service import review_spatial_clue
    from modules.world.map_structure_schemas import MapRevisionReview
    from modules.world.map_structure_service import MapStructureService

    scene, _start, _end, clue = await _stage_bound_clue(db_session, test_project_id)
    await review_spatial_clue(
        db_session,
        test_project_id,
        str(clue.id),
        MapSpatialClueDecisionRequest(
            action="reject", expected_fingerprint=clue.fingerprint, confirmed=True
        ),
    )
    built = await build_map_auto_drafts(
        db_session, test_project_id, _build_request(scene, clue)
    )
    artifacts = await read_map_spatial_evaluation_artifacts(
        db_session, test_project_id, clue.run_id, [str(scene.id)]
    )
    assert built.revisions and built.tray_items
    assert artifacts["clues"][0]["scene_id"] == str(scene.id)
    assert artifacts["clues"][0]["status"] == "rejected"
    batch = next(
        item for item in artifacts["batches"] if item["id"] == str(built.batch_id)
    )
    for ref in batch["result_refs"]:
        assert not ref["source_clue_ids"]
        tray = [item for item in batch["tray_items"] if item["node_id"] == ref["node_id"]]
        assert tray and {item["clue_id"] for item in tray} == {str(clue.id)}
        rejected = await MapStructureService().review(
            db_session,
            test_project_id,
            ref["node_id"],
            ref["revision_id"],
            MapRevisionReview(action="reject", base_revision_id=None),
        )
        assert rejected.status == "rejected"
    after = await read_map_spatial_evaluation_artifacts(
        db_session, test_project_id, clue.run_id, [str(scene.id)]
    )
    assert all(
        ref["status"] == "rejected"
        for row in after["batches"]
        for ref in row["result_refs"]
    )
    assert after["batches"][0]["tray_items"] == batch["tray_items"]
    assert not any(node["official"] or node["head"] for node in after["nodes"])


@pytest.mark.asyncio
@pytest.mark.parametrize("history_size,truncated", [(2, False), (3, True)])
async def test_vocabulary_scope_is_filtered_before_limit_and_keeps_author_history(
    db_session, test_project_id, monkeypatch, history_size, truncated
):
    from modules.world import map_evaluation_read_service as service
    from modules.world.project_vocabulary_models import (
        ProjectVocabularyRevision,
        ProjectVocabularyTerm,
    )

    selected_scene, other_scene = str(uuid4()), str(uuid4())
    # Irrelevant terms sort first. Their revisions must not consume the bound.
    relevant, irrelevant = UUID(int=200), UUID(int=100)
    for term_id in [relevant, irrelevant]:
        db_session.add(
            ProjectVocabularyTerm(
                id=term_id,
                novel_id=UUID(test_project_id),
                kind="feature",
                source="author",
                status="active",
            )
        )
    await db_session.flush()
    for term_id, count in [(irrelevant, 30), (relevant, history_size)]:
        for index in range(count):
            evidence = [
                {"scene_id": selected_scene if term_id == relevant else other_scene}
            ]
            if term_id == relevant and index > 0:
                evidence = []  # Later author revisions remain part of the lineage.
            db_session.add(
                ProjectVocabularyRevision(
                    novel_id=UUID(test_project_id),
                    term_id=term_id,
                    revision_number=index + 1,
                    snapshot_json={"name": "合成类型", "evidence": evidence},
                    content_hash="a" * 64,
                    change_reason="author_edit",
                )
            )
    await db_session.flush()
    monkeypatch.setattr(service, "MAX_EVALUATION_VOCABULARY_REVISIONS", 2)
    artifacts = await read_map_spatial_evaluation_artifacts(
        db_session, test_project_id, "run", [selected_scene]
    )
    assert [item["revision_number"] for item in artifacts["vocabulary"]] == [1, 2]
    assert {item["id"] for item in artifacts["vocabulary"]} == {str(relevant)}
    assert artifacts["vocabulary"][1]["snapshot"]["evidence"] == []
    assert artifacts["truncated"] is truncated
    assert artifacts["omitted_count"] == int(truncated)
    assert bool(artifacts["missing"]) is truncated
