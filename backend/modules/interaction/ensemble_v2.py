"""Selected-path observations; confirmed participants are distinct from agents."""

from __future__ import annotations

import json
from copy import deepcopy
from uuid import UUID, uuid5

from core.errors import ConflictError, ValidationError
from infrastructure.llm.capabilities import capability_from_execution_settings
from infrastructure.llm.collaboration import content_hash
from modules.evidence.facade import compile_interaction_story_context
from modules.interaction.source_service import InteractionSourceService
from modules.story.contracts import ActionIntentContract, InputStimulusContract
from modules.story.facade import rehearse_round


def restore_environment(prior, nodes):
    positions = {str(node.id): index for index, node in enumerate(nodes)}
    available = [row for row in prior.values() if row.state_json.get("environment")]
    if not available:
        return {
            "observations": {},
            "resource_holders": {},
            "departed": [],
            "participants": [],
            "revision": 0,
        }
    newest = max(available, key=lambda row: positions[str(row.message_node_id)])
    environment = deepcopy(newest.state_json["environment"])
    same_point = [
        row for row in available if row.message_node_id == newest.message_node_id
    ]
    if len({content_hash(row.state_json["environment"]) for row in same_point}) != 1:
        raise ConflictError("选中路径的角色状态回执不一致")
    environment["observations"] = {
        key: deepcopy(row.state_json.get("observations", []))
        for key, row in prior.items()
    }
    return environment


async def prepare_ensemble_v2(run, journey, attempt, source):
    from modules.interaction.agent_runtime import StoryPreparation
    from modules.interaction.ensemble import selected_actor_states

    if run.state.get("collaboration", {}).get("resolved"):
        return StoryPreparation.model_validate(run.state["collaboration"]["plan"])
    nodes = await run.workflow.selected_context_nodes(
        run.db, journey=journey, attempt=attempt
    )
    response_to = nodes[-1]
    prior = await selected_actor_states(run.db, journey, nodes, source.id)
    state = restore_environment(prior, nodes)
    player_id = str(
        (journey.player_identity or {}).get("target_id")
        or uuid5(journey.id, "player-observer")
    )
    input_meta = dict(response_to.input_json or {}) if response_to.role == "user" else {}
    cast = list(state.get("participants", []))
    excluded = set((journey.reference_policy or {}).get("excluded", []))
    references = {
        str(item["target_id"]): item
        for item in source.reference_manifest or []
        if item.get("entity_type") == "character"
        and item.get("reference_key") not in excluded
        and InteractionSourceService.reference_visible(
            source, item, journey.source_anchor
        )
    }
    by_key = {value["reference_key"]: key for key, value in references.items()}
    if input_meta.get("cast_keys") is not None:
        if set(input_meta["cast_keys"]) - by_key.keys():
            raise ConflictError("本场人物不在当前可使用的作品资料内")
        cast = [by_key[key] for key in input_meta["cast_keys"]]
    cast = [str(UUID(value)) for value in cast if str(value) != player_id]
    if len(cast) > 3 or len(cast) != len(set(cast)) or set(cast) - references.keys():
        raise ConflictError("本场人物不在当前可使用的作品资料内")
    if input_meta.get("cast_keys") is not None:
        state["participants"] = cast
        state["departed"] = [
            actor for actor in state.get("departed", []) if actor not in cast
        ]
    else:
        cast = [actor for actor in cast if actor not in state.get("departed", [])]
    observers = {player_id, *cast}
    if set(input_meta.get("whisper_to") or []) - by_key.keys():
        raise ConflictError("私语对象不在当前可见资料内")
    whisper_to = [by_key[key] for key in input_meta.get("whisper_to") or []]
    if not set(whisper_to) <= observers:
        raise ConflictError("私语对象必须是本场参与者")
    kind = (
        input_meta.get("kind", "instruction") if response_to.role == "user" else "advance"
    )
    try:
        stimuli = (
            [
                InputStimulusContract(
                    actor_id=player_id,
                    kind=kind,
                    text=response_to.content,
                    visibility="whisper" if whisper_to else "public",
                    audience=whisper_to,
                    source_id=str(response_to.id),
                )
            ]
            if response_to.role == "user"
            else []
        )
    except ValueError:
        raise ValidationError("这一轮输入过长或缺少有效类型，请分成更短的动作") from None
    packets, actor_refs, known = {}, {}, {}
    for actor_id in cast:
        actor = references[actor_id]
        actor_refs[actor_id] = {
            "label": actor.get("label") or "人物",
            "parent_id": str(prior[actor_id].id) if actor_id in prior else None,
            "source_fingerprint": "",
            "reference_key": actor["reference_key"],
        }
        if kind == "instruction":
            continue
        packet = await compile_interaction_story_context(
            run.db,
            source_novel_id=str(source.source_novel_id),
            consumer_novel_id=run.novel_id,
            source_revision_id=str(source.id),
            source_manifest=list(source.source_manifest or []),
            anchor=dict(journey.source_anchor or {}),
            player_identity={
                "kind": "source_character",
                "reference_key": actor["reference_key"],
                "target_id": actor_id,
            },
            reference_manifest=list(source.reference_manifest or []),
            ambiguities=list(source.ambiguities or []),
            resolutions=dict(source.resolutions or {}),
            reference_policy=dict(journey.reference_policy or {}),
            query=str(actor.get("label") or "当前人物"),
            task_id=str(run.task.id),
            model=run.client.model_name,
            budget_tokens=5000,
        )
        if packet.blockers:
            continue
        packets[actor_id] = packet.rendered_context
        included = {item["reference_key"] for item in packet.included_refs}
        known[actor_id] = [
            key for key in cast if references[key]["reference_key"] in included
        ]
        actor_refs[actor_id]["source_fingerprint"] = packet.fingerprint
    actor_refs[player_id] = {
        "label": "你",
        "parent_id": str(prior[player_id].id) if player_id in prior else None,
        "source_fingerprint": content_hash(journey.player_identity),
    }
    source_id, input_content, input_role = (
        str(source.id),
        response_to.content,
        response_to.role,
    )
    from modules.interaction.ensemble_input import prepare_player_input

    input_plan = await prepare_player_input(
        run,
        nodes,
        state,
        player_id,
        {key: value["label"] for key, value in actor_refs.items()},
        kind,
    )
    for item in input_plan.resources:
        state.setdefault("resource_holders", {})[item.key] = item.holder
    state["input_initialized"] = True
    state["unknowns"] = list(
        dict.fromkeys([*state.get("unknowns", []), *input_plan.unknowns])
    )[-40:]
    provided = {}
    if kind in {"action", "narration"} and input_role == "user":
        if len(input_content) > 1500:
            raise ValidationError("多角色试演每轮先处理一个短动作，请缩短到 1500 字以内")
        provided[player_id] = ActionIntentContract(
            kind=input_plan.action_kind,
            action=input_content,
            unresolved=bool(input_plan.unknowns),
            resource_key=input_plan.resource_key,
            destination=input_plan.destination,
            visibility="whisper" if whisper_to else "public",
            audience=whisper_to,
        )
    await run.db.commit()
    run.db.expire_all()

    async def save_items(items):
        run.state["ensemble_items"] = items
        await run.checkpoint()

    capability = capability_from_execution_settings(run.prepared.executable_settings)
    result = await rehearse_round(
        client=run.client,
        packets=packets,
        state=state,
        authority="本轮输入只是意图或授权的叙述要求；按已有资料判断，不能把自称成功当作成功。\n"
        + "\n".join(message.content for message in run.prepared.messages),
        budget=run.budget,
        checkpoint=run.checkpoint,
        capability_id="interaction.story_generate",
        input_limit=capability.hard_input_tokens,
        saved_items=run.state.get("ensemble_items"),
        save_items=save_items,
        actor_labels={key: value["label"] for key, value in actor_refs.items()},
        known_actor_ids=known,
        protocol="observation_v2",
        observer_ids=observers,
        stimuli=[item.model_dump(mode="json") for item in stimuli],
        provided_intents=provided,
    )
    visible = [event for event in result["events"] if player_id in event["observers"]]
    environment = {
        key: value for key, value in result["state"].items() if key != "observations"
    }
    environment["participants"] = [
        actor for actor in cast if actor not in environment.get("departed", [])
    ]
    actors = {
        actor: {
            **values,
            "state": {
                "observations": result["state"].get("observations", {}).get(actor, []),
                "environment": environment,
                "history_unknown": actor not in prior,
                "departed": actor in environment.get("departed", []),
                "agent_invoked": actor in packets,
                "reference_key": values.get("reference_key"),
            },
        }
        for actor, values in actor_refs.items()
    }
    ref = run.remember(
        {
            "kind": "rehearsal_events",
            "text": json.dumps(visible, ensure_ascii=False),
            "authority": (
                "只能叙述实际提供的模拟事件；说法不证明为真，未定结果不补写成功。"
            ),
        }
    )
    plan = StoryPreparation(
        scene_intent="尊重本轮场内行动与场外要求；场外内容不得成为人物所知。仅叙述玩家可见的裁决事件。",
        evidence_ids=[ref["evidence_id"]],
        warnings=["未确认在场的人物不会因名字被提及就参与行动。"],
    )
    run.state["collaboration"] = {
        "protocol": "observation_v2",
        "resolved": True,
        "source_revision_id": source_id,
        "actors": actors,
        "resolution_batch": result.get("resolution_batch"),
        "events_hash": content_hash(visible),
        "plan": plan.model_dump(mode="json"),
    }
    run.state.pop("ensemble_items", None)
    run.state.pop("ensemble_input_plan", None)
    await run.checkpoint()
    return plan
