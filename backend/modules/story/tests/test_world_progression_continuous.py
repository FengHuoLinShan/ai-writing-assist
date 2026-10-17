from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from infrastructure.llm.workflow_budget import new_ai_run_envelope
from infrastructure.tasks.models import AsyncTask
from modules.evidence.compilation.contracts import StructureContextBundle
from modules.evidence.compilation.services.compiled_context import CompiledContext
from modules.evidence.compilation.services.object_dossier_sections import (
    ObjectDossierSectionBuilder,
)
from modules.story import world_progression_context, world_progression_continuous
from modules.story.simulation_v3 import SimulationReference, SimulationV3Context
from modules.story.world_progression_continuous_tasks import (
    handle_progression_chapter_commit_check,
)
from modules.story.world_progression_models import (
    StoryWorldProgressionAuthorization,
    StoryWorldProgressionBranch,
    StoryWorldProgressionRoot,
    StoryWorldProgressionStep,
)
from modules.story.world_progression_tasks import WORLD_PROGRESSION_TASK


async def _seed_continuous_run(db, novel_id: str):
    actor_id, scene_id, root_id, branch_id, target_id = [uuid4() for _ in range(5)]
    novel_uuid = UUID(novel_id)
    now = datetime.now(UTC)
    envelope = new_ai_run_envelope(
        operation_id=str(uuid4()),
        run_id=str(root_id),
        root_capability_id="story.world_progression",
        novel_id=novel_id,
        request_limit=50,
        token_limit=50000,
        budget_mode="bounded",
        started_at=now,
        deadline_at=now + timedelta(hours=2),
    )
    root = StoryWorldProgressionRoot(
        id=root_id,
        novel_id=novel_uuid,
        scene_id=scene_id,
        source_hash="a" * 64,
        request_json={"participants": [{"kind": "character", "id": str(actor_id)}]},
        source_snapshot_json={"scene_id": str(scene_id)},
        llm_execution_snapshot_json={"novel_id": novel_id},
        run_envelope_json=envelope.snapshot().model_dump(mode="json"),
        context_confirmation_id="root-confirmation",
        status="complete",
    )
    branch = StoryWorldProgressionBranch(
        id=branch_id,
        novel_id=novel_uuid,
        root_id=root_id,
        branch_kind="start",
        basis_choice="current",
        source_hash="a" * 64,
        request_json={"scene_id": str(scene_id)},
        source_snapshot_json={"scene_id": str(scene_id)},
        status="complete",
    )
    first = StoryWorldProgressionStep(
        id=uuid4(),
        novel_id=novel_uuid,
        root_id=root_id,
        branch_id=branch_id,
        step_number=1,
        source_hash="a" * 64,
        input_hash="b" * 64,
        output_hash="c" * 64,
        state_json={"departed": [f"object:{actor_id}"]},
    )
    second = StoryWorldProgressionStep(
        id=uuid4(),
        novel_id=novel_uuid,
        root_id=root_id,
        branch_id=branch_id,
        parent_step_id=first.id,
        step_number=2,
        source_hash="a" * 64,
        input_hash="b" * 64,
        output_hash="c" * 64,
        state_json={"departed": [f"object:{actor_id}"]},
        result_json={
            "goal_outcomes": [{"target_id": str(target_id), "status": "in_progress"}],
            "target_paths": [{"target_id": str(target_id), "actor_ids": [str(actor_id)]}],
        },
    )
    authorization = StoryWorldProgressionAuthorization(
        novel_id=novel_uuid,
        root_id=root_id,
        branch_id=branch_id,
        enabled=True,
        revision=4,
        participant_ids_json=[str(actor_id)],
        every_new_chapters=1,
        counted_read_chapters_json=[1],
        last_triggered_read_count=1,
        read_count_initialized=True,
        context_confirmation_id="standing-confirmation",
    )
    db.add_all([root, branch, first, second, authorization])
    await db.flush()
    return SimpleNamespace(
        actor_id=str(actor_id),
        scene_id=str(scene_id),
        root_id=str(root_id),
        branch_id=str(branch_id),
        root=root,
        branch=branch,
        first=first,
        second=second,
        authorization=authorization,
        envelope=root.run_envelope_json,
    )


def _confirmed_context(actor_id: str, scene_id: str):
    excluded_id = str(uuid4())
    raw_brief = {
        "scene_id": scene_id,
        "world_items": [
            {
                "entity_id": actor_id,
                "kind": "world_dossier",
                "entry_id": "selected-entry",
                "revision_id": "selected-revision",
                "facing_label": "背景",
                "content": "SELECTED_FACT",
            },
            {
                "entity_id": excluded_id,
                "kind": "world_dossier",
                "entry_id": "excluded-entry",
                "revision_id": "excluded-revision",
                "facing_label": "秘密",
                "content": "EXCLUDED_SECRET",
            },
        ],
        "continuity_items": [],
        "pattern_items": [],
    }
    sections = ObjectDossierSectionBuilder.build(
        StructureContextBundle(
            novel_id="test",
            task="continuous authorization scope",
            scope="scene",
            object_dossier_brief=raw_brief,
            object_reference_dimensions=["object_dossier"],
        ),
        None,
    )
    sections[0].items = [
        item for item in sections[0].items if item.key == "world:selected-entry"
    ]
    confirmed = SimpleNamespace(
        compiled=CompiledContext(sections=sections),
        compile_options={
            "scene_id": scene_id,
            "character_ids": [actor_id],
            "entity_ids": [],
        },
    )
    return confirmed, raw_brief


def _stub_progression_source_reads(
    monkeypatch, novel_id: str, scene_id: str, actor_id: str, raw_brief: dict
):
    scene_context = {
        "novel_id": novel_id,
        "scene_id": scene_id,
        "context_hash": "scene-context",
        "outline_bundle": {"scene": {"id": scene_id, "scene_index": 3}},
    }

    async def read_scene_context(_db, **_kwargs):
        return scene_context

    async def read_state(_db, *_args, **_kwargs):
        return {
            "scene_index": 3,
            "chapter_index": 4,
            "dimensions": [
                {"dimension": "timeline", "status": "missing", "facts": []},
                {"dimension": "entities", "status": "missing", "facts": []},
            ],
        }

    async def read_dossiers(_db, **_kwargs):
        return raw_brief

    async def read_identities(_db, **_kwargs):
        return (
            [
                SimpleNamespace(
                    entity_id=actor_id, status="canonical", entity_type="character"
                )
            ],
            [],
        )

    async def build_simulation(_db, **_kwargs):
        return SimulationV3Context(
            participants=[SimulationReference(kind="object", id=actor_id)]
        )

    async def no_op(*_args, **_kwargs):
        return None

    async def empty_notices(*_args, **_kwargs):
        return []

    async def empty_map(*_args, **_kwargs):
        return {
            "routes": [],
            "actor_routes": {},
            "coverage": "not_compared",
            "unknowns": [],
            "fingerprint": "map-state",
        }

    monkeypatch.setattr(
        world_progression_context, "get_scene_story_context", read_scene_context
    )
    monkeypatch.setattr(world_progression_context, "get_scene_state_view", read_state)
    monkeypatch.setattr(
        world_progression_context, "read_object_dossier_brief", read_dossiers
    )
    monkeypatch.setattr(
        world_progression_context, "get_hidden_guard_sources", read_identities
    )
    monkeypatch.setattr(
        world_progression_context, "build_scene_simulation_context", build_simulation
    )
    monkeypatch.setattr(
        world_progression_context, "validate_simulation_context_refs", no_op
    )
    monkeypatch.setattr(world_progression_context, "get", lambda _key: empty_notices)
    monkeypatch.setattr(
        world_progression_context, "read_map_progression_state", empty_map
    )


async def _queue_and_handle_read_check(db, novel_id: str) -> dict:
    task_id = await world_progression_continuous.queue_progression_read_check(
        db, novel_id=novel_id
    )
    assert task_id
    task = await db.get(AsyncTask, UUID(task_id))
    assert task is not None
    return await handle_progression_chapter_commit_check(db, task)


@pytest.mark.asyncio
async def test_read_commit_outbox_runs_with_original_confirmed_scope_and_budget(
    db_session, test_project_id, monkeypatch
):
    flow = await _seed_continuous_run(db_session, test_project_id)
    monkeypatch.setenv("STORY_WORLD_PROGRESSION_ENABLED", "true")
    monkeypatch.setattr(
        world_progression_continuous,
        "_completed_read_chapters",
        lambda *_args, **_kwargs: _completed_chapters([1, 2]),
    )

    async def same_scene(_db, _novel_id):
        return {"id": flow.scene_id}

    monkeypatch.setattr(world_progression_continuous, "_latest_written_scene", same_scene)
    confirmed, raw_brief = _confirmed_context(flow.actor_id, flow.scene_id)
    _stub_progression_source_reads(
        monkeypatch,
        test_project_id,
        flow.scene_id,
        flow.actor_id,
        raw_brief,
    )
    prepared_ids = []

    async def prepare(_db, **kwargs):
        prepared_ids.append(kwargs["confirmation_id"])
        return confirmed

    monkeypatch.setattr(
        world_progression_continuous, "prepare_confirmed_ai_action", prepare
    )

    result = await _queue_and_handle_read_check(db_session, test_project_id)

    assert result["status"] == "queued"
    assert prepared_ids == ["standing-confirmation"]
    assert flow.authorization.enabled is True
    assert flow.authorization.stop_reason is None
    assert flow.authorization.trigger_count == 1
    assert flow.root.run_envelope_json == flow.envelope
    child = await db_session.scalar(
        select(StoryWorldProgressionBranch).where(
            StoryWorldProgressionBranch.novel_id == UUID(test_project_id),
            StoryWorldProgressionBranch.id == UUID(result["branch_id"]),
        )
    )
    assert child is not None
    assert child.request_json["scene_id"] == flow.scene_id
    assert [
        item["entry_id"]
        for item in child.source_snapshot_json["author_brief"]["world_items"]
    ] == ["selected-entry"]
    assert "EXCLUDED_SECRET" not in str(child.source_snapshot_json)
    assert (
        await db_session.scalar(
            select(AsyncTask.id).where(
                AsyncTask.novel_id == UUID(test_project_id),
                AsyncTask.task_type == WORLD_PROGRESSION_TASK,
                AsyncTask.id == child.current_task_id,
            )
        )
        is not None
    )


async def _completed_chapters(values: list[int]) -> list[int]:
    return values


@pytest.mark.asyncio
async def test_read_commit_outbox_persists_scene_scope_stop_without_throwing(
    db_session, test_project_id, monkeypatch
):
    flow = await _seed_continuous_run(db_session, test_project_id)
    new_scene_id = str(uuid4())
    monkeypatch.setenv("STORY_WORLD_PROGRESSION_ENABLED", "true")
    monkeypatch.setattr(
        world_progression_continuous,
        "_completed_read_chapters",
        lambda *_args, **_kwargs: _completed_chapters([1, 2]),
    )

    async def later_scene(_db, _novel_id):
        return {"id": new_scene_id}

    monkeypatch.setattr(
        world_progression_continuous, "_latest_written_scene", later_scene
    )

    async def must_not_prepare(*_args, **_kwargs):
        raise AssertionError(
            "scope mismatch must stop before confirmation or dossier reads"
        )

    monkeypatch.setattr(
        world_progression_continuous, "prepare_confirmed_ai_action", must_not_prepare
    )
    monkeypatch.setattr(
        world_progression_continuous,
        "read_progression_source",
        must_not_prepare,
    )

    result = await _queue_and_handle_read_check(db_session, test_project_id)

    assert result == {
        "status": "confirmation_scope_changed",
        "task_id": None,
        "stop_reason": "confirmation_scope_changed",
    }
    assert flow.authorization.enabled is False
    assert flow.authorization.stop_reason == "confirmation_scope_changed"
    assert flow.authorization.revision == 5
    assert flow.authorization.root_id == flow.root.id
    assert flow.authorization.branch_id == flow.branch.id
    assert flow.root.current_task_id is None
    assert flow.root.run_envelope_json == flow.envelope
    persisted = await world_progression_continuous.read_continuous_authorization(
        db_session, test_project_id
    )
    assert persisted["stop_reason"] == "confirmation_scope_changed"
    assert persisted["root_id"] == flow.root_id
    assert (
        await db_session.scalar(
            select(AsyncTask.id).where(
                AsyncTask.novel_id == UUID(test_project_id),
                AsyncTask.task_type == WORLD_PROGRESSION_TASK,
            )
        )
        is None
    )
