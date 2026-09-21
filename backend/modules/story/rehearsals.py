"""Story-owned durable rehearsal rounds and immutable branch prefixes."""

from __future__ import annotations

import asyncio
import json
from copy import deepcopy
from uuid import UUID

from sqlalchemy import select

from core.errors import ConflictError, NotFoundError
from infrastructure.llm.agent_runtime import AgentRunBudget
from infrastructure.llm.capabilities import capability_from_execution_snapshot
from infrastructure.llm.collaboration import checkpoint_transaction, content_hash
from infrastructure.llm.workflow_budget import workflow_budget
from modules.evidence.facade import prepare_confirmed_ai_action
from modules.project.facade import require_active_project
from modules.story.generation import STORY_ONE_CLICK_ACTION, StoryGenerationService
from modules.story.models import StorySimulationRun, StorySimulationStep
from modules.story.schemas import OneClickOutput, StoryOneClickTaskRequest
from modules.story.simulation import rehearse_round


async def _run(db, novel_id, run_id, *, lock=False):
    query = select(StorySimulationRun).where(
        StorySimulationRun.novel_id == UUID(novel_id),
        StorySimulationRun.id == UUID(run_id),
    )
    row = await db.scalar(query.with_for_update() if lock else query)
    if row is None:
        raise NotFoundError("排演不存在")
    return row


async def _steps(db, novel_id, run_id):
    return list(
        (
            await db.scalars(
                select(StorySimulationStep)
                .where(
                    StorySimulationStep.novel_id == UUID(novel_id),
                    StorySimulationStep.run_id == UUID(run_id),
                )
                .order_by(StorySimulationStep.round_number)
            )
        ).all()
    )


async def run_rehearsal(
    db, task, data, *, client, authority, scene_context, character_reveals
):
    from modules.story.facade import get_scene_story_context
    from modules.story.observations import seeded_state

    novel_id, run_id = data.novel_id, str(task.id)
    source_hash = content_hash(
        {
            **(
                {
                    "protocol": data.simulation_protocol,
                    "seed": data.simulation_seed.model_dump(mode="json")
                    if data.simulation_seed
                    else None,
                }
                if data.simulation_protocol == "observation_v2"
                else {}
            ),
            "scene": scene_context["context_hash"],
            "characters": {
                key: value["hash"] for key, value in character_reveals.items()
            },
        }
    )
    row = await db.get(StorySimulationRun, task.id)
    if row is None:
        row = StorySimulationRun(
            id=task.id,
            novel_id=UUID(novel_id),
            scene_id=UUID(data.scene_id),
            parent_id=data.parent_rehearsal_id,
            fork_round=data.fork_round,
            source_hash=source_hash,
            request_json=data.model_dump(mode="json"),
            budget_json=AgentRunBudget(policy_version="team_v1").model_dump(mode="json"),
        )
        db.add(row)
        await db.flush()
        if data.parent_rehearsal_id:
            parent = await _run(db, novel_id, str(data.parent_rehearsal_id))
            prefix = [
                step
                for step in await _steps(db, novel_id, str(parent.id))
                if step.round_number <= data.fork_round
            ]
            if (
                parent.source_hash != source_hash
                or parent.scene_id != row.scene_id
                or not prefix
                or prefix[-1].round_number != data.fork_round
                or prefix[-1].output_hash != data.parent_round_hash
            ):
                raise ConflictError("原回合或场景依据已变化，不能沿用此分叉")
            for step in prefix:
                db.add(
                    StorySimulationStep(
                        novel_id=row.novel_id,
                        run_id=row.id,
                        round_number=step.round_number,
                        input_hash=step.input_hash,
                        output_hash=step.output_hash,
                        intents_json=deepcopy(step.intents_json),
                        events_json=deepcopy(step.events_json),
                        state_json=deepcopy(step.state_json),
                    )
                )
        await db.commit()
    if str(row.novel_id) != novel_id or row.source_hash != source_hash:
        raise ConflictError("排演来源已变化，请从当前场景开始新排演")
    if row.result_json:
        return row.result_json
    budget = AgentRunBudget.model_validate(row.budget_json)
    if budget.pending_usage:
        budget.usage_unknown, budget.usage_complete, budget.pending_usage = True, False, 0
    packets = {key: value["markdown"] for key, value in character_reveals.items()}
    from modules.world.facade import get_characters_context

    characters = await get_characters_context(db, novel_id, list(packets))
    actor_labels = {
        character.character_id: character.name for character in characters.characters
    }
    steps = await _steps(db, novel_id, run_id)
    state = (
        deepcopy(steps[-1].state_json)
        if steps
        else seeded_state(data.simulation_seed, packets)
    )
    pending = dict(row.request_json.get("pending_round") or {})
    lock = asyncio.Lock()

    async def checkpoint(_values=None):
        async with checkpoint_transaction(lock, db):
            await require_active_project(db, novel_id)
            current = await _run(db, novel_id, run_id, lock=True)
            current.budget_json = budget.model_dump(mode="json")
            current.request_json = {
                **current.request_json,
                "pending_round": deepcopy(pending),
            }
            await db.commit()

    async def revalidate():
        await prepare_confirmed_ai_action(
            db,
            novel_id=novel_id,
            action=STORY_ONE_CLICK_ACTION,
            confirmation_id=data.context_confirmation_id,
        )
        latest = await get_scene_story_context(
            db,
            novel_id=novel_id,
            scene_id=data.scene_id,
            character_ids=data.character_ids,
        )
        if latest is None or latest.context_hash != scene_context["context_hash"]:
            raise ConflictError("场景或人物资料已变化，已保留完成回合")

    profile = capability_from_execution_snapshot(task.meta["llm_execution_snapshot"])
    await db.commit()
    final_round = data.fork_round + data.rehearsal_rounds
    for number in range(len(steps) + 1, final_round + 1):
        if set(state.get("departed", [])) >= packets.keys():
            break
        if pending and pending.get("round") != number:
            raise ConflictError("排演恢复位置不一致")
        pending.setdefault("round", number)

        async def save_items(values):
            pending["items"] = values
            await checkpoint()

        result = await rehearse_round(
            client=client,
            packets=packets,
            state=state,
            authority=authority,
            budget=budget,
            checkpoint=checkpoint,
            capability_id="story.one_click",
            input_limit=profile.hard_input_tokens,
            saved_items=pending.get("items"),
            save_items=save_items,
            actor_labels=actor_labels,
            known_actor_ids={
                key: value.get("known_actor_ids", [])
                for key, value in character_reveals.items()
            },
            protocol=data.simulation_protocol,
        )
        await revalidate()
        step = StorySimulationStep(
            novel_id=UUID(novel_id),
            run_id=task.id,
            round_number=number,
            input_hash=result["input_hash"],
            output_hash=content_hash(result),
            intents_json={
                "intents": result["intents"],
                "resolution_batch": result["resolution_batch"],
            }
            if data.simulation_protocol == "observation_v2"
            else result["intents"],
            events_json=result["events"],
            state_json=result["state"],
        )
        db.add(step)
        state = result["state"]
        pending.clear()
        await checkpoint()
        steps.append(step)
        task.update_progress(min(0.8, number / max(1, final_round) * 0.8))
    events = [
        event
        for step in steps
        for event in step.events_json
        if not data.narrator_character_id
        or str(data.narrator_character_id) in event["observers"]
    ]
    await db.commit()
    with workflow_budget(budget, checkpoint):
        script = await StoryGenerationService().script_preview(
            client,
            context_markdown=json.dumps(events, ensure_ascii=False),
            scene_context={
                "novel_id": novel_id,
                "scene_id": data.scene_id,
                "adjudicated_events": events,
            },
            character_ids=data.character_ids,
            additional_notes="只叙述已裁决且已提供的事件；uncertai"
            "n 仍是未定，不能补写成功、新行动或新秘密。",
        )
    await revalidate()
    if str(script.scene_id) != data.scene_id:
        raise ConflictError("剧本没有绑定本次排演场景")
    row = await _run(db, novel_id, run_id, lock=True)
    row.result_json = {
        "preview": OneClickOutput(
            scene_id=data.scene_id, cards=[], reactions=[], script=script
        ).model_dump(mode="json"),
        "preview_only": True,
        "writes": [],
        "rehearsal_id": run_id,
        "round_count": len(steps),
        "source_hash": source_hash,
    }
    await checkpoint()
    return row.result_json


async def read_rehearsal(db, novel_id, run_id, actor_id=None):
    row = await _run(db, novel_id, run_id)
    data = StoryOneClickTaskRequest.model_validate(
        {key: value for key, value in row.request_json.items() if key != "pending_round"}
    )
    if actor_id and actor_id not in data.character_ids:
        raise NotFoundError("这名人物不属于该排演")
    steps = await _steps(db, novel_id, run_id)
    return {
        "id": run_id,
        "scene_id": str(row.scene_id),
        "parent_id": str(row.parent_id) if row.parent_id else None,
        "source_hash": row.source_hash,
        "protocol": data.simulation_protocol,
        "scenario_seed": data.simulation_seed.model_dump(mode="json")
        if data.simulation_seed and not actor_id
        else None,
        "result": row.result_json
        if not actor_id or str(data.narrator_character_id) == actor_id
        else {},
        "usage": row.budget_json,
        "rounds": [
            {
                "number": step.round_number,
                "hash": step.output_hash,
                "events": [
                    event
                    for event in step.events_json
                    if not actor_id or actor_id in event["observers"]
                ],
            }
            for step in steps
        ],
    }


async def replay_rehearsal(db, novel_id, run_id):
    from modules.story.observations import (
        ResolutionBatch,
        SimulationSeed,
        replay_batch,
        seeded_state,
    )

    row = await _run(db, novel_id, run_id)
    if row.request_json.get("simulation_protocol") != "observation_v2":
        raise ConflictError("这份旧排演没有可重放的状态差量，仍可查看原回合")
    state = seeded_state(
        SimulationSeed.model_validate(row.request_json["simulation_seed"])
        if row.request_json.get("simulation_seed")
        else None,
        row.request_json["character_ids"],
    )
    rounds = []
    for step in await _steps(db, novel_id, run_id):
        batch = ResolutionBatch.model_validate(step.intents_json["resolution_batch"])
        state = replay_batch(state, batch)
        if content_hash(state) != content_hash(step.state_json):
            raise ConflictError("排演状态回执不一致")
        rounds.append({"number": step.round_number, "state_hash": content_hash(state)})
    return {"verified": True, "model_requests": 0, "rounds": rounds}
