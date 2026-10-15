"""Author-authorized scene-director workflow over shared simulation_v3."""

from __future__ import annotations

import json
import re
from copy import deepcopy
from uuid import UUID

from sqlalchemy import select

from infrastructure.llm.agent_step_harness import run_managed_structured
from infrastructure.llm.capabilities import capability_from_execution_snapshot
from infrastructure.llm.collaboration import content_hash
from infrastructure.llm.schemas import LLMCallRequest, LLMMessage
from infrastructure.llm.workflow_budget import current_ai_run_envelope
from infrastructure.tasks.facade import (
    checkpoint_handler_session,
    require_task_checkpoint_session,
)
from infrastructure.tasks.registry import task_handler
from modules.evidence.facade import prepare_confirmed_ai_action
from modules.project.facade import open_project_snapshot_llm_client
from modules.story.director_budget import (
    budget_stop_reason,
    preview_director_budget,
    preview_director_continuation,
)
from modules.story.director_consistency import (
    build_consistency,
    validate_candidate_events,
    validate_intents,
    validate_material_references,
)
from modules.story.director_context import (
    actor_packet,
    director_only_packet,
    read_director_source,
)
from modules.story.director_schemas import (
    DirectorContinueRequest,
    DirectorPerformance,
    DirectorPerformanceBasis,
    DirectorRoundResult,
    DirectorSceneMaterials,
    DirectorStartRequest,
)
from modules.story.director_service import (
    get_director_branch,
    get_director_preferences,
    get_director_root,
    get_director_round,
)
from modules.story.generation import STORY_ONE_CLICK_ACTION
from modules.story.models import (
    StorySceneDirectorRoot,
    StorySceneDirectorRound,
)
from modules.story.rehearsals import validate_simulation_context_refs
from modules.story.simulation_v3 import (
    FiniteResolution,
    SimulationIntent,
    SimulationIntentDraft,
    SimulationReference,
    SimulationV3Context,
    replay_batch,
    resolve_simulation_v3,
)

STORY_SCENE_DIRECTOR_TASK = "story_scene_director"
DIRECTOR_CAPABILITY = "story.scene_director"


def _meta(task) -> dict:
    return dict(task.meta or {})


def _request_limit(task) -> int:
    return int(_meta(task).get("director_authorized_requests") or 1)


def _token_limit(task) -> int:
    value = _meta(task).get("director_authorized_tokens")
    return int(value) if value is not None else 1


def _deadline_seconds(task) -> float:
    return float(_meta(task).get("director_deadline_seconds") or 3600)


def _stable_root_id(task) -> str:
    value = str(_meta(task).get("director_root_id") or "").strip()
    if not value:
        raise ValueError("director root identity is required")
    return value


async def _mirror_run_envelope(session, task, payload):
    meta = _meta(task)
    root_id = meta.get("director_root_id")
    if not root_id:
        raise ValueError("director root identity is required for budget checkpoint")
    root = await session.scalar(
        select(StorySceneDirectorRoot)
        .where(
            StorySceneDirectorRoot.novel_id == task.novel_id,
            StorySceneDirectorRoot.id == UUID(str(root_id)),
        )
        .with_for_update()
    )
    if root is None:
        raise ValueError("director budget root disappeared")
    root.run_envelope_json = dict(payload)


@task_handler(
    STORY_SCENE_DIRECTOR_TASK,
    recovery_policy="never_retry",
    max_attempts=1,
    retry_transient_llm_errors=False,
    root_capability_id=DIRECTOR_CAPABILITY,
    run_request_limit=_request_limit,
    run_token_limit=_token_limit,
    run_deadline_seconds=_deadline_seconds,
    run_id=_stable_root_id,
    run_envelope_checkpoint=_mirror_run_envelope,
)
async def handle_scene_director(db, task):
    require_task_checkpoint_session(db)
    meta = _meta(task)
    novel_id = str(task.novel_id)
    root_id = str(meta.get("director_root_id") or "")
    branch_id = str(meta.get("director_branch_id") or "")
    if not root_id or not branch_id:
        raise ValueError("导演任务缺少持久化根或分支")

    root = await get_director_root(db, novel_id, root_id, lock=True)
    branch = await get_director_branch(db, novel_id, branch_id, lock=True)
    if str(branch.root_id) != root_id:
        raise ValueError("导演分支与运行根不匹配")
    request_payload = meta.get("request") or {}
    is_start = request_payload.get("mode") == "start"
    data = (
        DirectorStartRequest.model_validate(request_payload)
        if is_start
        else DirectorContinueRequest.model_validate(request_payload)
    )
    if data.novel_id != novel_id:
        raise ValueError("导演任务项目身份不匹配")
    envelope = current_ai_run_envelope()
    if (
        envelope is None
        or envelope.run_id != root_id
        or envelope.root_capability_id != DIRECTOR_CAPABILITY
        or envelope.snapshot().novel_id != novel_id
    ):
        raise ValueError("导演根预算信封身份不匹配")

    confirmed = await prepare_confirmed_ai_action(
        db,
        novel_id=novel_id,
        action=STORY_ONE_CLICK_ACTION,
        confirmation_id=data.context_confirmation_id,
    )
    confirmed_options = dict(confirmed.compile_options or {})
    if str(confirmed_options.get("scene_id") or "") != str(root.scene_id):
        raise ValueError("资料确认与当前 Scene 不匹配")

    if is_start:
        character_ids = list(data.character_ids)
        related_ids = list(data.related_object_ids)
        primary_ids = list(data.primary_character_ids)
        rounds_requested = data.rounds
        branch_request = data.model_dump(mode="json")
        basis_choice = "current"
    else:
        root_input = root.request_json
        character_ids = list(root_input.get("character_ids") or [])
        related_ids = list(root_input.get("related_object_ids") or [])
        primary_ids = list(root_input.get("primary_character_ids") or [])
        rounds_requested = data.rounds
        branch_request = data.model_dump(mode="json")
        basis_choice = data.basis_choice
        if not data.parent_round_id:
            raise ValueError("导演分支必须选择一个起始回合")

    confirmed_characters = confirmed_options.get("character_ids")
    if not isinstance(confirmed_characters, list) or set(
        map(str, confirmed_characters)
    ) != set(character_ids):
        raise ValueError("资料确认人物范围与本次导演参与者不一致")
    confirmed_entities = confirmed_options.get("entity_ids")
    if related_ids and (
        not isinstance(confirmed_entities, list)
        or not set(related_ids) <= set(map(str, confirmed_entities))
    ):
        raise ValueError("导演引用的相关对象超出作者已确认资料范围")

    current_source = await read_director_source(
        db,
        novel_id=novel_id,
        scene_id=str(root.scene_id),
        character_ids=character_ids,
        related_object_ids=related_ids,
    )
    if is_start:
        source = current_source
        parent_round = None
        source_changed = False
    else:
        parent_round, _ = await get_director_round(
            db, novel_id, str(data.parent_round_id)
        )
        if str(parent_round.root_id) != root_id:
            raise ValueError("所选回合不属于这个导演运行")
        frozen_source = (parent_round.input_json or {}).get("source_snapshot")
        if not isinstance(frozen_source, dict):
            raise ValueError("所选导演回合缺少可恢复的来源快照")
        source = current_source if basis_choice == "current" else frozen_source
        source_changed = current_source.get("source_hash") != frozen_source.get(
            "source_hash"
        )
        if data.branch_kind == "rewrite_character":
            prior_performances = (parent_round.output_json or {}).get(
                "performances"
            ) or []
            if (
                data.rewrite_character_id
                not in {item.get("character_id") for item in prior_performances}
                or data.rounds != 1
            ):
                raise ValueError("单人物重写只能针对该回合人物并且只生成一个版本")
        effective_intervention = data.intervention
        if data.selected_alternative:
            selected_alternative = next(
                (
                    item
                    for item in (parent_round.output_json or {}).get("alternatives", [])
                    if item.get("alternative_id") == data.selected_alternative
                ),
                None,
            )
            if selected_alternative is None:
                raise ValueError("所选分支方案不属于这个回合")
            effective_intervention = "\n\n".join(
                item
                for item in (
                    effective_intervention.strip(),
                    str(selected_alternative.get("branch_instruction") or "").strip(),
                )
                if item
            )
            data = data.model_copy(
                update={
                    "intervention": effective_intervention,
                    "divergence": data.divergence
                    or selected_alternative.get("divergence"),
                }
            )
        if data.branch_kind == "intervene" and not effective_intervention.strip():
            raise ValueError("介入分支必须说明作者希望调整的方向")
        branch_request = data.model_dump(mode="json")

    preview_request = _preview_input(
        scene_id=str(root.scene_id),
        character_ids=character_ids,
        related_object_ids=related_ids,
        primary_character_ids=primary_ids,
        rounds=rounds_requested,
        instructions=data.instructions,
        intervention=data.intervention,
        public_stimulus=data.public_stimulus,
        selected_alternative=data.selected_alternative if not is_start else None,
    )
    if is_start:
        expected_preview = preview_director_budget(preview_request, source)[
            "preview_hash"
        ]
    else:
        expected_preview = preview_director_continuation(
            preview_request,
            source,
            parent_round_id=str(data.parent_round_id),
        )["preview_hash"]
    if data.budget_preview_hash != expected_preview:
        raise ValueError("场景、人物或档案依据已有变化，请重新预览预算")
    if confirmed_options.get("scene_id") and str(confirmed_options["scene_id"]) != str(
        source["scene_id"]
    ):
        raise ValueError("Evidence Scene 截止点已变化")

    state_context = SimulationV3Context.model_validate(source["simulation_context"])
    await validate_simulation_context_refs(db, novel_id, state_context)
    source_hash = source["source_hash"]
    if is_start and root.source_hash != source_hash:
        raise ValueError("开始前场景或人物资料已变化，请重新预览")
    if not is_start and basis_choice == "current" and source_changed:
        branch.source_hash = source_hash

    root.status = "running"
    branch.status = "running"
    root.current_task_id = UUID(str(task.id))
    branch.current_task_id = UUID(str(task.id))
    branch.source_hash = source_hash
    if not branch.pending_round_json:
        branch.pending_round_json = {"source_snapshot": source}
    await checkpoint_handler_session(
        db,
        error_message="导演来源准备没有提交，不能开始模型请求",
    )

    run_snapshot = meta.get("llm_execution_snapshot") or root.llm_execution_snapshot_json
    if (
        not isinstance(run_snapshot, dict)
        or str(run_snapshot.get("novel_id") or "") != novel_id
    ):
        raise ValueError("导演任务缺少匹配的项目模型快照")
    capabilities = capability_from_execution_snapshot(run_snapshot)
    input_limit = int(capabilities.hard_input_tokens)
    acknowledged_unknown = int(meta.get("director_acknowledged_unknown_requests") or 0)
    baseline_requests_started = int(meta.get("director_baseline_requests_started") or 0)
    baseline_attempts_overflow = int(
        meta.get("director_baseline_recent_attempts_overflow") or 0
    )
    base_state = (
        deepcopy(parent_round.state_json)
        if parent_round is not None
        else state_context.initial_state()
    )
    first_round = (parent_round.round_number + 1) if parent_round is not None else 1
    if not is_start and data.branch_kind == "rewrite_character":
        result = await _rewrite_one_character(
            db,
            task,
            root,
            branch,
            data,
            parent_round,
            source,
            source_changed=source_changed,
            input_limit=input_limit,
            acknowledged_unknown=acknowledged_unknown,
            baseline_requests_started=baseline_requests_started,
            baseline_attempts_overflow=baseline_attempts_overflow,
            envelope=envelope,
        )
        return result

    total_completed = 0
    warnings: list[str] = []
    for offset in range(rounds_requested):
        round_number = first_round + offset
        parent_id = parent_round.id if parent_round is not None else None
        pending = dict(branch.pending_round_json or {})
        if pending.get("round_number") != round_number:
            pending = {
                "source_snapshot": source,
                "round_number": round_number,
                "parent_round_id": str(parent_id) if parent_id else None,
                "source_changed": source_changed,
                "previous_state": deepcopy(base_state),
                "instructions": data.instructions,
                "intervention": data.intervention,
                "public_stimulus": data.public_stimulus,
                "divergence": data.divergence or "balanced",
                "intents": {},
                "performances": {},
            }
            branch.pending_round_json = pending
            await checkpoint_handler_session(db, error_message="导演回合检查点未保存")
        try:
            result = await _run_one_round(
                db,
                task,
                root,
                branch,
                data,
                source,
                base_state,
                pending,
                character_ids=character_ids,
                primary_ids=primary_ids,
                input_limit=input_limit,
                source_changed=source_changed,
                cliche_phrases=(await get_director_preferences(db, novel_id))[
                    "cliche_phrases"
                ],
                acknowledged_unknown=acknowledged_unknown,
                baseline_requests_started=baseline_requests_started,
                baseline_attempts_overflow=baseline_attempts_overflow,
                envelope=envelope,
            )
        except DirectorPauseError as pause:
            branch.status = (
                "paused_budget"
                if pause.reason != "provider_result_unknown"
                else "paused_unknown"
            )
            root.status = branch.status
            root.current_task_id = None
            branch.current_task_id = None
            branch.pending_round_json = pending
            root.run_envelope_json = envelope.snapshot().model_dump(mode="json")
            await checkpoint_handler_session(db, error_message="导演暂停状态未保存")
            return {
                "status": branch.status,
                "completed_rounds": total_completed,
                "budget_stop": pause.reason,
                "root_id": root_id,
                "branch_id": branch_id,
                "needs_author_resume": True,
            }
        except Exception as exc:
            snapshot = envelope.snapshot()
            stop_reason = budget_stop_reason(
                envelope,
                acknowledged_unknown=acknowledged_unknown,
                baseline_requests_started=baseline_requests_started,
                baseline_recent_attempts_overflow=baseline_attempts_overflow,
            )
            if stop_reason in {"provider_result_unknown", "usage_incomplete"}:
                branch.status = "paused_unknown"
                root.status = branch.status
                root.current_task_id = None
                branch.current_task_id = None
                root.run_envelope_json = snapshot.model_dump(mode="json")
                await checkpoint_handler_session(db, error_message="不确定用量状态未保存")
                return {
                    "status": "paused_unknown",
                    "completed_rounds": total_completed,
                    "budget_stop": "provider_result_unknown",
                    "root_id": root_id,
                    "branch_id": branch_id,
                    "needs_author_resume": True,
                }
            branch.status = "failed"
            root.status = "failed"
            root.current_task_id = None
            branch.current_task_id = None
            branch.pending_round_json = {**pending, "safe_error": _safe_error(exc)}
            await checkpoint_handler_session(db, error_message="导演失败状态未保存")
            raise

        result.round_number = round_number
        result_data = result.model_dump(mode="json")
        round_input = {
            "request": branch_request,
            "basis_choice": basis_choice,
            "source_changed": source_changed,
            "source_snapshot": source,
            "initial_context": state_context.model_dump(mode="json"),
            "instructions": data.instructions if is_start else data.instructions,
            "public_stimulus": data.public_stimulus,
        }
        round_row = StorySceneDirectorRound(
            novel_id=UUID(novel_id),
            root_id=UUID(root_id),
            branch_id=UUID(branch_id),
            round_number=round_number,
            parent_round_id=parent_id,
            source_hash=source_hash,
            input_hash=content_hash(
                {
                    "source_hash": source_hash,
                    "parent": str(parent_id) if parent_id else None,
                    "request": round_input,
                    "previous_state": base_state,
                }
            ),
            output_hash=content_hash(result_data),
            input_json=round_input,
            output_json=result_data,
            state_json=result.state_after,
            run_envelope_json=envelope.snapshot().model_dump(mode="json"),
        )
        db.add(round_row)
        branch.pending_round_json = {}
        branch.status = "complete"
        root.run_envelope_json = envelope.snapshot().model_dump(mode="json")
        await checkpoint_handler_session(db, error_message="导演回合结果未持久化")
        parent_round = round_row
        base_state = result.state_after
        total_completed += 1
        warnings.extend(result.warnings)
        task.update_progress(min(0.95, total_completed / max(1, rounds_requested) * 0.95))
        stop_reason = budget_stop_reason(
            envelope,
            acknowledged_unknown=acknowledged_unknown,
            baseline_requests_started=baseline_requests_started,
            baseline_recent_attempts_overflow=baseline_attempts_overflow,
        )
        if stop_reason:
            branch.status = "paused_budget"
            root.status = branch.status
            root.current_task_id = None
            branch.current_task_id = None
            await checkpoint_handler_session(db, error_message="导演预算暂停状态未保存")
            return {
                "status": "paused_budget",
                "completed_rounds": total_completed,
                "budget_stop": stop_reason,
                "root_id": root_id,
                "branch_id": branch_id,
                "needs_author_resume": True,
                "warnings": list(dict.fromkeys(warnings)),
            }

    branch.status = "complete"
    root.status = "ready"
    root.current_task_id = None
    branch.current_task_id = None
    root.run_envelope_json = envelope.snapshot().model_dump(mode="json")
    await checkpoint_handler_session(db, error_message="导演完成状态未保存")
    task.update_progress(1.0)
    return {
        "status": "complete",
        "completed_rounds": total_completed,
        "root_id": root_id,
        "branch_id": branch_id,
        "warnings": list(dict.fromkeys(warnings)),
    }


class DirectorPauseError(Exception):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


def _safe_error(error: Exception) -> str:
    name = type(error).__name__
    if name in {"AIRunBudgetExceededError", "AIRunDeadlineExceededError"}:
        return "运行预算或时限已达到"
    if name in {"ProjectLLMConfigurationError", "CodexConnectionUnavailableError"}:
        return "项目模型连接不可用"
    return "生成未完成；已保存的回合与输入仍可查看"


def _preview_input(
    *,
    scene_id,
    character_ids,
    related_object_ids,
    primary_character_ids,
    rounds,
    instructions="",
    intervention="",
    public_stimulus="",
    selected_alternative=None,
):
    from types import SimpleNamespace

    return SimpleNamespace(
        scene_id=scene_id,
        character_ids=list(character_ids),
        related_object_ids=list(related_object_ids),
        primary_character_ids=list(primary_character_ids),
        rounds=rounds,
        instructions=instructions,
        intervention=intervention,
        public_stimulus=public_stimulus,
        selected_alternative=selected_alternative,
    )


def _role_context(
    source: dict, actor_id: str, state: dict, public_stimulus: str
) -> tuple[str, set[str]]:
    role = source["role_briefs"][actor_id]
    visible = set(role.get("known_participant_ids") or []) | {actor_id}
    actor_key = f"object:{actor_id}"
    observations = state.get("observations", {}).get(actor_key, [])
    visible.update(
        str(item.get("actor_id"))
        for item in observations
        if item.get("actor_id") in state.get("participants", [])
    )
    packet = json.loads(actor_packet(source, actor_id, public_stimulus))
    packet["known_participant_ids"] = sorted(visible)
    packet["own_observations"] = observations
    packet["own_beliefs"] = state.get("beliefs", {}).get(actor_key, {})
    packet["own_location"] = state.get("locations", {}).get(actor_key)
    packet["held_resources"] = [
        key
        for key, holder in state.get("resource_holders", {}).items()
        if holder == actor_key
    ]
    return json.dumps(packet, ensure_ascii=False, separators=(",", ":")), visible


def _fit_packet(
    source: dict,
    actor_id: str,
    public_stimulus: str,
    input_limit: int,
    *,
    include_author_examples: bool = False,
) -> tuple[str, list[dict]]:
    role = deepcopy(source["role_briefs"][actor_id])
    omitted = []
    packet = {
        "character_view": role["brief"],
        "expression_and_speech_anchors": role["style_anchors"],
        "author_examples": (
            source.get("author_examples") if include_author_examples else None
        ),
        "public_stimulus": public_stimulus,
        "known_participant_ids": role["known_participant_ids"],
    }

    def encoded() -> str:
        return json.dumps(packet, ensure_ascii=False, separators=(",", ":"))

    limit_chars = max(4000, int(input_limit * 2.2))
    for section, source_field, id_field in (
        ("pattern_items", "pattern_items", "revision_id"),
        ("world_items", "world_items", "revision_id"),
        ("continuity_items", "continuity_items", "checkpoint_id"),
    ):
        while len(encoded()) > limit_chars and packet["character_view"].get(source_field):
            item = packet["character_view"][source_field].pop()
            omitted.append(
                {
                    "source": section,
                    "source_id": str(item.get(id_field) or ""),
                    "reason": "单人物上下文容量；本条未交给模型",
                    "reference_scope_only": True,
                }
            )
    while len(encoded()) > limit_chars and packet.get("author_examples"):
        packet["author_examples"] = None
        omitted.append({"source": "author_examples", "reason": "上下文容量；本次未使用"})
    if len(encoded()) > limit_chars:
        for field in ("continuity_items", "world_items", "pattern_items"):
            values = packet["character_view"].get(field) or []
            for item in values:
                omitted.append(
                    {
                        "source": field,
                        "source_id": str(
                            item.get("checkpoint_id") or item.get("revision_id") or ""
                        ),
                        "reason": "单人物上下文容量；本条未交给模型",
                        "reference_scope_only": True,
                    }
                )
            packet["character_view"][field] = []
    packet["omitted_reference_items"] = omitted
    return encoded(), omitted


def _visible_source_index(source: dict, actor_id: str, packet: dict) -> dict[str, dict]:
    role = source["role_briefs"][actor_id]
    allowed = role.get("source_index") or {}
    visible_ids: set[str] = set()
    character_view = packet.get("character_view") or {}
    for section in ("world_items", "continuity_items", "pattern_items"):
        for row in character_view.get(section) or []:
            for key in ("entry_id", "revision_id", "checkpoint_id"):
                if row.get(key):
                    visible_ids.add(str(row[key]))
            for reference in row.get("source_refs") or []:
                for key in ("source_hash", "revision_id", "entry_id", "checkpoint_id"):
                    if reference.get(key):
                        visible_ids.add(str(reference[key]))
    for anchor in packet.get("expression_and_speech_anchors") or []:
        if anchor.get("source_id"):
            visible_ids.add(str(anchor["source_id"]))
    return {item: allowed[item] for item in visible_ids if item in allowed}


def _role_fingerprint(source: dict, actor_id: str) -> str:
    role = source["role_briefs"][actor_id]
    return content_hash(
        {
            "source_hash": source["source_hash"],
            "actor_id": actor_id,
            "brief_fingerprint": role["brief"].get("fingerprint"),
            "story_card_status": role.get("story_card_status"),
            "author_examples": content_hash(source.get("author_examples"))
            if source.get("author_examples") is not None
            else None,
        }
    )


def _visible_typed_references(
    source: dict,
    actor_id: str,
    state: dict,
    *,
    public_stimulus: str,
    input_limit: int,
    known_object_ids: set[str],
    known_map_node_ids: set[str],
) -> tuple[set[str], set[str]]:
    fitted, _ = _fit_packet(source, actor_id, public_stimulus, input_limit)
    packet = json.loads(fitted)
    role = source["role_briefs"][actor_id]
    objects = {actor_id, *(role.get("known_participant_ids") or [])}
    map_nodes: set[str] = set()
    for section in ("world_items", "continuity_items", "pattern_items"):
        for row in (packet.get("character_view") or {}).get(section) or []:
            entity = str(row.get("entity_id") or "")
            if entity in known_object_ids:
                objects.add(entity)
            if entity in known_map_node_ids:
                map_nodes.add(entity)
    actor_key = f"object:{actor_id}"
    location = state.get("locations", {}).get(actor_key)
    if location:
        kind, _, identity = str(location).partition(":")
        if kind == "object" and identity in known_object_ids:
            objects.add(identity)
        elif kind == "map_node" and identity in known_map_node_ids:
            map_nodes.add(identity)
    objects.update(
        str(key).partition(":")[2]
        for key, holder in state.get("resource_holders", {}).items()
        if holder == actor_key
        and str(key).startswith("object:")
        and str(key).partition(":")[2] in known_object_ids
    )
    for event in state.get("observations", {}).get(actor_key, []):
        observed_actor = str(event.get("actor_id") or "")
        if observed_actor in known_object_ids:
            objects.add(observed_actor)
    return objects, map_nodes


async def _run_one_round(
    db,
    task,
    root,
    branch,
    request,
    source,
    state,
    pending,
    *,
    character_ids,
    primary_ids,
    input_limit,
    source_changed,
    cliche_phrases,
    acknowledged_unknown,
    baseline_requests_started,
    baseline_attempts_overflow,
    envelope,
):

    actor_refs = {
        actor: SimulationReference(kind="object", id=actor) for actor in character_ids
    }
    active_ids = [
        actor
        for actor in character_ids
        if actor_refs[actor].state_key not in set(state.get("departed", []))
    ]
    if not active_ids:
        raise ValueError("本回合没有仍在场的人物")
    previous_output = {}
    parent_round_id = pending.get("parent_round_id")
    if parent_round_id:
        parent_row, _ = await get_director_round(db, str(root.novel_id), parent_round_id)
        previous_output = parent_row.output_json or {}
    instructions = pending.get("instructions") or ""
    intervention = pending.get("intervention") or ""
    public_stimulus = pending.get("public_stimulus") or ""
    director_packet = director_only_packet(source, instructions, intervention)
    source_index = _allowed_source_index(source)
    source_ids = set(source_index)
    event_index = {
        str(item["event_id"]): {
            "kind": "observed_event",
            "fingerprint": content_hash(item),
        }
        for item in (previous_output.get("observed_events") or [])
        if item.get("event_id")
    }
    event_ids = {
        str(item.get("event_id"))
        for item in (previous_output.get("observed_events") or [])
        if item.get("event_id")
    }
    known_objects = {
        *character_ids,
        *root.request_json.get("related_object_ids", []),
        *(
            item.get("entity_id")
            for item in source["author_brief"].get("world_items", [])
            if item.get("entity_id")
        ),
    }
    known_objects.update(
        str(reference["id"])
        for reference in _context_references(source["simulation_context"])
        if reference["kind"] == "object"
    )
    known_map_nodes = {
        str(reference["id"])
        for reference in _context_references(source["simulation_context"])
        if reference["kind"] == "map_node"
    }
    prompt_omitted: list[dict] = [
        {**item, "character_id": actor}
        for actor in character_ids
        for item in (source["role_briefs"][actor].get("omissions") or [])
    ]
    intent_models: dict[str, dict] = dict(pending.get("intents") or {})
    baseline = content_hash(
        {
            "source_hash": source["source_hash"],
            "round": pending["round_number"],
            "parent_round_id": parent_round_id,
            "state": state,
            "instructions": instructions,
            "intervention": intervention,
            "public_stimulus": public_stimulus,
        }
    )

    async with open_project_snapshot_llm_client(
        db,
        str(root.novel_id),
        root.llm_execution_snapshot_json,
    ) as client:
        for actor in active_ids:
            if actor in intent_models:
                continue
            stop = budget_stop_reason(
                envelope,
                acknowledged_unknown=acknowledged_unknown,
                baseline_requests_started=baseline_requests_started,
                baseline_recent_attempts_overflow=baseline_attempts_overflow,
            )
            if stop:
                raise DirectorPauseError(stop)
            packet, visible_ids = _role_context(source, actor, state, public_stimulus)
            fitting, omitted = _fit_packet(source, actor, public_stimulus, input_limit)
            prompt_omitted.extend({**item, "character_id": actor} for item in omitted)
            packet = fitting
            actor_key = actor_refs[actor].state_key
            user_data = {
                "actor_id": actor,
                "private_packet": json.loads(packet),
                "own_observations": state.get("observations", {}).get(actor_key, []),
                "own_beliefs": state.get("beliefs", {}).get(actor_key, {}),
                "own_location": state.get("locations", {}).get(actor_key),
                "held_resources": [
                    key
                    for key, holder in state.get("resource_holders", {}).items()
                    if holder == actor_key
                ],
            }
            await _checkpoint_before_provider(db)
            draft = await run_managed_structured(
                client,
                LLMCallRequest(
                    model=client.model_name,
                    messages=[
                        LLMMessage(
                            role="system",
                            content=(
                                "你只扮演当前人物。只依据 private_packet、本人观察与"
                                "本人信念提出一条 SimulationIntentDraft；"
                                "同轮其他人的意图不可见。"
                                "作者指示、秘密台账和其他人的私有资料不在你的信息范围。"
                                "行动是意图，不是结果。既有对象或地点只能使用"
                                "资料中给出的 typed ID；"
                                "新对象、新人物、新地点只用 candidate，并标明是本次候选；"
                                "不要伪造现有 ID。"
                                "internal_reason 只供本人，不得写进可观察事件；"
                                "信念只能引用本人观察过的 event_id。"
                            ),
                        ),
                        LLMMessage(
                            role="user", content=json.dumps(user_data, ensure_ascii=False)
                        ),
                    ],
                ),
                SimulationIntentDraft,
                step_name="story.scene_director.intent",
                capability_id=DIRECTOR_CAPABILITY,
                max_fix_attempts=0,
                transport_retries=False,
                timeout=client.timeout,
            )
            if any(
                ref.kind != "object" or ref.id not in visible_ids
                for ref in draft.audience
            ):
                raise ValueError("人物意图收聽者不在该人物可知范围内")
            intent_models[actor] = draft.model_dump(mode="json")
            pending["intents"] = intent_models
            pending["packet_omissions"] = prompt_omitted
            branch.pending_round_json = pending
            await checkpoint_handler_session(db, error_message="导演意图检查点未提交")

        intents: list[SimulationIntent] = []
        for actor, raw in intent_models.items():
            intents.append(
                SimulationIntentDraft.model_validate(raw).bind(
                    intent_id=f"{baseline}:{actor}",
                    actor=actor_refs[actor],
                    mode="director_round",
                )
            )
        known_participant_ids = {
            actor: set(source["role_briefs"][actor].get("known_participant_ids") or [])
            | {
                str(event.get("actor_id"))
                for event in state.get("observations", {}).get(
                    actor_refs[actor].state_key, []
                )
                if event.get("actor_id") in character_ids
            }
            for actor in character_ids
        }
        role_visible_object_ids: dict[str, set[str]] = {}
        role_visible_map_node_ids: dict[str, set[str]] = {}
        for actor in character_ids:
            visible_objects, visible_map_nodes = _visible_typed_references(
                source,
                actor,
                state,
                public_stimulus=public_stimulus,
                input_limit=input_limit,
                known_object_ids=known_objects,
                known_map_node_ids=known_map_nodes,
            )
            role_visible_object_ids[actor] = visible_objects
            role_visible_map_node_ids[actor] = visible_map_nodes
        candidates = validate_intents(
            intents,
            participant_ids=set(character_ids),
            known_participant_ids=known_participant_ids,
            role_visible_object_ids=role_visible_object_ids,
            role_visible_map_node_ids=role_visible_map_node_ids,
            existing_object_ids=known_objects,
            existing_map_node_ids=known_map_nodes,
        )
        resolution_raw = pending.get("resolution")
        if resolution_raw is None:
            stop = budget_stop_reason(
                envelope,
                acknowledged_unknown=acknowledged_unknown,
                baseline_requests_started=baseline_requests_started,
                baseline_recent_attempts_overflow=baseline_attempts_overflow,
            )
            if stop:
                raise DirectorPauseError(stop)
            await _checkpoint_before_provider(db)
            resolution = await run_managed_structured(
                client,
                LLMCallRequest(
                    model=client.model_name,
                    messages=[
                        LLMMessage(
                            role="system",
                            content=(
                                "你是有限环境裁决器。对每条 intent_id 只选"
                                "succeeded、failed、uncertain。"
                                "不得把意图当事实；资源、路线、位置或成功条件"
                                "不明确时，选 uncertain。"
                                "不要给出私有动机、观察或新剧情。"
                            ),
                        ),
                        LLMMessage(
                            role="user",
                            content=json.dumps(
                                {
                                    "director_only_constraints": json.loads(
                                        director_packet
                                    ),
                                    "state": state,
                                    "intents": [
                                        item.model_dump(
                                            mode="json",
                                            exclude={"internal_reason", "beliefs"},
                                        )
                                        for item in intents
                                    ],
                                },
                                ensure_ascii=False,
                            ),
                        ),
                    ],
                ),
                FiniteResolution,
                step_name="story.scene_director.resolve",
                capability_id=DIRECTOR_CAPABILITY,
                max_fix_attempts=0,
                transport_retries=False,
                timeout=client.timeout,
            )
            resolution_raw = resolution.model_dump(mode="json")
            pending["resolution"] = resolution_raw
            branch.pending_round_json = pending
            await checkpoint_handler_session(db, error_message="导演结算检查点未提交")
        resolution = FiniteResolution.model_validate(resolution_raw)
        batch = resolve_simulation_v3(
            intents,
            resolution,
            state,
            observers=set(state.get("participants", [])) - set(state.get("departed", [])),
            rule_revision=content_hash("simulation_v3:finite-effects-v1"),
        )
        after_state = replay_batch(state, batch)
        pending["resolution_batch"] = batch.model_dump(mode="json")
        pending["state_after"] = after_state
        pending["events"] = batch.events
        branch.pending_round_json = pending
        await checkpoint_handler_session(db, error_message="导演状态差量未提交")

        performances: dict[str, dict] = dict(pending.get("performances") or {})
        prior_performances = {
            item.get("character_id"): item
            for item in (previous_output.get("performances") or [])
        }
        for actor in active_ids:
            if actor in performances:
                continue
            stop = budget_stop_reason(
                envelope,
                acknowledged_unknown=acknowledged_unknown,
                baseline_requests_started=baseline_requests_started,
                baseline_recent_attempts_overflow=baseline_attempts_overflow,
            )
            if stop:
                raise DirectorPauseError(stop)
            visible_events = [
                item
                for item in batch.events
                if actor_refs[actor].state_key in item.get("observers", [])
            ]
            private_intent = intent_models.get(actor) or {}
            packet, omitted = _fit_packet(
                source,
                actor,
                public_stimulus,
                input_limit,
                include_author_examples=True,
            )
            prompt_omitted.extend({**item, "character_id": actor} for item in omitted)
            await _checkpoint_before_provider(db)
            performance = await run_managed_structured(
                client,
                LLMCallRequest(
                    model=client.model_name,
                    messages=[
                        LLMMessage(
                            role="system",
                            content=(
                                "为当前人物写完整表演卡，逐项写具体依据或明确写导演发挥。"
                                "动作必须对应给出的模拟结果；不得补写未发生的成功。只使用该人物可知资料与可观察事件。"
                                "表达方式/说话方式锚点缺失时要承认资料不足，不要捏造人物习惯。作者示例只作为语感参照，"
                                "不可复制原句；反例必须遵守作者备注。"
                            ),
                        ),
                        LLMMessage(
                            role="user",
                            content=json.dumps(
                                {
                                    "character_id": actor,
                                    "private_packet": json.loads(packet),
                                    "own_intent": private_intent,
                                    "visible_events": visible_events,
                                    "previous_performance": prior_performances.get(actor),
                                    "required_fields": [
                                        "action",
                                        "expression",
                                        "body_language",
                                        "voice_and_dialogue",
                                        "subtext",
                                        "motive_and_emotion",
                                        "trigger_and_defense",
                                        "attention",
                                        "ignored",
                                        "change_from_previous",
                                        "basis",
                                    ],
                                },
                                ensure_ascii=False,
                            ),
                        ),
                    ],
                ),
                DirectorPerformance,
                step_name="story.scene_director.performance",
                capability_id=DIRECTOR_CAPABILITY,
                max_fix_attempts=0,
                transport_retries=False,
                timeout=client.timeout,
            )
            if performance.character_id != actor:
                raise ValueError("表演卡人物身份与当前请求不匹配")
            role_index = _visible_source_index(source, actor, json.loads(packet))
            actor_event_ids = {
                str(item["event_id"]) for item in visible_events if item.get("event_id")
            }
            actor_event_index = {
                event_id: event_index[event_id]
                for event_id in actor_event_ids
                if event_id in event_index
            }
            actor_event_index.update(
                {
                    str(item["event_id"]): {
                        "kind": "observed_event",
                        "fingerprint": content_hash(item),
                    }
                    for item in visible_events
                    if item.get("event_id")
                }
            )
            performance = _validate_performance_basis(
                performance,
                allowed_sources=role_index,
                allowed_events=actor_event_index,
                role_fingerprint=_role_fingerprint(source, actor),
            )
            performances[actor] = performance.model_dump(mode="json")
            pending["performances"] = performances
            pending["packet_omissions"] = prompt_omitted
            branch.pending_round_json = pending
            await checkpoint_handler_session(db, error_message="人物表演卡检查点未提交")

        stop = budget_stop_reason(
            envelope,
            acknowledged_unknown=acknowledged_unknown,
            baseline_requests_started=baseline_requests_started,
            baseline_recent_attempts_overflow=baseline_attempts_overflow,
        )
        if stop:
            raise DirectorPauseError(stop)
        groups = {
            "primary_character_ids": list(primary_ids),
            "background_character_ids": [
                item for item in character_ids if item not in set(primary_ids)
            ],
            "role_intents": "每个人物使用独立角色可知简报，不合并私有意图",
            "background_materials": "背景人物在素材统筹中按群像汇总",
        }
        await _checkpoint_before_provider(db)
        materials = await run_managed_structured(
            client,
            LLMCallRequest(
                model=client.model_name,
                messages=[
                    LLMMessage(
                        role="system",
                        content=(
                            "你是作者可见的场景导演。可用 director_only 资料，"
                            "但所有新人物、物件和地点必须标为候选。"
                            "可以提出登场、离场或环境/消息事件；"
                            "新事件只写 candidate_events，"
                            "不得改写已裁定的状态差量，并保持 candidate_only=true、"
                            "applied_to_state=false。所有素材标感知者、感官方式和可核验来源。"
                            "文本推断不能冒充正史。输出 2–3 个角度建议，"
                            "并给出 2–3 个可分支的其他可能。"
                            "推荐角度需区分 POV、叙述距离、焦点和详略节奏。"
                            "source_ids 只能选提供的来源，不能编造。"
                        ),
                    ),
                    LLMMessage(
                        role="user",
                        content=json.dumps(
                            {
                                "director_only": json.loads(director_packet),
                                "participant_groups": groups,
                                "performances": list(performances.values()),
                                "events": batch.events,
                                "state_after": after_state,
                                "available_source_ids": sorted(source_ids | event_ids),
                                "available_object_ids": sorted(known_objects),
                                "available_map_node_ids": sorted(known_map_nodes),
                                "divergence": pending.get("divergence", "balanced"),
                                "candidate_event_rule": (
                                    "新登场对象/事件只做候选，不写入状态、不成为正史。"
                                ),
                            },
                            ensure_ascii=False,
                        ),
                    ),
                ],
            ),
            DirectorSceneMaterials,
            step_name="story.scene_director.materials",
            capability_id=DIRECTOR_CAPABILITY,
            max_fix_attempts=0,
            transport_retries=False,
            timeout=client.timeout,
        )

    all_events = list(batch.events)
    event_observers = {
        str(item.get("event_id")): set(item.get("observers") or [])
        for item in all_events
        if item.get("event_id")
    }
    checked_materials = validate_material_references(
        materials.materials,
        participant_ids=set(character_ids),
        known_event_ids=set(event_observers),
        known_event_index={
            str(item["event_id"]): {
                "kind": "observed_event",
                "fingerprint": content_hash(item),
            }
            for item in all_events
            if item.get("event_id")
        },
        event_observers=event_observers,
        known_source_index=source_index,
        role_source_indexes={
            actor: _visible_source_index(
                source,
                actor,
                json.loads(_fit_packet(source, actor, public_stimulus, input_limit)[0]),
            )
            for actor in character_ids
        },
        existing_object_ids=known_objects,
        existing_map_node_ids=known_map_nodes,
    )
    candidate_events = validate_candidate_events(
        materials.candidate_events,
        existing_object_ids=known_objects,
        existing_map_node_ids=known_map_nodes,
        known_source_index=source_index,
        known_event_index={
            str(item["event_id"]): {
                "kind": "observed_event",
                "fingerprint": content_hash(item),
            }
            for item in all_events
            if item.get("event_id")
        },
    )
    _apply_angle_material_availability(
        materials.recommended_angles,
        checked_materials,
        set(character_ids),
    )
    performances_out = [performances[actor] for actor in active_ids]
    style_missing = [
        actor
        for actor in active_ids
        if not source["role_briefs"][actor].get("style_anchors")
    ]
    card_missing = [
        actor
        for actor in active_ids
        if not source["role_briefs"][actor].get("story_card_status", {}).get("available")
    ]
    warnings = []
    if source_changed:
        warnings.append("资料依据与所选历史轮次不同；本轮使用的是你选定的新依据。")
    if style_missing:
        warnings.extend(
            f"人物 {actor} 缺少表达方式或说话方式面向，表演容易趋同。"
            "可补全档案后重写此人。"
            for actor in style_missing
        )
    if card_missing:
        warnings.extend(
            f"人物 {actor} 没有当前有效的 Story 人物卡；"
            "本轮仅使用其 Evidence 角色投影，不从卡片自由文本补造认知。"
            "可完善档案后单独重写。"
            for actor in card_missing
        )
    warnings.extend(_cliche_warnings(performances_out, cliche_phrases))
    warnings.extend(_similarity_warnings(performances_out))
    if prompt_omitted:
        warnings.append(
            "部分参考条目因单人物上下文容量未交给模型；清单已在本轮披露，"
            "核心知识范围未写入 KnowledgeScopeReceipt。"
        )
    omitted = [
        {
            "source": "object_dossier",
            "reason": text,
            "scope_effect": "reference_only",
        }
        for text in source["author_brief"].get("omissions", [])
    ] + prompt_omitted
    consistency = build_consistency(
        source=source,
        intents=intents,
        candidates=candidates,
        materials=checked_materials,
        candidate_events=candidate_events,
        object_ids=known_objects,
        map_node_ids=known_map_nodes,
    )
    return DirectorRoundResult(
        round_number=int(pending["round_number"]),
        performances=[
            DirectorPerformance.model_validate(item) for item in performances_out
        ],
        materials=checked_materials,
        groups=groups,
        omitted=omitted,
        recommended_angles=materials.recommended_angles,
        alternatives=materials.alternatives,
        candidate_events=candidate_events,
        consistency=consistency,
        warnings=list(dict.fromkeys(warnings)),
        state_delta=batch.state_patches,
        state_after=after_state,
        observed_events=all_events,
    )


def _context_references(context: dict) -> list[dict]:
    refs = []
    for value in context.get("participants", []) + context.get("locations", []):
        refs.append(value)
    for position in context.get("positions", []):
        refs.extend([position["subject"], position["location"]])
    for resource in context.get("resources", []):
        refs.append(resource["resource"])
        if resource.get("holder"):
            refs.append(resource["holder"])
    for route in context.get("routes", []):
        refs.extend([route["origin"], route["destination"]])
    return refs


def _allowed_source_index(source: dict) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for section, kind in (
        ("world_items", "world_dossier"),
        ("continuity_items", "continuity"),
        ("pattern_items", "character_pattern"),
    ):
        for item in source["author_brief"].get(section, []):
            fingerprint = content_hash(item)
            for key in ("entry_id", "revision_id", "checkpoint_id"):
                if item.get(key):
                    result[str(item[key])] = {
                        "kind": kind,
                        "fingerprint": fingerprint,
                        "row": item,
                    }
            for ref in item.get("source_refs", []):
                for key in ("source_hash", "revision_id", "entry_id", "checkpoint_id"):
                    if ref.get(key):
                        result[str(ref[key])] = {
                            "kind": kind,
                            "fingerprint": fingerprint,
                            "row": item,
                        }
    for role in source.get("role_briefs", {}).values():
        result.update(role.get("source_index") or {})
    return result


def _validate_performance_basis(
    performance,
    *,
    allowed_sources: dict[str, dict],
    allowed_events: dict[str, dict],
    role_fingerprint: str,
):
    normalized = []
    for basis in performance.basis:
        if basis.source_kind == "director_inference":
            normalized.append(
                basis.model_copy(update={"source_id": None, "source_fingerprint": None})
            )
            continue
        source = None
        if basis.source_id:
            source = allowed_events.get(basis.source_id) or allowed_sources.get(
                basis.source_id
            )
        if source and source.get("kind") == basis.source_kind:
            normalized.append(
                basis.model_copy(
                    update={
                        "source_fingerprint": content_hash(
                            {
                                "role_packet_fingerprint": role_fingerprint,
                                "source_id": basis.source_id,
                                "source_fingerprint": source["fingerprint"],
                            }
                        ),
                    }
                )
            )
        else:
            normalized.append(
                DirectorPerformanceBasis(
                    source_kind="director_inference",
                    note="未找到可核验的所引来源；此处是导演发挥。",
                )
            )
    performance.basis = normalized or [
        DirectorPerformanceBasis(
            source_kind="director_inference", note="本项未找到可核验依据；这是导演发挥。"
        )
    ]
    return performance


def _cliche_warnings(performances: list[dict], phrases: list[str]) -> list[str]:
    warnings = []
    for card in performances:
        text = " ".join(
            str(card.get(key) or "")
            for key in (
                "action",
                "expression",
                "body_language",
                "voice_and_dialogue",
                "subtext",
            )
        )
        for phrase in phrases:
            if phrase and phrase in text:
                warnings.append(
                    f"发现套话“{phrase}”；可只重写该人物表演卡，并参考其表达方式锚点。"
                )
    return warnings


def _similarity_warnings(performances: list[dict]) -> list[str]:
    def grams(value: str) -> set[str]:
        normalized = re.sub(r"[\W_]+", "", value.casefold())
        if len(normalized) < 3:
            return {normalized} if normalized else set()
        return {normalized[index : index + 3] for index in range(len(normalized) - 2)}

    warnings = []
    for index, left in enumerate(performances):
        left_text = "".join(
            str(left.get(key) or "")
            for key in ("action", "expression", "body_language", "voice_and_dialogue")
        )
        left_grams = grams(left_text)
        for right in performances[index + 1 :]:
            right_text = "".join(
                str(right.get(key) or "")
                for key in ("action", "expression", "body_language", "voice_and_dialogue")
            )
            right_grams = grams(right_text)
            union = left_grams | right_grams
            overlap = len(left_grams & right_grams) / len(union) if union else 0
            if overlap >= 0.32:
                warnings.append(
                    "同轮人物动作或措辞较相似；可选择其中一人单独重写并区分其锚点。"
                )
    return warnings


def _apply_angle_material_availability(
    angles, materials, participant_ids: set[str]
) -> None:
    material_ids = {item.material_id for item in materials}
    for angle in angles:
        if angle.material_ids and not set(angle.material_ids) <= material_ids:
            raise ValueError("角度引用了本轮不存在的素材卡")
        if (
            angle.viewpoint_character_id
            and angle.viewpoint_character_id not in participant_ids
        ):
            raise ValueError("角度 POV 不属于本轮人物")
        angle.disabled_material_ids = sorted(
            {
                item.material_id
                for item in materials
                if angle.viewpoint_kind == "character"
                and angle.viewpoint_character_id in item.disabled_for_character_ids
            }
        )


async def _checkpoint_before_provider(db):
    await checkpoint_handler_session(
        db,
        error_message="导演 provider 请求需要先提交数据库检查点",
    )


def _status_to_outcome(result: dict) -> dict:
    return result


async def _rewrite_one_character(
    db,
    task,
    root,
    branch,
    request,
    base_round,
    source,
    *,
    source_changed,
    input_limit,
    acknowledged_unknown,
    baseline_requests_started,
    baseline_attempts_overflow,
    envelope,
):
    actor = request.rewrite_character_id
    if not actor:
        raise ValueError("单人物重写必须指定人物")
    prior = deepcopy(base_round.output_json)
    cards = {item["character_id"]: item for item in prior.get("performances", [])}
    if actor not in cards:
        raise ValueError("所选人物不在该回合表演卡中")
    stop = budget_stop_reason(
        envelope,
        acknowledged_unknown=acknowledged_unknown,
        baseline_requests_started=baseline_requests_started,
        baseline_recent_attempts_overflow=baseline_attempts_overflow,
    )
    if stop:
        raise DirectorPauseError(stop)
    branch_request = branch.request_json or {}
    packet, omitted = _fit_packet(
        source,
        actor,
        str(branch_request.get("public_stimulus") or ""),
        input_limit,
        include_author_examples=True,
    )
    events = [
        item
        for item in (prior.get("observed_events") or [])
        if f"object:{actor}" in item.get("observers", [])
    ]
    fitted_packet = json.loads(packet)
    allowed_sources = _visible_source_index(source, actor, fitted_packet)
    event_ids = {str(item.get("event_id")) for item in events if item.get("event_id")}
    await _checkpoint_before_provider(db)
    async with open_project_snapshot_llm_client(
        db, str(root.novel_id), root.llm_execution_snapshot_json
    ) as client:
        replacement = await run_managed_structured(
            client,
            LLMCallRequest(
                model=client.model_name,
                messages=[
                    LLMMessage(
                        role="system",
                        content="只重写这一名人物的表演卡。不得改动本轮其他人、事件、差量、素材或角度；依据只能来自其个人可知资料和可观察事件。档案缺失时不要编造锚点。",
                    ),
                    LLMMessage(
                        role="user",
                        content=json.dumps(
                            {
                                "character_id": actor,
                                "private_packet": json.loads(packet),
                                "prior_performance": cards[actor],
                                "visible_events": events,
                                "available_source_ids": sorted(
                                    set(allowed_sources) | event_ids
                                ),
                                "rewrite_instruction": request.intervention
                                or request.instructions,
                            },
                            ensure_ascii=False,
                        ),
                    ),
                ],
            ),
            DirectorPerformance,
            step_name="story.scene_director.performance_rewrite",
            capability_id=DIRECTOR_CAPABILITY,
            max_fix_attempts=0,
            transport_retries=False,
            timeout=client.timeout,
        )
    if replacement.character_id != actor:
        raise ValueError("重写结果人物身份与请求不匹配")
    replacement = _validate_performance_basis(
        replacement,
        allowed_sources=allowed_sources,
        allowed_events={
            str(item["event_id"]): {
                "kind": "observed_event",
                "fingerprint": content_hash(item),
            }
            for item in events
            if item.get("event_id")
        },
        role_fingerprint=_role_fingerprint(source, actor),
    )
    cards[actor] = replacement.model_dump(mode="json")
    prior["performances"] = list(cards.values())
    prior.setdefault("warnings", []).append(
        "作者只重写了该人物表演卡；原回合与其他人物保持不变。"
    )
    if omitted:
        prior.setdefault("omitted", []).extend(omitted)
    output_hash = content_hash(prior)
    row = StorySceneDirectorRound(
        novel_id=root.novel_id,
        root_id=root.id,
        branch_id=branch.id,
        round_number=base_round.round_number,
        parent_round_id=base_round.parent_round_id,
        source_hash=base_round.source_hash,
        input_hash=content_hash(
            {"rewrite_of": str(base_round.id), "actor": actor, "request": branch_request}
        ),
        output_hash=output_hash,
        input_json={
            **(base_round.input_json or {}),
            "rewrite_of_round_id": str(base_round.id),
            "rewrite_character_id": actor,
            "request": branch_request,
            "source_snapshot": source,
            "source_changed": source_changed,
        },
        output_json=prior,
        state_json=deepcopy(base_round.state_json),
        run_envelope_json=envelope.snapshot().model_dump(mode="json"),
    )
    db.add(row)
    branch.status = "complete"
    root.status = "ready"
    root.current_task_id = None
    branch.current_task_id = None
    root.run_envelope_json = envelope.snapshot().model_dump(mode="json")
    await checkpoint_handler_session(db, error_message="单人物表演卡重写没有保存")
    return {
        "status": "complete",
        "completed_rounds": 1,
        "rewritten_character": actor,
        "root_id": str(root.id),
        "branch_id": str(branch.id),
    }
