from copy import deepcopy

import pytest

from modules.story.observations import (
    InputStimulus,
    ResolutionProposal,
    observe_stimuli,
    replay_batch,
    resolve_batch,
)
from modules.story.simulation import ActionIntent


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
