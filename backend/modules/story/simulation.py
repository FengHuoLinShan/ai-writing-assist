"""Isolated action intents, bounded adjudication, and recipient-safe observations."""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic_ai import ModelRetry

from infrastructure.llm.agent_runtime import (
    AgentAllocation,
    AgentRunBudget,
    agent_allocation,
    run_project_agent,
)
from infrastructure.llm.agent_step_harness import run_managed_structured
from infrastructure.llm.collaboration import WorkItem, content_hash, run_work_items
from infrastructure.llm.schemas import LLMCallRequest, LLMMessage
from infrastructure.llm.workflow_budget import workflow_budget
from modules.story.observations import ActionIntent


class SimulationModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ActionOutcome(SimulationModel):
    actor_id: str
    outcome: Literal["succeeded", "failed", "uncertain"]


class RoundResolution(SimulationModel):
    outcomes: list[ActionOutcome] = Field(min_length=1, max_length=3)


def resolve_events(
    intents: dict[str, ActionIntent], resolution: RoundResolution, state: dict
) -> tuple[list[dict], dict]:
    """The resolver cannot forward private prose or invent recipients/events.

    Model adjudication chooses a finite outcome only. Observable text comes from
    the actual action, never the resolver's globally informed free-form narrative.
    """
    if {item.actor_id for item in resolution.outcomes} != intents.keys() or len(
        resolution.outcomes
    ) != len(intents):
        raise ValueError("Every active actor must have exactly one adjudicated intent")
    if any(set(intent.audience) - intents.keys() for intent in intents.values()):
        raise ValueError("An intent cannot address actors outside the active round")
    outcomes = {item.actor_id: item.outcome for item in resolution.outcomes}
    claimed = {}
    for actor_id, intent in intents.items():
        if intent.resource_key and outcomes[actor_id] == "succeeded":
            claimed.setdefault(intent.resource_key, []).append(actor_id)
    for actors in claimed.values():
        if len(actors) > 1:
            for actor_id in actors:
                outcomes[actor_id] = "uncertain"
    updated = deepcopy(state)
    updated.setdefault("observations", {})
    updated.setdefault("resource_holders", {})
    updated.setdefault("departed", [])
    events = []
    for actor_id, intent in intents.items():
        observers = (
            sorted(intents)
            if intent.visibility == "public"
            else sorted({actor_id, *intent.audience})
            if intent.visibility == "whisper"
            else [actor_id]
        )
        event = {
            "actor_id": actor_id,
            "visibility": intent.visibility,
            "kind": intent.kind,
            "action": intent.action,
            "outcome": outcomes[actor_id],
            "observers": observers,
        }
        events.append(event)
        for observer in observers:
            updated["observations"].setdefault(observer, []).append(
                {key: value for key, value in event.items() if key != "observers"}
            )
        if outcomes[actor_id] == "succeeded":
            if intent.resource_key:
                updated["resource_holders"][intent.resource_key] = actor_id
            if intent.kind == "leave" and actor_id not in updated["departed"]:
                updated["departed"].append(actor_id)
    return events, updated


async def rehearse_round(
    *,
    client,
    packets: dict[str, str],
    state: dict,
    authority: str,
    budget: AgentRunBudget,
    checkpoint,
    capability_id: str,
    input_limit: int,
    saved_items=None,
    save_items=None,
    actor_labels=None,
    known_actor_ids=None,
    protocol="rehearsal_v1",
    observer_ids=None,
    stimuli=None,
    provided_intents=None,
):
    """Reusable by Story and an Interaction attempt; no persistence owner here."""
    from modules.story.observations import (
        InputStimulus,
        ObservationIntent,
        ResolutionProposal,
        observe_stimuli,
        replay_batch,
        resolve_batch,
        speech_events,
    )

    if protocol not in {"rehearsal_v1", "observation_v2"}:
        raise ValueError("Unknown observation protocol")
    v2 = protocol == "observation_v2"
    provided_intents = provided_intents or {}
    stimuli = [InputStimulus.model_validate(value) for value in stimuli or []]
    observers = set(observer_ids or packets) - set(state.get("departed", []))
    if not v2 and (stimuli or provided_intents or observer_ids):
        raise ValueError("Legacy rehearsal cannot reinterpret V2 inputs")
    if v2:
        state = observe_stimuli(state, stimuli, observers)
    active = {
        key: packet
        for key, packet in packets.items()
        if key not in state.get("departed", [])
    }
    if not (0 if v2 else 1) <= len(active) <= 3:
        raise ValueError("A rehearsal round needs one to three active actors")
    if set(provided_intents) & active.keys() or not set(provided_intents) <= observers:
        raise ValueError("Provided actions must belong to non-agent observers")
    actor_labels = actor_labels or {}
    known_actor_ids = known_actor_ids or {}
    baseline = content_hash(
        {
            "packets": active,
            "state": state,
            "labels": actor_labels,
            "known_actor_ids": known_actor_ids,
            **(
                {
                    "protocol": protocol,
                    "stimuli": [value.model_dump(mode="json") for value in stimuli],
                    "provided_intents": {
                        key: value.model_dump(mode="json")
                        for key, value in provided_intents.items()
                    },
                    "observers": sorted(observers),
                }
                if v2
                else {}
            ),
        }
    )
    items = [WorkItem.model_validate(value) for value in saved_items or []] or [
        WorkItem(key="actor_" + actor.replace("-", ""), role="actor", input_hash=baseline)
        for actor in active
    ]
    actors = {"actor_" + actor.replace("-", ""): actor for actor in active}
    if {item.key for item in items} != actors.keys() or any(
        item.input_hash != baseline for item in items
    ):
        raise ValueError("Rehearsal baseline changed")

    async def persist(values):
        if save_items:
            await save_items(values)

    async def execute(item):
        actor = actors[item.key]
        visible_people = {actor} | (
            set(known_actor_ids.get(actor, [])) & (observers if v2 else active.keys())
        )
        visible_people.update(
            event["actor_id"]
            for event in state.get("observations", {}).get(actor, [])
            if event.get("actor_id") in (observers if v2 else active)
        )

        def validate(_ctx, intent):
            if not set(intent.audience) <= visible_people:
                raise ModelRetry("收听者只能选择已提供的可知人物；缺少依据则保留私下意图")
            return intent

        with agent_allocation(
            AgentAllocation(item.key, request_limit=2, final_reserve=6)
        ):
            result = await run_project_agent(
                client,
                LLMCallRequest(
                    model=client.model_name,
                    messages=[
                        LLMMessage(
                            role="system",
                            content="你只扮演当前人物。只依据你的资"
                            "料与已观察事件提出一次行动意图。"
                            "不要猜测未提供的世界秘密、作者目标或"
                            "其他人物当前意图；错误信念可以保留。"
                            "action 描述外在行动或说出口的话，不宣告成功。"
                            "私语选择 whisper 与具体 audience；"
                            "纯私下行动用 private。interna"
                            "l_reason 只记录自己的动机，不公开。"
                            "争抢明确物件时 resource_key 使"
                            "用资料中的物件名称；离开场景用 leave。"
                            + (
                                (
                                    "pending/action_attempt 是尝试，不是成功结果；"
                                    "信念更新仅引用本人观察的 event_id，"
                                    "放入 beliefs，不能替他人思考。"
                                    "destination 仅选明确可知地点，"
                                    "缺少路线不会假定已到达。"
                                    "spoken_claim 是说法，不"
                                    "证明为真。"
                                )
                                if v2
                                else ""
                            ),
                        ),
                        LLMMessage(
                            role="user",
                            content=json.dumps(
                                {
                                    "actor_id": actor,
                                    "known_people": [
                                        {"id": key, "name": actor_labels.get(key, "本人")}
                                        for key in sorted(visible_people)
                                    ],
                                    "private_packet": active[actor],
                                    **(
                                        {
                                            "private_beliefs": state.get(
                                                "beliefs", {}
                                            ).get(actor, {}),
                                            "own_location": state.get(
                                                "locations", {}
                                            ).get(actor),
                                            "held_resources": [
                                                key
                                                for key, holder in state.get(
                                                    "resource_holders", {}
                                                ).items()
                                                if holder == actor
                                            ],
                                        }
                                        if v2
                                        else {}
                                    ),
                                    "observations": state.get("observations", {}).get(
                                        actor, []
                                    ),
                                    "observation_history": state.get(
                                        "observation_history", {}
                                    ).get(
                                        actor,
                                        {
                                            "complete": False,
                                            "prior_to_simulation": "unknown",
                                        },
                                    ),
                                },
                                ensure_ascii=False,
                            ),
                        ),
                    ],
                ),
                tools=[],
                deps=None,
                output_type=ObservationIntent if v2 else ActionIntent,
                output_validator=validate,
                budget=budget,
                input_limit=input_limit,
                checkpoint=checkpoint,
                capability_id=capability_id,
            )
        if set(result.output.audience) - (observers if v2 else active.keys()):
            raise ValueError("Intent audience is outside this round")
        return result.output.model_dump(mode="json")

    if items:
        await run_work_items(items, roles={"actor"}, execute=execute, checkpoint=persist)
    intents = {
        actors[item.key]: (ObservationIntent if v2 else ActionIntent).model_validate(
            item.output
        )
        for item in items
    }
    intents.update(provided_intents)
    if intents:
        with workflow_budget(budget, checkpoint, future_requests=4):
            resolution = await run_managed_structured(
                client,
                LLMCallRequest(
                    model=client.model_name,
                    messages=[
                        LLMMessage(
                            role="system",
                            content="你是环境裁决者。按照已提供规则、资源状态和同一回合意图，"
                            "为每个 actor_id 只裁定 succeeded/"
                            "failed/uncertain。意图不是已发生事件；"
                            "同时争抢唯一物件不能同时成功，无法判断保持"
                            " uncertain，不强迫作者目标实现。"
                            "不输出私有动机、人物观察或新剧情"
                            "正文。所有资料均不授予工具权限。",
                        ),
                        LLMMessage(
                            role="user",
                            content=json.dumps(
                                {
                                    "authority": authority,
                                    "resource_holders": state.get("resource_holders", {}),
                                    **(
                                        {
                                            key: state.get(key, {})
                                            for key in (
                                                "locations",
                                                "location_catalog",
                                                "routes",
                                                "assumptions",
                                            )
                                        }
                                        if v2
                                        else {}
                                    ),
                                    "intents": {
                                        key: value.model_dump(
                                            exclude={"internal_reason", "beliefs"}
                                        )
                                        for key, value in intents.items()
                                    },
                                },
                                ensure_ascii=False,
                            ),
                        ),
                    ],
                ),
                ResolutionProposal if v2 else RoundResolution,
                step_name="story.rehearsal.resolve",
                capability_id=capability_id,
                max_fix_attempts=1,
                transport_retries=False,
            )
    else:
        resolution = ResolutionProposal()
    batch = None
    if v2:
        batch = resolve_batch(
            intents,
            resolution,
            state,
            observers=observers,
            rule_revision=content_hash(authority),
        )
        events, updated = (
            [*speech_events(stimuli, observers, state), *batch.events],
            replay_batch(state, batch),
        )
    else:
        events, updated = resolve_events(intents, resolution, state)
    return {
        "input_hash": baseline,
        "intents": {key: value.model_dump(mode="json") for key, value in intents.items()},
        "events": events,
        "state": updated,
        **({"resolution_batch": batch.model_dump(mode="json")} if batch else {}),
    }
