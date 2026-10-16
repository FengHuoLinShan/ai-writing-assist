"""Regression targets from the map-series review (T-20261016-map-series-claude-review).

Each case encodes the specified behavior for a confirmed review finding. Cases are
strict xfail while the defect is open: a fix turns them into an unexpected pass,
which fails the run until the marker is removed and the case becomes a plain
regression test.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from modules.story import director_api
from modules.story.director_budget import preview_director_budget
from modules.story.director_consistency import validate_intents
from modules.story.director_context import read_director_source
from modules.story.simulation_v3 import (
    FiniteResolution,
    SimulationIntent,
    SimulationReference,
    SimulationV3Context,
    resolve_simulation_v3,
)

# Reuse the offline Director workflow (rollback-only DB, synthetic provider).
from modules.story.tests.test_director_offline_workflow import (  # noqa: F401
    director_workflow,
)


@pytest.mark.xfail(
    strict=True,
    reason=(
        "B7-F1: the 80% line is checked before every provider request, so a run "
        "authorized with the previewed maximum pauses inside its last round"
    ),
)
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


@pytest.mark.xfail(
    strict=True,
    reason=(
        "B7-F2: validate_intents accepts a known participant as audience, but "
        "settlement raises when positions are unknown, after the paid resolution"
    ),
)
def test_b7_intent_audience_accepted_by_validation_settles_without_positions():
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
    try:
        validate_intents(
            [intent],
            participant_ids=participants,
            known_participant_ids={speaker: {listener}, listener: set()},
            role_visible_object_ids={speaker: participants, listener: participants},
            role_visible_map_node_ids={speaker: set(), listener: set()},
            existing_object_ids=participants,
            existing_map_node_ids=set(),
        )
    except ValueError:
        return  # rejected before the paid resolution request
    state = SimulationV3Context(
        participants=[
            SimulationReference(kind="object", id=item) for item in (speaker, listener)
        ]
    ).initial_state()
    resolve_simulation_v3(
        [intent],
        FiniteResolution(outcomes=[{"intent_id": "whisper-1", "outcome": "succeeded"}]),
        state,
        observers=set(state["participants"]) - set(state["departed"]),
        rule_revision="a" * 64,
    )
