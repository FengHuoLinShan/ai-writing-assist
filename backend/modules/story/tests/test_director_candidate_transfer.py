"""Author confirmation binds one frozen Director candidate to one World receipt."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from core.errors import ConflictError, NotFoundError
from modules.story import director_candidate_transfer as transfer_module
from modules.story.director_candidates import transfer_choices
from modules.story.director_schemas import DirectorCandidateTransferRequest
from modules.story.models import (
    StorySceneDirectorBranch,
    StorySceneDirectorCandidateTransfer,
    StorySceneDirectorRoot,
    StorySceneDirectorRound,
)


def test_event_free_object_refs_and_multi_reference_event_are_distinct_choices():
    visitor = {"kind": "candidate", "id": "visitor", "label": "陌生访客"}
    warehouse = {"kind": "candidate", "id": "warehouse", "label": "北门仓房"}
    output = {
        "materials": [{"object_refs": [visitor, warehouse]}],
        "candidate_events": [],
    }
    event_free = transfer_choices(output)
    assert {item["source_id"] for item in event_free} == {"visitor", "warehouse"}
    assert len({item["candidate_id"] for item in event_free}) == 2
    assert all(item["source_kind"] == "reference" for item in event_free)

    output["candidate_events"] = [
        {
            "candidate_id": "arrival",
            "label": "门口出现陌生访客",
            "description": "访客走向仓房。",
            "references": [visitor, warehouse],
        }
    ]
    with_event = transfer_choices(output)
    assert len(with_event) == 3
    assert {item["source_id"] for item in with_event} == {
        "visitor",
        "warehouse",
        "arrival",
    }
    labels = {item["source_id"]: item["label"] for item in with_event}
    assert labels["visitor"] == "陌生访客"
    assert labels["arrival"] == "门口出现陌生访客"


async def _source(db, novel_id: str):
    scene_id, root_id, branch_id, round_id = (uuid4() for _ in range(4))
    db.add_all(
        [
            StorySceneDirectorRoot(
                id=root_id,
                novel_id=UUID(novel_id),
                scene_id=scene_id,
                source_hash="a" * 64,
                request_json={"character_ids": [str(uuid4())], "related_object_ids": []},
                llm_execution_snapshot_json={},
                run_envelope_json={},
                status="ready",
            ),
            StorySceneDirectorBranch(
                id=branch_id,
                novel_id=UUID(novel_id),
                root_id=root_id,
                source_hash="a" * 64,
                request_json={},
                pending_round_json={},
                status="complete",
            ),
            StorySceneDirectorRound(
                id=round_id,
                novel_id=UUID(novel_id),
                root_id=root_id,
                branch_id=branch_id,
                round_number=1,
                source_hash="a" * 64,
                input_hash="b" * 64,
                output_hash="c" * 64,
                input_json={},
                output_json={
                    "candidate_events": [
                        {
                            "candidate_id": "new-visitor",
                            "label": "陌生访客",
                            "description": "一位新出现的访客，身份尚未证实。",
                            "timepoint": "this_scene",
                            "references": [],
                            "basis": [],
                            "candidate_only": True,
                            "applied_to_state": False,
                        }
                    ]
                },
                state_json={},
                run_envelope_json={},
            ),
        ]
    )
    await db.flush()
    return scene_id, round_id


@pytest.mark.asyncio
async def test_transfer_is_candidate_only_and_retries_keep_one_author_choice(
    db_session, project_factory, monkeypatch
):
    novel_id = await project_factory.create_project("director transfer")
    scene_id, round_id = await _source(db_session, str(novel_id))
    world_calls = []

    async def current_source(*_args, **_kwargs):
        return {"source_hash": "a" * 64}

    async def create_world(_db, _novel_id, data, *, candidate_id):
        world_calls.append((data, candidate_id))
        return {"id": candidate_id, "status": "candidate"}

    monkeypatch.setattr(transfer_module, "read_director_source", current_source)
    monkeypatch.setattr(transfer_module, "create_entity", create_world)
    round_row = await db_session.get(StorySceneDirectorRound, round_id)
    choice_id = transfer_choices(round_row.output_json)[0]["candidate_id"]
    request = DirectorCandidateTransferRequest(
        novel_id=str(novel_id),
        scene_id=scene_id,
        confirmed=True,
        candidate_id=choice_id,
        entity_type="event",
        expected_source_hash="a" * 64,
        expected_output_hash="c" * 64,
    )
    first = await transfer_module.transfer_director_candidate(
        db_session, str(round_id), request
    )
    second = await transfer_module.transfer_director_candidate(
        db_session, str(round_id), request
    )
    assert first.repeated is False and second.repeated is True
    assert first.world_candidate_id == second.world_candidate_id
    assert len(world_calls) == 1
    assert world_calls[0][0]["status"] == "candidate"
    source = world_calls[0][0]["content_json"]["director_source"]
    assert source["round_id"] == str(round_id)
    assert source["source_kind"] == "event"
    assert source["source_id"] == "new-visitor"
    assert (
        len((await db_session.scalars(select(StorySceneDirectorCandidateTransfer))).all())
        == 1
    )
    with pytest.raises(ConflictError):
        await transfer_module.transfer_director_candidate(
            db_session, str(round_id), request.model_copy(update={"entity_type": "item"})
        )
    with pytest.raises(ConflictError):
        await transfer_module.transfer_director_candidate(
            db_session,
            str(round_id),
            request.model_copy(update={"expected_output_hash": "d" * 64}),
        )


@pytest.mark.asyncio
async def test_transfer_rejects_stale_or_wrong_source_before_world_write(
    db_session, project_factory, monkeypatch
):
    novel_id = await project_factory.create_project("director transfer source")
    scene_id, round_id = await _source(db_session, str(novel_id))

    async def stale_source(*_args, **_kwargs):
        return {"source_hash": "e" * 64}

    async def forbidden_world(*_args, **_kwargs):
        raise AssertionError("World write must not start")

    monkeypatch.setattr(transfer_module, "read_director_source", stale_source)
    monkeypatch.setattr(transfer_module, "create_entity", forbidden_world)
    round_row = await db_session.get(StorySceneDirectorRound, round_id)
    choice_id = transfer_choices(round_row.output_json)[0]["candidate_id"]
    request = DirectorCandidateTransferRequest(
        novel_id=str(novel_id),
        scene_id=scene_id,
        confirmed=True,
        candidate_id=choice_id,
        entity_type="event",
        expected_source_hash="a" * 64,
        expected_output_hash="c" * 64,
    )
    with pytest.raises(ConflictError):
        await transfer_module.transfer_director_candidate(
            db_session, str(round_id), request
        )
    with pytest.raises(NotFoundError):
        await transfer_module.transfer_director_candidate(
            db_session, str(round_id), request.model_copy(update={"scene_id": uuid4()})
        )

    async def current_source(*_args, **_kwargs):
        return {"source_hash": "a" * 64}

    monkeypatch.setattr(transfer_module, "read_director_source", current_source)
    round_row.output_json = {
        "candidate_events": [{"candidate_id": "new-visitor", "label": "缺少描述"}]
    }
    with pytest.raises(ConflictError):
        await transfer_module.transfer_director_candidate(
            db_session, str(round_id), request
        )
    assert (
        await db_session.scalars(select(StorySceneDirectorCandidateTransfer))
    ).all() == []
