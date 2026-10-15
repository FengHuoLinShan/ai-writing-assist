"""Author-visible budget preview for one immutable world-progression root."""

from __future__ import annotations

import json

from infrastructure.llm.capabilities import capability_from_execution_snapshot
from infrastructure.llm.collaboration import content_hash
from modules.story.world_progression_engine import recommend_step_length


def progression_preview_identity(request, source: dict) -> dict:
    return {
        "novel_id": request.novel_id,
        "scene_id": source["scene_id"],
        "participants": [item.model_dump(mode="json") for item in request.participants],
        "mode": request.mode,
        "step_length": request.step_length,
        "run_policy": request.run_policy,
        "steps": request.steps,
        "stop_at_goal": request.stop_at_goal,
        "targets": [item.model_dump(mode="json") for item in request.targets],
        "instructions": request.instructions,
        "retained_constraints": request.retained_constraints,
        "request_limit": request.request_limit,
        "token_limit": request.token_limit,
        "time_budget_seconds": request.time_budget_seconds,
        "source_hash": source["source_hash"],
        "model": (source.get("llm_execution_snapshot") or {})
        .get("profile", {})
        .get("model"),
        "provider": (source.get("llm_execution_snapshot") or {})
        .get("profile", {})
        .get("provider_id"),
    }


def preview_progression_budget(
    request, source: dict, *, model_name: str, metrics: list[dict]
) -> dict:
    participant_count = len(request.participants)
    calls_per_step = participant_count + 1
    if request.run_policy == "one_step":
        planned_steps = 1
        request_min = request_max = calls_per_step
    elif request.run_policy == "n_steps":
        planned_steps = int(request.steps)
        request_min = request_max = calls_per_step * planned_steps
    else:
        planned_steps = None
        request_min = calls_per_step
        # Goal/budget runs have no known completion count. Show at least the
        # calls needed for one complete step even when the author grants less.
        request_max = max(request_min, request.request_limit)

    role_text = sum(
        len(json.dumps(value.get("brief") or {}, ensure_ascii=False))
        for value in source.get("role_briefs", {}).values()
    )
    director_text = len(
        json.dumps(
            {
                "scene": source.get("scene_context"),
                "author_brief": source.get("author_brief"),
                "targets": source.get("targets"),
                "instructions": request.instructions,
                "constraints": request.retained_constraints,
            },
            ensure_ascii=False,
        )
    )
    chars_per_step = role_text + director_text + participant_count * 1400
    steps_for_estimate = planned_steps or max(1, request.request_limit // calls_per_step)
    tokens_low = max(1, int(chars_per_step / 4.0)) * steps_for_estimate
    tokens_high = max(tokens_low, int(chars_per_step / 2.5)) * steps_for_estimate
    time_low = request_min * 2
    time_high = request_max * 25
    # The worker checks the 80% guard before each provider request. A final
    # request may cross it, then the next request is refused.
    requests_before_guard = (request.request_limit * 4 + 4) // 5
    enough_one_step = requests_before_guard >= calls_per_step
    warnings = [
        "这是授权预览；实际请求和 token 以运行账本为准，不估算金额。",
        "预算到 80%、计费状态未知或新调用可能导致停在半步时暂停。",
        "角色意图分人单独请求；目标节点与保留项只进入导演裁决层。",
    ]
    if not enough_one_step:
        warnings.append("请求额度不足以在 80% 闸门前完成一个完整步骤。")
    elif planned_steps is not None and requests_before_guard < request_max:
        warnings.append("请求额度不足以在 80% 闸门前完成所选全部步骤。")
    if tokens_low > request.token_limit:
        warnings.append("预计 Token 最低需求超过授权上限，运行可能提前暂停。")
    if time_low > request.time_budget_seconds:
        warnings.append("预计最短耗时超过授权时长，运行可能提前暂停。")
    if planned_steps is None:
        warnings.append(
            "目标或预算停止模式无法预知完成步数；区间只估算首步与当前授权窗口。"
        )
    map_state = source.get("map_state", {})
    if map_state.get("coverage") != "available":
        warnings.extend(map_state.get("unknowns") or [])
        if not source.get("map_state", {}).get("unknowns"):
            warnings.append("未发现可核验的当前地图路线；只按结构化同目的地检查交汇。")

    capability = (
        capability_from_execution_snapshot(source.get("llm_execution_snapshot") or {})
        if source.get("llm_execution_snapshot")
        else None
    )
    input_limit = capability.hard_input_tokens if capability is not None else None
    return {
        "preview_hash": content_hash(progression_preview_identity(request, source)),
        "scene_id": source["scene_id"],
        "scene_index": source.get("scene_index"),
        "scene_title": (
            ((source.get("scene_context") or {}).get("outline_bundle") or {})
            .get("scene", {})
            .get("title")
        ),
        "participants": participant_count,
        "participant_ids": [item.id for item in request.participants],
        "grouping": source.get("context_groups", {}),
        "mode": request.mode,
        "step_length": request.step_length,
        "run_policy": request.run_policy,
        "selected_steps": planned_steps,
        "request_budget": {
            "limit": request.request_limit,
            "estimate_minimum": request_min,
            "estimate_maximum": request_max,
            "max_complete_steps_before_guard": requests_before_guard // calls_per_step,
            "estimate_scope": (
                "complete_selection"
                if planned_steps is not None
                else "authorization_window"
            ),
        },
        "token_budget": {
            "limit": request.token_limit,
            "estimate_minimum": tokens_low,
            "estimate_maximum": tokens_high,
            "input_context_limit": input_limit,
            "method": "按冻结资料文本长度估算区间；不代表 provider 实际用量。",
        },
        "time_budget": {
            "limit_seconds": request.time_budget_seconds,
            "estimate_minimum_seconds": time_low,
            "estimate_maximum_seconds": time_high,
        },
        "fee_status": "可能产生计费请求；未估算金额",
        "model": model_name,
        "step_length_recommendation": recommend_step_length(
            metrics, model_name=model_name
        ),
        "source_hash": source["source_hash"],
        "coverage": source.get("coverage", {}),
        "warnings": list(dict.fromkeys(warnings)),
    }
