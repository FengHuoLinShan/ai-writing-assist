"""V2 observation and resolution protocol, independent of agents and storage."""

from __future__ import annotations

from copy import deepcopy
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from infrastructure.llm.collaboration import content_hash


class ObservationModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReaderBelief(ObservationModel):
    belief: str = Field(min_length=1, max_length=1500)
    excerpt: str = Field(min_length=1, max_length=1000)
    interpretation: str = Field(default="", max_length=1500)


class ReadingNode(ObservationModel):
    known: list[ReaderBelief] = Field(default_factory=list, max_length=15)
    guesses: list[ReaderBelief] = Field(default_factory=list, max_length=15)
    unanswered: list[str] = Field(default_factory=list, max_length=12)
    newly_revealed: list[ReaderBelief] = Field(default_factory=list, max_length=10)


class ActionIntent(ObservationModel):
    kind: Literal["act", "speak", "observe", "wait", "leave"]
    action: str = Field(min_length=1, max_length=1500)
    internal_reason: str = Field(default="", max_length=1500)
    visibility: Literal["public", "private", "whisper"] = "public"
    audience: list[str] = Field(default_factory=list, max_length=3)
    resource_key: str | None = Field(default=None, min_length=1, max_length=120)


class BeliefChange(ObservationModel):
    key: str = Field(min_length=1, max_length=120)
    statement: str = Field(min_length=1, max_length=1500)
    stance: Literal["believes", "doubts", "unknown"]
    evidence_events: list[str] = Field(min_length=1, max_length=12)


class ObservationIntent(ActionIntent):
    unresolved: bool = False
    destination: str | None = Field(default=None, min_length=1, max_length=120)
    beliefs: list[BeliefChange] = Field(default_factory=list, max_length=8)

    @model_validator(mode="after")
    def physical_actions(self):
        if self.resource_key and self.kind != "act":
            raise ValueError("Only an action attempt can transfer a physical resource")
        if self.destination and self.kind not in {"act", "leave"}:
            raise ValueError("Speaking or observing cannot move the subject")
        if len({belief.key for belief in self.beliefs}) != len(self.beliefs):
            raise ValueError("A belief can only change once per round")
        return self


class SimulationSeed(ObservationModel):
    resource_holders: dict[str, str | None] = Field(default_factory=dict, max_length=40)
    locations: dict[str, str] = Field(default_factory=dict, max_length=4)
    location_catalog: list[str] = Field(default_factory=list, max_length=40)
    routes: list[tuple[str, str]] = Field(default_factory=list, max_length=80)
    assumptions: list[str] = Field(default_factory=list, max_length=12)

    @model_validator(mode="after")
    def finite_locations(self):
        if set(self.locations.values()) - set(self.location_catalog) or any(
            source not in self.location_catalog or target not in self.location_catalog
            for source, target in self.routes
        ):
            raise ValueError("Scenario locations and routes must be declared")
        if any(not 1 <= len(key) <= 120 for key in self.resource_holders):
            raise ValueError("Scenario resources need short distinct labels")
        if len(self.location_catalog) != len(set(self.location_catalog)):
            raise ValueError("Scenario locations cannot be duplicated")
        return self


def seeded_state(seed, actors):
    state = {"observations": {}, "resource_holders": {}, "departed": []}
    if seed is None:
        return state
    state.update(seed.model_dump(mode="json"))
    if set(seed.locations) - set(actors) or set(seed.resource_holders.values()) - {
        None,
        *actors,
    }:
        raise ValueError("Initial holders and locations must belong to selected actors")
    for resource, holder in seed.resource_holders.items():
        event = {
            "event_id": content_hash(["scenario_seed", resource, holder]),
            "event_type": "scenario_assumption",
            "resource_key": resource,
            "action": f"试验初始公开物品：{resource}",
            "truth": "author_supplied_scenario",
        }
        for actor in actors:
            state["observations"].setdefault(actor, []).append(event)
    return state


class InputStimulus(ObservationModel):
    actor_id: str = Field(min_length=1, max_length=100)
    kind: Literal["speech", "action", "instruction", "narration"]
    text: str = Field(min_length=1, max_length=12000)
    visibility: Literal["public", "whisper", "private"] = "public"
    audience: list[str] = Field(default_factory=list, max_length=4)
    source_id: str = Field(min_length=1, max_length=100)


class ObservationPacket(ObservationModel):
    observer_id: str
    state_revision: int = Field(ge=0)
    events: list[dict] = Field(default_factory=list, max_length=1000)
    history_complete: bool = False


class ResolutionOutcome(ObservationModel):
    actor_id: str
    outcome: Literal["succeeded", "failed", "uncertain"]


class ResolutionProposal(ObservationModel):
    outcomes: list[ResolutionOutcome] = Field(default_factory=list, max_length=4)


class StateDelta(ObservationModel):
    kind: Literal["resource_holder", "departed", "observation", "location", "belief"]
    key: str
    before: str | bool | dict | None = None
    after: str | bool | dict


class ResolutionBatch(ObservationModel):
    protocol: Literal["observation_v2"] = "observation_v2"
    base_state_revision: int = Field(ge=0)
    base_state_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    intents_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    rule_revision: str = Field(pattern=r"^[a-f0-9]{64}$")
    events: list[dict] = Field(max_length=16)
    state_patches: list[StateDelta] = Field(max_length=100)
    unresolved_outcomes: list[str] = Field(default_factory=list, max_length=4)
    assumptions: list[str] = Field(default_factory=list, max_length=12)


def recipients(actor, visibility, audience, observers, state=None):
    locations = (state or {}).get("locations", {})
    origin = locations.get(actor)
    if origin is not None:
        observers = {
            person for person in observers if locations.get(person, origin) == origin
        }
    if actor not in observers or set(audience) - observers:
        raise ValueError("Observation recipients must belong to this scene")
    if visibility == "private":
        return [actor]
    return sorted(observers if visibility == "public" else {actor, *audience})


def observe_stimuli(state, stimuli, observers):
    """Only speech is a delivered claim. Actions are perceptible attempts, not results."""
    updated = deepcopy(state)
    updated.setdefault("observations", {})
    for stimulus in stimuli:
        if stimulus.kind in {"instruction", "narration"}:
            continue
        visible = recipients(
            stimulus.actor_id, stimulus.visibility, stimulus.audience, observers, state
        )
        event = {
            "event_type": "utterance" if stimulus.kind == "speech" else "action_attempt",
            "actor_id": stimulus.actor_id,
            "action": stimulus.text,
            "source_id": stimulus.source_id,
            "event_id": content_hash([stimulus.source_id, stimulus.kind, stimulus.text]),
            "outcome": "spoken_claim" if stimulus.kind == "speech" else "pending",
            "truth": "not_established",
            "visibility": stimulus.visibility,
        }
        for observer in visible:
            history = updated["observations"].setdefault(observer, [])
            if not any(
                item.get("source_id") == stimulus.source_id
                and item.get("event_type") == event["event_type"]
                for item in history
            ):
                history.append(event)
    return updated


def speech_events(stimuli, observers, state=None):
    return [
        {
            "event_type": "utterance",
            "actor_id": item.actor_id,
            "kind": "speak",
            "action": item.text,
            "outcome": "spoken_claim",
            "truth": "not_established",
            "visibility": item.visibility,
            "source_id": item.source_id,
            "observers": recipients(
                item.actor_id, item.visibility, item.audience, observers, state
            ),
        }
        for item in stimuli
        if item.kind == "speech"
    ]


def resolve_batch(intents, resolution, state, *, observers, rule_revision):
    actors = set(intents)
    outcomes = {item.actor_id: item.outcome for item in resolution.outcomes}
    if (
        len(outcomes) != len(resolution.outcomes)
        or set(outcomes) != actors
        or not actors <= observers
    ):
        raise ValueError("Every acting subject needs exactly one outcome")
    claimed = {}
    for actor, intent in intents.items():
        if intent.resource_key and outcomes[actor] == "succeeded":
            claimed.setdefault(intent.resource_key, []).append(actor)
    for claimants in claimed.values():
        if len(claimants) > 1:
            for actor in claimants:
                outcomes[actor] = "uncertain"
    patches, events = [], []
    holders = state.get("resource_holders", {})
    for actor, intent in intents.items():
        observers_for_event = recipients(
            actor, intent.visibility, intent.audience, observers, state
        )
        outcome = outcomes[actor]
        if outcome == "succeeded" and getattr(intent, "unresolved", False):
            outcome = outcomes[actor] = "uncertain"
        if (
            outcome == "succeeded"
            and intent.resource_key
            and intent.resource_key not in holders
        ):
            outcome = outcomes[actor] = "uncertain"
        holder = holders.get(intent.resource_key)
        locations = state.get("locations", {})
        if (
            outcome == "succeeded"
            and intent.resource_key
            and holder is not None
            and holder != actor
            and (
                holder not in observers
                or holder in state.get("departed", [])
                or locations.get(holder) is not None
                and locations.get(actor) != locations[holder]
            )
        ):
            outcome = outcomes[actor] = "uncertain"
        destination = getattr(intent, "destination", None)
        if destination:
            origin = state.get("locations", {}).get(actor)
            routes = {tuple(route) for route in state.get("routes", [])}
            if destination not in state.get("location_catalog", []) or (
                origin != destination and (origin, destination) not in routes
            ):
                outcome = outcomes[actor] = "uncertain"
        observed = {
            event.get("event_id") or event.get("source_id")
            for event in state.get("observations", {}).get(actor, [])
        }
        for belief in getattr(intent, "beliefs", []):
            if set(belief.evidence_events) - observed:
                raise ValueError(
                    "Belief changes must cite the subject's own observations"
                )
            patches.append(
                StateDelta(
                    kind="belief",
                    key=f"{actor}:{belief.key}",
                    before=state.get("beliefs", {}).get(actor, {}).get(belief.key),
                    after={
                        "actor_id": actor,
                        "key": belief.key,
                        **belief.model_dump(mode="json"),
                    },
                )
            )
        if intent.kind == "speak" and outcome != "succeeded":
            observers_for_event = [actor]
        # The resolver cannot invent prose for a less-informed recipient.
        # Observable wording comes only from the acting subject's restricted intent.
        action = (
            intent.action
            if outcome == "succeeded"
            else f"尝试：{intent.action}；"
            + ("未成功。" if outcome == "failed" else "结果仍未确定。")
        )
        event = {
            "actor_id": actor,
            "event_type": "utterance"
            if intent.kind == "speak" and outcome == "succeeded"
            else "resolved_action",
            "kind": intent.kind,
            "action": action,
            "outcome": outcome,
            "visibility": intent.visibility,
            "observers": observers_for_event,
            "truth": "spoken_claim" if intent.kind == "speak" else "simulated_outcome",
        }
        event["event_id"] = content_hash(
            [content_hash(state), actor, intent.model_dump(mode="json"), outcome]
        )
        if outcome == "succeeded" and destination:
            patches.append(
                StateDelta(
                    kind="location",
                    key=actor,
                    before=state.get("locations", {}).get(actor),
                    after=destination,
                )
            )
        events.append(event)
        # Failed speech is not delivered; private unsuccessful intentions stay private.
        for observer in (
            observers_for_event
            if intent.kind != "speak" or outcome == "succeeded"
            else [actor]
        ):
            patches.append(
                StateDelta(
                    kind="observation",
                    key=observer,
                    after={
                        key: value for key, value in event.items() if key != "observers"
                    },
                )
            )
        if outcome == "succeeded" and intent.resource_key:
            patches.append(
                StateDelta(
                    kind="resource_holder",
                    key=intent.resource_key,
                    before=holders.get(intent.resource_key),
                    after=actor,
                )
            )
        if outcome == "succeeded" and intent.kind == "leave":
            patches.append(
                StateDelta(
                    kind="departed",
                    key=actor,
                    before=actor in state.get("departed", []),
                    after=True,
                )
            )
    return ResolutionBatch(
        base_state_revision=state.get("revision", 0),
        base_state_hash=content_hash(state),
        intents_hash=content_hash(
            {actor: intent.model_dump(mode="json") for actor, intent in intents.items()}
        ),
        rule_revision=rule_revision,
        events=events,
        state_patches=patches,
        unresolved_outcomes=[
            actor for actor, outcome in outcomes.items() if outcome == "uncertain"
        ],
        assumptions=["这是给定资料与规则下的一次模拟裁决，不是事实证明。"],
    )


def replay_batch(state, batch: ResolutionBatch):
    """Replay stored events/deltas exactly; no provider call or random re-sampling."""
    if (
        state.get("revision", 0) != batch.base_state_revision
        or content_hash(state) != batch.base_state_hash
    ):
        raise ValueError("Resolution batch belongs to a different state revision")
    updated = deepcopy(state)
    updated.setdefault("resource_holders", {})
    updated.setdefault("observations", {})
    updated.setdefault("departed", [])
    for patch in batch.state_patches:
        if patch.kind == "resource_holder":
            if updated["resource_holders"].get(patch.key) != patch.before:
                raise ValueError("Resource state changed before resolution")
            updated["resource_holders"][patch.key] = patch.after
        elif patch.kind == "departed":
            if (patch.key in updated["departed"]) != patch.before:
                raise ValueError("Presence changed before resolution")
            if patch.after and patch.key not in updated["departed"]:
                updated["departed"].append(patch.key)
        elif patch.kind == "location":
            locations = updated.setdefault("locations", {})
            if locations.get(patch.key) != patch.before:
                raise ValueError("Location changed before resolution")
            locations[patch.key] = patch.after
        elif patch.kind == "belief":
            value = patch.after
            beliefs = updated.setdefault("beliefs", {}).setdefault(value["actor_id"], {})
            if beliefs.get(value["key"]) != patch.before:
                raise ValueError("Belief changed before resolution")
            beliefs[value["key"]] = value
        else:
            updated["observations"].setdefault(patch.key, []).append(patch.after)
    updated["revision"] = batch.base_state_revision + 1
    # ponytail: keep 128 recent observations per subject; older immutable state
    # revisions remain the audit trail. A reader must not assume full recall.
    for actor, events in updated["observations"].items():
        if len(events) > 128:
            history = updated.setdefault("observation_history", {})
            history[actor] = {
                "complete": False,
                "omitted": history.get(actor, {}).get("omitted", 0) + len(events) - 128,
            }
            updated["observations"][actor] = events[-128:]
    return updated
