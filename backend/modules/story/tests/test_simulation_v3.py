import pytest

from modules.story.simulation_v3 import (
    FiniteOutcome,
    FiniteResolution,
    SimulationBeliefChange,
    SimulationIntent,
    SimulationPosition,
    SimulationReference,
    SimulationResourceHolder,
    SimulationRoute,
    SimulationV3Context,
    replay_batch,
    resolve_simulation_v3,
)


def _object(identifier: str) -> SimulationReference:
    return SimulationReference(kind="object", id=identifier)


def test_simulation_v3_context_has_typed_identities_and_no_actor_or_location_caps():
    actors = [_object(f"actor-{index}") for index in range(8)]
    locations = [
        SimulationReference(kind="map_node", id=f"node-{index}") for index in range(6)
    ]
    candidate = SimulationReference(
        kind="candidate", id="candidate-1", label="临时登场者"
    )
    text_label = SimulationReference(kind="text_label", text="只作描述的堂屋")
    resources = [
        SimulationResourceHolder(resource=_object(f"resource-{index}"), holder=actors[0])
        for index in range(7)
    ]
    context = SimulationV3Context(
        participants=[*actors, candidate],
        locations=[*locations, text_label],
        positions=[SimulationPosition(subject=actors[0], location=locations[0])],
        resources=resources,
        routes=[
            SimulationRoute(origin=left, destination=right)
            for left, right in zip(locations, locations[1:])
        ],
    )

    state = context.initial_state()
    intent = SimulationIntent(
        intent_id="wide-audience",
        actor=actors[0],
        kind="speak",
        action="把消息告诉所有在场者",
        visibility="whisper",
        audience=[*actors[1:], candidate],
    )
    assert len(context.participants) == 9
    assert len(state["location_catalog"]) == 7
    assert len(intent.audience) == 8
    assert state["resource_holders"]["object:resource-6"] == "object:actor-0"
    assert candidate.state_key.startswith("candidate:")
    assert text_label.state_key.startswith("text_label:")
    assert _object("candidate:candidate-1").state_key != candidate.state_key
    with pytest.raises(ValueError, match="typed locations"):
        SimulationV3Context(
            participants=actors,
            locations=locations,
            positions=[
                SimulationPosition(
                    subject=actors[0],
                    location=SimulationReference(kind="text_label", text="未登记地点"),
                )
            ],
        )


def test_simulation_v3_requires_typed_reference_shapes():
    with pytest.raises(ValueError, match="existing references"):
        SimulationReference(kind="object", label="伪装成对象 ID 的标签")
    with pytest.raises(ValueError, match="text labels"):
        SimulationReference(kind="text_label", id="object-1", text="堂屋")
    with pytest.raises(ValueError, match="destination"):
        SimulationIntent(
            intent_id="move-1",
            actor=_object("actor-1"),
            kind="move",
            action="前往堂屋",
            effect="move",
        )


@pytest.mark.parametrize(
    ("actor_location", "witness_location", "witness_can_observe"),
    [
        (None, "elsewhere", False),
        (None, None, False),
        ("hall", None, False),
        ("hall", "hall", True),
        ("hall", "elsewhere", False),
    ],
)
def test_public_event_requires_known_shared_location_for_other_observers(
    actor_location: str | None,
    witness_location: str | None,
    witness_can_observe: bool,
):
    actor, witness = _object("actor-1"), _object("actor-2")
    locations = {}
    if actor_location:
        locations[actor.state_key] = f"candidate:{actor_location}"
    if witness_location:
        locations[witness.state_key] = f"candidate:{witness_location}"
    state = {
        "revision": 0,
        "observations": {},
        "locations": locations,
    }
    intent = SimulationIntent(
        intent_id="say-1",
        actor=actor,
        kind="speak",
        action="我持有钥匙",
        visibility="public",
    )
    batch = resolve_simulation_v3(
        [intent],
        FiniteResolution(outcomes=[{"intent_id": "say-1", "outcome": "succeeded"}]),
        state,
        observers={actor.state_key, witness.state_key},
        rule_revision="a" * 64,
    )
    expected_observers = (
        [actor.state_key, witness.state_key] if witness_can_observe else [actor.state_key]
    )
    assert batch.events[0]["observers"] == expected_observers
    replayed = replay_batch(state, batch)
    assert (witness.state_key in replayed["observations"]) is witness_can_observe


def test_simulation_v3_applies_only_successful_transfer_and_replays_exactly():
    actor, recipient, resource = _object("actor-1"), _object("actor-2"), _object("key-1")
    state = {
        "revision": 4,
        "participants": [actor.state_key, recipient.state_key],
        "observations": {},
        "resource_holders": {resource.state_key: actor.state_key},
        "departed": [],
    }
    intent = SimulationIntent(
        intent_id="transfer-1",
        actor=actor,
        kind="transfer_key",
        action="把钥匙交给乙",
        effect="resource_transfer",
        resource=resource,
        recipient=recipient,
        visibility="private",
    )
    original = dict(state)
    batch = resolve_simulation_v3(
        [intent],
        FiniteResolution(
            outcomes=[FiniteOutcome(intent_id="transfer-1", outcome="succeeded")]
        ),
        state,
        observers={actor.state_key, recipient.state_key},
        rule_revision="a" * 64,
    )

    replayed = replay_batch(state, batch)
    assert batch.protocol == "simulation_v3"
    assert state == original
    assert replayed["resource_holders"][resource.state_key] == recipient.state_key
    assert batch.events[0]["outcome"] == "succeeded"
    assert replay_batch(state, batch) == replayed
    with pytest.raises(ValueError, match="different state"):
        replay_batch(replayed, batch)

    failed = resolve_simulation_v3(
        [intent],
        FiniteResolution(
            outcomes=[FiniteOutcome(intent_id="transfer-1", outcome="failed")]
        ),
        state,
        observers={actor.state_key, recipient.state_key},
        rule_revision="a" * 64,
    )
    assert not any(delta.kind == "resource_holder" for delta in failed.state_patches)
    replayed_failed = replay_batch(state, failed)
    assert replayed_failed["resource_holders"][resource.state_key] == actor.state_key

    invented_world_recipient = intent.model_copy(
        update={"recipient": _object("not-a-declared-participant")}
    )
    unproven = resolve_simulation_v3(
        [invented_world_recipient],
        FiniteResolution(outcomes=[{"intent_id": "transfer-1", "outcome": "succeeded"}]),
        state,
        observers={actor.state_key, recipient.state_key},
        rule_revision="a" * 64,
    )
    assert unproven.events[0]["outcome"] == "uncertain"
    assert not any(delta.kind == "resource_holder" for delta in unproven.state_patches)


def test_simulation_v3_move_conflict_and_belief_evidence_are_finite():
    actor, witness = _object("actor-1"), _object("actor-2")
    hall = SimulationReference(kind="map_node", id="node-hall")
    tower = SimulationReference(kind="map_node", id="node-tower")
    state = {
        "revision": 0,
        "observations": {
            actor.state_key: [{"event_id": "observed-1"}],
            witness.state_key: [],
        },
        "resource_holders": {},
        "locations": {actor.state_key: hall.state_key},
        "location_catalog": [hall.state_key, tower.state_key],
        "routes": [[hall.state_key, tower.state_key]],
        "departed": [],
    }
    move = SimulationIntent(
        intent_id="move-1",
        actor=actor,
        kind="move",
        action="前往塔楼",
        effect="move",
        destination=tower,
    )
    belief = SimulationIntent(
        intent_id="belief-1",
        actor=actor,
        kind="reflect",
        action="相信门后有人",
        effect="belief_change",
        beliefs=[
            SimulationBeliefChange(
                key="door",
                statement="门后有人",
                stance="believes",
                evidence_events=["observed-1"],
            )
        ],
    )
    batch = resolve_simulation_v3(
        [move, belief],
        FiniteResolution(
            outcomes=[
                {"intent_id": "move-1", "outcome": "succeeded"},
                {"intent_id": "belief-1", "outcome": "succeeded"},
            ]
        ),
        state,
        observers={actor.state_key, witness.state_key},
        rule_revision="b" * 64,
    )
    replayed = replay_batch(state, batch)
    assert replayed["locations"][actor.state_key] == tower.state_key
    assert replayed["beliefs"][actor.state_key]["door"]["statement"] == "门后有人"

    unsupported_evidence = belief.beliefs[0].model_copy(
        update={"evidence_events": ["private"]}
    )
    bad_belief = belief.model_copy(update={"beliefs": [unsupported_evidence]})
    with pytest.raises(ValueError, match="own observations"):
        resolve_simulation_v3(
            [bad_belief],
            FiniteResolution(
                outcomes=[{"intent_id": "belief-1", "outcome": "succeeded"}]
            ),
            state,
            observers={actor.state_key, witness.state_key},
            rule_revision="b" * 64,
        )
