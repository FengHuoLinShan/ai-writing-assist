"""Isolated, author-budgeted candidate world-progression task over simulation_v3."""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select

from infrastructure.llm.agent_step_harness import run_managed_structured
from infrastructure.llm.capabilities import capability_from_execution_snapshot
from infrastructure.llm.collaboration import content_hash
from infrastructure.llm.schemas import AI_RUN_ENVELOPE_KEY, LLMCallRequest, LLMMessage
from infrastructure.llm.workflow_budget import current_ai_run_envelope
from infrastructure.tasks.facade import (
    checkpoint_handler_session,
    require_task_checkpoint_session,
)
from infrastructure.tasks.registry import task_handler
from modules.evidence.facade import prepare_confirmed_ai_action
from modules.project.facade import open_project_snapshot_llm_client
from modules.story.generation import STORY_ONE_CLICK_ACTION
from modules.story.rehearsals import validate_simulation_context_refs
from modules.story.simulation_v3 import (
    FiniteOutcome,
    FiniteResolution,
    SimulationIntentDraft,
    SimulationReference,
    SimulationV3Context,
    replay_batch,
    resolve_simulation_v3,
)
from modules.story.world_progression_context import (
    read_progression_source,
    scope_progression_source,
)
from modules.story.world_progression_engine import (
    derive_progression_metrics,
    detect_progression_intersections,
    low_progress_advice,
)
from modules.story.world_progression_models import (
    StoryWorldProgressionAuthorization,
    StoryWorldProgressionRoot,
    StoryWorldProgressionStep,
)
from modules.story.world_progression_schemas import (
    ProgressionActorDraft,
    ProgressionActorIntent,
    ProgressionParticipant,
    ProgressionStepResolution,
    ProgressionTarget,
)
from modules.story.world_progression_service import (
    append_progression_step,
    get_progression_branch,
    get_progression_root,
    get_progression_step,
    lineage_metrics,
)

WORLD_PROGRESSION_TASK = "story_world_progression"
WORLD_PROGRESSION_CAPABILITY = "story.world_progression"


def _task_meta(
    *,
    request,
    root_id,
    branch_id,
    execution_snapshot,
    envelope,
    acknowledged_unknown=0,
):
    frozen = envelope.snapshot()
    snapshot = frozen.model_dump(mode="json")
    return {
        "meta_version": 1,
        "request": request,
        "world_progression_root_id": str(root_id),
        "world_progression_branch_id": str(branch_id),
        "world_progression_authorized_requests": int(snapshot["request_limit"]),
        "world_progression_authorized_tokens": int(snapshot["token_limit"]),
        "world_progression_deadline_seconds": max(
            1,
            int((frozen.deadline_at - frozen.started_at).total_seconds())
            if frozen.deadline_at
            else 3600,
        ),
        "world_progression_acknowledged_unknown_requests": acknowledged_unknown,
        "world_progression_baseline_requests_started": snapshot["requests_started"],
        "llm_execution_snapshot": execution_snapshot,
        AI_RUN_ENVELOPE_KEY: snapshot,
    }


def _meta(task) -> dict:
    return dict(task.meta or {})


def _request_limit(task) -> int:
    return int(_meta(task).get("world_progression_authorized_requests") or 1)


def _token_limit(task) -> int:
    return int(_meta(task).get("world_progression_authorized_tokens") or 1)


def _deadline_seconds(task) -> float:
    return float(_meta(task).get("world_progression_deadline_seconds") or 3600)


def _stable_root_id(task) -> str:
    root_id = str(_meta(task).get("world_progression_root_id") or "").strip()
    if not root_id:
        raise ValueError("世界推进任务缺少持久根身份")
    return root_id


def _monotonic_envelope(previous: dict, current: dict) -> None:
    for field in (
        "run_id",
        "root_capability_id",
        "novel_id",
        "started_at",
        "deadline_at",
    ):
        if field in previous and previous[field] != current.get(field):
            raise ValueError("世界推进预算检查点的根身份或时限发生变化")
    for field in (
        "requests_started",
        "requests_settled",
        "requests_unknown",
        "recent_attempts_overflow",
        "request_limit",
        "token_limit",
    ):
        old, new = previous.get(field), current.get(field)
        if old is not None and (new is None or int(new) < int(old)):
            raise ValueError("拒绝用旧预算快照覆盖累计账本")
    old_tokens = (previous.get("usage") or {}).get("total_tokens")
    new_tokens = (current.get("usage") or {}).get("total_tokens")
    if old_tokens is not None and (
        new_tokens is None or int(new_tokens) < int(old_tokens)
    ):
        raise ValueError("拒绝用旧 Token 快照覆盖累计账本")


async def _mirror_run_envelope(session, task, payload):
    meta = _meta(task)
    root_id = meta.get("world_progression_root_id")
    if not root_id:
        raise ValueError("世界推进预算检查点缺少运行根")
    root = await session.scalar(
        select(StoryWorldProgressionRoot)
        .where(
            StoryWorldProgressionRoot.novel_id == task.novel_id,
            StoryWorldProgressionRoot.id == UUID(str(root_id)),
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if root is None:
        raise ValueError("世界推进预算根已不存在")
    previous = root.run_envelope_json or {}
    _monotonic_envelope(previous, payload)
    root.run_envelope_json = dict(payload)


@task_handler(
    WORLD_PROGRESSION_TASK,
    recovery_policy="never_retry",
    max_attempts=1,
    retry_transient_llm_errors=False,
    root_capability_id=WORLD_PROGRESSION_CAPABILITY,
    run_request_limit=_request_limit,
    run_token_limit=_token_limit,
    run_deadline_seconds=_deadline_seconds,
    run_id=_stable_root_id,
    run_envelope_checkpoint=_mirror_run_envelope,
    run_eighty_percent_stop=True,
)
async def handle_world_progression(db, task):
    """Run one or more explicitly authorized steps; no canon or manuscript writes."""
    require_task_checkpoint_session(db)
    meta = _meta(task)
    novel_id = str(task.novel_id)
    root_id = str(meta.get("world_progression_root_id") or "")
    branch_id = str(meta.get("world_progression_branch_id") or "")
    if not root_id or not branch_id:
        raise ValueError("世界推进任务缺少持久根或分支")
    continuous_revision = meta.get("continuous_authorization_revision")
    if continuous_revision is not None:
        # Chapter ingestion takes authorization before root. Match that order
        # before the first durable checkpoint to avoid an authorization/root cycle.
        await db.scalar(
            select(StoryWorldProgressionAuthorization)
            .where(StoryWorldProgressionAuthorization.novel_id == UUID(novel_id))
            .with_for_update()
        )
    root = await get_progression_root(db, novel_id, root_id, lock=True)
    branch = await get_progression_branch(db, novel_id, branch_id, lock=True)
    if str(branch.root_id) != root_id:
        raise ValueError("世界推进分支与运行根不匹配")
    if str(task.id) != str(root.current_task_id) or str(task.id) != str(
        branch.current_task_id
    ):
        raise ValueError("世界推进任务身份已失效")

    payload = meta.get("request") or {}
    if str(payload.get("novel_id") or "") != novel_id:
        raise ValueError("世界推进任务与作品身份不匹配")
    envelope = current_ai_run_envelope()
    if (
        envelope is None
        or envelope.run_id != root_id
        or envelope.root_capability_id != WORLD_PROGRESSION_CAPABILITY
        or envelope.snapshot().novel_id != novel_id
    ):
        raise ValueError("世界推进根预算信封身份不匹配")
    budget_guard = {
        "acknowledged_unknown": int(
            meta.get("world_progression_acknowledged_unknown_requests") or 0
        ),
        "baseline_requests_started": int(
            meta.get("world_progression_baseline_requests_started") or 0
        ),
    }

    root_request = dict(root.request_json or {})
    branch_overrides = dict(branch.request_json or {})
    for key in (
        "participants",
        "mode",
        "step_length",
        "run_policy",
        "steps",
        "stop_at_goal",
        "scene_id",
        "targets",
        "instructions",
        "retained_constraints",
    ):
        if key in branch_overrides:
            root_request[key] = branch_overrides[key]
    participants = [
        ProgressionParticipant.model_validate(item)
        for item in root_request.get("participants") or []
    ]
    character_ids = [item.id for item in participants if item.kind == "character"]
    if continuous_revision is not None:
        authorization = await db.scalar(
            select(StoryWorldProgressionAuthorization)
            .where(StoryWorldProgressionAuthorization.novel_id == UUID(novel_id))
            .with_for_update()
        )
        if (
            authorization is None
            or not authorization.enabled
            or authorization.revision != int(continuous_revision)
            or str(authorization.root_id) != root_id
            or str(authorization.branch_id) != branch_id
            or set(authorization.participant_ids_json or [])
            != set(meta.get("continuous_authorized_participant_ids") or [])
            or not {item.id for item in participants}
            <= set(authorization.participant_ids_json or [])
        ):
            raise ValueError("持续推进授权已撤销或参与范围已变化")
        context_confirmation_id = str(authorization.context_confirmation_id or "")
    else:
        context_confirmation_id = str(payload.get("context_confirmation_id") or "")
    if not context_confirmation_id:
        raise ValueError("世界推进任务缺少原资料确认")
    confirmed = await prepare_confirmed_ai_action(
        db,
        novel_id=novel_id,
        action=STORY_ONE_CLICK_ACTION,
        confirmation_id=context_confirmation_id,
    )
    options = dict(confirmed.compile_options or {})
    confirmed_characters = set(map(str, options.get("character_ids") or []))
    confirmed_entities = set(map(str, options.get("entity_ids") or []))
    participant_ids = {item.id for item in participants}
    if continuous_revision is None:
        if confirmed_characters != set(character_ids):
            raise ValueError("资料确认人物范围与世界推进参与者不一致")
    elif not set(character_ids) <= confirmed_characters:
        raise ValueError("持续推进确认没有包含本次参与人物")
    if not participant_ids <= confirmed_entities | confirmed_characters:
        raise ValueError("资料确认对象范围与世界推进参与者不一致")

    selected_scene_id = root_request.get("scene_id") or str(root.scene_id)
    current_source = await read_progression_source(
        db,
        novel_id=novel_id,
        scene_id=str(selected_scene_id),
        participants=participants,
        targets=[
            ProgressionTarget.model_validate(item)
            for item in root_request.get("targets") or []
        ],
        confirmed_context=confirmed,
    )
    frozen_source = dict(branch.source_snapshot_json or root.source_snapshot_json or {})
    if not frozen_source:
        raise ValueError("世界推进根缺少冻结来源快照")
    if branch.basis_choice == "current":
        source = current_source
        if current_source["source_hash"] != branch.source_hash:
            branch.status = root.status = "failed"
            branch.stop_reason = "source_changed_before_execution"
            branch.current_task_id = root.current_task_id = None
            await _checkpoint(db, root, branch, "来源漂移的失败状态未保存")
            raise ValueError("已选当前来源在任务入队后变化；请刷新并明确选择新依据")
        basis_changed = current_source["source_hash"] != root.source_hash
    else:
        source = await scope_progression_source(
            db,
            frozen_source,
            confirmed.compiled,
            expected_novel_id=novel_id,
            expected_scene_id=str(root.scene_id),
        )
        basis_changed = current_source["source_hash"] != source["source_hash"]
    scene_id = str(source["scene_id"])
    if options.get("scene_id") and str(options["scene_id"]) != scene_id:
        raise ValueError("确认资料的 Scene 截止点已变化")
    simulation_context = SimulationV3Context.model_validate(source["simulation_context"])
    await validate_simulation_context_refs(db, novel_id, simulation_context)
    run_snapshot = meta.get("llm_execution_snapshot") or root.llm_execution_snapshot_json
    if (
        not isinstance(run_snapshot, dict)
        or str(run_snapshot.get("novel_id") or "") != novel_id
    ):
        raise ValueError("世界推进任务缺少匹配的项目模型快照")
    input_limit = int(capability_from_execution_snapshot(run_snapshot).hard_input_tokens)

    pending = dict(branch.pending_step_json or {})
    if pending and (
        pending.get("parent_step_id") != str(branch.parent_step_id or "")
        or pending.get("source_hash") != source["source_hash"]
    ):
        raise ValueError("未完成步骤的输入依据已变化；请先选择冻结或当前历史分支")
    if not pending:
        parent = (
            await get_progression_step(db, novel_id, str(branch.parent_step_id))
            if branch.parent_step_id
            else None
        )
        initial_state = (
            deepcopy(parent.state_json)
            if parent is not None
            else simulation_context.initial_state()
        )
        initial_state.setdefault("candidate_status", {})
        initial_state.setdefault("candidate_attitudes", {})
        initial_state.setdefault("candidate_knowledge", {})
        initial_state.setdefault("candidate_resources", {})
        initial_state.setdefault("rolling_summary", "")
        pending = {
            "parent_step_id": str(branch.parent_step_id or ""),
            "parent_output_hash": parent.output_hash if parent is not None else None,
            "source_hash": source["source_hash"],
            "source_snapshot": source,
            "state_before": initial_state,
            "actor_drafts": {},
            "resolution": None,
        }
        branch.pending_step_json = pending
        branch.status = "running"
        root.status = "running"
        await _checkpoint(db, root, branch, "世界推进首个模型请求检查点未保存")

    request_count = (
        int(root_request.get("steps") or 1)
        if root_request.get("run_policy") == "n_steps"
        else 1
    )
    if root_request.get("run_policy") == "one_step":
        request_count = 1
    if root_request.get("run_policy") in {"until_goal", "until_budget"}:
        request_count = 0  # continue only while the author-authorized root budget permits
    if request_count:
        prior_count = int(
            await db.scalar(
                select(func.count())
                .select_from(StoryWorldProgressionStep)
                .where(
                    StoryWorldProgressionStep.novel_id == UUID(novel_id),
                    StoryWorldProgressionStep.branch_id == UUID(branch_id),
                )
            )
            or 0
        )
        request_count -= prior_count
        if request_count <= 0:
            raise ValueError("本分支已完成作者选择的全部步数，不能重复续算")
    completed = 0
    last_step_id = str(branch.parent_step_id) if branch.parent_step_id else None
    while True:
        stop = _budget_stop(envelope, **budget_guard)
        if stop:
            paused = (
                "paused_unknown" if stop == "provider_result_unknown" else "paused_budget"
            )
            root.status = branch.status = paused
            branch.stop_reason = stop
            root.current_task_id = branch.current_task_id = None
            root.run_envelope_json = envelope.snapshot().model_dump(mode="json")
            await _checkpoint(db, root, branch, "世界推进预算暂停状态未保存")
            return _task_result(paused, root_id, branch_id, completed, stop, last_step_id)

        state = deepcopy(pending["state_before"])
        parent_id = pending.get("parent_step_id") or None
        try:
            result = await _run_one_step(
                db,
                task,
                root,
                branch,
                root_request,
                pending,
                source,
                participants,
                simulation_context,
                input_limit=input_limit,
                envelope=envelope,
                budget_guard=budget_guard,
                basis_changed=basis_changed,
            )
        except Exception as error:
            stop = _budget_stop(envelope, **budget_guard)
            branch.status = (
                "paused_unknown"
                if stop == "provider_result_unknown"
                else "paused_budget"
                if stop
                else "failed"
            )
            root.status = branch.status
            if stop:
                branch.stop_reason = stop
            elif isinstance(error, ValueError) and pending.get("resolution"):
                branch.stop_reason = "invalid_resolution"
            else:
                branch.stop_reason = "step_failed"
            branch.current_task_id = root.current_task_id = None
            root.run_envelope_json = envelope.snapshot().model_dump(mode="json")
            await _checkpoint(db, root, branch, "世界推进失败或暂停状态未保存")
            raise
        metrics = result.pop("metrics")
        state_after = result.pop("state_after")
        input_payload = {
            "parent_output_hash": pending.get("parent_output_hash"),
            "basis_choice": branch.basis_choice,
            "source_changed": basis_changed,
            "step_length": pending["step_length"],
            "input_hash_basis": content_hash(
                {"source_hash": source["source_hash"], "parent_state": state}
            ),
        }
        prior_lineage = await lineage_metrics(db, novel_id, parent_step_id=parent_id)
        advice = low_progress_advice([*prior_lineage, {**metrics, "step_id": "pending"}])
        if advice:
            result["progress_advice"] = advice
        row = await append_progression_step(
            db,
            novel_id=novel_id,
            root=root,
            branch=branch,
            parent_step_id=parent_id,
            source_hash=source["source_hash"],
            input_payload=input_payload,
            output_payload=result,
            state=state_after,
            metrics=metrics,
            basis_changed=basis_changed,
        )
        last_step_id = str(row.id)
        last_output_hash = row.output_hash
        completed += 1
        branch.pending_step_json = {}
        branch.parent_step_id = row.id
        branch.status = "ready"
        branch.stop_reason = None
        root.status = "ready"
        root.run_envelope_json = envelope.snapshot().model_dump(mode="json")
        await _checkpoint(db, root, branch, "世界推进步骤与历史哈希未持久化")
        task.update_progress(
            min(0.98, completed / max(1, request_count or completed + 1))
        )

        if _goals_reached(result, source) and (
            root_request.get("run_policy") == "until_goal"
            or root_request.get("stop_at_goal", False)
        ):
            break
        if request_count and completed >= request_count:
            break
        if not request_count and root_request.get("run_policy") == "until_goal":
            # If model explicitly reports that every goal is blocked, further steps
            # need an author decision rather than an unbounded speculative loop.
            outcomes = result.get("goal_outcomes") or []
            if outcomes and all(item.get("status") == "blocked" for item in outcomes):
                break
        if _budget_stop(envelope, **budget_guard):
            break
        pending = _new_pending_step(
            source=source,
            state=state_after,
            parent_step_id=last_step_id,
            parent_output_hash=last_output_hash,
            step_length=root_request.get("step_length", "auto"),
        )
        branch.pending_step_json = pending
        await _checkpoint(db, root, branch, "下一世界推进步骤检查点未保存")
        if root_request.get("run_policy") == "one_step":
            break
        if (
            not request_count
            and root_request.get("run_policy") == "until_budget"
            and completed
        ):
            # Keep every step durable and stop before the next provider call if the
            # remaining budget cannot reach the 80% safety margin.
            if _budget_stop(envelope, **budget_guard):
                break

    branch.pending_step_json = {}
    branch.status = "complete"
    branch.stop_reason = None
    branch.current_task_id = None
    root.status = "ready"
    root.current_task_id = None
    root.run_envelope_json = envelope.snapshot().model_dump(mode="json")
    await _checkpoint(db, root, branch, "世界推进完成状态未保存")
    task.update_progress(1.0)
    return _task_result("complete", root_id, branch_id, completed, None, last_step_id)


def _new_pending_step(*, source, state, parent_step_id, parent_output_hash, step_length):
    return {
        "parent_step_id": parent_step_id or "",
        "parent_output_hash": parent_output_hash,
        "source_hash": source["source_hash"],
        "source_snapshot": source,
        "state_before": deepcopy(state),
        "actor_drafts": {},
        "resolution": None,
        "step_length": step_length,
    }


def _task_result(status, root_id, branch_id, completed, stop_reason, step_id):
    return {
        "status": status,
        "root_id": root_id,
        "branch_id": branch_id,
        "completed_steps": completed,
        "last_step_id": step_id,
        "budget_stop": stop_reason,
        "needs_author_resume": status in {"paused_budget", "paused_unknown"},
        "candidate_only": True,
    }


def _goals_reached(result: dict, source: dict) -> bool:
    statuses = {
        str(item.get("target_id")): item.get("status")
        for item in result.get("goal_outcomes", [])
    }
    required = {
        str(item.get("id"))
        for item in source.get("targets", [])
        if item.get("must_reach")
    }
    if required:
        return all(statuses.get(target_id) == "completed" for target_id in required)
    return any(status == "completed" for status in statuses.values())


def _actor_view_packet(role: dict, state: dict, actor_id: str, step_length: str) -> dict:
    """Only project this actor's visible evidence; the author summary is private."""
    actor_key = f"object:{actor_id}"
    known_entities = set(role.get("known_entity_ids") or [])
    holders = state.get("resource_holders", {})
    return {
        "viewpoint": role.get("viewpoint"),
        "visible_brief": role.get("brief"),
        "source_ids": role.get("source_ids", []),
        "known_participant_ids": role.get("known_participant_ids", []),
        "known_entity_ids": role.get("known_entity_ids", []),
        "known_route_ids": role.get("known_route_ids", []),
        "own_observations": state.get("observations", {}).get(actor_key, []),
        "own_location": state.get("locations", {}).get(actor_key),
        "own_candidate_status": {
            key: value
            for key, value in state.get("candidate_status", {}).items()
            if key.startswith(f"{actor_id}:")
        },
        "own_candidate_knowledge": {
            key: value
            for key, value in state.get("candidate_knowledge", {}).items()
            if key.startswith(f"{actor_id}:")
            and value.get("modality") in {"direct_observation", "reported_claim"}
        },
        "own_candidate_attitudes": {
            key: value
            for key, value in state.get("candidate_attitudes", {}).items()
            if key.startswith(f"{actor_id}:")
        },
        "held_resources": [key for key, holder in holders.items() if holder == actor_key],
        "known_resource_keys": [
            key
            for key, holder in holders.items()
            if key.partition(":")[2] in known_entities or holder == actor_key
        ],
        "step_length": step_length,
    }


def _budget_stop(
    envelope,
    *,
    acknowledged_unknown: int = 0,
    baseline_requests_started: int = 0,
) -> str | None:
    snapshot = envelope.snapshot()
    if snapshot.requests_unknown > acknowledged_unknown:
        return "provider_result_unknown"
    if any(
        attempt.request_index > baseline_requests_started
        and (
            attempt.outcome.value in {"unknown", "in_flight"}
            or attempt.charge_state.value == "possible"
        )
        for attempt in snapshot.recent_attempts
    ):
        return "provider_result_unknown"
    if not snapshot.usage_complete and (
        not acknowledged_unknown or snapshot.legacy_untracked
    ):
        return "usage_incomplete"
    # The bounded attempt window may overflow during a long, fully settled run.
    # Cumulative unknown and usage counters remain authoritative across eviction.
    if (
        snapshot.request_limit
        and snapshot.requests_started * 5 >= snapshot.request_limit * 4
    ):
        return "request_budget_80_percent"
    if (
        snapshot.token_limit
        and snapshot.usage.total_tokens * 5 >= snapshot.token_limit * 4
    ):
        return "token_budget_80_percent"
    if snapshot.deadline_at is not None:
        started = snapshot.started_at
        deadline = snapshot.deadline_at
        if started.tzinfo is None:
            started = started.replace(tzinfo=UTC)
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=UTC)
        duration = (deadline - started).total_seconds()
        if (
            duration <= 0
            or (datetime.now(UTC) - started).total_seconds() * 5 >= duration * 4
        ):
            return "time_budget_80_percent"
    return None


async def _run_one_step(
    db,
    task,
    root,
    branch,
    root_request,
    pending,
    source,
    participants,
    simulation_context,
    *,
    input_limit,
    envelope,
    budget_guard,
    basis_changed,
):
    state = deepcopy(pending["state_before"])
    step_length = pending.setdefault(
        "step_length", root_request.get("step_length", "auto")
    )
    baseline = content_hash(
        {
            "root_id": str(root.id),
            "branch_id": str(branch.id),
            "parent_step_id": pending.get("parent_step_id"),
            "state_hash": content_hash(state),
            "source_hash": source["source_hash"],
        }
    )
    role_drafts = dict(pending.get("actor_drafts") or {})
    active_participant_ids = {item.id for item in participants}
    actor_refs = {
        item.id: SimulationReference(kind="object", id=item.id) for item in participants
    }
    role_limit = int(input_limit * 2)
    async with open_project_snapshot_llm_client(
        db, str(root.novel_id), root.llm_execution_snapshot_json
    ) as client:
        for participant in participants:
            actor_id = participant.id
            if actor_id in role_drafts:
                continue
            stop = _budget_stop(envelope, **budget_guard)
            if stop:
                raise RuntimeError(f"预算已到停止边界：{stop}")
            role = source["role_briefs"][actor_id]
            packet = _actor_view_packet(role, state, actor_id, step_length)
            encoded = json.dumps(packet, ensure_ascii=False, separators=(",", ":"))
            if len(encoded) > role_limit:
                # Grouping was already disclosed by the source reader. Here we do
                # not silently truncate a role packet: fail before paid generation.
                raise ValueError("单人物资料超过模型上下文；请缩小本次参与者或资料范围")
            await _checkpoint(db, root, branch, "人物意图请求前检查点未保存")
            await _lock_continuous_authorization(db, task, participants)
            draft = await run_managed_structured(
                client,
                LLMCallRequest(
                    model=client.model_name,
                    messages=[
                        LLMMessage(
                            role="system",
                            content=(
                                "你只扮演当前参与者，只能依据 visible_brief、"
                                "本人已观察事件、本人候选状态/知识及本人可见路线提出一步意图。"
                                "候选状态只属于本次模拟，不是 Story 正史。"
                                "不要看到作者目标、秘密、保留项或其他人物私有意图。"
                                "身份必须等于当前 actor_id。旧地名不能转成 ID；"
                                "地点、对象、路线、资源与收信者只可引用输入的 typed ID。"
                                "行为只是意图，不能写成结果或正史。"
                            ),
                        ),
                        LLMMessage(
                            role="user",
                            content=json.dumps(
                                {"actor_id": actor_id, "packet": packet},
                                ensure_ascii=False,
                            ),
                        ),
                    ],
                ),
                ProgressionActorDraft,
                step_name="story.world_progression.actor_intent",
                capability_id=WORLD_PROGRESSION_CAPABILITY,
                max_fix_attempts=0,
                transport_retries=False,
            )
            if draft.intent.actor_id != actor_id:
                raise ValueError("人物意图身份与当前角色不一致")
            _validate_actor_intent(
                draft.intent,
                participant,
                role,
                source,
                state,
                active_participant_ids=active_participant_ids,
            )
            role_drafts[actor_id] = draft.intent.model_dump(mode="json")
            pending["actor_drafts"] = role_drafts
            branch.pending_step_json = pending
            await _checkpoint(db, root, branch, "人物意图持久检查点未提交")

        intents = []
        action_rows = []
        movement_checks = []
        intent_ids = {}
        for actor_id, raw in role_drafts.items():
            draft = ProgressionActorIntent.model_validate(raw)
            intent_id = content_hash({"step": baseline, "actor_id": actor_id})
            intent_ids[actor_id] = intent_id
            actor_ref = actor_refs[actor_id]
            movement_check = _check_movement_feasibility(
                draft,
                source=source,
                state=state,
                role=source["role_briefs"][actor_id],
                actor_id=actor_id,
            )
            if movement_check is not None:
                movement_checks.append(movement_check)
            sim_draft = SimulationIntentDraft(
                kind=draft.kind,
                action=draft.action,
                internal_reason=draft.reason,
                effect=draft.effect,
                visibility=draft.visibility,
                audience=[
                    SimulationReference(kind="object", id=value)
                    for value in draft.information_recipient_ids
                ],
                resource=_resource_reference(draft.resource_key, state)
                if draft.effect == "resource_transfer"
                else None,
                recipient=SimulationReference(kind="object", id=draft.target_object_id)
                if draft.target_object_id
                else None,
                destination=(
                    SimulationReference(
                        kind=draft.location_target.kind, id=draft.location_target.id
                    )
                    if draft.location_target
                    else None
                ),
                unresolved=bool(
                    movement_check and movement_check["status"] == "uncertain"
                ),
            )
            intent = sim_draft.bind(
                intent_id=intent_id, actor=actor_ref, mode="world_progression_step"
            )
            intents.append(intent)
            action_rows.append({**draft.model_dump(mode="json"), "intent_id": intent_id})

        intersection_result = detect_progression_intersections(
            action_rows,
            route_comparison_available=source.get("map_state", {}).get(
                "coverage", "not_available"
            ),
        )
        resolution_raw = pending.get("resolution")
        if resolution_raw is None:
            stop = _budget_stop(envelope, **budget_guard)
            if stop:
                raise RuntimeError(f"预算已到停止边界：{stop}")
            director_packet = {
                "author_mode": root_request.get("mode"),
                "author_instructions": root_request.get("instructions", ""),
                "retained_constraints": root_request.get("retained_constraints", []),
                "targets": source.get("targets", []),
                "author_time_basis": source.get("time_basis", {}),
                "target_paths_previous": root_request.get("target_paths_previous", []),
                "step_length": step_length,
                "state_before": state,
                "participant_intents": action_rows,
                "movement_feasibility": movement_checks,
                "structural_intersections": intersection_result,
                "available_author_sources": source.get("author_source_ids", []),
                "life_state_checks": source.get("life_state_checks", []),
                "typed_object_validity": source.get("object_validity_notices", []),
                "source_gaps": _progression_source_gaps(source),
                "target_rule": (
                    "软目标默认；must_reach=true 的目标须保留明确状态，不得违背资料强推。"
                ),
                "time_rule": (
                    "story_time_text 是模型估计，不代表产品日历实现；回执须标明估计性质。"
                ),
            }
            if len(json.dumps(director_packet, ensure_ascii=False)) > input_limit * 2:
                raise ValueError("导演裁决资料超过模型上下文，需缩小选择范围")
            await _checkpoint(db, root, branch, "有限裁决请求前检查点未保存")
            await _lock_continuous_authorization(db, task, participants)
            resolution = await run_managed_structured(
                client,
                LLMCallRequest(
                    model=client.model_name,
                    messages=[
                        LLMMessage(
                            role="system",
                            content=(
                                "你是世界推进的有限裁决器。逐 intent_id 返回三态结果，"
                                "只给状态、态度、知识、资源、目标路径、交汇结果与钩子候选，不写正文。"
                                "narrative_summary 只概述本步；rolling_summary 要把"
                                " state_before.rolling_summary 的前情与本步合并压缩成"
                                "不超过 4000 字的累计摘要，保留未完成承诺和目标；"
                                "候选变化须有真实来源或当前模拟事件；缺字段即 uncertain。"
                                "传闻标为 reported_claim，不能当事实。"
                                "不得写 World、continuity、正文或 RP 知识。"
                                "目标和秘密只在本层；报告因果路径、必要铺垫、不自然处与副线。"
                                "仅按 movement_feasibility 中的 typed route 检查移动；"
                                "缺少精确位置/路线时必须视为 uncertain。"
                                "typed_object_validity 的 gap 是明确缺口；"
                                "author_priority 按作者有效期，"
                                "story_override 按同一地图声明的精确 Story 状态。"
                                "遇到资料冲突或路线/行程/时间不确定时，"
                                "标 uncertain 并说明未核验项。"
                            ),
                        ),
                        LLMMessage(
                            role="user",
                            content=json.dumps(
                                {
                                    "intent_ids": intent_ids,
                                    "director_packet": director_packet,
                                },
                                ensure_ascii=False,
                            ),
                        ),
                    ],
                ),
                ProgressionStepResolution,
                step_name="story.world_progression.resolve",
                capability_id=WORLD_PROGRESSION_CAPABILITY,
                max_fix_attempts=0,
                transport_retries=False,
            )
            resolution_raw = resolution.model_dump(mode="json")
            pending["resolution"] = resolution_raw
            branch.pending_step_json = pending
            await _checkpoint(db, root, branch, "有限裁决持久检查点未提交")

        resolution = ProgressionStepResolution.model_validate(resolution_raw)
        finite = FiniteResolution(
            outcomes=[
                FiniteOutcome(
                    intent_id=intent.intent_id,
                    outcome=resolution.outcomes.get(intent.intent_id, "uncertain"),
                )
                for intent in intents
            ]
        )
        outcome_ids = set(resolution.outcomes)
        expected_ids = {intent.intent_id for intent in intents}
        if outcome_ids != expected_ids:
            raise ValueError("裁决必须为每条意图提供且只提供一个结算结果")
        batch = resolve_simulation_v3(
            intents,
            finite,
            state,
            observers={f"object:{actor_id}" for actor_id in active_participant_ids},
            rule_revision=content_hash("simulation_v3:world-progression:v1"),
        )
        state_after = replay_batch(state, batch)
        settled_outcomes = {
            str(event["intent_id"]): str(event["outcome"]) for event in batch.events
        }
        expected_intersections = {
            item["intersection_id"]: set(item["actor_ids"])
            for item in intersection_result.get("items") or []
        }
        seen_intersections = {}
        for item in resolution.intersections:
            if item.intersection_id in seen_intersections:
                raise ValueError("结构化交汇结果不能重复")
            seen_intersections[item.intersection_id] = set(item.actor_ids)
        if seen_intersections != expected_intersections:
            raise ValueError("每个结构化交汇都必须返回匹配参与者的结算")
        event_visibility = {}
        for observer, events in state.get("observations", {}).items():
            for event in events:
                event_id = str(event.get("event_id") or "")
                if not event_id:
                    continue
                item = event_visibility.setdefault(
                    event_id, {"event": dict(event), "observers": set()}
                )
                item["observers"].add(str(observer))
        for event in batch.events:
            event_id = str(event.get("event_id") or "")
            if not event_id:
                continue
            item = event_visibility.setdefault(
                event_id, {"event": dict(event), "observers": set()}
            )
            item["event"] = dict(event)
            item["observers"].update(map(str, event.get("observers") or []))
        state_after = _apply_candidate_updates(
            state_after,
            resolution,
            participants={item.id for item in participants},
            source_ids=set(source.get("author_source_ids") or []),
            event_visibility=event_visibility,
            route_ids={
                str(item.get("route_ref_id"))
                for item in (source.get("map_state") or {}).get("routes", [])
            },
            resource_keys=set(state.get("resource_holders", {})),
            current_event_ids={str(event["event_id"]) for event in batch.events},
            targets={
                str(item.get("id")): bool(item.get("must_reach"))
                for item in source.get("targets", [])
            },
            entity_ids={
                str(item.get("entity_id"))
                for item in source.get("author_brief", {}).get("world_items", [])
                if item.get("entity_id")
            },
        )
        state_after["rolling_summary"] = _rolling_summary(
            state_after, resolution, batch.events
        )
        metrics = derive_progression_metrics(
            before_state=state,
            after_state=state_after,
            resolution=resolution.model_dump(mode="json"),
            intersections=intersection_result,
        )
        metrics.update(
            {
                "model_name": client.model_name,
                "step_length": step_length,
                "basis_changed": basis_changed,
                "route_comparison": intersection_result["route_comparison"],
            }
        )
        return {
            "protocol": "story.world_progression.v1",
            "story_time_text": resolution.story_time_text,
            "story_time_basis": "model_estimate_not_calendar",
            "narrative_summary": resolution.narrative_summary,
            "mode": root_request.get("mode", "free"),
            "step_length": step_length,
            "basis_changed": basis_changed,
            "actor_intents": action_rows,
            "movement_feasibility": movement_checks,
            "intent_outcomes": [
                {
                    "intent_id": intent.intent_id,
                    "outcome": settled_outcomes[intent.intent_id],
                }
                for intent in intents
            ],
            "simulated_events": batch.events,
            "state_delta": [item.model_dump(mode="json") for item in batch.state_patches],
            "intersections": intersection_result,
            "intersection_outcomes": [
                item.model_dump(mode="json") for item in resolution.intersections
            ],
            "goal_outcomes": [
                item.model_dump(mode="json") for item in resolution.goal_outcomes
            ],
            "target_paths": [
                item.model_dump(mode="json") for item in resolution.target_paths
            ],
            "setup_needed": resolution.setup_needed,
            "unnatural_points": resolution.unnatural_points,
            "subplots": resolution.subplots,
            "plot_hooks": [
                item.model_dump(mode="json") for item in resolution.plot_hooks
            ],
            "candidate_status_updates": [
                item.model_dump(mode="json") for item in resolution.status_updates
            ],
            "candidate_attitude_updates": [
                item.model_dump(mode="json") for item in resolution.attitude_updates
            ],
            "candidate_resource_updates": [
                item.model_dump(mode="json") for item in resolution.resource_updates
            ],
            "candidate_knowledge_updates": [
                item.model_dump(mode="json") for item in resolution.knowledge_updates
            ],
            "typed_object_validity": source.get("object_validity_notices", []),
            "life_state_checks": source.get("life_state_checks", []),
            "source_gaps": _progression_source_gaps(source),
            "rationale": resolution.rationale,
            "metrics": metrics,
            "state_after": state_after,
        }


def _check_movement_feasibility(
    intent: ProgressionActorIntent,
    *,
    source: dict,
    state: dict,
    role: dict,
    actor_id: str,
) -> dict | None:
    if intent.effect != "move" or intent.location_target is None:
        return None
    actor_key = f"object:{actor_id}"
    origin = state.get("locations", {}).get(actor_key)
    destination = f"{intent.location_target.kind}:{intent.location_target.id}"
    if origin == destination:
        return {
            "actor_id": actor_id,
            "origin": origin,
            "destination": destination,
            "status": "already_at_destination",
            "route_ids": [],
            "basis": "exact_simulation_position",
        }
    if not origin:
        return {
            "actor_id": actor_id,
            "origin": None,
            "destination": destination,
            "status": "uncertain",
            "route_ids": [],
            "reason": "exact_current_position_missing",
        }
    time_facts = (source.get("time_basis") or {}).get("facts") or []
    if not time_facts:
        return {
            "actor_id": actor_id,
            "origin": origin,
            "destination": destination,
            "status": "uncertain",
            "route_ids": [],
            "reason": "exact_cutoff_time_fact_missing",
        }

    cited_route_ids = set(intent.journey_route_ids)
    visible_route_ids = set(role.get("known_route_ids") or [])
    routes_by_id = {
        str(item.get("route_ref_id")): item
        for item in (source.get("map_state") or {}).get("routes", [])
        if item.get("route_ref_id")
    }
    allowed = cited_route_ids & visible_route_ids
    adjacency: dict[str, list[tuple[str, str]]] = {}
    for route_id in sorted(allowed):
        route = routes_by_id.get(route_id)
        if route is None:
            continue
        route_origin = f"{route.get('origin_kind')}:{route.get('origin_id')}"
        route_destination = (
            f"{route.get('destination_kind')}:{route.get('destination_id')}"
        )
        adjacency.setdefault(route_origin, []).append((route_destination, route_id))

    direct = [
        (route_id, routes_by_id[route_id])
        for next_location, route_id in adjacency.get(origin, [])
        if next_location == destination and route_id in routes_by_id
    ]
    if direct:
        route_id, route = direct[0]
        typed_duration = route.get("duration")
        typed_types = route.get("travel_type_evidence") or []
        if not typed_duration or not typed_types:
            return {
                "actor_id": actor_id,
                "origin": origin,
                "destination": destination,
                "status": "uncertain",
                "route_ids": [item[0] for item in direct],
                "reason": "typed_duration_or_travel_type_missing",
            }
        return {
            "actor_id": actor_id,
            "origin": origin,
            "destination": destination,
            "status": "route_evidence_available",
            "route_ids": [item[0] for item in direct],
            "basis": "actor_visible_current_map_routes_and_exact_cutoff_time",
            "duration": typed_duration,
            "travel_type_evidence": typed_types,
            "access_conditions": route.get("access_conditions") or [],
            "outcome_rule": "finite_model_must_assess_time_and_conditions",
        }
    return {
        "actor_id": actor_id,
        "origin": origin,
        "destination": destination,
        "status": "uncertain",
        "route_ids": sorted(allowed),
        "reason": (
            "no_actor_visible_typed_route_path"
            if allowed
            else "route_not_cited_or_not_visible"
        ),
        "route_coverage": (source.get("map_state") or {}).get(
            "coverage", "not_available"
        ),
    }


def _progression_source_gaps(source: dict) -> list[str]:
    gaps = list((source.get("map_state") or {}).get("unknowns") or [])
    if source.get("validity_notice_limit_reached"):
        gaps.append("object_validity_notice_limit_reached:100")
    for check in source.get("life_state_checks") or []:
        if check.get("status") != "verified_typed_fact":
            gaps.append(
                f"life_state_unknown:{check.get('participant_id')}:{check.get('reason')}"
            )
    if (source.get("author_brief") or {}).get("coverage") != "complete":
        gaps.append("author_evidence_coverage_incomplete")
    if not (source.get("time_basis") or {}).get("facts"):
        gaps.append("exact_cutoff_time_fact_missing")
    return sorted(set(gaps))


def _resource_reference(
    resource_key: str | None, state: dict
) -> SimulationReference | None:
    if not resource_key or resource_key not in state.get("resource_holders", {}):
        raise ValueError("资源转移引用的 resource_key 不在当前结构化状态中")
    kind, _, identity = resource_key.partition(":")
    if kind != "object" or not identity:
        raise ValueError("simulation_v3 目前只允许使用已结构化对象资源身份")
    return SimulationReference(kind="object", id=identity)


async def _lock_continuous_authorization(db, task, participants) -> None:
    """Hold the author-consent row through one provider request at a time."""
    meta = _meta(task)
    revision = meta.get("continuous_authorization_revision")
    if revision is None:
        return
    authorization = await db.scalar(
        select(StoryWorldProgressionAuthorization)
        .where(StoryWorldProgressionAuthorization.novel_id == task.novel_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    authorized_ids = set(meta.get("continuous_authorized_participant_ids") or [])
    if (
        authorization is None
        or not authorization.enabled
        or int(authorization.revision) != int(revision)
        or str(authorization.root_id) != str(meta.get("world_progression_root_id"))
        or str(authorization.branch_id) != str(meta.get("world_progression_branch_id"))
        or set(authorization.participant_ids_json or []) != authorized_ids
        or not {item.id for item in participants} <= authorized_ids
    ):
        raise ValueError("持续推进授权已撤销或范围已变化；未继续调用模型")


def _validate_actor_intent(
    intent, participant, role, source, state, *, active_participant_ids
):
    if intent.actor_id != participant.id:
        raise ValueError("角色意图身份不匹配")
    visible = set(role.get("source_ids") or [])
    visible.update(role.get("known_route_ids") or [])
    own_actor_key = f"object:{participant.id}"
    visible.update(
        str(item.get("event_id"))
        for item in state.get("observations", {}).get(own_actor_key, [])
        if item.get("event_id")
    )
    if not set(intent.basis_ids) <= visible:
        raise ValueError("角色意图引用了其不可见的来源或事件")
    known_entities = set(role.get("known_entity_ids") or [])
    known_entities.update(role.get("known_participant_ids") or [])
    if (
        intent.location_target
        and intent.location_target.kind == "object"
        and intent.location_target.id not in known_entities
    ):
        raise ValueError("人物不可知悉该地点对象")
    if (
        intent.location_target
        and intent.location_target.kind == "map_node"
        and intent.location_target.id not in known_entities
    ):
        raise ValueError("人物不可知悉该地图节点")
    if intent.target_object_id and intent.target_object_id not in known_entities:
        raise ValueError("人物不可知悉该目标对象")
    if not set(intent.information_recipient_ids) <= set(
        role.get("known_participant_ids") or []
    ):
        raise ValueError("信息接收者不在人物可知范围内")
    if not set(intent.information_recipient_ids) <= active_participant_ids:
        raise ValueError("本步未参与的角色不能接收新事件")
    if not set(intent.journey_route_ids) <= set(role.get("known_route_ids") or []):
        raise ValueError("人物引用了不可见或过期的结构化路线")
    if not set(intent.journey_route_ids) <= set(intent.basis_ids):
        raise ValueError("行程路线身份必须同时作为人物可见依据引用")
    known_resource_keys = {
        key
        for key in state.get("resource_holders", {})
        if key.partition(":")[2] in set(role.get("known_entity_ids") or [])
        or state.get("resource_holders", {}).get(key) == own_actor_key
    }
    if intent.resource_key and intent.resource_key not in known_resource_keys:
        raise ValueError("人物引用了不可见或不存在的资源键")
    if intent.effect == "resource_transfer":
        if intent.resource_key not in state.get("resource_holders", {}):
            raise ValueError("资源不在当前结构化状态中")
        if state.get("resource_holders", {}).get(intent.resource_key) != own_actor_key:
            raise ValueError("参与者没有依据证明持有该资源")
        if intent.target_object_id not in role.get("known_participant_ids", []):
            raise ValueError("资源接收者不是该人物已知参与者")


def _apply_candidate_updates(
    state,
    resolution,
    *,
    participants,
    source_ids,
    event_visibility,
    route_ids,
    resource_keys,
    current_event_ids,
    targets,
    entity_ids,
):
    result = deepcopy(state)
    used_ids = source_ids | set(event_visibility) | route_ids | resource_keys
    successful_current_events = {
        event_id
        for event_id in current_event_ids
        if (event_visibility.get(event_id) or {}).get("event", {}).get("outcome")
        == "succeeded"
    }

    def actor_observed_success(basis_ids, actor_id):
        return any(
            event_id in successful_current_events
            and (
                (event_visibility[event_id]["event"].get("actor_id") == actor_id)
                or f"object:{actor_id}" in event_visibility[event_id]["observers"]
            )
            for event_id in basis_ids
        )

    for update in resolution.status_updates:
        if update.actor_id not in participants or not set(update.basis_ids) <= used_ids:
            raise ValueError("候选状态变化超出参与者或来源范围")
        if not actor_observed_success(update.basis_ids, update.actor_id):
            raise ValueError("候选状态变化必须引用本步成功的模拟事件")
        result.setdefault("candidate_status", {})[f"{update.actor_id}:{update.field}"] = {
            "value": update.value,
            "basis_ids": list(update.basis_ids),
        }
    for update in resolution.attitude_updates:
        if update.subject_id not in participants or update.target_id not in (
            participants | entity_ids
        ):
            raise ValueError("候选态度端点不在本次参与者范围")
        if not set(update.basis_ids) <= used_ids:
            raise ValueError("候选态度引用了未知来源")
        if not actor_observed_success(update.basis_ids, update.subject_id):
            raise ValueError("候选态度变化必须引用本步成功的模拟事件")
        result.setdefault("candidate_attitudes", {})[
            f"{update.subject_id}:{update.target_id}"
        ] = update.model_dump(mode="json")
    for update in resolution.knowledge_updates:
        if update.receiver_id not in participants:
            raise ValueError("知识更新的接收者不是参与者")
        visible_event = event_visibility.get(str(update.source_event_id))
        if update.modality == "direct_observation":
            if (
                visible_event is None
                or f"object:{update.receiver_id}" not in visible_event["observers"]
            ):
                raise ValueError("直接观察必须引用接收者可见的结构化事件")
        if update.modality == "reported_claim":
            event = visible_event["event"] if visible_event is not None else {}
            if (
                update.source_actor_id not in participants
                or event.get("actor_id") != update.source_actor_id
                or event.get("truth") != "spoken_claim"
                or event.get("outcome") != "succeeded"
                or f"object:{update.receiver_id}" not in visible_event["observers"]
            ):
                raise ValueError("传闻必须来自接收者可见的成功发言事件")
        result.setdefault("candidate_knowledge", {})[
            f"{update.receiver_id}:{update.subject_key}"
        ] = update.model_dump(mode="json")
    for update in resolution.resource_updates:
        if (
            update.resource_key not in resource_keys
            or not set(update.basis_ids) <= used_ids
        ):
            raise ValueError("候选资源变化缺少当前资源或来源依据")
        if not set(update.basis_ids) & successful_current_events:
            raise ValueError("候选资源变化必须引用本步成功的模拟事件")
        if update.holder_id and update.holder_id not in participants | entity_ids:
            raise ValueError("候选资源持有者没有已证明的身份")
        current_holder = str(
            state.get("resource_holders", {}).get(update.resource_key) or ""
        )
        if current_holder and update.holder_id != current_holder.partition(":")[2]:
            raise ValueError("候选资源持有者与 simulation_v3 结算结果不一致")
        if not current_holder and update.holder_id is not None:
            raise ValueError("候选资源持有者与 simulation_v3 结算结果不一致")
        result.setdefault("candidate_resources", {})[update.resource_key] = {
            "holder_id": update.holder_id,
            "basis_ids": list(update.basis_ids),
        }
    prior_completed_targets = {
        str(item.get("target_id"))
        for item in (state.get("rolling_summary") or {}).get(
            "candidate_goal_statuses", []
        )
        if item.get("status") == "completed"
    }
    for outcome in resolution.goal_outcomes:
        if outcome.target_id not in targets:
            raise ValueError("目标回执引用了非本次选择的结构节点")
        newly_completed = (
            outcome.status == "completed"
            and outcome.target_id not in prior_completed_targets
        )
        if newly_completed and not any(
            path.target_id == outcome.target_id
            and set(path.basis_ids) & successful_current_events
            for path in resolution.target_paths
        ):
            raise ValueError("目标完成必须由本步成功事件及目标路径共同证明")
    reported_targets = {item.target_id for item in resolution.goal_outcomes}
    if set(targets) != reported_targets:
        raise ValueError("每个本次选择的目标都必须保留明确的阶段状态")
    for path in resolution.target_paths:
        if path.target_id not in targets or not set(path.actor_ids) <= participants:
            raise ValueError("目标路径引用了非本次目标或参与者")
        if not set(path.basis_ids) <= used_ids:
            raise ValueError("目标路径引用了未知来源")
    for hook in resolution.plot_hooks:
        if not set(hook.basis_ids) <= used_ids or not set(hook.actor_ids) <= participants:
            raise ValueError("钩子候选引用了未知来源或参与者")
    return result


def _rolling_summary(state, resolution, events):
    return {
        "candidate_state_revision": state.get("revision", 0),
        "cumulative_summary": resolution.rolling_summary,
        "event_count": len(events),
        "event_ids": [item.get("event_id") for item in events],
        "candidate_goal_statuses": [
            {"target_id": item.target_id, "status": item.status}
            for item in resolution.goal_outcomes
        ],
    }


async def _checkpoint(db, root, branch, error):
    await checkpoint_handler_session(db, error_message=error)
    await db.refresh(root)
    await db.refresh(branch)
    await db.commit()
    if db.in_transaction():
        raise RuntimeError(error)
