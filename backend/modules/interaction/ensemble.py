"""Private, branch-owned NPC rehearsal within the current RP attempt."""

from __future__ import annotations

import json
from copy import deepcopy
from uuid import UUID

from sqlalchemy import select

from infrastructure.llm.capabilities import capability_from_execution_settings
from infrastructure.llm.collaboration import content_hash
from modules.evidence.facade import compile_interaction_story_context
from modules.interaction.models import InteractionActorStateRevision
from modules.interaction.source_service import InteractionSourceService
from modules.story.facade import rehearse_round


async def selected_actor_states(db, journey, nodes, source_revision_id):
    positions = {node.id: index for index, node in enumerate(nodes)}
    if not positions:
        return {}
    rows = list(
        (
            await db.scalars(
                select(InteractionActorStateRevision).where(
                    InteractionActorStateRevision.novel_id == journey.novel_id,
                    InteractionActorStateRevision.journey_id == journey.id,
                    InteractionActorStateRevision.source_revision_id
                    == source_revision_id,
                    InteractionActorStateRevision.message_node_id.in_(positions),
                )
            )
        ).all()
    )
    result = {}
    for row in sorted(rows, key=lambda item: positions[item.message_node_id]):
        if content_hash(row.state_json) != row.state_hash:
            raise ValueError("RP actor state receipt changed")
        result[str(row.actor_id)] = row
    return result


async def prepare_ensemble(run):
    from modules.interaction.agent_runtime import StoryPreparation

    journey, attempt, source = await run.guard()
    if source is None:
        raise ValueError("RP ensemble requires a frozen source revision")
    if (
        (run.prepared.executable_settings.get("_agent_runtime") or {}).get(
            "collaboration"
        )
        or {}
    ).get("protocol") == "observation_v2":
        from modules.interaction.ensemble_v2 import prepare_ensemble_v2

        return await prepare_ensemble_v2(run, journey, attempt, source)
    if run.state.get("collaboration", {}).get("resolved"):
        return StoryPreparation.model_validate(run.state["collaboration"]["plan"])
    nodes = await run.workflow.selected_context_nodes(
        run.db, journey=journey, attempt=attempt
    )
    response_to = nodes[-1]
    prior = await selected_actor_states(run.db, journey, nodes, source.id)
    ignored = set((journey.reference_policy or {}).get("excluded", []))
    player_id = str((journey.player_identity or {}).get("target_id") or "")
    candidates = [
        item
        for item in source.reference_manifest or []
        if item.get("entity_type") == "character"
        and item.get("reference_key") not in ignored
        and str(item.get("target_id")) != player_id
        and InteractionSourceService.reference_visible(
            source, item, journey.source_anchor
        )
    ]
    # Prefer characters mentioned in the current user turn; other eligible actors
    # are a bounded cast proposal, not proof they observed the whole journey.
    candidates.sort(
        key=lambda item: (
            str(item.get("label") or "") not in response_to.content,
            str(item.get("target_id")),
        )
    )
    visible_beat = "\n".join(node.content for node in nodes[-2:])
    cast = [
        actor
        for actor in candidates
        if str(actor.get("label") or "") in visible_beat
        and not (
            str(actor.get("target_id")) in prior
            and prior[str(actor["target_id"])].state_json.get("departed")
        )
    ][:3]
    packets, actor_refs, known_actor_ids = {}, {}, {}
    for actor in cast:
        actor_id = str(actor["target_id"])
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
        included = {reference["reference_key"] for reference in packet.included_refs}
        known_actor_ids[actor_id] = [
            str(item["target_id"]) for item in cast if item["reference_key"] in included
        ]
        actor_refs[actor_id] = {
            "label": str(actor.get("label") or "人物"),
            "source_fingerprint": packet.fingerprint,
            "parent_id": str(prior[actor_id].id) if actor_id in prior else None,
        }
    state = {
        "observations": {
            key: deepcopy(prior[key].state_json.get("observations", []))
            if key in prior
            else []
            for key in packets
        },
        "resource_holders": {},
        "departed": [],
    }
    source_id = str(source.id)
    await run.db.commit()
    run.db.expire_all()
    if packets:
        capability = capability_from_execution_settings(run.prepared.executable_settings)

        async def save_items(items):
            run.state["ensemble_items"] = items
            await run.checkpoint()

        result = await rehearse_round(
            client=run.client,
            packets=packets,
            state=state,
            authority="当前已选玩家资料与合法叙述：\n"
            + "\n".join(message.content for message in run.prepared.messages),
            budget=run.budget,
            checkpoint=run.checkpoint,
            capability_id="interaction.story_generate",
            input_limit=capability.hard_input_tokens,
            saved_items=run.state.get("ensemble_items"),
            save_items=save_items,
            actor_labels={key: value["label"] for key, value in actor_refs.items()},
            known_actor_ids=known_actor_ids,
        )
        visible = [
            event
            for event in result["events"]
            if event.get("visibility") == "public" or player_id in event["observers"]
        ]
        actors = {
            actor_id: {
                **actor_refs[actor_id],
                "state": {
                    "observations": result["state"]["observations"].get(actor_id, []),
                    "history_unknown": actor_id not in prior,
                    "departed": actor_id in result["state"]["departed"],
                },
            }
            for actor_id in packets
        }
    else:
        visible, actors = [], {}
    reference = run.remember(
        {
            "kind": "rehearsal_events",
            "text": json.dumps(visible, ensure_ascii=False),
            "authority": (
                "只叙述这些已裁决且玩家可观察的行动；没有事件支持时不得替人物添加行动。"
            ),
        }
    )
    plan = StoryPreparation(
        scene_intent="按照玩家当前选择和可观察的裁决事件写本轮故事。未定结果保留未定，不替玩家做决定。",
        evidence_ids=[reference["evidence_id"]],
        warnings=[
            "角色在旧私有旅程中缺少已保存观察的部分保持未知；只复用当前选中分支的状态。"
        ],
    )
    run.state["collaboration"] = {
        "protocol": "team_v1",
        "resolved": True,
        "source_revision_id": source_id,
        "actors": actors,
        "events_hash": content_hash(visible),
        "plan": plan.model_dump(mode="json"),
    }
    run.state.pop("ensemble_items", None)
    await run.checkpoint()
    return plan


async def persist_actor_states(db, *, journey, attempt, node):
    """Called inside the existing node/selection transaction, before private cleanup."""
    data = (attempt.agent_checkpoint_json or {}).get("collaboration") or {}
    if data.get("protocol") not in {"team_v1", "observation_v2"} or not data.get(
        "resolved"
    ):
        raise ValueError("RP ensemble state is not ready for node commit")
    if str(attempt.source_revision_id) != data["source_revision_id"]:
        raise ValueError("RP ensemble source changed")
    response_to = await db.get(type(node), attempt.response_to_node_id)
    from modules.interaction.repositories import InteractionRepository

    ancestry = await InteractionRepository().get_ancestry(
        db, journey=journey, node=response_to
    )
    latest = await selected_actor_states(
        db, journey, ancestry, attempt.source_revision_id
    )
    refs = []
    for actor_id, actor in data["actors"].items():
        parent = latest.get(actor_id)
        if actor["parent_id"] != (str(parent.id) if parent else None):
            raise ValueError("RP actor parent is outside the selected ancestry")
        row = InteractionActorStateRevision(
            novel_id=journey.novel_id,
            journey_id=journey.id,
            message_node_id=node.id,
            actor_id=UUID(actor_id),
            parent_id=parent.id if parent else None,
            source_revision_id=attempt.source_revision_id,
            state_json=actor["state"],
            state_hash=content_hash(actor["state"]),
        )
        db.add(row)
        await db.flush()
        refs.append(str(row.id))
    return refs
