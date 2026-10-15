"""Author-deleted history keeps its independent, copied reference materials."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from modules.story.director_schemas import DirectorAngle, DirectorSaveReferenceRequest
from modules.story.director_service import (
    delete_director_branch,
    list_director_history,
    purge_expired_director_history,
    recheck_director_round_consistency,
    restore_director_branch,
    save_director_reference,
)
from modules.story.models import (
    StorySceneDirectorBranch,
    StorySceneDirectorReference,
    StorySceneDirectorRoot,
    StorySceneDirectorRound,
)


async def _history_fixture(db_session, novel_id: str):
    actor_id, scene_id = uuid.uuid4(), uuid.uuid4()
    root_id, branch_id, round_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    root = StorySceneDirectorRoot(
        id=root_id,
        novel_id=uuid.UUID(novel_id),
        scene_id=scene_id,
        source_hash="a" * 64,
        request_json={
            "character_ids": [str(actor_id)],
            "related_object_ids": [],
        },
        llm_execution_snapshot_json={"novel_id": novel_id},
        run_envelope_json={"requests_started": 3, "usage": {"total_tokens": 70}},
        status="ready",
    )
    branch = StorySceneDirectorBranch(
        id=branch_id,
        novel_id=uuid.UUID(novel_id),
        root_id=root.id,
        branch_kind="start",
        source_hash=root.source_hash,
        request_json={"mode": "start"},
        pending_round_json={},
        status="complete",
    )
    material = {
        "material_id": "lamp-light",
        "category": "environment",
        "content": "灯罩边缘积着一圈灰。",
        "object_refs": [],
        "perceiver_ids": [str(actor_id)],
        "senses": ["sight"],
        "source_kind": "world_dossier",
        "source_ids": ["lamp-source"],
        "source_fingerprints": {"lamp-source": "b" * 64},
        "conflict_status": "clear",
        "candidate_only": False,
        "internal_character_id": None,
        "perception_status": "known",
        "perception_note": "当前角色资料包中的对象状态",
        "disabled_for_character_ids": [],
    }
    round_row = StorySceneDirectorRound(
        id=round_id,
        novel_id=uuid.UUID(novel_id),
        root_id=root.id,
        branch_id=branch.id,
        round_number=1,
        source_hash=root.source_hash,
        input_hash="c" * 64,
        output_hash="d" * 64,
        input_json={"request": {"instructions": "只供导演查看"}, "source_snapshot": {}},
        output_json={
            "materials": [material],
            "performances": [],
            "recommended_angles": [],
        },
        state_json={},
        run_envelope_json={"requests_started": 3, "usage": {"total_tokens": 70}},
    )
    db_session.add_all([root, branch, round_row])
    await db_session.flush()
    return root, branch, round_row, actor_id, material


async def test_saved_reference_survives_branch_deletion_and_restoration(
    db_session, test_project_id
):
    root, branch, round_row, actor_id, material = await _history_fixture(
        db_session, test_project_id
    )
    angle = DirectorAngle(
        angle_id="close-lamp",
        label="贴近灯下的人物",
        viewpoint_kind="character",
        viewpoint_character_id=str(actor_id),
        narrative_distance="close",
        focus="手边的灯",
        detail_and_pacing="慢写触感与停顿",
        material_ids=[material["material_id"]],
    )
    saved = await save_director_reference(
        db_session,
        test_project_id,
        DirectorSaveReferenceRequest(
            novel_id=test_project_id,
            name="灯下停顿",
            source_round_id=round_row.id,
            material_ids=[material["material_id"]],
            angle=angle,
            annotation="作者手写的节奏备注",
        ),
    )
    reference_id = saved["id"]
    await db_session.flush()

    deleted = await delete_director_branch(db_session, test_project_id, str(branch.id))
    assert deleted["affected_round_count"] == 1
    history = await list_director_history(
        db_session, test_project_id, str(root.scene_id), purge_expired=False
    )
    assert history["branches"] == []
    assert history["rounds"] == []
    assert history["references"][0]["id"] == reference_id
    assert history["references"][0]["source_deleted"] is True
    assert history["references"][0]["source_round_deleted"] is True
    assert history["references"][0]["content_copy"]["materials"] == [material]
    assert history["references"][0]["angle"] == angle.model_dump(mode="json")

    await restore_director_branch(db_session, test_project_id, str(branch.id))
    restored = await list_director_history(
        db_session, test_project_id, str(root.scene_id), purge_expired=False
    )
    assert len(restored["rounds"]) == 1
    assert restored["references"][0]["source_deleted"] is False


async def test_consistency_recheck_uses_current_exact_source_without_editing_history(
    db_session, test_project_id, monkeypatch
):
    _root, _branch, round_row, actor_id, _material = await _history_fixture(
        db_session, test_project_id
    )

    async def current_source(*_args, **_kwargs):
        return {
            "source_hash": "z" * 64,
            "author_brief": {
                "coverage": "partial",
                "continuity_items": [
                    {
                        "entity_id": str(actor_id),
                        "dimension": "location",
                        "field": "place",
                        "value": value,
                        "checkpoint_id": checkpoint,
                        "provenance": {"status": "exact"},
                    }
                    for value, checkpoint in (("北门", "cp-a"), ("南门", "cp-b"))
                ],
            },
        }

    monkeypatch.setattr(
        "modules.story.director_context.read_director_source", current_source
    )
    before = dict(round_row.output_json)
    result = await recheck_director_round_consistency(
        db_session, test_project_id, str(round_row.id)
    )
    assert result["source_changed"] is True
    assert result["consistency"]["coverage"] == "unknown"
    assert any(
        item["field"] == "location:place" and item["severity"] == "conflict"
        for item in result["consistency"]["findings"]
    )
    assert round_row.output_json == before


async def test_expired_history_is_purged_without_purging_reference_copy(
    db_session, test_project_id
):
    root, branch, _round_row, _actor_id, material = await _history_fixture(
        db_session, test_project_id
    )
    reference = StorySceneDirectorReference(
        novel_id=uuid.UUID(test_project_id),
        root_id=root.id,
        scene_id=root.scene_id,
        source_round_id=_round_row.id,
        source_basis_hash=root.source_hash,
        source_deleted=True,
        name="独立副本",
        content_copy_json={"materials": [material], "angle": {"label": "close"}},
        material_ids_json=[material["material_id"]],
        angle_json={"label": "close"},
        annotation="",
    )
    branch.deleted_at = datetime.now(UTC) - timedelta(days=31)
    branch.restore_until = datetime.now(UTC) - timedelta(seconds=1)
    db_session.add(reference)
    await db_session.flush()

    await purge_expired_director_history(db_session, test_project_id)
    history = await list_director_history(
        db_session, test_project_id, str(root.scene_id), purge_expired=False
    )

    assert history["branches"] == []
    assert history["rounds"] == []
    assert len(history["references"]) == 1
    assert history["references"][0]["content_copy"]["materials"] == [material]
    assert history["references"][0]["source_deleted"] is True
