"""Real owner HTTP and World persistence for an explicit Director candidate."""

from __future__ import annotations

import asyncio
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport
from sqlalchemy import func, select

from app.main import app
from core.database import get_manager
from modules.account.contracts import BOOTSTRAP_ACCOUNT_ID
from modules.account.models import Account
from modules.assistant.operation_trace_models import AssistantOperationTrace
from modules.project.models import Project
from modules.story.director_candidates import transfer_choices
from modules.story.director_context import read_director_source
from modules.story.models import (
    StorySceneDirectorBranch,
    StorySceneDirectorCandidateTransfer,
    StorySceneDirectorRoot,
    StorySceneDirectorRound,
)
from modules.story.outline_state.models import Scene
from modules.world.models import CoreEntity
from modules.world.models.character import Character
from tests.support.http import XhrAsyncClient

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e]


@pytest.mark.parametrize("with_event", [False, True])
async def test_author_transfers_exact_round_once_and_world_stays_candidate(with_event):
    novel_id, other_id, other_owner, scene_id, actor_id = (uuid4() for _ in range(5))
    root_id, branch_id, round_id = (uuid4() for _ in range(3))
    visitor_ref = {"kind": "candidate", "id": "new-visitor", "label": "陌生访客"}
    place_ref = {"kind": "candidate", "id": "new-place", "label": "北门外的隐秘仓房"}
    concept_ref = {"kind": "candidate", "id": "new-concept", "label": "北门的守望誓约"}
    output = {
        "materials": [
            {
                "category": "object",
                "object_refs": [visitor_ref, place_ref, concept_ref],
            }
        ],
        "candidate_events": [
            {
                "candidate_id": "arrival",
                "label": "门口出现神秘信使",
                "description": "一个事件，同时引用访客和仓房。",
                "timepoint": "this_scene",
                "references": [visitor_ref, place_ref],
                "basis": [],
                "candidate_only": True,
                "applied_to_state": False,
            }
        ]
        if with_event
        else [],
    }
    choices = transfer_choices(output)
    choice_ids = {choice["source_id"]: choice["candidate_id"] for choice in choices}
    assert len(choices) == 3 + int(with_event)
    async with get_manager().session_factory() as db:
        if await db.get(Account, BOOTSTRAP_ACCOUNT_ID) is None:
            db.add(Account(id=BOOTSTRAP_ACCOUNT_ID, support_code="director-candidate"))
        db.add(
            Account(
                id=other_owner,
                support_code=f"other-{other_owner.hex[:16]}",
            )
        )
        db.add_all(
            [
                Project(
                    id=novel_id,
                    owner_id=BOOTSTRAP_ACCOUNT_ID,
                    title="导演候选作者作品",
                ),
                Project(id=other_id, owner_id=other_owner, title="另一个作者作品"),
            ]
        )
        await db.flush()
        db.add(
            CoreEntity(
                id=actor_id,
                novel_id=novel_id,
                entity_type="character",
                name="阿澄",
                summary="谨慎的守夜人",
                status="canonical",
            )
        )
        await db.flush()
        db.add_all(
            [
                Character(
                    entity_id=actor_id,
                    novel_id=novel_id,
                    name="阿澄",
                    status="canonical",
                ),
                Scene(id=scene_id, novel_id=novel_id, scene_index=0, title="北门对峙"),
            ]
        )
        await db.commit()
    async with get_manager().session_factory() as db:
        source = await read_director_source(
            db,
            novel_id=str(novel_id),
            scene_id=str(scene_id),
            character_ids=[str(actor_id)],
            related_object_ids=[],
        )
        source_hash = source["source_hash"]
        db.add(
            StorySceneDirectorRoot(
                id=root_id,
                novel_id=novel_id,
                scene_id=scene_id,
                source_hash=source_hash,
                request_json={
                    "character_ids": [str(actor_id)],
                    "related_object_ids": [],
                },
                llm_execution_snapshot_json={},
                run_envelope_json={},
                status="ready",
            )
        )
        await db.flush()
        db.add(
            StorySceneDirectorBranch(
                id=branch_id,
                novel_id=novel_id,
                root_id=root_id,
                source_hash=source_hash,
                request_json={},
                pending_round_json={},
                status="complete",
            )
        )
        await db.flush()
        db.add(
            StorySceneDirectorRound(
                id=round_id,
                novel_id=novel_id,
                root_id=root_id,
                branch_id=branch_id,
                round_number=1,
                source_hash=source_hash,
                input_hash="b" * 64,
                output_hash="c" * 64,
                input_json={},
                output_json=output,
                state_json={},
                run_envelope_json={},
            )
        )
        await db.commit()

    path = f"/api/story/director/rounds/{round_id}/world-candidates"
    payload = {
        "novel_id": str(novel_id),
        "scene_id": str(scene_id),
        "confirmed": True,
        "candidate_id": choice_ids["new-visitor"],
        "entity_type": "character",
        "expected_source_hash": source_hash,
        "expected_output_hash": "c" * 64,
    }
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with (
        XhrAsyncClient(transport=transport, base_url="http://test") as first,
        XhrAsyncClient(transport=transport, base_url="http://test") as second,
    ):
        unconfirmed = await first.post(path, json={**payload, "confirmed": False})
        assert unconfirmed.status_code == 422
        results = await asyncio.gather(
            first.post(path, json=payload), second.post(path, json=payload)
        )
        assert [result.status_code for result in results] == [201, 201], [
            result.text for result in results
        ]
        receipts = [result.json() for result in results]
        assert sorted(result["repeated"] for result in receipts) == [False, True]
        candidate_id = receipts[0]["world_candidate_id"]
        assert receipts[1]["world_candidate_id"] == candidate_id

        world = await first.get(
            f"/api/world/entities/{candidate_id}", params={"novel_id": str(novel_id)}
        )
        assert world.status_code == 200, world.text
        assert world.json()["status"] == "candidate"
        assert world.json()["name"] == "陌生访客"
        assert world.json()["summary"] is None
        assert world.json()["content_json"]["director_source"]["round_id"] == str(
            round_id
        )
        assert (
            world.json()["content_json"]["director_source"]["source_id"] == "new-visitor"
        )
        if with_event:
            assert (
                await first.post(
                    path, json={**payload, "candidate_id": choice_ids["arrival"]}
                )
            ).status_code == 409
        assert (
            await first.post(path, json={**payload, "entity_type": "item"})
        ).status_code == 409
        assert (
            await first.post(path, json={**payload, "expected_output_hash": "d" * 64})
        ).status_code == 409
        assert (
            await first.post(path, json={**payload, "candidate_id": "missing"})
        ).status_code == 409
        assert (
            await first.post(path, json={**payload, "novel_id": str(other_id)})
        ).status_code in {403, 404}
        location = await first.post(
            path,
            json={
                **payload,
                "candidate_id": choice_ids["new-place"],
                "entity_type": "location",
            },
        )
        assert location.status_code == 201, location.text
        assert location.json()["world_candidate_id"] != candidate_id
        async with get_manager().session_factory() as db:
            scene = await db.get(Scene, scene_id)
            scene.title = "北门对峙后续已改写"
            await db.commit()
        stale = await first.post(
            path,
            json={
                **payload,
                "candidate_id": choice_ids["new-concept"],
                "entity_type": "concept",
            },
        )
        assert stale.status_code == 409, stale.text
        history = await first.get(
            f"/api/story/scenes/{scene_id}/director/history",
            params={"novel_id": str(novel_id)},
        )
        assert history.status_code == 200, history.text
        saved = {
            item["candidate_id"]: item for item in history.json()["candidate_transfers"]
        }
        assert saved == {
            choice_ids["new-visitor"]: {
                "round_id": str(round_id),
                "candidate_id": choice_ids["new-visitor"],
                "world_candidate_id": candidate_id,
                "entity_type": "character",
            },
            choice_ids["new-place"]: {
                "round_id": str(round_id),
                "candidate_id": choice_ids["new-place"],
                "world_candidate_id": location.json()["world_candidate_id"],
                "entity_type": "location",
            },
        }
        preference = await first.get("/api/assistant/operation-traces/preference")
        assert preference.status_code == 200, preference.text
        original_enabled = preference.json()["enabled"]
        enabled = await first.put(
            "/api/assistant/operation-traces/preference", json={"enabled": True}
        )
        assert enabled.status_code == 200, enabled.text
        try:
            async with get_manager().session_factory() as db:
                baseline_trace_id = await db.scalar(
                    select(func.coalesce(func.max(AssistantOperationTrace.id), 0)).where(
                        AssistantOperationTrace.novel_id == novel_id,
                        AssistantOperationTrace.op_id
                        == "story.scene_director.transfer_world_candidate",
                    )
                )
            traced = await first.post(path, json=payload)
            assert traced.status_code == 201 and traced.json()["repeated"] is True
            assert traced.headers.get("x-novelcraft-operation-trace-incomplete") is None
            async with get_manager().session_factory() as db:
                rows = (
                    await db.scalars(
                        select(AssistantOperationTrace).where(
                            AssistantOperationTrace.novel_id == novel_id,
                            AssistantOperationTrace.op_id
                            == "story.scene_director.transfer_world_candidate",
                            AssistantOperationTrace.id > baseline_trace_id,
                        )
                    )
                ).all()
            assert [row.event_type for row in rows].count("confirmed") == 1
            assert [row.event_type for row in rows].count("executed") == 1
            assert all(row.actor_type == "ui" for row in rows)
            executed = next(row for row in rows if row.event_type == "executed")
            assert executed.result_refs == [
                {"type": "world_candidate", "id": candidate_id}
            ]
        finally:
            restored = await first.put(
                "/api/assistant/operation-traces/preference",
                json={"enabled": original_enabled},
            )
            assert restored.status_code == 200, restored.text

    async with get_manager().session_factory() as db:
        receipt_rows = (
            await db.scalars(
                select(StorySceneDirectorCandidateTransfer).where(
                    StorySceneDirectorCandidateTransfer.novel_id == novel_id
                )
            )
        ).all()
        assert len(receipt_rows) == 2
        assert {row.world_candidate_id for row in receipt_rows} == {
            UUID(candidate_id),
            UUID(location.json()["world_candidate_id"]),
        }
        world_candidates = (
            await db.scalars(
                select(CoreEntity).where(
                    CoreEntity.novel_id == novel_id,
                    CoreEntity.id.in_([row.world_candidate_id for row in receipt_rows]),
                )
            )
        ).all()
        assert len(world_candidates) == 2
        assert all(row.approved_by is None for row in world_candidates)
