"""Versioned intent, finite resolution, and replay protocol for Story simulations."""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from infrastructure.llm.collaboration import content_hash


class SimulationV3Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SimulationReference(SimulationV3Model):
    """A typed reference; candidates and labels cannot be mistaken for World IDs."""

    kind: Literal["object", "map_node", "candidate", "text_label"]
    id: str | None = Field(default=None, min_length=1)
    label: str | None = Field(default=None, min_length=1)
    text: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def valid_reference_shape(self):
        if self.kind in {"object", "map_node"}:
            if self.id is None or self.text is not None:
                raise ValueError("existing references need an object or map node ID")
        elif self.kind == "candidate":
            if self.id is None or self.label is None or self.text is not None:
                raise ValueError("candidate references need their own ID and label")
        elif self.id is not None or self.label is not None or self.text is None:
            raise ValueError("text labels must remain explicit labels, not IDs")
        return self

    @property
    def state_key(self) -> str:
        if self.kind == "object":
            return f"object:{self.id}"
        if self.kind == "map_node":
            return f"map_node:{self.id}"
        if self.kind == "candidate":
            return f"candidate:{self.id}"
        digest = sha256(str(self.text).encode("utf-8")).hexdigest()
        return f"text_label:{digest}"

    @property
    def public_id(self) -> str:
        if self.kind in {"object", "map_node"}:
            return str(self.id)
        return self.state_key


class SimulationPosition(SimulationV3Model):
    subject: SimulationReference
    location: SimulationReference


class SimulationResourceHolder(SimulationV3Model):
    resource: SimulationReference
    holder: SimulationReference | None = None


class SimulationRoute(SimulationV3Model):
    origin: SimulationReference
    destination: SimulationReference


class SimulationV3Context(SimulationV3Model):
    """Typed simulation facts. Lists intentionally have no product count limit."""

    participants: list[SimulationReference] = Field(default_factory=list)
    locations: list[SimulationReference] = Field(default_factory=list)
    positions: list[SimulationPosition] = Field(default_factory=list)
    resources: list[SimulationResourceHolder] = Field(default_factory=list)
    routes: list[SimulationRoute] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_context_references(self):
        participant_keys = [item.state_key for item in self.participants]
        location_keys = [item.state_key for item in self.locations]
        resource_keys = [item.resource.state_key for item in self.resources]
        position_keys = [item.subject.state_key for item in self.positions]
        if len(participant_keys) != len(set(participant_keys)):
            raise ValueError("simulation participants must be unique")
        if len(location_keys) != len(set(location_keys)):
            raise ValueError("simulation locations must be unique")
        if len(resource_keys) != len(set(resource_keys)):
            raise ValueError("simulation resources must be unique")
        if len(position_keys) != len(set(position_keys)):
            raise ValueError("each participant can have only one initial position")
        if set(position_keys) - set(participant_keys):
            raise ValueError("initial positions must belong to declared participants")
        if {item.location.state_key for item in self.positions} - set(location_keys):
            raise ValueError("initial positions must use declared typed locations")
        if any(
            {route.origin.state_key, route.destination.state_key} - set(location_keys)
            for route in self.routes
        ):
            raise ValueError("routes must use declared typed locations")
        return self

    def initial_state(self) -> dict:
        return {
            "revision": 0,
            "participants": [item.state_key for item in self.participants],
            "observations": {},
            "resource_holders": {
                item.resource.state_key: item.holder.state_key if item.holder else None
                for item in self.resources
            },
            "locations": {
                item.subject.state_key: item.location.state_key
                for item in self.positions
            },
            "location_catalog": [item.state_key for item in self.locations],
            "routes": [
                [item.origin.state_key, item.destination.state_key]
                for item in self.routes
            ],
            "assumptions": list(self.assumptions),
            "departed": [],
        }


class SimulationBeliefChange(SimulationV3Model):
    key: str = Field(min_length=1)
    statement: str = Field(min_length=1)
    stance: Literal["believes", "doubts", "unknown"]
    evidence_events: list[str] = Field(min_length=1)


class SimulationIntent(SimulationV3Model):
    """An attempt. Its declared effect is applied only after finite adjudication."""

    intent_id: str = Field(min_length=1)
    mode: Literal[
        "director_round", "world_progression_step", "state_trial", "observer_round"
    ] = "director_round"
    actor: SimulationReference
    kind: str = Field(min_length=1)
    action: str = Field(min_length=1)
    internal_reason: str = ""
    effect: Literal["none", "resource_transfer", "move", "leave", "belief_change"] = (
        "none"
    )
    visibility: Literal["public", "private", "whisper"] = "public"
    audience: list[SimulationReference] = Field(default_factory=list)
    resource: SimulationReference | None = None
    recipient: SimulationReference | None = None
    destination: SimulationReference | None = None
    beliefs: list[SimulationBeliefChange] = Field(default_factory=list)
    unresolved: bool = False
    record_observation: bool = True

    @model_validator(mode="after")
    def valid_effect_inputs(self):
        if self.effect == "resource_transfer" and (
            self.resource is None or self.recipient is None
        ):
            raise ValueError("resource transfers need a resource and recipient")
        if self.effect == "move" and self.destination is None:
            raise ValueError("movement needs a typed destination")
        if self.effect != "belief_change" and self.beliefs:
            raise ValueError("belief changes need the belief_change effect")
        if len({belief.key for belief in self.beliefs}) != len(self.beliefs):
            raise ValueError("a belief can only change once in one intent")
        return self


class SimulationIntentDraft(SimulationV3Model):
    """Role-local proposal; Story binds actor and identity after validation."""

    kind: str = Field(min_length=1)
    action: str = Field(min_length=1)
    internal_reason: str = ""
    effect: Literal["none", "resource_transfer", "move", "leave", "belief_change"] = (
        "none"
    )
    visibility: Literal["public", "private", "whisper"] = "public"
    audience: list[SimulationReference] = Field(default_factory=list)
    resource: SimulationReference | None = None
    recipient: SimulationReference | None = None
    destination: SimulationReference | None = None
    beliefs: list[SimulationBeliefChange] = Field(default_factory=list)
    unresolved: bool = False

    def bind(
        self,
        *,
        intent_id: str,
        actor: SimulationReference,
        mode: Literal[
            "director_round", "world_progression_step", "state_trial", "observer_round"
        ] = "director_round",
    ) -> SimulationIntent:
        return SimulationIntent(
            intent_id=intent_id,
            mode=mode,
            actor=actor,
            **self.model_dump(mode="python"),
        )


class FiniteOutcome(SimulationV3Model):
    intent_id: str = Field(min_length=1)
    outcome: Literal["succeeded", "failed", "uncertain"]


class FiniteResolution(SimulationV3Model):
    outcomes: list[FiniteOutcome] = Field(default_factory=list)


class StateDelta(SimulationV3Model):
    kind: Literal[
        "resource_holder", "departed", "observation", "location", "belief"
    ]
    key: str = Field(min_length=1)
    before: str | bool | dict | None = None
    after: str | bool | dict


class ResolutionBatch(SimulationV3Model):
    protocol: Literal["simulation_v3", "observation_v2"]
    base_state_revision: int = Field(ge=0)
    base_state_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    intents_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    rule_revision: str = Field(pattern=r"^[a-f0-9]{64}$")
    events: list[dict] = Field(default_factory=list)
    state_patches: list[StateDelta] = Field(default_factory=list)
    unresolved_outcomes: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def preserve_observation_v2_limits(self):
        if self.protocol == "observation_v2" and (
            len(self.events) > 16
            or len(self.state_patches) > 100
            or len(self.unresolved_outcomes) > 4
            or len(self.assumptions) > 12
        ):
            raise ValueError("observation_v2 batch exceeds its original limits")
        return self


def _observers_for(
    intent: SimulationIntent, observers: set[str], state: dict
) -> list[str]:
    actor = intent.actor.state_key
    locations = state.get("locations", {})
    origin = locations.get(actor)
    visible = {
        observer
        for observer in observers
        if origin is None or locations.get(observer, origin) == origin
    }
    audience = {item.state_key for item in intent.audience}
    if actor not in visible or audience - visible:
        raise ValueError("Observation recipients must belong to this scene")
    if intent.visibility == "private":
        return [actor]
    if intent.visibility == "whisper":
        return sorted({actor, *audience})
    return sorted(visible)


def resolve_simulation_v3(
    intents: list[SimulationIntent],
    resolution: FiniteResolution,
    state: dict,
    *,
    observers: set[str],
    rule_revision: str,
    assumptions: list[str] | None = None,
) -> ResolutionBatch:
    """Settle declared effects, then return an immutable batch for replay."""
    by_id = {intent.intent_id: intent for intent in intents}
    outcomes = {item.intent_id: item.outcome for item in resolution.outcomes}
    if (
        len(by_id) != len(intents)
        or len(outcomes) != len(resolution.outcomes)
        or set(outcomes) != set(by_id)
        or any(intent.actor.state_key not in observers for intent in intents)
    ):
        raise ValueError("Every intent needs exactly one outcome for an active actor")
    if len({intent.mode for intent in intents}) > 1:
        raise ValueError("A resolution batch must use one simulation mode")

    claimed: dict[str, list[str]] = {}
    for intent in intents:
        if (
            intent.effect == "resource_transfer"
            and outcomes[intent.intent_id] == "succeeded"
        ):
            assert intent.resource is not None
            claimed.setdefault(intent.resource.state_key, []).append(intent.intent_id)
    for claimants in claimed.values():
        if len(claimants) > 1:
            for intent_id in claimants:
                outcomes[intent_id] = "uncertain"

    holders = state.get("resource_holders", {})
    locations = state.get("locations", {})
    catalog = set(state.get("location_catalog", []))
    routes = {tuple(route) for route in state.get("routes", [])}
    patches: list[StateDelta] = []
    events: list[dict] = []
    for intent in intents:
        actor = intent.actor.state_key
        outcome = outcomes[intent.intent_id]
        if outcome == "succeeded" and intent.unresolved:
            outcome = outcomes[intent.intent_id] = "uncertain"
        if outcome == "succeeded" and intent.effect == "resource_transfer":
            assert intent.resource is not None and intent.recipient is not None
            resource_key = intent.resource.state_key
            if resource_key not in holders or holders[resource_key] != actor:
                outcome = outcomes[intent.intent_id] = "uncertain"
        if outcome == "succeeded" and intent.effect == "move":
            assert intent.destination is not None
            destination = intent.destination.state_key
            origin = locations.get(actor)
            if destination not in catalog or (
                origin != destination and (origin, destination) not in routes
            ):
                outcome = outcomes[intent.intent_id] = "uncertain"

        observers_for_event = _observers_for(intent, observers, state)
        if intent.kind == "speak" and outcome != "succeeded":
            observers_for_event = [actor]
        action = intent.action
        if outcome != "succeeded":
            action = f"尝试：{action}；" + (
                "未成功。" if outcome == "failed" else "结果仍未确定。"
            )
        event = {
            "actor_id": intent.actor.public_id,
            "mode": intent.mode,
            "event_type": "utterance"
            if intent.kind == "speak" and outcome == "succeeded"
            else "resolved_action",
            "kind": intent.kind,
            "action": action,
            "outcome": outcome,
            "visibility": intent.visibility,
            "observers": observers_for_event,
            "truth": "spoken_claim"
            if intent.kind == "speak"
            else "simulated_outcome",
            "event_id": content_hash(
                [content_hash(state), intent.model_dump(mode="json"), outcome]
            ),
            "intent_id": intent.intent_id,
        }
        if outcome == "succeeded" and intent.effect == "resource_transfer":
            assert intent.resource is not None and intent.recipient is not None
            resource_key = intent.resource.state_key
            patches.append(
                StateDelta(
                    kind="resource_holder",
                    key=resource_key,
                    before=holders[resource_key],
                    after=intent.recipient.state_key,
                )
            )
        if outcome == "succeeded" and intent.effect == "move":
            assert intent.destination is not None
            patches.append(
                StateDelta(
                    kind="location",
                    key=actor,
                    before=locations.get(actor),
                    after=intent.destination.state_key,
                )
            )
        if outcome == "succeeded" and intent.effect == "leave":
            patches.append(
                StateDelta(
                    kind="departed",
                    key=actor,
                    before=actor in state.get("departed", []),
                    after=True,
                )
            )
        if outcome == "succeeded" and intent.effect == "belief_change":
            observed = {
                event.get("event_id") or event.get("source_id")
                for event in state.get("observations", {}).get(actor, [])
            }
            beliefs = state.get("beliefs", {}).get(actor, {})
            for belief in intent.beliefs:
                if set(belief.evidence_events) - observed:
                    raise ValueError(
                        "Belief changes must cite the subject's own observations"
                    )
                patches.append(
                    StateDelta(
                        kind="belief",
                        key=f"{actor}:{belief.key}",
                        before=beliefs.get(belief.key),
                        after={
                            "actor_id": actor,
                            **belief.model_dump(mode="json"),
                        },
                    )
                )
        events.append(event)
        if intent.record_observation:
            visible_observers = (
                observers_for_event
                if intent.kind != "speak" or outcome == "succeeded"
                else [actor]
            )
            for observer in visible_observers:
                patches.append(
                    StateDelta(
                        kind="observation",
                        key=observer,
                        after={
                            key: value
                            for key, value in event.items()
                            if key != "observers"
                        },
                    )
                )

    return ResolutionBatch(
        protocol="simulation_v3",
        base_state_revision=state.get("revision", 0),
        base_state_hash=content_hash(state),
        intents_hash=content_hash(
            [intent.model_dump(mode="json") for intent in intents]
        ),
        rule_revision=rule_revision,
        events=events,
        state_patches=patches,
        unresolved_outcomes=[
            intent.actor.public_id
            for intent in intents
            if outcomes[intent.intent_id] == "uncertain"
        ],
        assumptions=assumptions or ["这是给定资料与规则下的一次模拟裁决，不是事实证明。"],
    )


def replay_batch(state: dict, batch: ResolutionBatch) -> dict:
    """Replay stored events and deltas exactly, with no provider or random calls."""
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
        elif patch.kind == "observation":
            updated["observations"].setdefault(patch.key, []).append(patch.after)
        else:
            raise ValueError(f"Unknown state delta kind: {patch.kind}")
    updated["revision"] = batch.base_state_revision + 1
    if batch.protocol == "observation_v2":
        for actor, events in updated["observations"].items():
            if len(events) > 128:
                history = updated.setdefault("observation_history", {})
                history[actor] = {
                    "complete": False,
                    "omitted": (
                        history.get(actor, {}).get("omitted", 0) + len(events) - 128
                    ),
                }
                updated["observations"][actor] = events[-128:]
    return updated
