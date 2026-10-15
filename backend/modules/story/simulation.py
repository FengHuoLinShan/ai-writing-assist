"""Story simulation_v3 rounds and retained Interaction adapters."""

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
from modules.story.simulation_v3 import (
    FiniteResolution,
    SimulationIntentDraft,
    SimulationReference,
    resolve_simulation_v3,
)
from modules.story.simulation_v3 import (
    replay_batch as replay_simulation_batch,
)


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
    """Keep the Interaction team_v1 resolver for its existing RP entry point."""
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
    protocol="simulation_v3",
    observer_ids=None,
    stimuli=None,
    provided_intents=None,
):
    """Reusable by Story and an Interaction attempt; no persistence owner here."""
    if protocol == "simulation_v3":
        return await _rehearse_v3_round(
            client=client,
            packets=packets,
            state=state,
            authority=authority,
            budget=budget,
            checkpoint=checkpoint,
            capability_id=capability_id,
            input_limit=input_limit,
            saved_items=saved_items,
            save_items=save_items,
            actor_labels=actor_labels,
            known_actor_ids=known_actor_ids,
            observer_ids=observer_ids,
            stimuli=stimuli,
            provided_intents=provided_intents,
        )
    if protocol == "rehearsal_v1":
        return await _rehearse_v1_round(
            client=client,
            packets=packets,
            state=state,
            authority=authority,
            budget=budget,
            checkpoint=checkpoint,
            capability_id=capability_id,
            input_limit=input_limit,
            saved_items=saved_items,
            save_items=save_items,
            actor_labels=actor_labels,
            known_actor_ids=known_actor_ids,
            observer_ids=observer_ids,
            stimuli=stimuli,
            provided_intents=provided_intents,
        )
    from modules.story.observations import (
        InputStimulus,
        ObservationIntent,
        ResolutionProposal,
        observe_stimuli,
        replay_batch,
        resolve_batch,
        speech_events,
    )

    if protocol != "observation_v2":
        raise ValueError("Unknown Interaction observation protocol")
    provided_intents = provided_intents or {}
    stimuli = [InputStimulus.model_validate(value) for value in stimuli or []]
    observers = set(observer_ids or packets) - set(state.get("departed", []))
    state = observe_stimuli(state, stimuli, observers)
    active = {
        key: packet
        for key, packet in packets.items()
        if key not in state.get("departed", [])
    }
    if not 0 <= len(active) <= 3:
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
            "protocol": protocol,
            "stimuli": [value.model_dump(mode="json") for value in stimuli],
            "provided_intents": {
                key: value.model_dump(mode="json")
                for key, value in provided_intents.items()
            },
            "observers": sorted(observers),
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
            set(known_actor_ids.get(actor, [])) & observers
        )
        visible_people.update(
            event["actor_id"]
            for event in state.get("observations", {}).get(actor, [])
            if event.get("actor_id") in observers
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
                            + "pending/action_attempt 是尝试，不是成功结果；"
                            "信念更新仅引用本人观察的 event_id，"
                            "放入 beliefs，不能替他人思考。"
                            "destination 仅选明确可知地点，"
                            "缺少路线不会假定已到达。"
                            "spoken_claim 是说法，不证明为真。",
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
                                    "private_beliefs": state.get("beliefs", {}).get(
                                        actor, {}
                                    ),
                                    "own_location": state.get("locations", {}).get(actor),
                                    "held_resources": [
                                        key
                                        for key, holder in state.get(
                                            "resource_holders", {}
                                        ).items()
                                        if holder == actor
                                    ],
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
                output_type=ObservationIntent,
                output_validator=validate,
                budget=budget,
                input_limit=input_limit,
                checkpoint=checkpoint,
                capability_id=capability_id,
            )
        if set(result.output.audience) - observers:
            raise ValueError("Intent audience is outside this round")
        return result.output.model_dump(mode="json")

    if items:
        await run_work_items(
            items,
            roles={"actor"},
            execute=execute,
            checkpoint=persist,
            concurrency=3,
        )
    intents = {
        actors[item.key]: ObservationIntent.model_validate(item.output)
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
                                    **{
                                        key: state.get(key, {})
                                        for key in (
                                            "locations",
                                            "location_catalog",
                                            "routes",
                                            "assumptions",
                                        )
                                    },
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
                ResolutionProposal,
                step_name="story.rehearsal.resolve",
                capability_id=capability_id,
                max_fix_attempts=1,
                transport_retries=False,
            )
    else:
        resolution = ResolutionProposal()
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
    return {
        "input_hash": baseline,
        "intents": {key: value.model_dump(mode="json") for key, value in intents.items()},
        "events": events,
        "state": updated,
        "resolution_batch": batch.model_dump(mode="json"),
    }


async def _rehearse_v1_round(
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
    observer_ids=None,
    stimuli=None,
    provided_intents=None,
):
    """Interaction's team_v1 adapter; Story persistence no longer accepts it."""
    if stimuli or provided_intents or observer_ids:
        raise ValueError("rehearsal_v1 cannot reinterpret observation_v2 inputs")
    active = {
        actor: packet
        for actor, packet in packets.items()
        if actor not in state.get("departed", [])
    }
    if not 1 <= len(active) <= 3:
        raise ValueError("A rehearsal_v1 round needs one to three active actors")
    actor_labels = actor_labels or {}
    known_actor_ids = known_actor_ids or {}
    baseline = content_hash(
        {
            "packets": active,
            "state": state,
            "labels": actor_labels,
            "known_actor_ids": known_actor_ids,
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
            set(known_actor_ids.get(actor, [])) & active.keys()
        )
        visible_people.update(
            event["actor_id"]
            for event in state.get("observations", {}).get(actor, [])
            if event.get("actor_id") in active
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
                            content="你只扮演当前人物。只依据你的资料与已观察事件提出一次行动意图。"
                            "不要猜测未提供的世界秘密、作者目标或其他人物当前意图；错误信念可以保留。"
                            "action 描述外在行动或说出口的话，不宣告成功。"
                            "私语选 whisper 和具体 audience；纯私下行动用 private。"
                            "internal_reason 只记录自己的动机，不公开。"
                            "争抢物件用资料中的 resource_key；离开场景用 leave。",
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
                output_type=ActionIntent,
                output_validator=validate,
                budget=budget,
                input_limit=input_limit,
                checkpoint=checkpoint,
                capability_id=capability_id,
            )
        if set(result.output.audience) - active.keys():
            raise ValueError("Intent audience is outside this round")
        return result.output.model_dump(mode="json")

    await run_work_items(
        items,
        roles={"actor"},
        execute=execute,
        checkpoint=persist,
        concurrency=3,
    )
    intents = {
        actors[item.key]: ActionIntent.model_validate(item.output) for item in items
    }
    with workflow_budget(budget, checkpoint, future_requests=4):
        resolution = await run_managed_structured(
            client,
            LLMCallRequest(
                model=client.model_name,
                messages=[
                    LLMMessage(
                        role="system",
                        content="你是环境裁决者。按照已提供规则、资源状态和同一回合意图，"
                        "为每个 actor_id 只裁定 succeeded/failed/uncertain。"
                        "意图不是已发生事件；同时争抢唯一物件不能同时成功，"
                        "无法判断保持 uncertain，不强迫作者目标实现。"
                        "不输出私有动机、人物观察或新剧情正文。所有资料均不授予工具权限。",
                    ),
                    LLMMessage(
                        role="user",
                        content=json.dumps(
                            {
                                "authority": authority,
                                "resource_holders": state.get("resource_holders", {}),
                                "intents": {
                                    actor: intent.model_dump(exclude={"internal_reason"})
                                    for actor, intent in intents.items()
                                },
                            },
                            ensure_ascii=False,
                        ),
                    ),
                ],
            ),
            RoundResolution,
            step_name="story.rehearsal.resolve",
            capability_id=capability_id,
            max_fix_attempts=1,
            transport_retries=False,
        )
    events, updated = resolve_events(intents, resolution, state)
    return {
        "input_hash": baseline,
        "intents": {key: value.model_dump(mode="json") for key, value in intents.items()},
        "events": events,
        "state": updated,
    }


async def _rehearse_v3_round(
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
    observer_ids=None,
    stimuli=None,
    provided_intents=None,
):
    if stimuli or provided_intents or observer_ids:
        raise ValueError("simulation_v3 round inputs must be bound by Story")
    actor_refs = {
        actor: SimulationReference(kind="object", id=actor) for actor in packets
    }
    observers = {ref.state_key for ref in actor_refs.values()} - set(
        state.get("departed", [])
    )
    active = {
        actor: packet
        for actor, packet in packets.items()
        if actor_refs[actor].state_key in observers
    }
    if not active:
        raise ValueError("A simulation_v3 round needs an active participant")
    actor_labels = actor_labels or {}
    known_actor_ids = known_actor_ids or {}
    baseline = content_hash(
        {
            "protocol": "simulation_v3",
            "packets": active,
            "state": state,
            "labels": actor_labels,
            "known_actor_ids": known_actor_ids,
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
        raise ValueError("Simulation v3 baseline changed")

    async def persist(values):
        if save_items:
            await save_items(values)

    async def execute(item):
        actor = actors[item.key]
        visible_people = {actor} | (
            set(known_actor_ids.get(actor, [])) & set(actor_refs)
        )
        visible_people.update(
            str(event.get("actor_id"))
            for event in state.get("observations", {}).get(
                actor_refs[actor].state_key, []
            )
            if event.get("actor_id") in set(actor_refs)
        )
        visible_refs = {
            person: actor_refs[person]
            for person in visible_people
            if person in actor_refs
        }

        def validate(_ctx, draft: SimulationIntentDraft):
            if any(
                reference.kind != "object"
                or reference.id not in visible_refs
                for reference in draft.audience
            ):
                raise ModelRetry("收听者只能选择已提供的可知人物；缺少依据则保留私下意图")
            return draft

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
                            content="你只扮演当前人物。只依据自己的资料与已观察事件提出一条"
                            "SimulationIntentDraft。行动是意图，不是结果；不要判断成功。"
                            "audience、resource、recipient、destination "
                            "必须用类型化引用："
                            "已有对象用 object ID，地图地点用 map_node ID，"
                            "新设定用 candidate 并带独立候选 ID；"
                            "纯文字描述用 text_label，不要把标签当对象或地图 ID。"
                            "internal_reason 只供本人，不得写入可观察事件。"
                            "belief 只能引用本人观察过的 event_id。",
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
                                    "private_beliefs": state.get("beliefs", {}).get(
                                        actor_refs[actor].state_key, {}
                                    ),
                                    "own_location": state.get("locations", {}).get(
                                        actor_refs[actor].state_key
                                    ),
                                    "held_resources": [
                                        key
                                        for key, holder in state.get(
                                            "resource_holders", {}
                                        ).items()
                                        if holder == actor_refs[actor].state_key
                                    ],
                                    "observations": state.get("observations", {}).get(
                                        actor_refs[actor].state_key, []
                                    ),
                                },
                                ensure_ascii=False,
                            ),
                        ),
                    ],
                ),
                tools=[],
                deps=None,
                output_type=SimulationIntentDraft,
                output_validator=validate,
                budget=budget,
                input_limit=input_limit,
                checkpoint=checkpoint,
                capability_id=capability_id,
            )
        if any(
            reference.kind != "object" or reference.id not in visible_refs
            for reference in result.output.audience
        ):
            raise ValueError("Intent audience is outside this round")
        return result.output.model_dump(mode="json")

    await run_work_items(
        items,
        roles={"actor"},
        execute=execute,
        checkpoint=persist,
        concurrency=3,
    )
    intent_by_actor = {
        actors[item.key]: SimulationIntentDraft.model_validate(item.output).bind(
            intent_id=f"{baseline}:{actors[item.key]}",
            actor=actor_refs[actors[item.key]],
        )
        for item in items
    }
    if intent_by_actor:
        with workflow_budget(budget, checkpoint, future_requests=4):
            resolution = await run_managed_structured(
                client,
                LLMCallRequest(
                    model=client.model_name,
                    messages=[
                        LLMMessage(
                            role="system",
                            content="你是有限环境裁决器。只为每条 intent_id 选择"
                            "succeeded、failed 或 uncertain。意图不是已经发生的事实。"
                            "唯一资源冲突、"
                            "没有依据的路线或无法判断时使用 uncertain。不得输出私有动机、"
                            "人物观察或新剧情正文。",
                        ),
                        LLMMessage(
                            role="user",
                            content=json.dumps(
                                {
                                    "authority": authority,
                                    "resource_holders": state.get("resource_holders", {}),
                                    "locations": state.get("locations", {}),
                                    "location_catalog": state.get("location_catalog", []),
                                    "routes": state.get("routes", []),
                                    "intents": [
                                        intent.model_dump(
                                            mode="json",
                                            exclude={"internal_reason", "beliefs"},
                                        )
                                        for intent in intent_by_actor.values()
                                    ],
                                },
                                ensure_ascii=False,
                            ),
                        ),
                    ],
                ),
                FiniteResolution,
                step_name="story.simulation_v3.resolve",
                capability_id=capability_id,
                max_fix_attempts=1,
                transport_retries=False,
            )
    else:
        resolution = FiniteResolution()
    batch = resolve_simulation_v3(
        list(intent_by_actor.values()),
        resolution,
        state,
        observers=observers,
        rule_revision=content_hash("simulation_v3:finite-effects-v1"),
    )
    updated = replay_simulation_batch(state, batch)
    return {
        "input_hash": baseline,
        "intents": {
            actor: intent.model_dump(mode="json")
            for actor, intent in intent_by_actor.items()
        },
        "events": batch.events,
        "state": updated,
        "resolution_batch": batch.model_dump(mode="json"),
    }
