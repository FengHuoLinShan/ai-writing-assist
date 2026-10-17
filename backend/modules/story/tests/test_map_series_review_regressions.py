"""Regression targets from the map-series review (T-20261016-map-series-claude-review).

Cases cover the repaired behavior and author-resume failure paths.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import select

from core.errors import ConflictError
from infrastructure.llm.schemas import read_ai_run_envelope
from infrastructure.llm.workflow_budget import AIRunEnvelope
from modules.evidence.compilation.contracts import StructureContextBundle
from modules.evidence.compilation.services.compiled_context import CompiledContext
from modules.evidence.compilation.services.object_dossier_sections import (
    ObjectDossierSectionBuilder,
)
from modules.story import director_api, world_progression_context
from modules.story.director_budget import preview_director_budget, preview_director_resume
from modules.story.director_consistency import validate_intents
from modules.story.director_context import read_director_source
from modules.story.director_schemas import DirectorContinueRequest
from modules.story.models import (
    StorySceneDirectorBranch,
    StorySceneDirectorRoot,
    StorySceneDirectorRound,
)
from modules.story.simulation_v3 import (
    SimulationIntent,
    SimulationReference,
    SimulationV3Context,
)

# Reuse the offline Director workflow (rollback-only DB, synthetic provider).
from modules.story.tests.test_director_offline_workflow import (  # noqa: F401
    director_workflow,
)
from modules.story.world_progression_schemas import ProgressionParticipant


async def test_b7_director_last_round_completes_within_previewed_maximum(
    director_workflow,  # noqa: F811
):
    """README: the last selected round still completes when it reaches 80%.

    The author authorizes exactly the request maximum the budget preview shows.
    Every request of the selected rounds fits that limit, so the run must finish
    instead of pausing before the final request of the last round.
    """
    flow = director_workflow
    source = await read_director_source(
        flow.db,
        novel_id=flow.novel_id,
        scene_id=flow.scene_id,
        character_ids=[flow.actor],
        related_object_ids=[],
    )
    start = flow.start.model_copy(update={"operation_id": uuid4(), "rounds": 2})
    preview = preview_director_budget(start, source)
    start = start.model_copy(
        update={
            "request_limit": preview["request_count"]["maximum"],
            "budget_preview_hash": preview["preview_hash"],
        }
    )
    assert start.request_limit == 8

    accepted = await director_api.submit_director_start(flow.db, start)
    result = await flow.execute(accepted)

    assert flow.provider.calls <= start.request_limit
    assert result["status"] == "complete", result
    assert result["completed_rounds"] == 2


def test_b7_intent_audience_without_positions_is_rejected_before_resolution():
    """Director validation and simulation_v3 settlement must agree on audiences.

    In a Scene without exact location facts, an intent addressed to a participant
    the speaker verifiably knows either fails validation (before the paid
    resolution request) or settles. It must not pass validation and then raise.
    """
    speaker, listener = str(uuid4()), str(uuid4())
    intent = SimulationIntent(
        intent_id="whisper-1",
        actor=SimulationReference(kind="object", id=speaker),
        kind="speak",
        action="低声说：门外有人。",
        visibility="whisper",
        audience=[SimulationReference(kind="object", id=listener)],
    )
    participants = {speaker, listener}
    with pytest.raises(ValueError, match="同场位置"):
        validate_intents(
            [intent],
            participant_ids=participants,
            known_participant_ids={speaker: {listener}, listener: set()},
            participant_locations={},
            role_visible_object_ids={speaker: participants, listener: participants},
            role_visible_map_node_ids={speaker: set(), listener: set()},
            existing_object_ids=participants,
            existing_map_node_ids=set(),
        )

    with pytest.raises(ValueError, match="仍在场参与者"):
        validate_intents(
            [intent],
            participant_ids={speaker},
            known_participant_ids={speaker: {listener}, listener: set()},
            participant_locations={
                f"object:{speaker}": "north-gate",
                f"object:{listener}": "north-gate",
            },
            role_visible_object_ids={speaker: participants, listener: participants},
            role_visible_map_node_ids={speaker: set(), listener: set()},
            existing_object_ids=participants,
            existing_map_node_ids=set(),
        )


async def test_b7_resume_reuses_paid_intent_and_resolution_checkpoints(
    director_workflow,  # noqa: F811
):
    flow = director_workflow
    start = flow.start.model_copy(update={"operation_id": uuid4(), "request_limit": 2})
    accepted = await director_api.submit_director_start(flow.db, start)
    paused = await flow.execute(accepted)
    assert paused["status"] == "paused_budget"
    assert flow.provider.calls == 2

    root = await flow.db.get(StorySceneDirectorRoot, accepted.root_id)
    branch = await flow.db.scalar(
        select(StorySceneDirectorBranch).where(
            StorySceneDirectorBranch.root_id == root.id
        )
    )
    assert len(branch.pending_round_json["intents"]) == 1
    assert branch.pending_round_json["resolution"]
    preview = preview_director_resume(
        str(root.id), branch, AIRunEnvelope(read_ai_run_envelope(root.run_envelope_json))
    )
    request = DirectorContinueRequest(
        operation_id=uuid4(),
        novel_id=flow.novel_id,
        parent_round_id=None,
        resume_branch_id=branch.id,
        rounds=1,
        basis_choice="current",
        context_confirmation_id=start.context_confirmation_id,
        additional_requests=2,
        budget_preview_hash=preview["preview_hash"],
    )
    pending = branch.pending_round_json
    branch.pending_round_json = {**pending, "preview_binding_probe": True}
    with pytest.raises(ConflictError, match="检查点或累计账本已变化"):
        await director_api.continue_director_root(
            flow.db, root_id=str(root.id), data=request
        )
    assert flow.provider.calls == 2
    branch.pending_round_json = pending
    resumed = await director_api.continue_director_root(
        flow.db, root_id=str(root.id), data=request
    )
    duplicate = await director_api.continue_director_root(
        flow.db, root_id=str(root.id), data=request
    )
    assert resumed.task_id == duplicate.task_id
    with pytest.raises(ValueError, match="different request"):
        await director_api.continue_director_root(
            flow.db,
            root_id=str(root.id),
            data=request.model_copy(update={"additional_requests": 3}),
        )

    result = await flow.execute(resumed)
    assert result["status"] == "complete"
    assert flow.provider.calls == 4  # Two paid checkpoints were reused.
    rounds = list(
        (
            await flow.db.scalars(
                select(StorySceneDirectorRound).where(
                    StorySceneDirectorRound.root_id == root.id
                )
            )
        ).all()
    )
    assert len(rounds) == 1 and rounds[0].branch_id == branch.id
    assert branch.status == "complete" and branch.pending_round_json == {}


async def test_b7_resume_continues_after_completed_round_pause(
    director_workflow,  # noqa: F811
):
    from modules.story.director_context import read_director_source

    flow = director_workflow
    start = flow.start.model_copy(
        update={"operation_id": uuid4(), "request_limit": 4, "rounds": 2}
    )
    source = await read_director_source(
        flow.db,
        novel_id=flow.novel_id,
        scene_id=flow.scene_id,
        character_ids=[flow.actor],
        related_object_ids=[],
    )
    start.budget_preview_hash = preview_director_budget(start, source)["preview_hash"]
    accepted = await director_api.submit_director_start(flow.db, start)
    paused = await flow.execute(accepted)
    assert paused["status"] == "paused_budget" and paused["completed_rounds"] == 1
    assert flow.provider.calls == 4

    root = await flow.db.get(StorySceneDirectorRoot, accepted.root_id)
    branch = await flow.db.scalar(
        select(StorySceneDirectorBranch).where(
            StorySceneDirectorBranch.root_id == root.id
        )
    )
    assert branch.pending_round_json == {}
    preview = preview_director_resume(
        str(root.id), branch, AIRunEnvelope(read_ai_run_envelope(root.run_envelope_json))
    )
    request = DirectorContinueRequest(
        operation_id=uuid4(),
        novel_id=flow.novel_id,
        parent_round_id=None,
        resume_branch_id=branch.id,
        rounds=1,
        basis_choice="current",
        context_confirmation_id=start.context_confirmation_id,
        additional_requests=5,
        budget_preview_hash=preview["preview_hash"],
    )
    resumed = await director_api.continue_director_root(
        flow.db, root_id=str(root.id), data=request
    )
    result = await flow.execute(resumed)
    assert result["status"] == "complete" and result["completed_rounds"] == 1
    assert flow.provider.calls == 8
    rows = list(
        (
            await flow.db.scalars(
                select(StorySceneDirectorRound).where(
                    StorySceneDirectorRound.root_id == root.id
                )
            )
        ).all()
    )
    assert [row.round_number for row in rows] == [1, 2]
    assert len({row.branch_id for row in rows}) == 1


async def test_b7_resume_unknown_request_requires_duplicate_charge_ack(
    director_workflow,  # noqa: F811
):
    flow = director_workflow
    flow.provider.fail_next = True
    start = flow.start.model_copy(update={"operation_id": uuid4()})
    accepted = await director_api.submit_director_start(flow.db, start)
    paused = await flow.execute(accepted)
    assert paused["status"] == "paused_unknown" and flow.provider.calls == 1

    root = await flow.db.get(StorySceneDirectorRoot, accepted.root_id)
    branch = await flow.db.scalar(
        select(StorySceneDirectorBranch).where(
            StorySceneDirectorBranch.root_id == root.id
        )
    )
    preview = preview_director_resume(
        str(root.id), branch, AIRunEnvelope(read_ai_run_envelope(root.run_envelope_json))
    )
    request = DirectorContinueRequest(
        operation_id=uuid4(),
        novel_id=flow.novel_id,
        parent_round_id=None,
        resume_branch_id=branch.id,
        rounds=1,
        basis_choice="current",
        context_confirmation_id=start.context_confirmation_id,
        additional_requests=1,
        budget_preview_hash=preview["preview_hash"],
    )
    with pytest.raises(ConflictError, match="明确确认可能重复计费"):
        await director_api.continue_director_root(
            flow.db, root_id=str(root.id), data=request
        )
    assert flow.provider.calls == 1

    # The synthetic provider dispatches by call count; reset its script position
    # while retaining request history so the retry emits the intent schema.
    flow.provider.calls = 0
    request.allow_possible_duplicate_charge = True
    resumed = await director_api.continue_director_root(
        flow.db, root_id=str(root.id), data=request
    )
    result = await flow.execute(resumed)
    assert result["status"] == "complete", result
    assert flow.provider.calls == 4 and len(flow.provider.requests) == 5
    ledger = read_ai_run_envelope(root.run_envelope_json)
    assert ledger.authorizations[-1].reason.value == "duplicate_charge_confirmed"


@pytest.mark.asyncio
async def test_b7_progression_dossiers_are_intersected_with_confirmation(monkeypatch):
    actor, listener, scene_id = (str(uuid4()) for _ in range(3))
    novel_id = str(uuid4())
    raw_brief = {
        "scene_id": scene_id,
        "world_items": [
            {
                "entity_id": actor,
                "kind": "world_dossier",
                "entry_id": "confirmed-entry",
                "revision_id": "confirmed-revision",
                "facing_label": "背景",
                "content": "CONFIRMED_FACT",
            },
            {
                "entity_id": listener,
                "kind": "world_dossier",
                "entry_id": "excluded-entry",
                "revision_id": "excluded-revision",
                "facing_label": "秘密",
                "content": "EXCLUDED_SECRET",
            },
        ],
        "continuity_items": [
            {
                "entity_id": actor,
                "dimension": "entities",
                "field": "position",
                "value": "CONFIRMED_POSITION",
                "layer": "fact",
                "checkpoint_id": "confirmed-checkpoint",
            },
            {
                "entity_id": actor,
                "dimension": "entities",
                "field": "custody",
                "value": "EXCLUDED_STATE",
                "layer": "fact",
                "checkpoint_id": "excluded-checkpoint",
            },
        ],
        "pattern_items": [],
    }
    sections = ObjectDossierSectionBuilder.build(
        StructureContextBundle(
            novel_id=novel_id,
            task="world progression confirmation test",
            scope="scene",
            object_dossier_brief=raw_brief,
            object_reference_dimensions=["object_dossier"],
        ),
        None,
    )
    sections[0].items = [
        item
        for item in sections[0].items
        if item.key == "world:confirmed-entry" or "CONFIRMED_POSITION" in item.content
    ]
    confirmed = SimpleNamespace(compiled=CompiledContext(sections=sections))
    scene_context = {
        "novel_id": novel_id,
        "scene_id": scene_id,
        "context_hash": "scene-context",
        "outline_bundle": {"scene": {"id": scene_id, "scene_index": 1}},
    }
    observed_simulation_briefs = []

    async def scene_context_reader(_db, **_kwargs):
        return scene_context

    async def state_view(_db, *_args, **_kwargs):
        return {
            "scene_index": 1,
            "chapter_index": 2,
            "dimensions": [
                {"dimension": "timeline", "status": "missing", "facts": []},
                {"dimension": "entities", "status": "missing", "facts": []},
            ],
        }

    async def dossier_reader(_db, **_kwargs):
        return raw_brief

    async def identity_reader(_db, **_kwargs):
        return (
            [
                SimpleNamespace(
                    entity_id=actor, status="canonical", entity_type="character"
                ),
                SimpleNamespace(
                    entity_id=listener, status="canonical", entity_type="character"
                ),
            ],
            [],
        )

    async def simulation_builder(_db, **kwargs):
        observed_simulation_briefs.append(kwargs["brief"])
        return SimulationV3Context(
            participants=[
                SimulationReference(kind="object", id=actor),
                SimulationReference(kind="object", id=listener),
            ]
        )

    async def validate_refs(*_args, **_kwargs):
        return None

    async def map_reader(*_args, **_kwargs):
        return {
            "routes": [],
            "actor_routes": {},
            "coverage": "not_compared",
            "unknowns": [],
            "fingerprint": "map-state",
        }

    async def notices_reader(*_args):
        return []

    monkeypatch.setattr(
        world_progression_context, "get_scene_story_context", scene_context_reader
    )
    monkeypatch.setattr(world_progression_context, "get_scene_state_view", state_view)
    monkeypatch.setattr(
        world_progression_context, "read_object_dossier_brief", dossier_reader
    )
    monkeypatch.setattr(
        world_progression_context, "get_hidden_guard_sources", identity_reader
    )
    monkeypatch.setattr(
        world_progression_context, "build_scene_simulation_context", simulation_builder
    )
    monkeypatch.setattr(
        world_progression_context, "validate_simulation_context_refs", validate_refs
    )
    monkeypatch.setattr(world_progression_context, "get", lambda _key: notices_reader)

    source = await world_progression_context.read_progression_source(
        None,
        novel_id=novel_id,
        scene_id=scene_id,
        participants=[
            ProgressionParticipant(id=actor, kind="character"),
            ProgressionParticipant(id=listener, kind="character"),
        ],
        targets=[],
        confirmed_context=confirmed,
        map_reader=map_reader,
    )

    assert [item["entry_id"] for item in source["author_brief"]["world_items"]] == [
        "confirmed-entry"
    ]
    assert [
        item["value"] for item in source["author_brief"]["continuity_items"]
    ] == ["CONFIRMED_POSITION"]
    assert [
        item["value"]
        for item in source["role_briefs"][actor]["brief"]["continuity_items"]
    ] == ["CONFIRMED_POSITION"]
    assert "excluded-entry" not in source["role_briefs"][actor]["source_ids"]
    assert source["role_briefs"][actor]["known_participant_ids"] == [actor]
    assert "EXCLUDED_SECRET" not in json.dumps(
        [source["author_brief"], source["role_briefs"], observed_simulation_briefs]
    )

    narrowed = await world_progression_context.scope_progression_source(
        None,
        source,
        CompiledContext(sections=[]),
        expected_novel_id=novel_id,
        expected_scene_id=scene_id,
    )
    assert narrowed["author_brief"]["world_items"] == []
    assert narrowed["role_briefs"][actor]["known_participant_ids"] == [actor]
    assert narrowed["role_briefs"][actor]["source_ids"] == [f"world:entity:{actor}"]

    with pytest.raises(ValueError, match="缺少作品或 Scene 身份"):
        await world_progression_context.scope_progression_source(
            None,
            {**source, "scene_id": ""},
            CompiledContext(sections=[]),
            expected_novel_id=novel_id,
            expected_scene_id=scene_id,
        )
    with pytest.raises(ValueError, match="不匹配"):
        await world_progression_context.scope_progression_source(
            None,
            source,
            CompiledContext(sections=[]),
            expected_novel_id=novel_id,
            expected_scene_id=str(uuid4()),
        )


@pytest.mark.asyncio
async def test_b7_progression_source_fails_closed_without_confirmation():
    with pytest.raises(ValueError, match="必须重验原资料确认"):
        await world_progression_context.read_progression_source(
            None,
            novel_id=str(uuid4()),
            scene_id=str(uuid4()),
            participants=[],
            targets=[],
        )
