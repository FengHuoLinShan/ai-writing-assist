from copy import deepcopy

import pytest
from pydantic import ValidationError

from modules.story.observations import (
    InputStimulus,
    ObservationIntent,
    ResolutionBatch,
    ResolutionProposal,
    observe_stimuli,
    replay_batch,
    resolve_batch,
)
from modules.story.simulation import ActionIntent

GOLDEN_BASE_STATE_HASH = (
    "1d0fae5ef5d3615330e409faad20400"
    "4019eaca34872d882d1820deb6c6d23e7"
)
GOLDEN_INTENTS_HASH = (
    "0150d7cccac6efffe315e4098e97cb38"
    "d7439e81cfe0fd76d59d9505d32cb4c4"
)
GOLDEN_EVENT_ID = (
    "afed6d44030a6bdcd7e23ff4b2362268"
    "99294e3ad41bc2e42568ce3a6282917d"
)


def test_player_speech_action_and_out_of_scene_instruction_remain_distinct():
    observers = {"player", "a", "b"}
    inputs = [
        InputStimulus(
            actor_id="player",
            kind="speech",
            text="我知道门后是什么",
            visibility="whisper",
            audience=["a"],
            source_id="speech",
        ),
        InputStimulus(
            actor_id="player", kind="action", text="我一拳打倒对手", source_id="action"
        ),
        InputStimulus(
            actor_id="player",
            kind="instruction",
            text="场外：A其实是凶手",
            source_id="ooc",
        ),
    ]
    state = observe_stimuli({}, inputs, observers)
    assert "凶手" not in str(state)
    assert "门后" not in str(state["observations"]["b"])
    assert state["observations"]["a"][0]["outcome"] == "spoken_claim"
    assert state["observations"]["b"][0]["outcome"] == "pending"
    assert observe_stimuli(state, inputs, observers) == state


def test_failed_action_never_changes_resource_and_player_can_receive_npc_whisper():
    state = {"revision": 2, "resource_holders": {"钥匙": "keeper"}}
    baseline = deepcopy(state)
    intents = {
        "a": ActionIntent(kind="act", action="取得钥匙", resource_key="钥匙"),
        "b": ActionIntent(
            kind="speak", action="门后有人", visibility="whisper", audience=["player"]
        ),
    }
    batch = resolve_batch(
        intents,
        ResolutionProposal(
            outcomes=[
                {"actor_id": "a", "outcome": "failed"},
                {"actor_id": "b", "outcome": "succeeded"},
            ]
        ),
        state,
        observers={"a", "b", "player"},
        rule_revision="a" * 64,
    )
    result = replay_batch(state, batch)
    assert state == baseline
    assert result["resource_holders"]["钥匙"] == "keeper"
    assert "未成功" in result["observations"]["a"][0]["action"]
    assert "门后有人" in str(result["observations"]["player"])
    assert "门后有人" not in str(result["observations"]["a"])
    assert replay_batch(state, batch) == result
    with pytest.raises(ValueError, match="different state"):
        replay_batch(result, batch)


def test_unique_resource_race_remains_uncertain_and_unregistered_observer_is_rejected():
    intents = {
        actor: ActionIntent(kind="act", action="取得钥匙", resource_key="钥匙")
        for actor in ("a", "b")
    }
    batch = resolve_batch(
        intents,
        ResolutionProposal(
            outcomes=[{"actor_id": actor, "outcome": "succeeded"} for actor in intents]
        ),
        {},
        observers={"a", "b"},
        rule_revision="b" * 64,
    )
    assert set(batch.unresolved_outcomes) == {"a", "b"}
    assert replay_batch({}, batch)["resource_holders"] == {}
    with pytest.raises(ValueError):
        observe_stimuli(
            {},
            [
                InputStimulus(
                    actor_id="a",
                    kind="speech",
                    text="秘密",
                    visibility="whisper",
                    audience=["outsider"],
                    source_id="s",
                )
            ],
            {"a", "b"},
        )


def test_beliefs_are_private_and_movement_requires_declared_route():
    from modules.story.observations import ObservationIntent, SimulationSeed, seeded_state

    seed = SimulationSeed(
        resource_holders={"铜钥匙": None},
        locations={"a": "门厅", "b": "门厅"},
        location_catalog=["门厅", "走廊"],
        routes=[("门厅", "走廊")],
    )
    state = seeded_state(seed, {"a", "b"})
    event_id = state["observations"]["a"][0]["event_id"]
    intent = ObservationIntent(
        kind="act",
        action="拿起钥匙并走向走廊",
        resource_key="铜钥匙",
        destination="走廊",
        beliefs=[
            {
                "key": "key",
                "statement": "我猜这把钥匙能打开走廊的门",
                "stance": "believes",
                "evidence_events": [event_id],
            }
        ],
    )
    batch = resolve_batch(
        {"a": intent},
        ResolutionProposal(outcomes=[{"actor_id": "a", "outcome": "succeeded"}]),
        state,
        observers={"a", "b"},
        rule_revision="a" * 64,
    )
    next_state = replay_batch(state, batch)
    assert next_state["resource_holders"]["铜钥匙"] == "a"
    assert next_state["locations"]["a"] == "走廊"
    assert next_state["beliefs"]["a"]["key"]["stance"] == "believes"
    assert "我猜" not in str(next_state["observations"]["b"])
    spoken = observe_stimuli(
        next_state,
        [
            InputStimulus(
                actor_id="a", kind="speech", text="走廊里的低语", source_id="later"
            )
        ],
        {"a", "b"},
    )
    assert "低语" not in str(spoken["observations"]["b"])
    bad = intent.model_copy(update={"destination": "未提供的密室"})
    rejected = resolve_batch(
        {"a": bad},
        ResolutionProposal(outcomes=[{"actor_id": "a", "outcome": "succeeded"}]),
        state,
        observers={"a", "b"},
        rule_revision="a" * 64,
    )
    assert rejected.unresolved_outcomes == ["a"]
    assert replay_batch(state, rejected)["locations"]["a"] == "门厅"
    bad = intent.model_copy(
        update={
            "beliefs": [
                intent.beliefs[0].model_copy(update={"evidence_events": ["private-b"]})
            ]
        }
    )
    with pytest.raises(ValueError, match="own observations"):
        resolve_batch(
            {"a": bad},
            ResolutionProposal(outcomes=[{"actor_id": "a", "outcome": "succeeded"}]),
            state,
            observers={"a", "b"},
            rule_revision="a" * 64,
        )


def test_unresolved_player_claim_cannot_be_promoted_by_resolver():
    from modules.story.observations import (
        ObservationIntent,
        ResolutionProposal,
        resolve_batch,
    )

    state = {
        "revision": 0,
        "observations": {},
        "resource_holders": {"钥匙": "guard"},
        "locations": {"player": "hall", "guard": "tower"},
        "departed": [],
    }
    intents = {
        "player": ObservationIntent(
            kind="act", action="我已经拿到了钥匙", resource_key="钥匙"
        )
    }
    batch = resolve_batch(
        intents,
        ResolutionProposal(outcomes=[{"actor_id": "player", "outcome": "succeeded"}]),
        state,
        observers={"player", "guard"},
        rule_revision="a" * 64,
    )
    assert batch.events[0]["outcome"] == "uncertain"
    assert not any(patch.kind == "resource_holder" for patch in batch.state_patches)
    intents = {
        "player": ObservationIntent(
            kind="act", action="我一步完成三个动作", unresolved=True
        )
    }
    batch = resolve_batch(
        intents,
        ResolutionProposal(outcomes=[{"actor_id": "player", "outcome": "succeeded"}]),
        state,
        observers={"player", "guard"},
        rule_revision="a" * 64,
    )
    assert batch.unresolved_outcomes == ["player"]


def test_observation_v2_replay_golden_for_existing_rp_round():
    """Freeze the pre-v3 observer batch and replay bytes for existing RP runs."""
    state = {
        "revision": 0,
        "resource_holders": {"key-1": "actor-2"},
        "locations": {"actor-1": "hall"},
        "location_catalog": ["hall"],
        "routes": [],
        "observations": {},
        "departed": [],
    }
    batch = resolve_batch(
        {
            "actor-1": ObservationIntent(
                kind="act", action="取钥匙", resource_key="key-1"
            )
        },
        ResolutionProposal(
            outcomes=[{"actor_id": "actor-1", "outcome": "succeeded"}]
        ),
        state,
        observers={"actor-1", "actor-2"},
        rule_revision="a" * 64,
    )
    replayed = replay_batch(state, batch)

    assert batch.model_dump(mode="json") == {
        "protocol": "observation_v2",
        "base_state_revision": 0,
        "base_state_hash": GOLDEN_BASE_STATE_HASH,
        "intents_hash": GOLDEN_INTENTS_HASH,
        "rule_revision": "a" * 64,
        "events": [
            {
                "actor_id": "actor-1",
                "event_type": "resolved_action",
                "kind": "act",
                "action": "取钥匙",
                "outcome": "succeeded",
                "visibility": "public",
                "observers": ["actor-1", "actor-2"],
                "truth": "simulated_outcome",
                "event_id": GOLDEN_EVENT_ID,
            }
        ],
        "state_patches": [
            {
                "kind": "observation",
                "key": "actor-1",
                "before": None,
                "after": {
                    "actor_id": "actor-1",
                    "event_type": "resolved_action",
                    "kind": "act",
                    "action": "取钥匙",
                    "outcome": "succeeded",
                    "visibility": "public",
                    "truth": "simulated_outcome",
                    "event_id": GOLDEN_EVENT_ID,
                },
            },
            {
                "kind": "observation",
                "key": "actor-2",
                "before": None,
                "after": {
                    "actor_id": "actor-1",
                    "event_type": "resolved_action",
                    "kind": "act",
                    "action": "取钥匙",
                    "outcome": "succeeded",
                    "visibility": "public",
                    "truth": "simulated_outcome",
                    "event_id": GOLDEN_EVENT_ID,
                },
            },
            {
                "kind": "resource_holder",
                "key": "key-1",
                "before": "actor-2",
                "after": "actor-1",
            },
        ],
        "unresolved_outcomes": [],
        "assumptions": ["这是给定资料与规则下的一次模拟裁决，不是事实证明。"],
    }
    assert replayed == {
        "revision": 1,
        "resource_holders": {"key-1": "actor-1"},
        "locations": {"actor-1": "hall"},
        "location_catalog": ["hall"],
        "routes": [],
        "observations": {
            "actor-1": [
                {
                    "actor_id": "actor-1",
                    "event_type": "resolved_action",
                    "kind": "act",
                    "action": "取钥匙",
                    "outcome": "succeeded",
                    "visibility": "public",
                    "truth": "simulated_outcome",
                    "event_id": GOLDEN_EVENT_ID,
                }
            ],
            "actor-2": [
                {
                    "actor_id": "actor-1",
                    "event_type": "resolved_action",
                    "kind": "act",
                    "action": "取钥匙",
                    "outcome": "succeeded",
                    "visibility": "public",
                    "truth": "simulated_outcome",
                    "event_id": GOLDEN_EVENT_ID,
                }
            ],
        },
        "departed": [],
    }


def test_observation_v2_resolution_batch_keeps_its_historical_limit():
    data = {
        "protocol": "observation_v2",
        "base_state_revision": 0,
        "base_state_hash": "a" * 64,
        "intents_hash": "b" * 64,
        "rule_revision": "c" * 64,
        "events": [{} for _ in range(17)],
    }
    with pytest.raises(ValidationError, match="observation_v2 batch"):
        ResolutionBatch.model_validate(data)
